"""趋势跟随者 — 均线交叉 + 放量策略。

逻辑：
- MA5 上穿 MA20 + 成交量放大 → 买入
- MA5 下穿 MA20 → 卖出
- 止损 -8%
"""
from __future__ import annotations


import logging

from .base import BaseTrader, OrderIntent, TraderState
from ..data.provider import MarketSnapshot

logger = logging.getLogger(__name__)


class TrendFollower(BaseTrader):
    """趋势跟随者 — 顺势而为，截断亏损，让利润奔跑。"""

    def decide(
        self,
        state: TraderState,
        market: dict[str, MarketSnapshot],
        date: str,
    ) -> list[OrderIntent]:
        orders: list[OrderIntent] = []
        params = self.params

        ma_short: int = params.get("ma_short", 5)
        ma_long: int = params.get("ma_long", 20)
        volume_ratio: float = params.get("volume_ratio", 1.5)
        stop_loss: float = params.get("stop_loss", -0.08)
        max_positions: int = params.get("max_positions", 3)

        # === 卖出逻辑 ===
        for symbol, pos in list(state.positions.items()):
            snap = market.get(symbol)
            if snap is None:
                continue

            pnl_pct = (snap.close - pos.avg_cost) / pos.avg_cost if pos.avg_cost > 0 else 0

            # 止损
            if pnl_pct <= stop_loss:
                orders.append(OrderIntent(
                    symbol=symbol,
                    action="sell",
                    shares=pos.available_shares,
                    reason=f"止损: {pnl_pct:+.1%}",
                ))
                continue

            # MA 死叉（MA5 下穿 MA20）
            ma5 = snap.ma_5
            ma20 = snap.ma_20
            if ma5 and ma20 and ma5 < ma20:
                orders.append(OrderIntent(
                    symbol=symbol,
                    action="sell",
                    shares=pos.available_shares,
                    reason=f"MA5({ma5:.2f}) < MA20({ma20:.2f}), 死叉",
                ))

        # === 买入逻辑 ===
        current_positions = len(state.positions)
        if current_positions >= max_positions:
            return orders

        # 筛选金叉 + 放量候选
        candidates = []
        for symbol, snap in market.items():
            if symbol in state.positions:
                continue
            # 需要均线数据
            ma5 = snap.ma_5
            ma20 = snap.ma_20
            if ma5 is None or ma20 is None:
                continue
            # MA5 上穿 MA20（金叉）
            if ma5 <= ma20:
                continue
            # 放量判断：换手率 > 3%（若无数据则只靠均线）
            if snap.turnover_rate is not None and snap.turnover_rate < 3.0:
                continue
            candidates.append((symbol, snap))

        # 按涨幅排序，选最强趋势
        candidates.sort(key=lambda x: x[1].change_pct, reverse=True)

        # 买入（集中持仓前 2 只）
        slots = max_positions - current_positions
        for symbol, snap in candidates[:slots]:
            budget = state.cash * 0.45  # 每只最多用 45% 余款
            lots = int(budget / (snap.close * 100))
            if lots >= 1:
                shares = lots * 100
                orders.append(OrderIntent(
                    symbol=symbol,
                    action="buy",
                    shares=shares,
                    reason=f"MA5({snap.ma_5:.2f}) > MA20({snap.ma_20:.2f}), 金叉放量",
                ))
                slots -= 1
                if state.cash < 500:
                    break

        return orders
