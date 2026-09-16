"""价值猎手策略单元测试。"""

from __future__ import annotations

import pytest

from src.traders.value_hunter import ValueHunter
from src.traders.base import TraderState, Position
from src.data.provider import MarketSnapshot


def make_snap(symbol="600519", close=100.0, pe=15.0, pb=1.5) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol, name="测试", close=close, open=99.0,
        high=101.0, low=98.0, volume=1e6, change_pct=0.02,
        pe=pe, pb=pb,
    )


class TestValueHunter:
    def test_no_trade_when_no_candidates(self):
        """所有股票 PE 太高时不交易。"""
        hunter = ValueHunter("test", 100000, {"max_positions": 5, "pe_threshold": 0.7})
        state = TraderState(name="test", cash=100000, params=hunter.params)

        market = {
            "A": make_snap("A", 10, pe=50, pb=1.0),  # PE 太高
            "B": make_snap("B", 20, pe=60, pb=1.0),
        }

        orders = hunter.decide(state, market, "2026-06-05")
        assert len(orders) == 0

    def test_buy_low_pe_pb(self):
        """低 PE 低 PB 股票被买入。"""
        hunter = ValueHunter("test", 10000, {"max_positions": 3, "pe_threshold": 0.7, "pb_max": 2.0})
        state = TraderState(name="test", cash=10000, params=hunter.params)

        market = {
            "A": make_snap("A", 10, pe=8, pb=1.0),    # 低估值
            "B": make_snap("B", 20, pe=50, pb=1.0),   # PE 太高
            "C": make_snap("C", 30, pe=5, pb=0.5),    # 极低估值
        }

        orders = hunter.decide(state, market, "2026-06-05")

        buy_orders = [o for o in orders if o.action == "buy"]
        assert len(buy_orders) >= 1  # 至少买入一只

        # 应该优先买入 PE 最低的 C
        if buy_orders:
            assert buy_orders[0].symbol == "C"  # PE=5 最低

    def test_sell_on_stop_loss(self):
        """止损卖出。"""
        hunter = ValueHunter("test", 10000, {"max_positions": 5, "stop_loss": -0.15})
        state = TraderState(name="test", cash=5000, params=hunter.params, positions={
            "BAD": Position("BAD", "坏股票", "stock", 100, 0, 100.0),
        })

        # 股价从 100 跌到 80（-20%，超过 -15% 止损线）
        market = {"BAD": make_snap("BAD", 80.0)}

        orders = hunter.decide(state, market, "2026-06-05")

        sell_orders = [o for o in orders if o.action == "sell"]
        assert len(sell_orders) == 1
        assert "止损" in sell_orders[0].reason
