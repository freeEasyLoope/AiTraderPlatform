"""漏斗集成测试 — 用 mock 数据验证 5 步全流程。"""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from src.screening.models import ScreeningResult, StockAssessment, StepScore
from src.screening.pipeline import ScreenPipeline
from src.screening.datasource import FunnelDataSource


class TestStepScore:
    def test_passed_score(self):
        s = StepScore(step=1, passed=True, score=0.9, reason="通过")
        assert s.passed
        assert s.score == 0.9

    def test_failed_score(self):
        s = StepScore(step=1, passed=False, score=0.0, reason="PE过高")
        assert not s.passed


class TestScreeningResult:
    def test_empty_result(self):
        r = ScreeningResult(date="2026-06-11", input_count=100, output_count=0)
        assert r.input_count == 100
        assert r.output_count == 0
        assert len(r.passed_symbols) == 0

    def test_with_passed(self):
        r = ScreeningResult(
            date="2026-06-11",
            input_count=100,
            output_count=30,
            passed_symbols=["600519", "000858"],
            step_stats={1: {"before": 100, "after": 60, "dropped": 40}},
        )
        assert len(r.passed_symbols) == 2
        assert r.step_stats[1]["dropped"] == 40


class TestPipelineWithMockData:
    """用 mock FunnelDataSource 测试完整流程。"""

    def _make_mock_data_source(self):
        """构建一个返回可控数据的 FunnelDataSource。"""
        ds = MagicMock(spec=FunnelDataSource)

        # 全市场行情：5 只模拟股票
        ds.get_market_spot.return_value = pd.DataFrame([
            {"代码": "600519", "名称": "贵州茅台", "市盈率-动态": 20, "市净率": 8,
             "换手率": 0.8, "总市值": 2e12, "行业": "白酒"},
            {"代码": "000858", "名称": "五粮液", "市盈率-动态": 35, "市净率": 5,
             "换手率": 1.2, "总市值": 8e11, "行业": "白酒"},
            {"代码": "600000", "名称": "浦发银行", "市盈率-动态": 5, "市净率": 0.6,
             "换手率": 0.3, "总市值": 3e11, "行业": "银行"},
            {"代码": "300750", "名称": "宁德时代", "市盈率-动态": 80, "市净率": 6,
             "换手率": 3.0, "总市值": 1e12, "行业": "新能源"},
            {"代码": "000001", "名称": "*ST平安", "市盈率-动态": 12, "市净率": 1.5,
             "换手率": 0.1, "总市值": 5e10, "行业": "金融"},
        ])

        # 历史成交量（近 30 日每日成交量）
        # avg_5d / avg_all >= 1.1 才算温和放量
        ds.get_historical_volume.return_value = {
            "600519": [1e6] * 25 + [1.5e6] * 5,   # avg_5d=1.5M, avg_all=1.08M, ratio=1.38 > 1.1
            "000858": [1e6] * 25 + [1.3e6] * 5,   # avg_5d=1.3M, avg_all=1.05M, ratio=1.24 > 1.1
            "600000": [5e5] * 25 + [7e5] * 5,     # avg_5d=0.7M, avg_all=0.53M, ratio=1.31 > 1.1
            "300750": [2e6] * 25 + [3e6] * 5,     # 明显放大
            "000001": [1e4] * 30,                  # 极低量
        }

        # 主力资金流向
        ds.get_individual_fund_flow.return_value = {
            "600519": {"main_net_10d": 5e7, "super_large_net_10d": 2e7},
            "000858": {"main_net_10d": -1e7, "super_large_net_10d": -5e6},
            "600000": {"main_net_10d": 1e8, "super_large_net_10d": 5e7},
            "300750": {"main_net_10d": 8e7, "super_large_net_10d": 4e7},
        }

        # 北向资金
        ds.get_north_bound_flow.return_value = {
            "daily_flows": [1e8, 2e8, -5e7, 3e8, 1e8],
            "cumulative": 6.5e8,
            "trend": "inflow",
        }

        # 回撤
        ds.get_price_drawdown.return_value = {
            "600519": {"max_drawdown": 0.10, "drawdown_from_peak": 0.05},
            "000858": {"max_drawdown": 0.25, "drawdown_from_peak": 0.20},
            "600000": {"max_drawdown": 0.05, "drawdown_from_peak": 0.01},
            "300750": {"max_drawdown": 0.45, "drawdown_from_peak": 0.40},
        }

        # 解禁
        ds.get_restricted_shares.return_value = {}

        # 财务（默认不活跃）
        ds.get_financial_performance.return_value = {}
        ds.get_balance_health.return_value = {}

        # 行业
        ds.get_industry_map.return_value = {}
        ds.get_industry_performance.return_value = pd.DataFrame()

        return ds

    def test_pipeline_135_steps(self):
        """测试第①③⑤步漏斗：应正确淘汰 ST、PE虚高、资金流出、高回撤的股票。"""
        ds = self._make_mock_data_source()

        config = {
            "active_steps": [1, 3, 5],
            "step1_volume": {"volume_window": 30, "volume_amplify_min": 1.1,
                             "pe_vs_industry_max": 1.0, "exclude_st": True},
            "step3_capital": {"main_net_inflow_days": 10, "north_net_inflow_days": 10,
                              "require_north": False},
            "step5_risk": {"max_drawdown_60d": 0.30, "restricted_share_days": 30,
                           "pe_extreme_multiple": 3.0},
        }

        symbols = ["600519", "000858", "600000", "300750", "000001"]
        pipeline = ScreenPipeline(ds, config=config)
        result = pipeline.run(symbols=symbols, steps=[1, 3, 5])

        # 验证
        assert result.input_count == 5
        assert result.output_count < 5  # 至少淘汰一部分

        # 000001 (*ST) 应该在步骤1被淘汰
        a_st = result.assessments.get("000001")
        assert a_st is not None
        assert not a_st.passed
        step1_st = next((s for s in a_st.steps if s.step == 1), None)
        assert step1_st is not None
        assert "ST" in step1_st.reason

        # 300750 (高 PE + 高回撤) 应该被淘汰
        a_300750 = result.assessments.get("300750")
        # PE=80 >> 行业中位数, 且 max_drawdown=0.45 > 0.30
        step1 = next((s for s in a_300750.steps if s.step == 1), None)
        step5 = next((s for s in a_300750.steps if s.step == 5), None)
        assert (step1 and not step1.passed) or (step5 and not step5.passed)

        # 600519 (合理 PE + 资金流入 + 低回撤) 应该通过
        assert "600519" in result.passed_symbols

        # 步骤统计应该存在
        for step_num in [1, 3, 5]:
            assert step_num in result.step_stats

    def test_pipeline_stops_early_on_no_candidates(self):
        """空候选池应立即返回。"""
        ds = self._make_mock_data_source()
        pipeline = ScreenPipeline(ds)

        result = pipeline.run(symbols=[], steps=[1, 3, 5])
        assert result.input_count == 0
        assert result.output_count == 0

    def test_step_failure_does_not_crash_pipeline(self):
        """某步骤抛异常时，不应崩溃，应放行全部。"""
        ds = self._make_mock_data_source()
        # 让第3步抛异常
        ds.get_individual_fund_flow.side_effect = RuntimeError("API 挂了")

        pipeline = ScreenPipeline(ds)
        result = pipeline.run(symbols=["600519", "000858", "600000", "300750", "000001"],
                              steps=[1, 3, 5])

        # 不应崩溃
        assert result.input_count == 5
        # 第3步出错，全部放行
        assert len(result.errors) >= 1
