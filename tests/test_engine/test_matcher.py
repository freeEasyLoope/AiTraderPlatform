"""交易撮合引擎单元测试。"""

from __future__ import annotations

import pytest

from src.engine.matcher import TradeMatcher, MatchResult
from src.traders.base import OrderIntent, TraderState, Position
from src.data.provider import MarketSnapshot


def make_snap(symbol="600519", close=100.0, change_pct=0.02) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol, name="测试", close=close, open=99.0,
        high=101.0, low=98.0, volume=1e6, change_pct=change_pct,
    )


class TestTradeMatcher:
    def setup_method(self):
        self.matcher = TradeMatcher(
            stamp_tax=0.001, commission=0.0003,
            min_shares=100, price_limit_main=0.10,
        )

    def test_buy_success(self):
        """正常买入：资金充足，整手。"""
        state = TraderState(name="test", cash=50000)
        market = {"600519": make_snap("600519", 100.0)}
        order = OrderIntent("600519", "buy", 200, "测试买入")

        result = self.matcher.match_one(state, order, market, "2026-06-05")

        assert result.status == "filled"
        assert result.executed_price == 100.0
        assert result.fee > 0  # 佣金

    def test_buy_insufficient_funds(self):
        """资金不足被拒绝。"""
        state = TraderState(name="test", cash=500)
        market = {"600519": make_snap("600519", 100.0)}
        order = OrderIntent("600519", "buy", 100)

        result = self.matcher.match_one(state, order, market, "2026-06-05")

        assert result.status == "rejected"
        assert "资金不足" in result.reject_reason

    def test_sell_success(self):
        """正常卖出。"""
        state = TraderState(name="test", cash=10000, positions={
            "600519": Position("600519", "茅台", "stock", 200, 0, 90.0),
        })
        market = {"600519": make_snap("600519", 100.0)}
        order = OrderIntent("600519", "sell", 100, "止盈")

        result = self.matcher.match_one(state, order, market, "2026-06-05")

        assert result.status == "filled"
        assert result.fee > 0  # 佣金 + 印花税

    def test_sell_t_plus_1_blocked(self):
        """T+1：今日买入的股票不能卖。"""
        state = TraderState(name="test", cash=10000, positions={
            "600519": Position("600519", "茅台", "stock", 200, 200, 90.0),  # 全部锁定
        })
        market = {"600519": make_snap("600519", 100.0)}
        order = OrderIntent("600519", "sell", 100)

        result = self.matcher.match_one(state, order, market, "2026-06-05")

        assert result.status == "rejected"
        assert "不足" in result.reject_reason

    def test_limit_up_block_buy(self):
        """涨停不能买入。"""
        state = TraderState(name="test", cash=50000)
        market = {"600519": make_snap("600519", 100.0, change_pct=0.099)}
        order = OrderIntent("600519", "buy", 100)

        result = self.matcher.match_one(state, order, market, "2026-06-05")

        assert result.status == "rejected"
        assert "涨停" in result.reject_reason

    def test_limit_down_block_sell(self):
        """跌停不能卖出。"""
        state = TraderState(name="test", cash=10000, positions={
            "600519": Position("600519", "茅台", "stock", 200, 0, 90.0),
        })
        market = {"600519": make_snap("600519", 100.0, change_pct=-0.099)}
        order = OrderIntent("600519", "sell", 100)

        result = self.matcher.match_one(state, order, market, "2026-06-05")

        assert result.status == "rejected"
        assert "跌停" in result.reject_reason

    def test_min_lot_size(self):
        """非整手被拒绝。"""
        state = TraderState(name="test", cash=50000)
        market = {"600519": make_snap("600519", 100.0)}
        order = OrderIntent("600519", "buy", 150)  # 不是 100 的整数倍

        result = self.matcher.match_one(state, order, market, "2026-06-05")

        assert result.status == "rejected"

    def test_unlock_t_plus_1(self):
        """收盘后 T+1 解冻。"""
        positions = [
            Position("600519", "", "stock", 100, 100, 0),  # locked
            Position("000858", "", "stock", 200, 200, 0),  # all locked
        ]
        self.matcher.unlock_t_plus_1(positions)
        assert positions[0].locked_shares == 0
        assert positions[1].locked_shares == 0
