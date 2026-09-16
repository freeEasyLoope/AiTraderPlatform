"""第③步：主力资金 + 北向资金近10日净流入验证。

淘汰条件：
- 近10日主力资金净流出
- 北向资金整体呈流出趋势（可选）
"""

from __future__ import annotations

import logging

from ..datasource import FunnelDataSource
from ..models import StepScore

logger = logging.getLogger(__name__)


def filter_capital(
    data: FunnelDataSource,
    symbols: list[str],
    params: dict,
) -> dict[str, StepScore]:
    """执行资金流向验证。"""
    main_days = params.get("main_net_inflow_days", 10)
    north_days = params.get("north_net_inflow_days", 10)
    require_north = params.get("require_north", False)

    result: dict[str, StepScore] = {}

    # 1. 北向资金整体趋势
    north_data = data.get_north_bound_flow(days=north_days)
    north_trend = north_data.get("trend", "unknown")
    north_ok = north_trend == "inflow"

    # 2. 个股主力资金
    fund_flows = data.get_individual_fund_flow(symbols, days=main_days)

    # 3. 逐只判断
    for symbol in symbols:
        flow = fund_flows.get(symbol)
        failed = []

        if flow is None:
            # 无主力资金数据 → 放行
            result[symbol] = StepScore(step=3, passed=True, score=0.4,
                                        reason="无资金流向数据")
            continue

        main_net = flow.get("main_net_10d", 0)

        if main_net <= 0:
            failed.append(f"主力净流出({main_net/1e4:.0f}万)")

        if require_north and not north_ok:
            failed.append(f"北向资金趋势: {north_trend}")

        passed = len(failed) == 0
        # 主力净流入越大分数越高
        main_score = min(1.0, max(0.1, 0.5 + main_net / 1e8)) if main_net > 0 else 0.2
        score = main_score if passed else 0.1

        result[symbol] = StepScore(
            step=3, passed=passed, score=score,
            reason="; ".join(failed) if failed else f"主力净流入 {main_net/1e4:.0f}万",
            metrics=flow,
        )

    return result
