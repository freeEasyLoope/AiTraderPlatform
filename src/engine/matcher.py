"""交易撮合引擎：验资、T+1、涨跌停、手续费。"""
from __future__ import annotations


import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..data.provider import MarketSnapshot
from ..traders.base import OrderIntent, Position, TraderState

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """撮合结果。"""
    order: OrderIntent
    status: str             # "filled" | "rejected"
    reject_reason: str = ""
    fee: float = 0.0
    executed_price: float = 0.0


class TradeMatcher:
    """A股交易撮合引擎。

    规则：
    - T+1: 当日买入次日才能卖
    - 涨跌停限制
    - 最小交易单位 (股票 100 股)
    - 佣金 0.03% 买卖双向
    - 印花税 0.1% 仅卖方
    """

    def __init__(
        self,
        stamp_tax: float = 0.001,
        commission: float = 0.0003,
        min_shares: int = 100,
        price_limit_main: float = 0.10,
        price_limit_gem: float = 0.20,
    ):
        self.stamp_tax = stamp_tax
        self.commission = commission
        self.min_shares = min_shares
        self.price_limit_main = price_limit_main
        self.price_limit_gem = price_limit_gem

    def match_all(
        self,
        state: TraderState,
        orders: list[OrderIntent],
        market: dict[str, MarketSnapshot],
        date: str,
    ) -> list[MatchResult]:
        """批量撮合订单。资金不足时停止后续订单。"""
        results = []
        for order in orders:
            result = self.match_one(state, order, market, date)
            results.append(result)
            if result.status == "filled":
                self._apply_to_state(state, order, result)
            elif "资金不足" in result.reject_reason:
                # 没钱了，后续订单全标记为拒绝（不浪费算力）
                break
        # 剩余未处理的订单标记为跳过
        for order in orders[len(results):]:
            results.append(MatchResult(order, "rejected", "资金不足(批量跳过)"))
        return results

    def match_one(
        self,
        state: TraderState,
        order: OrderIntent,
        market: dict[str, MarketSnapshot],
        date: str,
    ) -> MatchResult:
        """撮合单笔订单。"""
        # 1. 获取行情
        snapshot = market.get(order.symbol)
        if snapshot is None:
            return MatchResult(order, "rejected", f"无行情数据: {order.symbol}")

        # 2. 涨跌停检查
        price = snapshot.close
        if snapshot.is_limit_up and order.action == "buy":
            return MatchResult(order, "rejected", f"涨停无法买入: {order.symbol}")
        if snapshot.is_limit_down and order.action == "sell":
            return MatchResult(order, "rejected", f"跌停无法卖出: {order.symbol}")

        # 3. 最小单位检查
        if order.shares % self.min_shares != 0:
            return MatchResult(
                order, "rejected",
                f"数量必须是 {self.min_shares} 的整数倍"
            )

        # 4. 买卖逻辑
        if order.action == "buy":
            return self._match_buy(state, order, price)
        elif order.action == "sell":
            return self._match_sell(state, order, price)
        else:
            return MatchResult(order, "rejected", f"未知操作: {order.action}")

    def _match_buy(
        self, state: TraderState, order: OrderIntent, price: float
    ) -> MatchResult:
        """买入撮合。"""
        total_cost = price * order.shares
        fee = total_cost * self.commission  # 只有佣金
        total_needed = total_cost + fee

        if state.cash < total_needed:
            return MatchResult(
                order, "rejected",
                f"资金不足: 需要 ¥{total_needed:,.2f}, 可用 ¥{state.cash:,.2f}"
            )

        return MatchResult(
            order=order,
            status="filled",
            fee=fee,
            executed_price=price,
        )

    def _match_sell(
        self, state: TraderState, order: OrderIntent, price: float
    ) -> MatchResult:
        """卖出撮合。"""
        pos = state.positions.get(order.symbol)
        if pos is None:
            return MatchResult(order, "rejected", f"无持仓: {order.symbol}")

        available = pos.shares - pos.locked_shares
        if available < order.shares:
            return MatchResult(
                order, "rejected",
                f"可用数量不足: 需要 {order.shares}, 可用 {available} (锁定 {pos.locked_shares})"
            )

        total_value = price * order.shares
        fee = total_value * (self.commission + self.stamp_tax)  # 佣金+印花税

        return MatchResult(
            order=order,
            status="filled",
            fee=fee,
            executed_price=price,
        )

    def _apply_to_state(
        self, state: TraderState, order: OrderIntent, result: MatchResult
    ) -> None:
        """将成交结果应用到内存状态。"""
        price = result.executed_price

        if order.action == "buy":
            today = datetime.now().strftime("%Y-%m-%d")
            # 更新持仓
            pos = state.positions.get(order.symbol)
            if pos:
                # 计算新的平均成本
                old_total = pos.shares * pos.avg_cost
                new_total = order.shares * price + result.fee
                pos.shares += order.shares
                pos.avg_cost = (old_total + new_total) / pos.shares
                pos.locked_shares += order.shares  # T+1 锁定
                pos.last_buy_date = today
            else:
                state.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    name=order.symbol,  # 外部填入真实名称
                    type="stock",
                    shares=order.shares,
                    locked_shares=order.shares,
                    avg_cost=(order.shares * price + result.fee) / order.shares,
                    buy_date=today,
                    last_buy_date=today,
                )
            state.cash -= order.shares * price + result.fee

        elif order.action == "sell":
            pos = state.positions[order.symbol]
            pos.shares -= order.shares
            pos.locked_shares = max(0, pos.locked_shares - order.shares)
            state.cash += order.shares * price - result.fee
            # 不删除零仓位——让 save_positions 同步到 DB

    def unlock_t_plus_1(self, positions: list[Position]) -> None:
        """解冻 T+1 锁定（收盘后调用）。"""
        for pos in positions:
            pos.locked_shares = 0

    def get_price_limit(self, symbol: str) -> float:
        """判断股票涨跌停幅度。"""
        # 科创板 (688)、创业板 (300/301) 涨跌停 20%
        if symbol.startswith(("688", "300", "301")):
            return self.price_limit_gem
        return self.price_limit_main
