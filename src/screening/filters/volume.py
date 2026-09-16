"""第①步：成交量温和放大 + PE < 行业均值 + 无退市风险。

淘汰条件：
- ST/*ST/退市整理
- 近30日成交量无温和放大（5日均/30日均 < amplify_min）
- PE(动态) > 行业中位数
"""

from __future__ import annotations

import logging
from statistics import median

from ..datasource import FunnelDataSource
from ..models import StepScore

logger = logging.getLogger(__name__)


def filter_volume(
    data: FunnelDataSource,
    symbols: list[str],
    params: dict,
) -> dict[str, StepScore]:
    """执行成交量+PE筛选。"""
    volume_window = params.get("volume_window", 30)
    amplify_min = params.get("volume_amplify_min", 1.2)
    pe_max_ratio = params.get("pe_vs_industry_max", 1.0)
    exclude_st = params.get("exclude_st", True)

    result: dict[str, StepScore] = {}

    # 1. 获取全市场行情快照
    spot_df = data.get_market_spot()
    if spot_df.empty:
        logger.warning("全市场行情数据为空，第①步全部放行")
        for s in symbols:
            result[s] = StepScore(step=1, passed=True, score=0.5, reason="数据不足")
        return result

    # 构建 symbol → 行 索引
    spot_map = {}
    for _, row in spot_df.iterrows():
        code = str(row.get("代码", ""))
        spot_map[code] = row

    # 2. 计算行业 PE 中位数
    industry_pe = _calc_industry_median_pe(spot_df)

    # 3. 获取历史成交量
    hist_vol = data.get_historical_volume(symbols, days=volume_window)

    # 4. 逐只判断
    for symbol in symbols:
        row = spot_map.get(symbol)
        if row is None:
            result[symbol] = StepScore(step=1, passed=True, score=0.3,
                                        reason="不在全市场行情中")
            continue

        name = str(row.get("名称", ""))
        failed_reasons = []

        # — ST 过滤 —
        if exclude_st:
            if "ST" in name or "*ST" in name or "退市" in name:
                result[symbol] = StepScore(step=1, passed=False, score=0.0,
                                            reason="ST/退市风险", metrics={"name": name})
                continue

        # — PE 检查 —
        pe_raw = row.get("市盈率-动态")
        try:
            pe = float(pe_raw) if pe_raw is not None and str(pe_raw) != "nan" else None
        except (ValueError, TypeError):
            pe = None

        ind = str(row.get("行业", "")) or "其他"
        ind_median_pe = industry_pe.get(ind)
        if pe is not None and pe > 0 and ind_median_pe is not None and ind_median_pe > 0:
            if pe > ind_median_pe * pe_max_ratio:
                failed_reasons.append(f"PE({pe:.1f})>行业中位数({ind_median_pe:.1f})")

        # — 成交量检查 —
        vols = hist_vol.get(symbol, [])
        has_vol_data = vols and len(vols) >= 10
        if has_vol_data:
            avg_5d = sum(vols[-5:]) / min(len(vols[-5:]), 5)
            avg_all = sum(vols) / len(vols)
            if avg_all > 0:
                vol_ratio = avg_5d / avg_all
                if vol_ratio < amplify_min:
                    failed_reasons.append(f"量比({vol_ratio:.2f})<{amplify_min}")
        else:
            # 无历史数据时，用换手率辅助判断
            turnover = row.get("换手率")
            try:
                t = float(turnover) if turnover is not None else -1
            except (ValueError, TypeError):
                t = -1
            # 换手率数据缺失或为0（Sina 不提供此字段）→ 放行，不做成交量过滤
            if t > 0 and t < 0.5:
                failed_reasons.append(f"换手率({t:.2f}%)偏低")

        # — 汇总 —
        passed = len(failed_reasons) == 0
        score = 1.0 if passed else max(0.1, 1.0 - 0.3 * len(failed_reasons))
        result[symbol] = StepScore(
            step=1, passed=passed, score=score,
            reason="; ".join(failed_reasons) if failed_reasons else "通过",
            metrics={"pe": pe, "industry": ind, "industry_median_pe": ind_median_pe},
        )

    return result


def _calc_industry_median_pe(spot_df) -> dict[str, float]:
    """从全市场快照计算各行业 PE 中位数。"""
    industry_pes: dict[str, list[float]] = {}
    for _, row in spot_df.iterrows():
        pe_raw = row.get("市盈率-动态")
        try:
            pe = float(pe_raw) if pe_raw is not None and str(pe_raw) != "nan" else None
        except (ValueError, TypeError):
            pe = None
        if pe is not None and 0 < pe < 500:
            ind = str(row.get("行业", "其他")) if "行业" in spot_df.columns else "全市场"
            industry_pes.setdefault(ind, []).append(pe)

    return {ind: median(pes) for ind, pes in industry_pes.items() if pes}
