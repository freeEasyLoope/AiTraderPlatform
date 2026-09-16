"""第⑤步：回撤 + 解禁 + 极端估值风险过滤。

淘汰条件：
- 60日最大回撤 > max_drawdown_60d
- 未来 N 日内有限售股解禁
- PE > 行业PE × extreme_multiple（极端高估）
"""

from __future__ import annotations

import logging

from ..datasource import FunnelDataSource
from ..models import StepScore

logger = logging.getLogger(__name__)


def filter_risk(
    data: FunnelDataSource,
    symbols: list[str],
    params: dict,
) -> dict[str, StepScore]:
    """执行风险过滤。"""
    max_dd = params.get("max_drawdown_60d", 0.30)
    restricted_days = params.get("restricted_share_days", 30)
    pe_extreme = params.get("pe_extreme_multiple", 3.0)

    result: dict[str, StepScore] = {}

    # 1. 获取回撤数据
    drawdowns = data.get_price_drawdown(symbols, days=60)

    # 2. 获取解禁数据
    restricted = data.get_restricted_shares(lookahead_days=restricted_days)

    # 3. 获取 PE（复用 spot 数据）
    spot_df = data.get_market_spot()
    pe_map: dict[str, float] = {}
    industry_map: dict[str, str] = {}
    for _, row in spot_df.iterrows():
        code = str(row.get("代码", ""))
        try:
            pe = float(row.get("市盈率-动态", 0) or 0)
        except (ValueError, TypeError):
            pe = 0.0
        pe_map[code] = pe
        industry_map[code] = str(row.get("行业", "其他"))

    # 计算行业 PE 中位数
    from .volume import _calc_industry_median_pe
    industry_median = _calc_industry_median_pe(spot_df)

    # 4. 逐只判断
    for symbol in symbols:
        failed = []
        metrics: dict = {}

        # — 回撤 —
        dd_data = drawdowns.get(symbol, {})
        dd = dd_data.get("max_drawdown", 0)
        metrics["max_drawdown_60d"] = dd
        if dd > max_dd:
            failed.append(f"60日最大回撤({dd:.1%})>{max_dd:.0%}")

        # — 解禁 —
        unlocks = restricted.get(symbol, [])
        metrics["pending_unlocks"] = len(unlocks)
        if unlocks:
            dates = [u["release_date"] for u in unlocks[:3]]
            ratios = [u.get("ratio", 0) for u in unlocks[:3]]
            failed.append(f"近期解禁({', '.join(dates)}, 占比{max(ratios):.1%})")

        # — 极端估值 —
        pe = pe_map.get(symbol, 0)
        ind = industry_map.get(symbol, "其他")
        ind_med = industry_median.get(ind)
        if pe > 0 and ind_med and ind_med > 0:
            if pe > ind_med * pe_extreme:
                failed.append(f"PE({pe:.0f})>>行业中位数({ind_med:.0f})")

        passed = len(failed) == 0
        score = 1.0 if passed else max(0.1, 1.0 - 0.3 * len(failed))

        result[symbol] = StepScore(
            step=5, passed=passed, score=score,
            reason="; ".join(failed) if failed else "风险可控",
            metrics=metrics,
        )

    return result
