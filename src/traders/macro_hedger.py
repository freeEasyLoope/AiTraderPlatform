"""宏观对冲者 — 根据利率环境在股/债/金之间轮动。

逻辑：
- SHIBOR 上行 → 减仓股票，增持债券和黄金
- SHIBOR 下行 → 增持股票，减仓债券
- 配置偏离超过阈值 → 再平衡
"""
from __future__ import annotations


import logging

from .base import BaseTrader, OrderIntent, TraderState
from ..data.provider import MarketSnapshot

logger = logging.getLogger(__name__)


class MacroHedger(BaseTrader):
    """宏观对冲者 — 自上而下，顺势轮动。"""

    # 资产映射
    ASSET_MAP = {
        "stock": "510300",   # 沪深300ETF
        "bond": "511010",    # 国债ETF
        "gold": "518880",    # 黄金ETF
    }

    def decide(
        self,
        state: TraderState,
        market: dict[str, MarketSnapshot],
        date: str,
    ) -> list[OrderIntent]:
        orders: list[OrderIntent] = []
        params = self.params

        stock_weight: float = params.get("stock_weight", 0.50)
        bond_weight: float = params.get("bond_weight", 0.30)
        gold_weight: float = params.get("gold_weight", 0.20)
        rebalance_threshold: float = params.get("rebalance_threshold", 0.05)

        # 获取 SHIBOR（简化：用固定值，实际应由外部注入）
        # 这里通过市场数据间接判断：如果过去一周债券 ETF 上涨 → 利率下行
        bond_snap = market.get(self.ASSET_MAP["bond"])
        gold_snap = market.get(self.ASSET_MAP["gold"])
        stock_snap = market.get(self.ASSET_MAP["stock"])

        # 简化版宏观判断：根据各资产近期表现调整权重
        if bond_snap and bond_snap.change_pct > 0:
            # 债券上涨 = 利率下行 = 利好股票
            adj_stock = stock_weight + 0.10
            adj_bond = bond_weight - 0.05
            adj_gold = gold_weight - 0.05
        elif bond_snap and bond_snap.change_pct < -0.005:
            # 债券下跌 = 利率上行 = 利好债券（高收益率）和黄金（避险）
            adj_stock = stock_weight - 0.10
            adj_bond = bond_weight + 0.05
            adj_gold = gold_weight + 0.05
        else:
            adj_stock = stock_weight
            adj_bond = bond_weight
            adj_gold = gold_weight

        # 归一化
        total_w = adj_stock + adj_bond + adj_gold
        if total_w > 0:
            adj_stock /= total_w
            adj_bond /= total_w
            adj_gold /= total_w

        target_weights = {
            self.ASSET_MAP["stock"]: adj_stock,
            self.ASSET_MAP["bond"]: adj_bond,
            self.ASSET_MAP["gold"]: adj_gold,
        }

        # 计算当前持仓市值
        total_value = state.cash
        current_weights: dict[str, float] = {}
        for symbol, pos in state.positions.items():
            snap = market.get(symbol)
            if snap:
                mv = pos.shares * snap.close
                total_value += mv
                current_weights[symbol] = mv

        # 再平衡
        for symbol, target_w in target_weights.items():
            target_mv = total_value * target_w
            current_mv = current_weights.get(symbol, 0.0)

            snap = market.get(symbol)
            if snap is None:
                continue

            diff_pct = (target_mv - current_mv) / total_value if total_value > 0 else 0

            # 偏离超过阈值才调整
            if abs(diff_pct) < rebalance_threshold:
                continue

            diff_value = target_mv - current_mv

            if diff_value > 0:
                # 买入
                lots = int(diff_value / (snap.close * 100))
                if lots >= 1:
                    shares = lots * 100
                    if state.cash >= shares * snap.close:
                        orders.append(OrderIntent(
                            symbol=symbol,
                            action="buy",
                            shares=shares,
                            reason=f"再平衡: 目标权重 {target_w:.0%}, 差额 ¥{diff_value:,.0f}",
                        ))
            elif diff_value < 0:
                # 卖出
                pos = state.positions.get(symbol)
                if pos:
                    lots = int(abs(diff_value) / (snap.close * 100))
                    shares = min(lots * 100, pos.available_shares)
                    if lots >= 1 and shares >= 100:
                        orders.append(OrderIntent(
                            symbol=symbol,
                            action="sell",
                            shares=shares,
                            reason=f"再平衡: 目标权重 {target_w:.0%}, 超额 ¥{abs(diff_value):,.0f}",
                        ))

        return orders
