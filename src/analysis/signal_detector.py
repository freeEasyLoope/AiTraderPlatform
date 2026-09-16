"""策略信号检测器 — 对自选池运行所有策略，收集买卖信号 + 自然语言解释。

用途：每日收盘后生成信号简报，告诉用户"今天哪些自选股触发了什么信号"。
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..traders.registry import registry
from ..traders.base import TraderState, OrderIntent
from ..traders.value_hunter import ValueHunter
from ..traders.trend_follower import TrendFollower
from ..traders.mean_reversion import MeanReversion
from ..traders.dividend_collector import DividendCollector
from ..traders.index_dca import IndexDca
from ..traders.macro_hedger import MacroHedger
from ..data.provider import MarketSnapshot

logger = logging.getLogger(__name__)

# 策略注册 + 元信息
STRATEGY_META = {
    "value_hunter.ValueHunter": {
        "name": "价值猎手", "group": "long", "icon": "🔍",
        "philosophy": "寻找低PE低PB的被低估股票",
        "buy_condition": "PE低于行业均值×阈值 且 PB<上限",
        "sell_condition": "PE回归行业均值/止盈+30%/止损-15%",
    },
    "trend_follower.TrendFollower": {
        "name": "趋势跟随者", "group": "short", "icon": "↗",
        "philosophy": "跟随趋势——金叉买入、死叉卖出",
        "buy_condition": "MA5上穿MA20(金叉) + 成交量放大",
        "sell_condition": "MA5下穿MA20(死叉)/止损-8%",
    },
    "mean_reversion.MeanReversion": {
        "name": "均值回归者", "group": "short", "icon": "↺",
        "philosophy": "超卖反弹——在别人恐慌时入场",
        "buy_condition": "RSI<30 + 价格触及布林下轨",
        "sell_condition": "RSI>70(超买)/回归中轨/持仓超期/止损-10%",
    },
    "dividend_collector.DividendCollector": {
        "name": "红利收集者", "group": "long", "icon": "💎",
        "philosophy": "高股息+低估值——稳健现金流",
        "buy_condition": "股息率>3% 且 PB<1.5",
        "sell_condition": "股息率<2%/PB过高/止盈+20%",
    },
    "index_dca.IndexDca": {
        "name": "指数定投者", "group": "long", "icon": "🐢",
        "philosophy": "每周定投指数——靠时间赚钱",
        "buy_condition": "每周一固定金额买入ETF",
        "sell_condition": "永不卖出（长期持有）",
    },
    "macro_hedger.MacroHedger": {
        "name": "宏观对冲者", "group": "short", "icon": "🌐",
        "philosophy": "股/债/金大类资产轮动",
        "buy_condition": "资产偏离目标权重超过阈值",
        "sell_condition": "再平衡——卖出超额资产",
    },
}


def _ensure_registered():
    """确保所有策略已注册。"""
    for path, cls in [
        ("value_hunter.ValueHunter", ValueHunter),
        ("trend_follower.TrendFollower", TrendFollower),
        ("mean_reversion.MeanReversion", MeanReversion),
        ("dividend_collector.DividendCollector", DividendCollector),
        ("index_dca.IndexDca", IndexDca),
        ("macro_hedger.MacroHedger", MacroHedger),
    ]:
        if path not in registry._traders:
            registry.register(path, cls)


def detect_signals(
    market: dict[str, MarketSnapshot],
    date: str | None = None,
) -> list[dict]:
    """对所有自选标的运行六位策略，检测买卖信号。

    Args:
        market: {symbol: MarketSnapshot} 自选池行情
        date: 检测日期

    Returns:
        [{symbol, name, strategy_name, strategy_icon, action, shares, reason,
          current_price, strategy_group, buy_condition, sell_condition}, ...]
    """
    _ensure_registered()
    date = date or datetime.now().strftime("%Y-%m-%d")

    advisor_list = [
        (ValueHunter, "value_hunter.ValueHunter"),
        (DividendCollector, "dividend_collector.DividendCollector"),
        (IndexDca, "index_dca.IndexDca"),
        (TrendFollower, "trend_follower.TrendFollower"),
        (MeanReversion, "mean_reversion.MeanReversion"),
        (MacroHedger, "macro_hedger.MacroHedger"),
    ]

    signals = []
    for cls, path in advisor_list:
        meta = STRATEGY_META.get(path, {})
        inst = registry.create(path, meta.get("name", path), 10000)
        if inst is None:
            continue

        state = TraderState(name=meta.get("name", path), cash=10000, params=inst.params)
        try:
            orders = inst.decide(state, market, date)
            for o in orders:
                current_price = market[o.symbol].close if o.symbol in market else 0
                signals.append({
                    "symbol": o.symbol,
                    "name": market[o.symbol].name if o.symbol in market else o.symbol,
                    "strategy_name": meta.get("name", path),
                    "strategy_icon": meta.get("icon", "📊"),
                    "strategy_group": meta.get("group", "short"),
                    "action": "买入" if o.action == "buy" else "卖出",
                    "shares": o.shares,
                    "reason": o.reason,
                    "current_price": round(current_price, 2),
                    "buy_condition": meta.get("buy_condition", ""),
                    "sell_condition": meta.get("sell_condition", ""),
                    "philosophy": meta.get("philosophy", ""),
                })
        except Exception as e:
            logger.debug(f"信号检测异常 {meta.get('name', path)}: {e}")
            continue

    return signals


def generate_briefing_text(signals: list[dict]) -> str:
    """将信号列表转换为自然语言简报。"""
    if not signals:
        return "今日无策略信号触发。所有自选标的均未满足六位操盘手的交易条件。"

    buy_signals = [s for s in signals if s["action"] == "买入"]
    sell_signals = [s for s in signals if s["action"] == "卖出"]

    parts = []
    parts.append(f"📊 **今日信号简报** — 共 {len(signals)} 条信号（{len(buy_signals)} 买入，{len(sell_signals)} 卖出）\n")

    # 按股票分组
    by_stock: dict[str, list] = {}
    for s in signals:
        by_stock.setdefault(s["symbol"], []).append(s)

    for symbol, stock_signals in by_stock.items():
        name = stock_signals[0]["name"]
        price = stock_signals[0]["current_price"]
        parts.append(f"\n### {name}（{symbol}）¥{price:.2f}")

        for sig in stock_signals:
            icon = sig["strategy_icon"]
            sname = sig["strategy_name"]
            action = sig["action"]
            reason = sig["reason"]
            parts.append(f"- {icon} **{sname}**：{action} — {reason}")

    # 总结
    parts.append(f"\n---\n💡 **如何使用**：以上信号由六位操盘手基于各自策略独立生成。")
    parts.append("多个操盘手同时对同一只股票发出信号 → 置信度更高。")
    parts.append("买入信号多 ≠ 马上涨，卖出信号多 ≠ 马上跌。关键是理解信号背后的逻辑。")

    return "\n".join(parts)
