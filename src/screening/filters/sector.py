"""第④步：行业景气度 + 政策利好 — 优先高增长赛道。

不做硬淘汰，而是打分排序：
- 行业近期涨跌幅排名（前 N 名高分）
- 行业资金流向判断
- 政策关键词匹配加分
- 综合得分影响最终排序

数据来源：akshare stock_board_industry_name_em() 行业板块行情。
"""

from __future__ import annotations

import logging

from ..datasource import FunnelDataSource
from ..models import StepScore

logger = logging.getLogger(__name__)


def filter_sector(
    data: FunnelDataSource,
    symbols: list[str],
    params: dict,
) -> dict[str, StepScore]:
    """执行行业景气度评分。

    软过滤：不会淘汰任何股票，但评分低的行业股票在最终排序中靠后。
    """
    top_n = params.get("sector_top_n", 5)
    keywords = params.get("policy_keywords", [])

    result: dict[str, StepScore] = {}

    # 1. 行业分类 — 从全市场行情快照直接提取（比 stock_board_industry_name_em 快）
    spot_df = data.get_market_spot()
    symbol_industry: dict[str, str] = {}
    symbol_name: dict[str, str] = {}
    if not spot_df.empty and "行业" in spot_df.columns:
        for _, row in spot_df.iterrows():
            code = str(row.get("代码", ""))
            symbol_industry[code] = str(row.get("行业", "其他"))
            symbol_name[code] = str(row.get("名称", ""))
    else:
        # fallback: 专用行业 API
        symbol_industry = data.get_industry_map()

    # 2. 行业板块表现排名
    sector_perf = data.get_industry_performance()
    sector_scores: dict[str, float] = {}
    sector_ranking: list[str] = []

    if sector_perf is not None and not sector_perf.empty:
        # 找涨跌幅列
        change_col = None
        for col in ["涨跌幅", "板块涨跌幅", "涨幅", "涨跌幅度"]:
            if col in sector_perf.columns:
                change_col = col
                break

        # 找板块名称列
        name_col = None
        for col in ["板块名称", "行业名称", "名称", "name"]:
            if col in sector_perf.columns:
                name_col = col
                break

        if change_col and name_col:
            rows = []
            for _, row in sector_perf.iterrows():
                try:
                    chg = float(row[change_col])
                except (ValueError, TypeError):
                    chg = 0.0
                industry_name = str(row.get(name_col, ""))
                if industry_name:
                    rows.append((industry_name, chg))

            if rows:
                all_changes = [r[1] for r in rows]
                max_chg = max(all_changes)
                min_chg = min(all_changes)
                rng = max_chg - min_chg if max_chg != min_chg else 1.0

                for ind_name, chg in rows:
                    # 归一化：表现最好的行业得分 = 1.0，最差 = 0.0
                    sector_scores[ind_name] = (chg - min_chg) / rng

                # 排名前 N
                sector_ranking = [
                    name for name, _ in
                    sorted(rows, key=lambda x: x[1], reverse=True)[:top_n]
                ]

                logger.info(
                    f"行业排名前{top_n}: {', '.join(sector_ranking[:5])}"
                )

    # 3. 为每只股票打分
    top_sectors = set(sector_ranking)
    keyword_matched_industries: set[str] = set()

    # 政策关键词匹配（在行业名称中搜索）
    if keywords and sector_scores:
        for ind_name in sector_scores:
            for kw in keywords:
                if kw in ind_name:
                    keyword_matched_industries.add(ind_name)
                    # 匹配政策关键词的行业加分
                    sector_scores[ind_name] = min(1.0, sector_scores.get(ind_name, 0.5) + 0.15)
                    break

    for symbol in symbols:
        industry = symbol_industry.get(symbol, "未知")
        base_score = sector_scores.get(industry, 0.5)

        # 加分项
        bonus = 0.0
        reasons = []

        if industry in top_sectors:
            bonus += 0.15
            reasons.append(f"行业前{top_n}")

        if industry in keyword_matched_industries:
            bonus += 0.10
            matched_kw = [kw for kw in keywords if kw in industry]
            reasons.append(f"政策关键词: {matched_kw}")

        final_score = min(1.0, base_score + bonus)

        # 软过滤：得分 < 0.2 时标记为不过（行业明显弱势）
        passed = final_score >= 0.15  # 极低门槛，只在行业崩盘时淘汰

        if not reasons:
            reasons.append(f"行业得分{base_score:.2f}")

        result[symbol] = StepScore(
            step=4,
            passed=passed,
            score=final_score,
            reason="; ".join(reasons),
            metrics={
                "industry": industry,
                "sector_score": base_score,
                "in_top_sectors": industry in top_sectors,
            },
        )

    return result
