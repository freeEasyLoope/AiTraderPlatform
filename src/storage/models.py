"""SQLAlchemy ORM 模型定义。"""
from __future__ import annotations


from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Trader(Base):
    """操盘手账户。"""

    __tablename__ = "traders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, comment="操盘手名称")
    strategy = Column(String(100), nullable=False, comment="策略类路径")
    initial_capital = Column(Float, nullable=False, comment="初始资金")
    cash = Column(Float, nullable=False, comment="当前现金")
    created_at = Column(String(30), nullable=False, default=lambda: datetime.now().isoformat())
    active = Column(Integer, default=1, comment="是否启用")
    group = Column(String(10), default="short", comment="分组: short/long")

    positions = relationship("Position", back_populates="trader", lazy="selectin")
    orders = relationship("Order", back_populates="trader", lazy="selectin")

    @property
    def is_active(self) -> bool:
        return self.active == 1


class Position(Base):
    """持仓。"""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trader_id = Column(Integer, ForeignKey("traders.id"), nullable=False)
    symbol = Column(String(20), nullable=False, comment="代码")
    name = Column(String(50), nullable=False, comment="名称")
    type = Column(String(20), nullable=False, comment="类型: stock/fund/bond/gold_etf")
    shares = Column(Integer, nullable=False, comment="持有数量")
    avg_cost = Column(Float, nullable=False, comment="平均成本价")
    locked_shares = Column(Integer, default=0, comment="T+1 锁定数量")
    buy_date = Column(String(20), default="", comment="首次买入日期")
    last_buy_date = Column(String(20), default="", comment="最近加仓日期")
    updated_at = Column(String(30), nullable=False, default=lambda: datetime.now().isoformat())

    trader = relationship("Trader", back_populates="positions")


class Order(Base):
    """委托/成交记录。"""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trader_id = Column(Integer, ForeignKey("traders.id"), nullable=False)
    symbol = Column(String(20), nullable=False, comment="代码")
    type = Column(String(10), nullable=False, comment="buy/sell")
    shares = Column(Integer, nullable=False, comment="数量")
    price = Column(Float, nullable=False, comment="成交价")
    fee = Column(Float, nullable=False, default=0.0, comment="手续费+印花税")
    status = Column(String(20), nullable=False, comment="filled/rejected/cancelled")
    reject_reason = Column(String(100), comment="拒绝原因")
    reason = Column(String(200), comment="决策理由")
    created_at = Column(String(30), nullable=False, default=lambda: datetime.now().isoformat())

    trader = relationship("Trader", back_populates="orders")


class DailySnapshot(Base):
    """每日净值快照。"""

    __tablename__ = "daily_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trader_id = Column(Integer, ForeignKey("traders.id"), nullable=False)
    date = Column(String(20), nullable=False, comment="日期 YYYY-MM-DD")
    total_value = Column(Float, nullable=False, comment="总资产")
    pnl = Column(Float, nullable=False, comment="当日盈亏")
    pnl_pct = Column(Float, nullable=False, comment="当日收益率")
    cash = Column(Float, nullable=False, comment="现金")
    market_value = Column(Float, nullable=False, comment="持仓市值")


class WeeklyReport(Base):
    """周报。"""

    __tablename__ = "weekly_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(String(20), nullable=False, comment="周起始日")
    week_end = Column(String(20), nullable=False, comment="周结束日")
    llm_raw = Column(Text, comment="LLM 原始输出")
    summary = Column(Text, comment="摘要")
    rankings = Column(Text, comment="JSON: 操盘手排名")
    created_at = Column(String(30), nullable=False, default=lambda: datetime.now().isoformat())


class MarketDataCache(Base):
    """市场数据缓存。"""

    __tablename__ = "market_data_cache"

    symbol = Column(String(20), primary_key=True, comment="代码")
    name = Column(String(50), comment="名称")
    type = Column(String(20), comment="类型")
    data = Column(Text, comment="JSON: 行情数据")
    updated_at = Column(String(30), nullable=False)


def create_database(path: str = "data/simulation.db", url: str | None = None):
    """创建数据库和表。

    url 优先（平台托管 PostgreSQL 注入 DATABASE_URL），否则 SQLite 落可写目录。
    """
    import os

    from ..runtime import db_url

    conn = url or db_url(path)
    if conn.startswith("sqlite"):
        file_path = conn.replace("sqlite:///", "", 1)
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)

    engine = create_engine(conn, echo=False)
    Base.metadata.create_all(engine)
    return engine
