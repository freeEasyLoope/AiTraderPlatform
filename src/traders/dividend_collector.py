"""红利收集者 — 高股息策略。

逻辑：
- 股息率 > 3% + PB < 1.5 → 买入
- 股息率 < 2% → 卖出
- 分散持仓，最多 10 只
"""
from __future__ import annotations


import logging

from .base import BaseTrader, OrderIntent, TraderState
from ..data.provider import MarketSnapshot

logger = logging.getLogger(__name__)


class DividendCollector(BaseTrader):
    """红利收集者 — 稳健现金流，等待估值回归。"""

    def decide(
        self,
        state: TraderState,
        market: dict[str, MarketSnapshot],
        date: str,
    ) -> list[OrderIntent]:
        orders: list[OrderIntent] = []
        params = self.params

        min_dividend_yield: float = params.get("min_dividend_yield", 0.03)
        max_pb: float = params.get("max_pb", 1.5)
        sell_dividend_yield: float = params.get("sell_dividend_yield", 0.02)
        max_positions: int = params.get("max_positions", 10)

        # === 卖出逻辑 ===
        for symbol, pos in list(state.positions.items()):
            snap = market.get(symbol)
            if snap is None:
                continue

            # 股息率下降
            if snap.dividend_yield is not None and snap.dividend_yield < sell_dividend_yield:
                orders.append(OrderIntent(
                    symbol=symbol,
                    action="sell",
                    shares=pos.available_shares,
                    reason=f"股息率 {snap.dividend_yield:.2%} < {sell_dividend_yield:.2%}",
                ))
                continue

            # PB 过高
            if snap.pb and snap.pb > max_pb * 2:
                orders.append(OrderIntent(
                    symbol=symbol,
                    action="sell",
                    shares=pos.available_shares,
                    reason=f"PB={snap.pb:.1f} 过高",
                ))
                continue

            # 止盈 20%
            pnl_pct = (snap.close - pos.avg_cost) / pos.avg_cost if pos.avg_cost > 0 else 0
            if pnl_pct >= 0.20:
                orders.append(OrderIntent(
                    symbol=symbol,
                    action="sell",
                    shares=pos.available_shares,
                    reason=f"止盈: {pnl_pct:+.1%}",
                ))

        # === 买入逻辑 ===
        current_positions = len(state.positions)
        if current_positions >= max_positions:
            return orders

        candidates = []
        for symbol, snap in market.items():
            if symbol in state.positions:
                continue
            # 股息率筛选
            if snap.dividend_yield is None or snap.dividend_yield < min_dividend_yield:
                continue
            # PB 筛选
            if snap.pb is None or snap.pb > max_pb:
                continue

            candidates.append((symbol, snap, snap.dividend_yield))

        # 按股息率从高到低排序
        candidates.sort(key=lambda x: x[2], reverse=True)

        slots = max_positions - current_positions
        for symbol, snap, div_yield in candidates[:slots]:
            budget = state.cash * 0.45  # 每只最多用 45% 余款
            lots = int(budget / (snap.close * 100))
            if lots >= 1:
                shares = lots * 100
                orders.append(OrderIntent(
                    symbol=symbol,
                    action="buy",
                    shares=shares,
                    reason=f"股息率={div_yield:.2%}, PB={snap.pb:.1f}",
                ))
                slots -= 1
                if state.cash < 500:
                    break

        return orders
