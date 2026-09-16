"""均值回归者 — RSI + 布林带策略。

逻辑：
- RSI(14) < 30 + 价格触及布林下轨 → 买入（超卖反弹）
- RSI(14) > 70 → 卖出（超买回落）
- 持仓超过 max_hold_days 个交易日 → 强制卖出
- 止损 -10%
"""
from __future__ import annotations


import logging
from datetime import datetime, timedelta

from .base import BaseTrader, OrderIntent, TraderState
from ..data.provider import MarketSnapshot

logger = logging.getLogger(__name__)


class MeanReversion(BaseTrader):
    """均值回归者 — 在别人恐慌时贪婪，在别人贪婪时恐慌。"""

    def decide(
        self,
        state: TraderState,
        market: dict[str, MarketSnapshot],
        date: str,
    ) -> list[OrderIntent]:
        orders: list[OrderIntent] = []
        params = self.params

        rsi_oversold: int = params.get("rsi_oversold", 30)
        rsi_overbought: int = params.get("rsi_overbought", 70)
        max_hold_days: int = params.get("max_hold_days", 10)
        max_positions: int = params.get("max_positions", 5)

        # === 卖出逻辑 ===
        for symbol, pos in list(state.positions.items()):
            snap = market.get(symbol)
            if snap is None:
                continue

            sell_reason = None

            # 计算持仓天数
            hold_days = self._calc_hold_days(pos, date)

            # 止损 -10%
            pnl_pct = (snap.close - pos.avg_cost) / pos.avg_cost if pos.avg_cost > 0 else 0
            if pnl_pct <= -0.10:
                sell_reason = f"止损: {pnl_pct:+.1%} (持有{hold_days}天)"

            # RSI 超买
            elif snap.rsi_14 and snap.rsi_14 > rsi_overbought:
                sell_reason = f"RSI={snap.rsi_14:.0f} > {rsi_overbought}, 超买 (持有{hold_days}天)"

            # 价格回归布林中轨以上 → 获利了结
            elif (snap.boll_mid and snap.boll_lower
                  and snap.close > snap.boll_mid
                  and pos.avg_cost < (snap.boll_lower or snap.close)):
                sell_reason = f"价格回归中轨, 获利了结 (持有{hold_days}天)"

            # max_hold_days 强制卖出
            elif hold_days >= max_hold_days:
                sell_reason = f"持仓{hold_days}天 ≥ {max_hold_days}天上限, 强制卖出 (盈亏{pnl_pct:+.1%})"

            if sell_reason:
                available = pos.available_shares
                if available > 0:
                    orders.append(OrderIntent(
                        symbol=symbol,
                        action="sell",
                        shares=available,
                        reason=sell_reason,
                    ))

        # === 买入逻辑 ===
        current_positions = len(state.positions)
        if current_positions >= max_positions:
            return orders

        candidates = []
        for symbol, snap in market.items():
            if symbol in state.positions:
                continue
            # RSI 超卖
            if snap.rsi_14 is None or snap.rsi_14 >= rsi_oversold:
                continue
            # 价格接近布林下轨
            if snap.boll_lower and snap.close <= snap.boll_lower * 1.02:
                candidates.append((symbol, snap, snap.rsi_14))

        # 按 RSI 从低到高（最超卖的优先）
        candidates.sort(key=lambda x: x[2])

        slots = max_positions - current_positions
        for symbol, snap, rsi in candidates[:slots]:
            budget = state.cash * 0.45  # 每只最多用 45% 余款
            lots = int(budget / (snap.close * 100))
            if lots >= 1:
                shares = lots * 100
                orders.append(OrderIntent(
                    symbol=symbol,
                    action="buy",
                    shares=shares,
                    reason=f"RSI={rsi:.0f}, 触及布林下轨, 超卖反弹",
                ))
                slots -= 1
                if state.cash < 500:
                    break

        return orders

    def _calc_hold_days(self, pos, current_date: str) -> int:
        """计算持仓天数（基于首次买入日期）。"""
        if not pos.buy_date:
            return 0
        try:
            buy_dt = datetime.strptime(pos.buy_date, "%Y-%m-%d")
            cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
            return (cur_dt - buy_dt).days
        except (ValueError, TypeError):
            return 0
