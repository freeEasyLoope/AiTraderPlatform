"""持仓管理器。"""
from __future__ import annotations


import logging
from datetime import datetime

from ..storage.repository import Repository
from ..traders.base import Position, TraderState

logger = logging.getLogger(__name__)


class PortfolioManager:
    """持仓管理：从数据库加载、更新、同步。"""

    def __init__(self, repo: Repository):
        self.repo = repo

    def load_state(self, trader_id: int, trader_name: str, params: dict) -> TraderState:
        """从数据库加载操盘手状态。"""
        trader = self.repo.get_trader(trader_id)
        if not trader:
            raise ValueError(f"操盘手不存在: {trader_id}")

        positions: dict[str, Position] = {}
        for p in self.repo.get_positions(trader_id):
            positions[p.symbol] = Position(
                symbol=p.symbol,
                name=p.name,
                type=p.type,
                shares=p.shares,
                locked_shares=p.locked_shares,
                avg_cost=p.avg_cost,
                buy_date=getattr(p, "buy_date", "") or "",
                last_buy_date=getattr(p, "last_buy_date", "") or "",
            )

        return TraderState(
            name=trader_name,
            cash=trader.cash,
            positions=positions,
            params=params,
        )

    def save_positions(self, trader_id: int, state: TraderState) -> None:
        """将持仓状态写回数据库。清理已清仓的记录。"""
        # 先获取 DB 中已有的持仓
        db_positions = {p.symbol for p in self.repo.get_positions(trader_id)}
        state_symbols = set(state.positions.keys())
        # 删除 state 中不存在的（已清仓）
        for sym in db_positions - state_symbols:
            self.repo.delete_position(trader_id, sym)

        for symbol, pos in state.positions.items():
            self.repo.upsert_position(
                trader_id=trader_id,
                symbol=symbol,
                name=pos.name,
                pos_type=pos.type,
                shares=pos.shares,
                avg_cost=pos.avg_cost,
                locked_shares=pos.locked_shares,
                buy_date=pos.buy_date if pos.buy_date else "",
                last_buy_date=pos.last_buy_date if pos.last_buy_date else "",
            )
        self.repo.update_trader_cash(trader_id, state.cash)

    def unlock_all(self, trader_id: int) -> None:
        """解冻所有 T+1 锁定。"""
        positions = self.repo.get_positions(trader_id)
        for pos in positions:
            if pos.locked_shares > 0:
                self.repo.upsert_position(
                    trader_id=trader_id,
                    symbol=pos.symbol,
                    name=pos.name,
                    pos_type=pos.type,
                    shares=pos.shares,
                    avg_cost=pos.avg_cost,
                    locked_shares=0,
                )
                logger.debug(f"  解冻 {pos.symbol}: {pos.locked_shares} 股")

    def calc_total_value(
        self, state: TraderState, market: dict[str, object]
    ) -> float:
        """计算总资产（现金 + 持仓市值）。"""
        total = state.cash
        for symbol, pos in state.positions.items():
            snapshot = market.get(symbol)
            if snapshot:
                total += pos.shares * snapshot.close
        state.total_value = total
        return total
