"""5步漏斗主协调器 — 串联筛选步骤，管理降级和错误处理。"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .datasource import FunnelDataSource
from .models import ScreeningResult, StockAssessment, StepScore

logger = logging.getLogger(__name__)


class ScreenPipeline:
    """5步选股漏斗。

    用法:
        data = FunnelDataSource(akshare_client)
        pipeline = ScreenPipeline(data)
        result = pipeline.run(universe="all", steps=[1, 3, 5])
        print(f"{result.input_count} -> {result.output_count} 只")
    """

    # 步骤号 → 模块路径映射（懒加载）
    _STEP_MODULES = {
        1: ".filters.volume",
        2: ".filters.financial",
        3: ".filters.capital",
        4: ".filters.sector",
        5: ".filters.risk",
    }

    def __init__(self, data: FunnelDataSource, config: dict | None = None):
        self.data = data
        self.config = config or {}
        self._filter_funcs: dict[int, callable] = {}

    # ── 主入口 ────────────────────────────────────────

    def run(
        self,
        symbols: list[str] | None = None,
        universe: str = "all",
        date: str | None = None,
        steps: list[int] | None = None,
    ) -> ScreeningResult:
        """执行漏斗筛选。

        Args:
            symbols: 预先提供的候选列表。为 None 时从 universe 获取
            universe: 标的池类型
            date: 日期字符串
            steps: 要执行的步骤列表。为 None 时取配置中的默认值

        Returns:
            ScreeningResult 含通过筛选的股票列表和每步详情
        """
        from datetime import datetime
        date = date or datetime.now().strftime("%Y-%m-%d")
        steps = steps or self._get_default_steps()

        t0 = time.monotonic()
        errors: list[str] = []

        # 1. 获取初始候选池
        if symbols is None:
            symbols = self.data.get_stock_universe(universe)

        symbols = [s for s in symbols if s and not s.startswith(("*", "ST", "退"))]
        input_count = len(symbols)
        current = list(symbols)
        logger.info(f"漏斗启动: {input_count} 只, 步骤 {steps}")

        # 初始化评估
        assessments: dict[str, StockAssessment] = {
            s: StockAssessment(symbol=s) for s in symbols
        }
        step_stats: dict[int, dict] = {}

        # 2. 逐步过滤
        for step_num in steps:
            before = len(current)
            try:
                filter_fn = self._load_filter(step_num)
                params = self._get_step_params(step_num)
                step_scores = filter_fn(self.data, current, params)

                # 应用结果
                new_current = []
                for s in current:
                    score = step_scores.get(s)
                    if score is None:
                        # 没有结果 = 数据不足，放行
                        score = StepScore(step=step_num, passed=True, score=0.5,
                                          reason="数据不足，放行")
                    if s in assessments:
                        assessments[s].steps.append(score)
                    if score.passed:
                        new_current.append(s)

                current = new_current
                after = len(current)
                step_stats[step_num] = {"before": before, "after": after,
                                         "dropped": before - after}
                logger.info(f"  第{step_num}步: {before} -> {after} (-{before - after})")

            except Exception as e:
                msg = f"第{step_num}步异常: {e}"
                logger.warning(msg)
                errors.append(msg)
                step_stats[step_num] = {"before": before, "after": before,
                                         "dropped": 0, "error": str(e)}
                # 异常时放行全部

        # 3. 汇总
        for sym in assessments:
            a = assessments[sym]
            a.passed = sym in current
            if a.steps:
                a.total_score = sum(s.score for s in a.steps) / len(a.steps)

        result = ScreeningResult(
            date=date,
            universe=universe,
            input_count=input_count,
            output_count=len(current),
            assessments=assessments,
            passed_symbols=current,
            step_stats=step_stats,
            errors=errors,
            duration_ms=round((time.monotonic() - t0) * 1000),
        )

        logger.info(
            f"漏斗完成: {input_count} -> {len(current)} 只, "
            f"耗时 {result.duration_ms}ms"
        )
        return result

    # ── 内部方法 ──────────────────────────────────────

    def _load_filter(self, step: int):
        """懒加载 filter 函数。"""
        if step in self._filter_funcs:
            return self._filter_funcs[step]

        module_path = self._STEP_MODULES.get(step)
        if module_path is None:
            raise ValueError(f"未知步骤: {step}")

        import importlib
        mod = importlib.import_module(module_path, package="src.screening")
        # 约定：每个 filter 模块导出一个同名函数
        func_name = f"filter_{['', 'volume', 'financial', 'capital', 'sector', 'risk'][step]}"
        func = getattr(mod, func_name, None)
        if func is None:
            raise ValueError(f"模块 {module_path} 中未找到 {func_name}")

        self._filter_funcs[step] = func
        return func

    def _get_default_steps(self) -> list[int]:
        """从配置或默认返回活跃步骤列表。"""
        return self.config.get("active_steps", [1, 3, 5])

    def _get_step_params(self, step: int) -> dict:
        """获取某步骤的配置参数。"""
        key_map = {
            1: "step1_volume",
            2: "step2_financial",
            3: "step3_capital",
            4: "step4_sector",
            5: "step5_risk",
        }
        return self.config.get(key_map.get(step, ""), {})
