"""指数定投者 — 定期定额投资宽基指数。

逻辑：
- 每周第一个交易日固定金额买入指定 ETF
- 不卖出（长期持有）
"""

from __future__ import annotations

import logging

from .base import BaseTrader, OrderIntent, TraderState
from ..data.provider import MarketSnapshot

logger = logging.getLogger(__name__)


class IndexDca(BaseTrader):
    """指数定投者 — 永不卖出，坚持定投。"""

    def decide(
        self,
        state: TraderState,
        market: dict[str, MarketSnapshot],
        date: str,
    ) -> list[OrderIntent]:
        orders: list[OrderIntent] = []
        params = self.params

        weekly_amount: float = params.get("weekly_amount", 50.0)
        etf_symbol: str = params.get("etf_symbol", "510300")

        # 判断是否是定投日（每周第一个交易日）
        if not self._is_dca_day(date):
            return []

        # 检查是否有足够资金
        if state.cash < weekly_amount:
            logger.info(f"指数定投者: 资金不足, 跳过 (现金 ${state.cash:,.2f})")
            return []

        snap = market.get(etf_symbol)
        if snap is None:
            logger.warning(f"指数定投者: 未找到 {etf_symbol} 行情")
            return []

        # 买入
        lots = int(weekly_amount / (snap.close * 100))
        if lots >= 1:
            shares = lots * 100
            orders.append(OrderIntent(
                symbol=etf_symbol,
                action="buy",
                shares=shares,
                reason=f"每周定投, ${shares * snap.close:,.2f}",
            ))

        return orders

    def _is_dca_day(self, date: str) -> bool:
        """判断是否是每周定投日（周一）。

        简化实现：周一即定投日。
        精确实现需要交易日历。
        """
        from datetime import datetime
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            return dt.weekday() == 0  # 周一
        except (ValueError, IndexError):
            return False
