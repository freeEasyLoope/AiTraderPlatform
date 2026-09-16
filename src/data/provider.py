"""市场数据提供者抽象。"""
from __future__ import annotations


from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketSnapshot:
    """市场快照 — 策略决策的输入。"""
    symbol: str
    name: str
    close: float
    open: float
    high: float
    low: float
    volume: float
    pe: Optional[float] = None
    pb: Optional[float] = None
    dividend_yield: Optional[float] = None
    change_pct: float = 0.0
    ma_5: Optional[float] = None
    ma_20: Optional[float] = None
    ma_60: Optional[float] = None
    rsi_14: Optional[float] = None
    boll_upper: Optional[float] = None
    boll_mid: Optional[float] = None
    boll_lower: Optional[float] = None
    turnover_rate: Optional[float] = None
    total_market_cap: Optional[float] = None

    @property
    def is_limit_up(self) -> bool:
        """主板 ±10% 涨停判断。"""
        return self.change_pct >= 0.099  # 接近涨停

    @property
    def is_limit_down(self) -> bool:
        """主板 ±10% 跌停判断。"""
        return self.change_pct <= -0.099


class MarketDataProvider(ABC):
    """市场数据提供者抽象。不同数据源（akshare/tushare）实现此接口。"""

    @abstractmethod
    def get_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        """获取单只股票快照。"""
        ...

    @abstractmethod
    def get_snapshots(self, symbols: list[str], date: str | None = None) -> dict[str, MarketSnapshot]:
        """批量获取快照。

        Args:
            symbols: 股票代码列表
            date: 交易日期 YYYY-MM-DD，用于获取历史指标
        """
        ...

    @abstractmethod
    def get_stock_universe(self, universe: str) -> list[str]:
        """获取标的池股票列表。

        Args:
            universe: hs300 / all / dividend_index / etf / macro

        Returns:
            股票代码列表
        """
        ...

    @abstractmethod
    def get_historical_data(
        self, symbols: list[str], start_date: str, end_date: str
    ) -> dict[str, list[MarketSnapshot]]:
        """获取历史数据（用于回测）。"""
        ...

    @abstractmethod
    def is_trading_day(self, date: str) -> bool:
        """判断是否为交易日。"""
        ...

    @abstractmethod
    def get_trading_days(self, year: int, month: int) -> list[str]:
        """获取指定月份的所有交易日。"""
        ...
