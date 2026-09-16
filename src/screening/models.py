"""漏斗数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StepScore:
    """单只股票在某个筛选步骤中的结果。"""

    step: int
    passed: bool
    score: float = 0.0  # 0.0 ~ 1.0 归一化评分
    reason: str = ""  # 通过/淘汰原因（人类可读）
    metrics: dict = field(default_factory=dict)  # 原始指标快照


@dataclass
class StockAssessment:
    """单只股票通过全部漏斗的完整评估。"""

    symbol: str
    name: str = ""
    passed: bool = False  # 通过所有活跃步骤
    steps: list[StepScore] = field(default_factory=list)
    total_score: float = 0.0  # 加权综合分
    industry: str = ""
    pe: Optional[float] = None
    pb: Optional[float] = None
    market_cap: Optional[float] = None


@dataclass
class ScreeningResult:
    """一次漏斗运行的完整输出。"""

    date: str
    universe: str = "all"
    input_count: int = 0
    output_count: int = 0
    assessments: dict[str, StockAssessment] = field(default_factory=dict)
    passed_symbols: list[str] = field(default_factory=list)
    step_stats: dict[int, dict] = field(default_factory=dict)
    # step_stats 格式: {1: {"before": 500, "after": 200, "dropped": 300}, ...}
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
