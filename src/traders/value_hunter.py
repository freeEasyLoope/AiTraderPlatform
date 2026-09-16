"""价值猎手 — PE/PB 价值投资策略。

逻辑：
- 筛选 PE < 行业均值 * 0.7 且 PB < 2.0 的股票
- 按 PE 从低到高排序，取前 max_positions 只
- 已持仓 PE 回归行业均值 → 卖出
- 止盈 +30%，止损 -15%
"""
from __future__ import annotations


import logging
from typing import Optional

from .base import BaseTrader, OrderIntent, TraderState
from ..data.provider import MarketSnapshot

logger = logging.getLogger(__name__)


class ValueHunter(BaseTrader):
    """价值猎手 — 寻找低估值的优质股票。"""

    def decide(
        self,
        state: TraderState,
        market: dict[str, MarketSnapshot],
        date: str,
    ) -> list[OrderIntent]:
        orders: list[OrderIntent] = []
        params = self.params

        max_positions: int = params.get("max_positions", 5)
        pe_threshold: float = params.get("pe_threshold", 0.7)
        pb_max: float = params.get("pb_max", 2.0)
        take_profit: float = params.get("take_profit", 0.30)
        stop_loss: float = params.get("stop_loss", -0.15)

        # 计算行业平均 PE
        industry_pe = self._calc_industry_avg_pe(market)

        # === 卖出逻辑 ===
        for symbol, pos in list(state.positions.items()):
            snap = market.get(symbol)
            if snap is None:
                continue

            # 计算盈亏
            pnl_pct = (snap.close - pos.avg_cost) / pos.avg_cost if pos.avg_cost > 0 else 0

            sell_reason: Optional[str] = None

            # 止盈
            if pnl_pct >= take_profit:
                sell_reason = f"止盈: {pnl_pct:+.1%}"
            # 止损
            elif pnl_pct <= stop_loss:
                sell_reason = f"止损: {pnl_pct:+.1%}"
            # PE 回归行业均值
            elif snap.pe and industry_pe and snap.pe >= industry_pe:
                sell_reason = f"PE({snap.pe:.1f}) >= 行业均值({industry_pe:.1f})"

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
        slots_available = max_positions - current_positions
        if slots_available <= 0:
            return orders

        # 筛选候选
        candidates = []
        for symbol, snap in market.items():
            # 跳过已持仓
            if symbol in state.positions:
                continue
            # PE 筛选
            if snap.pe is None or snap.pe <= 0:
                continue
            # PB 筛选
            if snap.pb is None or snap.pb > pb_max:
                continue
            # PE 低于行业均值
            if industry_pe and snap.pe >= industry_pe * pe_threshold:
                continue

            candidates.append((symbol, snap))

        # 按 PE 从低到高排序
        candidates.sort(key=lambda x: x[1].pe or 9999)

        # 买入（按 PE 从低到高依次建仓）
        for symbol, snap in candidates[:slots_available]:
            # 集中持仓：前 2 只最佳标的各用一半现金
            focus = min(slots_available, 2)
            budget = state.cash * 0.45  # 每只最多用 45% 余款
            lots = int(budget / (snap.close * 100))
            if lots >= 1:
                shares = lots * 100
                orders.append(OrderIntent(
                    symbol=symbol,
                    action="buy",
                    shares=shares,
                    reason=f"PE={snap.pe:.1f}, PB={snap.pb:.1f}, 低估值",
                ))
                slots_available -= 1
                if state.cash < snap.close * 100:
                    break

        return orders

    def _calc_industry_avg_pe(self, market: dict[str, MarketSnapshot]) -> Optional[float]:
        """计算市场 PE 中位数（简化版行业均值）。"""
        pes = [s.pe for s in market.values() if s.pe and s.pe > 0 and s.pe < 500]
        if not pes:
            return None
        pes.sort()
        return pes[len(pes) // 2]  # 中位数
