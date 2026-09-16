"""模拟器集成测试。"""

from __future__ import annotations

import pytest

from src.engine.simulator import Simulator
from src.engine.matcher import TradeMatcher
from src.data.mock_client import MockDataProvider
from src.traders.registry import TraderRegistry
from src.storage.repository import Repository
from src.traders.value_hunter import ValueHunter
from src.traders.trend_follower import TrendFollower
from src.traders.macro_hedger import MacroHedger


@pytest.fixture
def registry():
    reg = TraderRegistry()
    reg.register("value_hunter.ValueHunter", ValueHunter)
    reg.register("trend_follower.TrendFollower", TrendFollower)
    reg.register("macro_hedger.MacroHedger", MacroHedger)
    return reg


@pytest.fixture
def repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    r = Repository(db_path)
    r.init_traders([
        {"name": "价值猎手", "class": "value_hunter.ValueHunter",
         "initial_capital": 1666.67},
        {"name": "趋势跟随者", "class": "trend_follower.TrendFollower",
         "initial_capital": 1666.67},
        {"name": "宏观对冲者", "class": "macro_hedger.MacroHedger",
         "initial_capital": 1666.67},
    ])
    return r


class TestSimulator:
    def test_run_daily_no_crash(self, repo, registry):
        """run_daily 不崩溃且返回结果。"""
        data = MockDataProvider(seed=42)
        sim = Simulator(repo, data, registry)

        results = sim.run_daily("2026-06-08")  # Monday

        assert isinstance(results, dict)
        # 应该有 3 个操盘手的结果
        assert len(results) == 3

    def test_run_daily_skip_weekend(self, repo, registry):
        """周末跳过交易。"""
        data = MockDataProvider(seed=42)
        sim = Simulator(repo, data, registry)

        results = sim.run_daily("2026-06-07")  # Sunday

        assert results == {}

    def test_run_multi_day(self, repo, registry):
        """连续多日交易不崩溃。"""
        data = MockDataProvider(seed=42)
        sim = Simulator(repo, data, registry)

        for date in ["2026-06-08", "2026-06-09", "2026-06-10"]:
            results = sim.run_daily(date)
            assert isinstance(results, dict)

    def test_idempotent_check(self, repo, registry):
        """同一天重复执行被跳过。"""
        data = MockDataProvider(seed=42)
        sim = Simulator(repo, data, registry)

        first = sim.run_daily("2026-06-08")
        second = sim.run_daily("2026-06-08")
        # 第二次应该返回空（幂等保护）
        assert second == {}
