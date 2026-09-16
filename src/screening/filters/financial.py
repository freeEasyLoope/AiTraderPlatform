"""第②步：财务排雷 — 净利润趋势 + ROE + 财务造假信号。

淘汰条件：
- 最新季度净利润为负
- ROE < 阈值（默认 8%）
- 净利润同比大幅下滑（>30%）
- 商誉/净资产 > 30%（减值风险）
- 应收账款占比过大
- 存贷双高

数据来源：akshare stock_yjbb_em()（全市场业绩报表）+ stock_zcfz_em()（资产负债表）。
API 调用较慢（需遍历个股），默认配置中此步可选。
"""

from __future__ import annotations

import logging

from ..datasource import FunnelDataSource
from ..models import StepScore

logger = logging.getLogger(__name__)


def filter_financial(
    data: FunnelDataSource,
    symbols: list[str],
    params: dict,
) -> dict[str, StepScore]:
    """执行财务健康度排雷。

    两步验证：
    1. 业绩报表（净利润、ROE、营收增长率）
    2. 资产负债表红旗标记（商誉、应收、存贷双高）
    """
    roe_min = params.get("roe_min", 0.08)
    goodwill_max = params.get("goodwill_ratio_max", 0.30)
    ar_max = params.get("ar_revenue_ratio_max", 0.50)
    check_dual = params.get("dual_high_flag", True)
    require_positive_np = params.get("net_profit_positive_3y", True)

    result: dict[str, StepScore] = {}

    # 1. 获取业绩数据
    financials = data.get_financial_performance(symbols)
    if not financials:
        logger.warning("业绩报表数据为空，第②步全部放行")
        for s in symbols:
            result[s] = StepScore(step=2, passed=True, score=0.4,
                                   reason="财报数据不可用")
        return result

    # 2. 获取红旗标记
    flags = data.get_balance_health(symbols) if check_dual else {}

    # 3. 获取历史净利润趋势（用于判断三年走向）
    profit_trend = data.get_profit_trend(symbols)

    # 4. 逐只判断
    for symbol in symbols:
        fin = financials.get(symbol)
        if fin is None:
            result[symbol] = StepScore(step=2, passed=True, score=0.4,
                                        reason="无财报数据（可能新股或数据缺失）")
            continue

        failed = []
        metrics = dict(fin)

        # — 净利润 —
        np_val = fin.get("net_profit", 0)
        if np_val is not None and np_val < 0:
            failed.append(f"净利润为负({np_val/1e8:.1f}亿)")

        # — ROE —
        roe_val = fin.get("roe", 0)
        if roe_val is not None:
            metrics["roe"] = roe_val
            if roe_val < roe_min:
                failed.append(f"ROE({roe_val:.1%})<{roe_min:.0%}")
        else:
            # ROE 缺失时尝试从净利润和营收推算（粗略）
            revenue = fin.get("revenue", 0)
            if revenue > 0 and np_val > 0:
                estimated_roe = np_val / revenue  # 净利润率作为 ROE 的粗略代理
                metrics["roe_estimated"] = estimated_roe

        # — 净利润同比 —
        np_yoy = fin.get("net_profit_yoy", 0)
        if np_yoy is not None:
            metrics["net_profit_yoy"] = np_yoy
            if np_yoy < -0.50:
                failed.append(f"净利润同比暴跌({np_yoy:.1%})")
            elif np_yoy < -0.30:
                failed.append(f"净利润同比下滑({np_yoy:.1%})")

        # — 营收同比 —
        rev_yoy = fin.get("revenue_yoy", 0)
        if rev_yoy is not None:
            metrics["revenue_yoy"] = rev_yoy
            # 营收和利润双降是危险信号
            if rev_yoy < -0.20 and np_yoy < -0.20:
                failed.append(f"营收({rev_yoy:.1%})+净利润({np_yoy:.1%})双降")

        # — 三年净利润趋势 —
        trend = profit_trend.get(symbol, "unknown")
        if trend == "declining" and require_positive_np:
            failed.append("近三年净利润持续下滑")
        elif trend == "volatile":
            metrics["profit_trend"] = "波动较大"

        # — 红旗标记（资产负债表）—
        red_flags = flags.get(symbol, [])
        if "high_goodwill" in red_flags:
            failed.append("商誉过高(>30%净资产)")
        if "high_ar_ratio" in red_flags:
            failed.append("应收账款占比过大")
        if "dual_high_cash_debt" in red_flags:
            failed.append("存贷双高")

        # — 汇总 —
        passed = len(failed) == 0
        score = 1.0 if passed else max(0.1, 1.0 - 0.20 * len(failed))

        result[symbol] = StepScore(
            step=2, passed=passed, score=score,
            reason="; ".join(failed) if failed else "财务健康",
            metrics=metrics,
        )

    return result
