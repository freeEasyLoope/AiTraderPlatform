"""操盘手基类。"""
from __future__ import annotations


from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OrderIntent:
    """操盘手返回的交易意图，由引擎校验后执行。"""

    symbol: str           # 股票/基金代码
    action: str           # "buy" | "sell"
    shares: int           # 股数（正数）
    reason: str = ""      # 决策理由（用于日志/周报）


@dataclass
class Position:
    """持仓信息。"""

    symbol: str
    name: str
    type: str             # stock / fund / bond / gold_etf
    shares: int           # 总持有数量
    locked_shares: int = 0  # T+1 锁定数量
    avg_cost: float = 0.0
    buy_date: str = ""    # 首次买入日期 YYYY-MM-DD，用于持仓天数追踪
    last_buy_date: str = ""  # 最近一次加仓日期

    @property
    def available_shares(self) -> int:
        """可卖出数量。"""
        return self.shares - self.locked_shares

    @property
    def market_value(self) -> float:
        """市值（由引擎填入最新价）。"""
        return self._market_value

    @market_value.setter
    def market_value(self, value: float):
        self._market_value = value


@dataclass
class TraderState:
    """操盘手当前状态，传入 decide() 供策略使用。"""

    name: str
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    total_value: float = 0.0
    daily_pnl: float = 0.0
    params: dict = field(default_factory=dict)


class BaseTrader(ABC):
    """操盘手基类。

    子类只需实现 decide()，其余由引擎处理：
    - 资金校验
    - T+1 规则
    - 涨跌停校验
    - 手续费计算
    - 成交记录
    """

    def __init__(self, name: str, capital: float, params: Optional[dict] = None):
        self.name = name
        self.initial_capital = capital
        self.params = params or {}

    @abstractmethod
    def decide(
        self,
        state: TraderState,
        market: dict[str, object],   # dict[str, MarketSnapshot]
        date: str,
    ) -> list[OrderIntent]:
        """给定市场数据和当前状态，返回交易决策。

        Args:
            state: 当前操盘手状态（现金、持仓、参数等）
            market: 可选标的的市场快照 {symbol: MarketSnapshot}
            date: 当前日期 YYYY-MM-DD

        Returns:
            OrderIntent 列表，空列表表示今日不交易
        """
        ...

    def on_week_end(self, week_start: str, week_end: str) -> str:
        """周度反思（可选覆盖）。返回反思文本供 LLM 分析。"""
        return ""

    def get_strategy_name(self) -> str:
        return self.__class__.__name__
