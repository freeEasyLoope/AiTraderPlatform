"""A股 5步选股漏斗 — 统一的预筛选层。

在策略决策之前缩小候选池：
① 成交量+PE+退市风险 → ② 财务排雷 → ③ 资金流向验证 → ④ 行业景气度 → ⑤ 风险过滤
"""

from .models import ScreeningResult, StockAssessment, StepScore
from .pipeline import ScreenPipeline

__all__ = ["ScreenPipeline", "ScreeningResult", "StockAssessment", "StepScore"]
