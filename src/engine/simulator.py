"""模拟器主控：调度→选股→决策→撮合→记录。"""
from __future__ import annotations


import logging
from datetime import datetime

from ..data.provider import MarketDataProvider, MarketSnapshot
from ..storage.repository import Repository
from ..storage.models import DailySnapshot, Order as OrderModel
from ..traders.base import BaseTrader
from ..traders.registry import TraderRegistry
from ..config import load_settings
from .matcher import TradeMatcher
from .portfolio import PortfolioManager

logger = logging.getLogger(__name__)


class Simulator:
    """模拟器主控。

    每个交易日执行流程：
    1. 加载所有操盘手状态
    2. 获取市场数据（标的池）
    3. 每个操盘手做出决策
    4. 撮合引擎校验并执行
    5. 记录订单和快照
    6. T+1 解冻
    """

    def __init__(
        self,
        repo: Repository,
        data_provider: MarketDataProvider,
        registry: TraderRegistry,
    ):
        settings = load_settings()
        market_config = settings["market"]

        self.repo = repo
        self.data = data_provider
        self.registry = registry
        self.matcher = TradeMatcher(
            stamp_tax=market_config["stamp_tax"],
            commission=market_config["commission"],
            min_shares=market_config["min_shares_stock"],
            price_limit_main=market_config["price_limit_main"],
            price_limit_gem=market_config["price_limit_gem"],
        )
        self.portfolio = PortfolioManager(repo)

    def run_daily(self, date: str | None = None) -> dict[str, list]:
        """执行一个交易日的完整流程。

        Returns:
            {trader_name: [MatchResult, ...]}
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        logger.info(f"=== {date} 交易开始 ===")

        # 1. 交易日检查
        if not self.data.is_trading_day(date):
            logger.info(f"{date} 非交易日，跳过")
            return {}

        # 1.5 幂等检查：今日已跑过则跳过
        existing = self.repo.get_all_snapshots_for_date(date)
        if existing:
            logger.info(f"{date} 已有快照，跳过重复执行")
            return {}

        # 2. 获取操盘手
        traders_db = self.repo.get_traders(active_only=True)
        if not traders_db:
            logger.warning("没有活跃的操盘手")
            return {}

        # 3. 构建操盘手实例（仅活跃的）
        trader_instances: list[BaseTrader] = []
        for t_db in traders_db:
            instance = self.registry.create(
                t_db.strategy,
                name=t_db.name,
                capital=t_db.cash,
                params=self._get_params(t_db.name),
            )
            if instance:
                trader_instances.append(instance)
            else:
                logger.warning(f"无法创建操盘手: {t_db.name} ({t_db.strategy})")

        # 4. 获取全局标的池（合并所有操盘手的 universe）
        all_symbols = set()
        for t_db in traders_db:
            params = self._get_params(t_db.name)
            universe = params.get("universe", "hs300")
            symbols = self.data.get_stock_universe(universe)
            all_symbols.update(symbols)

        all_symbols_list = list(all_symbols)
        logger.info(f"标的池: {len(all_symbols_list)} 只")

        # 4.5 选股漏斗预筛选（可选）
        funnel_result = self._run_funnel(all_symbols_list, date)
        if funnel_result is not None:
            all_symbols_list = funnel_result.passed_symbols
            logger.info(
                f"漏斗后标的池: {len(all_symbols_list)} 只 "
                f"({funnel_result.input_count} -> {funnel_result.output_count})"
            )
        self._last_funnel_result = funnel_result

        # 5. 获取市场数据（传入日期以获取对应历史指标）
        market = self.data.get_snapshots(all_symbols_list, date)
        logger.info(f"获取行情: {len(market)} 只")

        # ── 5.5 分红入账 ──
        self._apply_dividends_for_date(traders_db, date)

        # 6. 逐个操盘手交易
        all_results: dict[str, list] = {}
        for t_db, instance in zip(traders_db, trader_instances):
            try:
                # 加载状态
                state = self.portfolio.load_state(t_db.id, t_db.name, self._get_params(t_db.name))

                # T+1 解冻
                self.portfolio.unlock_all(t_db.id)
                for pos in state.positions.values():
                    pos.locked_shares = 0

                # 过滤操盘手关心的标的
                trader_market = {
                    sym: snap for sym, snap in market.items()
                    if sym in all_symbols_list
                }

                # 决策
                orders = instance.decide(state, trader_market, date)

                # 撮合
                results = self.matcher.match_all(state, orders, market, date)

                # 记录到数据库
                filled_count = 0
                rejected_count = 0
                for r in results:
                    self.repo.save_order(OrderModel(
                        trader_id=t_db.id,
                        symbol=r.order.symbol,
                        type=r.order.action,
                        shares=r.order.shares,
                        price=r.executed_price if r.status == "filled" else 0,
                        fee=r.fee,
                        status=r.status,
                        reject_reason=r.reject_reason,
                        reason=r.order.reason,
                        created_at=f"{date}T15:00:00",
                    ))
                    if r.status == "filled":
                        filled_count += 1
                    else:
                        rejected_count += 1

                # 保存持仓
                self.portfolio.save_positions(t_db.id, state)

                # 计算总资产并记录快照
                total_value = self.portfolio.calc_total_value(state, market)
                prev_snapshots = self.repo.get_snapshots(t_db.id, limit=1)
                prev_value = prev_snapshots[0].total_value if prev_snapshots else t_db.initial_capital
                daily_pnl = total_value - prev_value
                daily_pnl_pct = (total_value - prev_value) / prev_value if prev_value > 0 else 0

                # ── 数据完整性校验 ──
                market_value = total_value - state.cash
                balance_check = abs((state.cash + market_value) - total_value)
                if balance_check > 0.01:
                    logger.error(f"❌ {t_db.name} 资产不平衡! cash={state.cash:.2f}+mkt={market_value:.2f}≠total={total_value:.2f}")
                if abs(daily_pnl_pct) > 0.15:
                    logger.warning(f"⚠ {t_db.name} 单日波动 {daily_pnl_pct:+.2%}，请核实交易记录")

                self.repo.save_snapshot(DailySnapshot(
                    trader_id=t_db.id,
                    date=date,
                    total_value=total_value,
                    pnl=daily_pnl,
                    pnl_pct=daily_pnl_pct,
                    cash=state.cash,
                    market_value=market_value,
                ))

                logger.info(f"  {t_db.name}: {filled_count} 成交, {rejected_count} 拒绝, "
                           f"总资产 ¥{total_value:,.2f} ({daily_pnl_pct:+.2%})")

                all_results[t_db.name] = results

            except Exception as e:
                logger.error(f"操盘手 {t_db.name} 交易异常: {e}", exc_info=True)

        # ── 6.5 组合集中度检查 ──
        self._check_concentration(traders_db, market, date)

        logger.info(f"=== {date} 交易结束 ===")
        return all_results

    def _apply_dividends_for_date(self, traders_db, date: str) -> None:
        """在指定日期对所有活跃操盘手持仓应用分红入账。"""
        try:
            from ..data.dividends import get_dividend_payments

            # 收集所有持仓代码
            all_held_symbols = set()
            positions_by_trader: dict[int, dict] = {}
            for t_db in traders_db:
                positions = {}
                for p in self.repo.get_positions(t_db.id):
                    if p.shares > 0:
                        positions[p.symbol] = p
                        all_held_symbols.add(p.symbol)
                if positions:
                    positions_by_trader[t_db.id] = positions

            if not all_held_symbols:
                return

            # 查询分红支付
            year = int(date[:4])
            payments = get_dividend_payments(list(all_held_symbols), year)

            if not payments:
                return

            # 匹配当日支付的分红
            total_credited = 0.0
            for trader_id, positions in positions_by_trader.items():
                credited = 0.0
                for symbol, pos in positions.items():
                    for p in payments.get(symbol, []):
                        if p["pay_date"] == date and pos.shares > 0:
                            cash = p["cash_per_share"] * pos.shares
                            credited += cash
                            logger.info(
                                f"💰 分红: {symbol} {pos.shares}股 × "
                                f"¥{p['cash_per_share']:.2f} = ¥{cash:.2f}"
                            )
                if credited > 0:
                    trader = self.repo.get_trader(trader_id)
                    if trader:
                        new_cash = trader.cash + credited
                        self.repo.update_trader_cash(trader_id, new_cash)
                        total_credited += credited
                        logger.info(f"💰 操盘手{trader_id} 分红入账 ¥{credited:.2f}")

            if total_credited > 0:
                logger.info(f"💰 当日总分红: ¥{total_credited:.2f}")
        except Exception as e:
            logger.warning(f"分红入账处理失败: {e}", exc_info=True)

    def _check_concentration(self, traders_db, market: dict, date: str) -> None:
        """组合集中度检查——跨操盘手持仓重叠 + 单股总敞口。"""
        try:
            # 统计每只股票被哪些操盘手持仓
            stock_holders: dict[str, list[tuple[int, str, float]]] = {}
            # {symbol: [(trader_id, trader_name, market_value), ...]}

            for t_db in traders_db:
                for p in self.repo.get_positions(t_db.id):
                    if p.shares <= 0:
                        continue
                    snap = market.get(p.symbol)
                    mv = p.shares * snap.close if snap else p.shares * p.avg_cost
                    stock_holders.setdefault(p.symbol, []).append(
                        (t_db.id, t_db.name, round(mv, 2))
                    )

            # 检查重叠
            warnings = []
            for symbol, holders in stock_holders.items():
                if len(holders) >= 2:
                    total_exposure = sum(h[2] for h in holders)
                    holder_names = [h[1] for h in holders]
                    if len(holders) >= 3:
                        warnings.append(
                            f"⚠ 高集中度: {symbol} 被 {len(holders)} 人持有 "
                            f"({', '.join(holder_names)}), 总敞口 ¥{total_exposure:,.0f}"
                        )
                    elif len(holders) == 2:
                        logger.info(
                            f"📊 持仓重叠: {symbol} 被 {holder_names[0]}, {holder_names[1]} 共同持有, "
                            f"总敞口 ¥{total_exposure:,.0f}"
                        )

            for w in warnings:
                logger.warning(w)
        except Exception as e:
            logger.warning(f"集中度检查失败: {e}", exc_info=True)

    def _get_params(self, trader_name: str) -> dict:
        """从配置加载操盘手参数。"""
        from ..config import load_traders
        traders_config = load_traders()
        for t in traders_config:
            if t["name"] == trader_name:
                return t.get("params", {})
        return {}

    def _run_funnel(self, symbols: list[str], date: str):
        """运行选股漏斗（如果配置启用）。

        漏斗在 get_snapshots 之前运行，从 500 只缩小到 ~30 只，
        减少后续 API 调用量并提高策略决策质量。
        """
        try:
            from ..config import load_screening_config
            cfg = load_screening_config()
        except Exception:
            return None

        if not cfg.get("enabled", False):
            return None

        try:
            from ..screening.datasource import FunnelDataSource
            from ..screening.pipeline import ScreenPipeline

            funnel_data = FunnelDataSource(self.data)
            pipeline = ScreenPipeline(funnel_data, config=cfg)
            result = pipeline.run(symbols=symbols, date=date)
            return result
        except Exception as e:
            logger.warning(f"漏斗执行失败，跳过预筛选: {e}")
            return None
