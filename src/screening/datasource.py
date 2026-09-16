"""漏斗专用数据源 — 封装 akshare 中筛选相关的 API 调用。

与 MarketDataProvider 分离：后者为策略提供即时行情，
FunnelDataSource 提供财务、资金、行业等"慢数据"。

每条方法都内置 try/except，失败时返回空数据不抛异常。
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from ..data.provider import MarketDataProvider
from .cache import ttl_cache

logger = logging.getLogger(__name__)


class FunnelDataSource:
    """漏斗专用数据源，组合已有的 MarketDataProvider 并扩展筛选专用 API。"""

    def __init__(self, market_provider: MarketDataProvider):
        self._market = market_provider

    # ═══════════════════════════════════════════════════
    # 第①步：成交量 + PE
    # ═══════════════════════════════════════════════════

    @ttl_cache(300)  # 5 分钟
    def get_market_spot(self) -> pd.DataFrame:
        """全市场 A 股实时行情快照。

        优先走已配置的 MarketDataProvider（避免直连 akshare 的 Eastmoney 问题），
        fallback 才用 akshare.stock_zh_a_spot_em()。

        返回 DataFrame 包含：代码, 名称, 最新价, 涨跌幅, 成交量, 成交额,
        换手率, 市盈率-动态, 市净率, 总市值, 行业
        """
        import pandas as pd

        # 方案 A：用已有的 MarketDataProvider（SinaClient 等）
        try:
            # 获取全市场标的
            symbols = self._market.get_stock_universe("all")
            if symbols:
                snapshots = self._market.get_snapshots(symbols)
                if snapshots:
                    rows = []
                    for sym, snap in snapshots.items():
                        rows.append({
                            "代码": sym,
                            "名称": snap.name or sym,
                            "最新价": snap.close,
                            "涨跌幅": snap.change_pct * 100,  # 转为百分比
                            "成交量": snap.volume,
                            "换手率": snap.turnover_rate or 0,
                            "市盈率-动态": snap.pe,
                            "市净率": snap.pb,
                            "总市值": snap.total_market_cap,
                            "行业": getattr(snap, 'industry', '其他') or '其他',
                        })
                    if rows:
                        logger.info(f"获取全市场行情(provider): {len(rows)} 只")
                        return pd.DataFrame(rows)
        except Exception as e:
            logger.info(f"Provider 行情获取失败: {e}, 尝试 akshare...")

        # 方案 B：直连 akshare
        import time
        last_error = None
        for attempt in range(2):
            try:
                import akshare as ak
                df = ak.stock_zh_a_spot_em()
                if df is not None and not df.empty:
                    logger.info(f"获取全市场行情(akshare): {len(df)} 只")
                    return df
            except Exception as e:
                last_error = e
                if attempt < 1:
                    time.sleep(3)

        logger.warning(f"获取全市场行情失败: {last_error}")
        return pd.DataFrame()

    @ttl_cache(3600)  # 1 小时（历史数据不变）
    def get_historical_volume(
        self, symbols: list[str], days: int = 30
    ) -> dict[str, list[float]]:
        """获取近 N 天每日成交量序列。

        优先用 MarketDataProvider 的历史数据接口，
        akshare 直连经常会超时，作为 fallback。

        Returns:
            {symbol: [vol_day1, vol_day2, ...]}（按时间升序）
        """
        result: dict[str, list[float]] = {}

        # 方案 A：用已有 provider 的历史接口
        try:
            from datetime import datetime, timedelta
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=days + 5)).strftime("%Y%m%d")
            hist = self._market.get_historical_data(symbols[:50], start, end)
            for sym, snapshots in hist.items():
                vols = [s.volume for s in snapshots if s.volume > 0]
                if vols:
                    result[sym] = vols[-days:] if len(vols) > days else vols
            if result:
                logger.info(f"获取历史成交量(provider): {len(result)} 只")
                return result
        except Exception as e:
            logger.info(f"Provider 历史数据不可用: {e}")

        # 方案 B：akshare（加超时）
        try:
            import akshare as ak
            import signal
            for symbol in symbols[:10]:  # 更小的批次
                try:
                    df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                            start_date="", end_date="",
                                            adjust="qfq", timeout=5)
                    if df is not None and not df.empty and "成交量" in df.columns:
                        vols = df["成交量"].tail(days).tolist()
                        result[symbol] = vols
                except Exception:
                    continue
            if result:
                logger.info(f"获取历史成交量(akshare): {len(result)} 只")
        except Exception as e:
            logger.warning(f"获取历史成交量失败: {e}")

        return result

    # ═══════════════════════════════════════════════════
    # 第②步：财务数据
    # ═══════════════════════════════════════════════════

    @ttl_cache(86400)  # 24 小时（财报数据日级不变）
    def get_financial_performance(self, symbols: list[str]) -> dict[str, dict]:
        """季度业绩报表：净利润、ROE、营收增长率。

        Returns:
            {symbol: {"net_profit": float, "roe": float, "revenue_yoy": float,
                      "report_date": str}}
        """
        result: dict[str, dict] = {}
        try:
            import akshare as ak
            # 获取全市场业绩报表
            df = ak.stock_yjbb_em(date="")  # 最新报告期
            if df is None or df.empty:
                logger.warning("业绩报表数据为空")
                return result

            symbol_set = set(symbols)
            for _, row in df.iterrows():
                code = str(row.get("股票代码", ""))
                if code not in symbol_set:
                    continue
                try:
                    result[code] = {
                        "net_profit": float(row.get("净利润", 0) or 0),
                        "net_profit_yoy": float(row.get("净利润同比增长", 0) or 0),
                        "revenue": float(row.get("营业收入", 0) or 0),
                        "revenue_yoy": float(row.get("营业收入同比增长", 0) or 0),
                        "roe": float(row.get("净资产收益率", 0) or 0),
                        "report_date": str(row.get("报告期", "")),
                    }
                except (ValueError, TypeError):
                    continue
            logger.info(f"获取业绩报表: {len(result)}/{len(symbols)} 只")
        except Exception as e:
            logger.warning(f"获取业绩报表失败: {e}")
        return result

    @ttl_cache(86400)
    def get_profit_trend(self, symbols: list[str]) -> dict[str, str]:
        """近三年净利润趋势判断。

        通过比较不同报告期的净利润数据来判断趋势。
        使用 stock_yjbb_em() 的多个报告期数据。

        Returns:
            {symbol: "growing"|"stable"|"declining"|"volatile"|"unknown"}
        """
        result: dict[str, str] = {}
        try:
            import akshare as ak
            # 尝试获取最近几个季度的数据
            from datetime import datetime
            current_year = datetime.now().year

            # 获取最近几个报告期
            periods = []
            for year in range(current_year - 2, current_year + 1):
                for q in [4, 3, 2, 1]:
                    p = f"{year}-{q:02d}-01"
                    periods.append(p)

            all_data: dict[str, list[float]] = {}
            for period in periods[-6:]:  # 最近 6 个季度
                try:
                    # 尝试用报告期参数
                    df = ak.stock_yjbb_em(date=period)
                    if df is None or df.empty:
                        continue
                    symbol_set = set(symbols)
                    for _, row in df.iterrows():
                        code = str(row.get("股票代码", ""))
                        if code not in symbol_set:
                            continue
                        try:
                            np_val = float(row.get("净利润", 0) or 0)
                            all_data.setdefault(code, []).append(np_val)
                        except (ValueError, TypeError):
                            continue
                except Exception:
                    continue

            # 分析趋势
            for symbol in symbols:
                profits = all_data.get(symbol, [])
                if len(profits) < 3:
                    result[symbol] = "unknown"
                    continue

                # 取有效的非零数据点
                valid = [p for p in profits if p != 0]
                if len(valid) < 3:
                    result[symbol] = "unknown"
                    continue

                # 简单线性趋势判断
                n = len(valid)
                inc_count = sum(1 for i in range(1, n) if valid[i] > valid[i-1])
                dec_count = sum(1 for i in range(1, n) if valid[i] < valid[i-1])

                if inc_count >= n * 0.7:
                    result[symbol] = "growing"
                elif dec_count >= n * 0.7:
                    result[symbol] = "declining"
                elif abs(valid[-1] - valid[0]) / (abs(valid[0]) + 1) < 0.1:
                    result[symbol] = "stable"
                else:
                    result[symbol] = "volatile"

            logger.info(f"三年利润趋势: {len(result)} 只")
        except Exception as e:
            logger.warning(f"获取利润趋势失败: {e}")
        return result

    @ttl_cache(86400)
    def get_balance_health(self, symbols: list[str]) -> dict[str, list[str]]:
        """资产负债表健康度检查，返回红旗标记列表。

        Returns:
            {symbol: ["high_goodwill", "dual_high_cash_debt", "high_ar", ...]}
        """
        result: dict[str, list[str]] = {}
        try:
            import akshare as ak
            for symbol in symbols[:50]:
                try:
                    df = ak.stock_zcfz_em(symbol=symbol)
                    if df is None or df.empty:
                        continue
                    latest = df.iloc[0]
                    flags = []

                    # 商誉 / 净资产
                    goodwill = float(latest.get("商誉", 0) or 0)
                    net_assets = float(latest.get("归属于母公司股东权益合计", 0) or 0)
                    if net_assets > 0 and goodwill / net_assets > 0.3:
                        flags.append("high_goodwill")

                    # 应收账款 / 总资产
                    ar = float(latest.get("应收账款", 0) or 0)
                    total_assets = float(latest.get("资产总计", 0) or 0)
                    if total_assets > 0 and ar / total_assets > 0.5:
                        flags.append("high_ar_ratio")

                    # 存贷双高（货币资金和短期借款同时很高）
                    cash = float(latest.get("货币资金", 0) or 0)
                    short_debt = float(latest.get("短期借款", 0) or 0)
                    if total_assets > 0:
                        if cash / total_assets > 0.2 and short_debt / total_assets > 0.15:
                            flags.append("dual_high_cash_debt")

                    if flags:
                        result[symbol] = flags
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"获取资产负债表失败: {e}")
        return result

    # ═══════════════════════════════════════════════════
    # 第③步：资金流向
    # ═══════════════════════════════════════════════════

    @ttl_cache(600)  # 10 分钟
    def get_north_bound_flow(self, days: int = 10) -> dict:
        """北向资金近 N 日净流入。

        使用 stock_hsgt_hist_em() 获取沪深港通历史资金流向。

        Returns:
            {"daily_flows": [float, ...], "cumulative": float, "trend": "inflow"|"outflow"}
        """
        try:
            import akshare as ak
            df = ak.stock_hsgt_hist_em()
            if df is None or df.empty:
                return {"daily_flows": [], "cumulative": 0.0, "trend": "unknown"}

            recent = df.tail(days)
            flows = []
            # 找到净流入列
            net_col = None
            for col in ["净买入额", "当日净流入", "净流入"]:
                if col in recent.columns:
                    net_col = col
                    break

            if net_col:
                for _, row in recent.iterrows():
                    try:
                        flows.append(float(row[net_col]))
                    except (ValueError, TypeError):
                        flows.append(0.0)

            cumulative = sum(flows) if flows else 0.0
            trend = "inflow" if cumulative > 0 else ("outflow" if cumulative < 0 else "neutral")
            return {"daily_flows": flows, "cumulative": cumulative, "trend": trend}
        except Exception as e:
            logger.warning(f"获取北向资金失败: {e}")
            return {"daily_flows": [], "cumulative": 0.0, "trend": "unknown"}

    @ttl_cache(600)
    def get_individual_fund_flow(
        self, symbols: list[str], days: int = 10
    ) -> dict[str, dict]:
        """个股主力资金近 N 日流向。

        使用 stock_fund_flow_individual() 获取个股资金流向。

        Returns:
            {symbol: {"main_net_10d": float, "super_large_net_10d": float}}
        """
        result: dict[str, dict] = {}
        try:
            import akshare as ak
            for symbol in symbols[:30]:  # 限制批次
                try:
                    df = ak.stock_fund_flow_individual(symbol=symbol)
                    if df is None or df.empty:
                        continue
                    recent = df.tail(days)
                    main_net = 0.0
                    super_net = 0.0
                    # 尝试找到主力净流入列
                    for col in ["主力净流入", "主力净流入-净额", "主力资金净流入"]:
                        if col in recent.columns:
                            main_net = float(recent[col].sum())
                            break
                    for col in ["超大单净流入", "超大单净流入-净额"]:
                        if col in recent.columns:
                            super_net = float(recent[col].sum())
                            break
                    result[symbol] = {
                        "main_net_10d": main_net,
                        "super_large_net_10d": super_net,
                    }
                except Exception:
                    continue
            logger.info(f"获取个股资金流向: {len(result)}/{len(symbols)} 只")
        except Exception as e:
            logger.warning(f"获取个股资金流向失败: {e}")
        return result

    # ═══════════════════════════════════════════════════
    # 第④步：行业数据
    # ═══════════════════════════════════════════════════

    @ttl_cache(86400)
    def get_industry_map(self) -> dict[str, str]:
        """股票代码 → 行业名称 映射。

        Returns:
            {symbol: "industry_name"}
        """
        try:
            import akshare as ak
            df = ak.stock_board_industry_name_em()
            if df is None or df.empty:
                return {}

            result = {}
            for _, row in df.iterrows():
                # 此 API 返回行业 → 成分股列表，需要反转
                industry = str(row.get("板块名称", ""))
                stocks_str = str(row.get("成分股代码", ""))
                if industry and stocks_str:
                    for code in stocks_str.split(","):
                        code = code.strip()
                        if code:
                            result[code] = industry
            logger.info(f"获取行业分类: {len(result)} 只")
            return result
        except Exception as e:
            logger.warning(f"获取行业分类失败: {e}")
            return {}

    @ttl_cache(300)
    def get_industry_performance(self) -> pd.DataFrame:
        """行业板块涨跌排名。

        优先使用 stock_board_industry_spot_em()（实时行情），
        fallback 到 stock_board_industry_name_em()。

        Returns DataFrame: 板块名称, 涨跌幅, 换手率, 领涨股
        """
        try:
            import akshare as ak
            # 优先用实时板块行情
            try:
                df = ak.stock_board_industry_spot_em()
                if df is not None and not df.empty:
                    logger.info(f"获取行业表现(spot): {len(df)} 个行业")
                    return df
            except Exception:
                pass

            # fallback
            df = ak.stock_board_industry_name_em()
            logger.info(f"获取行业表现(name): {len(df) if df is not None else 0} 个行业")
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.warning(f"获取行业表现失败: {e}")
            return pd.DataFrame()

    # ═══════════════════════════════════════════════════
    # 第⑤步：风险数据
    # ═══════════════════════════════════════════════════

    @ttl_cache(86400)
    def get_restricted_shares(self, lookahead_days: int = 30) -> dict[str, list[dict]]:
        """限售股解禁数据。

        Returns:
            {symbol: [{"release_date": "2026-07-01", "shares": 1000000, "ratio": 0.05}, ...]}
        """
        result: dict[str, list[dict]] = {}
        try:
            import akshare as ak
            df = ak.stock_restricted_release_detail_em()
            if df is None or df.empty:
                return result

            from datetime import datetime, timedelta
            cutoff = (datetime.now() + timedelta(days=lookahead_days)).strftime("%Y-%m-%d")
            today = datetime.now().strftime("%Y-%m-%d")

            for _, row in df.iterrows():
                release_date = str(row.get("解禁日期", ""))
                if today <= release_date <= cutoff:
                    symbol = str(row.get("股票代码", ""))
                    result.setdefault(symbol, []).append({
                        "release_date": release_date,
                        "shares": float(row.get("解禁数量", 0) or 0),
                        "ratio": float(row.get("占总股本比例", 0) or 0) / 100,
                    })
            logger.info(f"获取限售解禁: {len(result)} 只有近期解禁")
        except Exception as e:
            logger.warning(f"获取限售解禁失败: {e}")
        return result

    @ttl_cache(3600)
    def get_price_drawdown(
        self, symbols: list[str], days: int = 60
    ) -> dict[str, dict]:
        """计算近 N 日最大回撤。

        Returns:
            {symbol: {"max_drawdown": float, "drawdown_from_peak": float,
                       "peak_date": str, "current_vs_peak": float}}
        """
        result: dict[str, dict] = {}
        try:
            import akshare as ak
            for symbol in symbols[:60]:
                try:
                    df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                            start_date="", end_date="",
                                            adjust="qfq")
                    if df is None or df.empty or "收盘" not in df.columns:
                        continue

                    closes = df["收盘"].tail(days).astype(float).tolist()
                    if len(closes) < 5:
                        continue

                    peak = closes[0]
                    max_dd = 0.0
                    for c in closes:
                        peak = max(peak, c)
                        dd = (peak - c) / peak if peak > 0 else 0.0
                        max_dd = max(max_dd, dd)

                    current_vs_peak = (closes[-1] - peak) / peak if peak > 0 else 0.0
                    result[symbol] = {
                        "max_drawdown": round(max_dd, 4),
                        "drawdown_from_peak": round(-current_vs_peak, 4),
                        "current_vs_peak": round(current_vs_peak, 4),
                    }
                except Exception:
                    continue
            logger.info(f"计算回撤: {len(result)}/{len(symbols)} 只")
        except Exception as e:
            logger.warning(f"计算回撤失败: {e}")
        return result

    # ═══════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════

    def get_stock_universe(self, universe: str) -> list[str]:
        """代理 MarketDataProvider 的标的池获取。"""
        return self._market.get_stock_universe(universe)

    def is_trading_day(self, date: str) -> bool:
        """代理交易日检查。"""
        return self._market.is_trading_day(date)
