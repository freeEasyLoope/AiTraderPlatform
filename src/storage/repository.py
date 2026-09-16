"""数据仓库 — CRUD 操作封装。"""
from __future__ import annotations


from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .models import (
    DailySnapshot,
    MarketDataCache,
    Order,
    Position,
    Trader,
    WeeklyReport,
    create_database,
)


class Repository:
    """数据库操作仓库。"""

    def __init__(self, db_path: str = "data/simulation.db"):
        self.engine = create_database(db_path)

    def session(self) -> Session:
        return Session(self.engine)

    # ========== 操盘手 ==========

    def init_traders(self, trader_configs: list[dict]) -> list[dict]:
        """初始化操盘手账户，返回字典列表（避免 session detach 问题）。"""
        with self.session() as s:
            existing = s.query(Trader).count()
            if existing > 0:
                traders = s.query(Trader).all()
                return [
                    {"id": t.id, "name": t.name, "strategy": t.strategy,
                     "group": t.group or "short",
                     "cash": t.cash, "initial_capital": t.initial_capital}
                    for t in traders
                ]

            result = []
            for config in trader_configs:
                trader = Trader(
                    name=config["name"],
                    strategy=config["class"],
                    group=config.get("group", "short"),
                    initial_capital=config.get("initial_capital", 1666.67),
                    cash=config.get("initial_capital", 1666.67),
                )
                s.add(trader)
                result.append(trader)
            s.commit()
            return [
                {"id": t.id, "name": t.name, "strategy": t.strategy,
                 "cash": t.cash, "initial_capital": t.initial_capital}
                for t in result
            ]

    def get_traders(self, active_only: bool = True, group: str | None = None) -> list[Trader]:
        """获取所有操盘手，可按分组过滤。"""
        with self.session() as s:
            q = s.query(Trader)
            if active_only:
                q = q.filter(Trader.active == 1)
            if group:
                q = q.filter(Trader.group == group)
            return q.all()

    def get_trader(self, trader_id: int) -> Optional[Trader]:
        """获取单个操盘手。"""
        with self.session() as s:
            return s.query(Trader).filter(Trader.id == trader_id).first()

    def update_trader_cash(self, trader_id: int, cash: float) -> None:
        """更新操盘手现金。"""
        with self.session() as s:
            trader = s.query(Trader).filter(Trader.id == trader_id).first()
            if trader:
                trader.cash = cash
                s.commit()

    # ========== 持仓 ==========

    def get_positions(self, trader_id: int) -> list[Position]:
        """获取操盘手持仓。"""
        with self.session() as s:
            return s.query(Position).filter(Position.trader_id == trader_id).all()

    def get_position(self, trader_id: int, symbol: str) -> Optional[Position]:
        """获取特定持仓。"""
        with self.session() as s:
            return (
                s.query(Position)
                .filter(Position.trader_id == trader_id, Position.symbol == symbol)
                .first()
            )

    def upsert_position(
        self,
        trader_id: int,
        symbol: str,
        name: str,
        pos_type: str,
        shares: int,
        avg_cost: float,
        locked_shares: int = 0,
        buy_date: str = "",
        last_buy_date: str = "",
    ) -> None:
        """创建或更新持仓。"""
        with self.session() as s:
            pos = (
                s.query(Position)
                .filter(Position.trader_id == trader_id, Position.symbol == symbol)
                .first()
            )
            if pos:
                pos.shares = shares
                pos.avg_cost = avg_cost
                pos.locked_shares = locked_shares
                pos.updated_at = datetime.now().isoformat()
                if last_buy_date:
                    pos.last_buy_date = last_buy_date
                if buy_date and not pos.buy_date:
                    pos.buy_date = buy_date
            else:
                pos = Position(
                    trader_id=trader_id,
                    symbol=symbol,
                    name=name,
                    type=pos_type,
                    shares=shares,
                    avg_cost=avg_cost,
                    locked_shares=locked_shares,
                    buy_date=buy_date or datetime.now().strftime("%Y-%m-%d"),
                    last_buy_date=last_buy_date or datetime.now().strftime("%Y-%m-%d"),
                )
                s.add(pos)
            s.commit()

    def delete_position(self, trader_id: int, symbol: str) -> None:
        """删除清仓后的持仓记录。"""
        with self.session() as s:
            s.query(Position).filter(
                Position.trader_id == trader_id,
                Position.symbol == symbol,
            ).delete()
            s.commit()

    # ========== 订单 ==========

    def save_order(self, order: Order) -> None:
        """保存订单。"""
        with self.session() as s:
            s.add(order)
            s.commit()

    def get_orders(self, trader_id: int, limit: int = 50) -> list[Order]:
        """获取操盘手订单。"""
        with self.session() as s:
            return (
                s.query(Order)
                .filter(Order.trader_id == trader_id)
                .order_by(Order.id.desc())
                .limit(limit)
                .all()
            )

    # ========== 快照 ==========

    def save_snapshot(self, snapshot: DailySnapshot) -> None:
        """保存每日快照。"""
        with self.session() as s:
            s.add(snapshot)
            s.commit()

    def get_snapshots(self, trader_id: int, limit: int = 90) -> list[DailySnapshot]:
        """获取操盘手历史快照。"""
        with self.session() as s:
            return (
                s.query(DailySnapshot)
                .filter(DailySnapshot.trader_id == trader_id)
                .order_by(DailySnapshot.date.desc())
                .limit(limit)
                .all()
            )

    def get_all_snapshots_for_date(self, date: str) -> list[DailySnapshot]:
        """获取某日所有操盘手快照。"""
        with self.session() as s:
            return s.query(DailySnapshot).filter(DailySnapshot.date == date).all()

    # ========== 周报 ==========

    def save_weekly_report(self, report: WeeklyReport) -> None:
        """保存周报。"""
        with self.session() as s:
            s.add(report)
            s.commit()

    def get_latest_report(self) -> Optional[WeeklyReport]:
        """获取最新周报。"""
        with self.session() as s:
            return (
                s.query(WeeklyReport)
                .order_by(WeeklyReport.id.desc())
                .first()
            )

    # ========== 缓存 ==========

    def get_cached_snapshot(self, symbol: str) -> Optional[dict]:
        """从缓存获取行情数据。"""
        import json

        with self.session() as s:
            cache = s.query(MarketDataCache).filter(MarketDataCache.symbol == symbol).first()
            if cache:
                # 检查是否当日数据
                if cache.updated_at.startswith(datetime.now().strftime("%Y-%m-%d")):
                    return json.loads(cache.data)
        return None

    def cache_snapshot(self, symbol: str, name: str, snap_type: str, data: dict) -> None:
        """缓存行情数据。"""
        import json

        with self.session() as s:
            cache = s.query(MarketDataCache).filter(MarketDataCache.symbol == symbol).first()
            if cache:
                cache.data = json.dumps(data, default=str)
                cache.updated_at = datetime.now().isoformat()
            else:
                cache = MarketDataCache(
                    symbol=symbol,
                    name=name,
                    type=snap_type,
                    data=json.dumps(data, default=str),
                    updated_at=datetime.now().isoformat(),
                )
                s.add(cache)
            s.commit()
