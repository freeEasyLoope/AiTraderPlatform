"""模拟数据客户端 — 用于开发测试，无需 akshare。

生成模拟的 A 股市场数据，覆盖沪深300成分股 + ETF + 黄金。
数据包含 PE、PB、RSI、布林带等指标，使所有策略都能触发买卖。
"""
from __future__ import annotations


import random
from datetime import datetime, timedelta
from typing import Optional

from .provider import MarketDataProvider, MarketSnapshot


class MockDataProvider(MarketDataProvider):
    """模拟市场数据提供者。

    生成合理范围内的模拟数据，使六个策略都能正常运转。
    通过 seed 保证可重复性。
    """

    # 模拟股票池（沪深300代表性标的）
    STOCK_POOL = [
        ("600519", "贵州茅台"), ("000858", "五粮液"), ("601318", "中国平安"),
        ("600036", "招商银行"), ("000333", "美的集团"), ("600276", "恒瑞医药"),
        ("000651", "格力电器"), ("601398", "工商银行"), ("600030", "中信证券"),
        ("000725", "京东方A"), ("002415", "海康威视"), ("600900", "长江电力"),
        ("601888", "中国中免"), ("000568", "泸州老窖"), ("600809", "山西汾酒"),
        ("300750", "宁德时代"), ("300059", "东方财富"), ("002594", "比亚迪"),
        ("601012", "隆基绿能"), ("688981", "中芯国际"), ("000002", "万科A"),
        ("600048", "保利发展"), ("600585", "海螺水泥"), ("601668", "中国建筑"),
        ("600019", "宝钢股份"), ("000063", "中兴通讯"), ("002230", "科大讯飞"),
        ("600570", "恒生电子"), ("300124", "汇川技术"), ("002475", "立讯精密"),
    ]

    ETF_POOL = [
        ("510300", "沪深300ETF"),
        ("510050", "上证50ETF"),
    ]

    BOND_POOL = [
        ("511010", "国债ETF"),
        ("511260", "10年国债ETF"),
    ]

    GOLD_POOL = [
        ("518880", "黄金ETF"),
        ("159934", "黄金ETF易方达"),
    ]

    UNIVERSE_MAP = {
        "hs300": [s[0] for s in STOCK_POOL],
        "all": [s[0] for s in STOCK_POOL],
        "dividend_index": [s[0] for s in STOCK_POOL[:10]],  # 前10只有分红
        "etf": ["510300"],
        "macro": ["510300", "511010", "518880"],
    }

    def __init__(self, seed: int = 42):
        random.seed(seed)
        self._price_cache: dict[str, float] = {}
        self._init_prices()

    def _init_prices(self):
        """初始化基础价格。"""
        for symbol, _ in self.STOCK_POOL:
            self._price_cache[symbol] = random.uniform(5, 200)
        for symbol, _ in self.ETF_POOL:
            self._price_cache[symbol] = random.uniform(3, 5)
        for symbol, _ in self.BOND_POOL:
            self._price_cache[symbol] = random.uniform(100, 105)
        for symbol, _ in self.GOLD_POOL:
            self._price_cache[symbol] = random.uniform(4, 6)

    def _random_walk(self, symbol: str, date: str) -> MarketSnapshot:
        """生成一只股票的随机游走快照。"""
        base = self._price_cache.get(symbol, 10.0)

        # 基于日期做确定性随机
        date_seed = hash(f"{symbol}:{date}") % 10000
        rng = random.Random(date_seed)

        change_pct = rng.uniform(-0.08, 0.08)  # -8% ~ +8%
        close = base * (1 + change_pct)
        open_price = close * rng.uniform(0.99, 1.01)
        high = max(open_price, close) * rng.uniform(1.00, 1.02)
        low = min(open_price, close) * rng.uniform(0.98, 1.00)

        # 更新缓存
        self._price_cache[symbol] = close

        # 技术指标
        ma5 = close * rng.uniform(0.97, 1.03)
        ma20 = close * rng.uniform(0.95, 1.05)
        ma60 = close * rng.uniform(0.90, 1.10)
        rsi = rng.uniform(20, 80)
        boll_mid = close * rng.uniform(0.98, 1.02)
        boll_upper = boll_mid * 1.05
        boll_lower = boll_mid * 0.95

        # 估值指标
        pe = rng.uniform(8, 60) if rng.random() > 0.1 else None
        pb = rng.uniform(0.5, 5.0) if rng.random() > 0.1 else None
        div_yield = rng.uniform(0.01, 0.06) if symbol in [s[0] for s in self.STOCK_POOL[:10]] else None

        return MarketSnapshot(
            symbol=symbol,
            name=dict(self.STOCK_POOL + self.ETF_POOL + self.BOND_POOL + self.GOLD_POOL).get(symbol, symbol),
            close=close,
            open=open_price,
            high=high,
            low=low,
            volume=rng.uniform(1e6, 1e8),
            pe=pe,
            pb=pb,
            dividend_yield=div_yield,
            change_pct=change_pct,
            ma_5=ma5,
            ma_20=ma20,
            ma_60=ma60,
            rsi_14=rsi,
            boll_upper=boll_upper,
            boll_mid=boll_mid,
            boll_lower=boll_lower,
            turnover_rate=rng.uniform(0.5, 8.0),
            total_market_cap=rng.uniform(5e9, 2e12),
        )

    def get_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        today = datetime.now().strftime("%Y-%m-%d")
        return self._random_walk(symbol, today)

    def get_snapshots(self, symbols: list[str], date: str = None) -> dict[str, MarketSnapshot]:
        today = date or datetime.now().strftime("%Y-%m-%d")
        result = {}
        for s in symbols:
            result[s] = self._random_walk(s, today)
        return result

    def get_stock_universe(self, universe: str) -> list[str]:
        return self.UNIVERSE_MAP.get(universe, self.UNIVERSE_MAP["hs300"])

    def get_historical_data(
        self, symbols: list[str], start_date: str, end_date: str
    ) -> dict[str, list[MarketSnapshot]]:
        result: dict[str, list[MarketSnapshot]] = {}
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        days = (end - start).days

        for symbol in symbols:
            snapshots = []
            for i in range(days):
                date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
                # 跳过周末
                dt = start + timedelta(days=i)
                if dt.weekday() >= 5:
                    continue
                snapshots.append(self._random_walk(symbol, date))
            result[symbol] = snapshots
        return result

    def is_trading_day(self, date: str) -> bool:
        dt = datetime.strptime(date, "%Y-%m-%d")
        return dt.weekday() < 5

    def get_trading_days(self, year: int, month: int) -> list[str]:
        result = []
        dt = datetime(year, month, 1)
        while dt.month == month:
            if dt.weekday() < 5:
                result.append(dt.strftime("%Y-%m-%d"))
            dt += timedelta(days=1)
        return result
