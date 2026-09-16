"""风险情景模拟引擎 — 对持仓组合施加历史危机冲击，估算潜在损失。

用途：教育新手理解"如果XX事件重演，你的组合会跌多少"。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from ..data.provider import MarketSnapshot

logger = logging.getLogger(__name__)

# 行业→场景冲击键映射
SECTOR_IMPACT_MAP = {
    # 科技/TMT
    "300750": "sector_tech",  # 宁德时代
    "002415": "sector_tech",  # 海康威视
    "002230": "sector_tech",  # 科大讯飞
    "002475": "sector_tech",  # 立讯精密
    "688981": "sector_tech",  # 中芯国际
    "300059": "sector_tech",  # 东方财富
    # 地产/银行
    "000002": "sector_property",
    "600048": "sector_property",
    "600036": "sector_bank",
    "601398": "sector_bank",
    "000001": "sector_bank",
    "601166": "sector_bank",
    # 消费
    "600519": "sector_consumer",
    "000858": "sector_consumer",
    "000333": "sector_consumer",
    "600887": "sector_consumer",
    # 医药
    "600276": "sector_medical",
    "300760": "sector_medical",
    "000538": "sector_medical",
    "300015": "sector_medical",
    # 旅游/航空
    "600009": "sector_travel",
    "601111": "sector_travel",
    # 建材/材料
    "600585": "sector_material",
    "600309": "sector_material",
    "601899": "sector_material",
}


def load_scenarios() -> list[dict]:
    """加载所有历史危机场景。"""
    path = Path(__file__).parent.parent.parent / "config" / "scenarios.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("scenarios", [])


def simulate_scenario(
    positions: list[dict],       # [{symbol, name, shares, current_price, market_value}, ...]
    scenario: dict,
) -> dict:
    """将指定场景的冲击应用到当前持仓组合。

    Args:
        positions: 当前持仓列表
        scenario: 场景定义（从 scenarios.yaml 加载）

    Returns:
        {
            scenario_name, scenario_icon, description,
            total_before, total_after, total_loss, loss_pct,
            breakdown: [{symbol, name, before, after, loss, loss_pct, impact_type}, ...],
            lessons: [...],
        }
    """
    shocks = scenario.get("shocks", {})
    total_before = sum(p.get("market_value", 0) for p in positions if p.get("market_value", 0) > 0)
    if total_before <= 0:
        return _empty_result(scenario)

    breakdown = []
    total_after = 0.0

    for pos in positions:
        mv = pos.get("market_value", 0)
        if mv <= 0:
            continue

        symbol = pos.get("symbol", "")
        # 确定冲击幅度
        impact = _get_impact(symbol, shocks)
        after = round(mv * (1 + impact), 2)
        loss = round(mv - after, 2)
        loss_pct = impact * 100

        impact_type = _classify_impact(impact)

        breakdown.append({
            "symbol": symbol,
            "name": pos.get("name", symbol),
            "shares": pos.get("shares", 0),
            "before": round(mv, 2),
            "after": after,
            "loss": loss,
            "loss_pct": round(abs(loss_pct), 1),
            "impact_type": impact_type,
        })
        total_after += after

    # 现金不动
    total_loss = round(total_before - total_after, 2)
    loss_pct = round((total_before - total_after) / total_before * 100, 1) if total_before > 0 else 0

    # 按亏损排序
    breakdown.sort(key=lambda x: x["loss"], reverse=True)

    return {
        "scenario_name": scenario.get("name", ""),
        "scenario_icon": scenario.get("icon", ""),
        "scenario_id": scenario.get("id", ""),
        "description": scenario.get("description", ""),
        "duration": scenario.get("duration", ""),
        "total_before": round(total_before, 2),
        "total_after": round(total_after, 2),
        "total_loss": total_loss,
        "loss_pct": loss_pct,
        "breakdown": breakdown,
        "lessons": scenario.get("lessons", []),
    }


def _get_impact(symbol: str, shocks: dict) -> float:
    """获取某只股票在场景中的冲击幅度。

    优先级：行业冲击 > 市值冲击 > 通用冲击
    """
    # 1. 行业冲击
    sector_key = SECTOR_IMPACT_MAP.get(symbol)
    if sector_key and sector_key in shocks:
        return shocks[sector_key]

    # 2. 市值判断：小盘 vs 大盘
    if symbol.startswith(("688", "300", "301", "002")):
        # 创业板/科创板/中小板 → 小盘冲击
        return shocks.get("stock_small", shocks.get("stock_index", -0.15))
    elif symbol.startswith(("51", "15")):
        # ETF → 债券或黄金
        if "bond" in symbol.lower() or "国债" in symbol:
            return shocks.get("bond", 0.02)
        if "gold" in symbol.lower() or "黄金" in symbol:
            return shocks.get("gold", 0.0)
        return shocks.get("stock_index", -0.10)

    # 3. 大盘冲击
    return shocks.get("stock_index", -0.10)


def _classify_impact(impact: float) -> str:
    """分类冲击严重程度。"""
    if impact <= -0.3:
        return "重创"
    elif impact <= -0.15:
        return "严重"
    elif impact <= -0.05:
        return "中度"
    elif impact < 0:
        return "轻微"
    elif impact > 0.05:
        return "逆势上涨"
    elif impact > 0:
        return "抗跌"
    else:
        return "无影响"


def _empty_result(scenario: dict) -> dict:
    """空持仓的结果。"""
    return {
        "scenario_name": scenario.get("name", ""),
        "scenario_icon": scenario.get("icon", ""),
        "description": scenario.get("description", ""),
        "duration": scenario.get("duration", ""),
        "total_before": 0,
        "total_after": 0,
        "total_loss": 0,
        "loss_pct": 0,
        "breakdown": [],
        "lessons": scenario.get("lessons", []),
    }


def run_all_scenarios(positions: list[dict]) -> list[dict]:
    """对所有历史场景运行压力测试。"""
    scenarios = load_scenarios()
    results = []
    for sc in scenarios:
        result = simulate_scenario(positions, sc)
        results.append(result)
    return results
