"""股息率查询 & 分红入账 — 通过 baostock 获取分红数据。"""

from __future__ import annotations

import io
import logging
import sys
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 分红缓存（按年份+代码），减少重复查询
_dividend_cache: dict[str, list[dict]] = {}


def _login_baostock(retries: int = 3, backoff: float = 1.0):
    """带重试的 baostock 登录。"""
    import baostock as bs

    for attempt in range(retries):
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            lg = bs.login()
        finally:
            sys.stdout = old
        if lg.error_code == "0":
            return bs
        if attempt < retries - 1:
            time.sleep(backoff * (2 ** attempt))
    return None


def _to_baostock_code(symbol: str) -> str:
    """600519 -> sh.600519"""
    if symbol.startswith(("6", "5", "9", "68")):
        return f"sh.{symbol}"
    return f"sz.{symbol}"


def enrich_dividend_yields(snapshots: dict, symbols: list[str], date: str) -> None:
    """为快照补充股息率（通过 baostock 分红数据估算）。

    方法：查询最近 2 年的分红记录，用年度股息 / 当前股价 估算股息率。
    """
    bs = _login_baostock()
    if bs is None:
        logger.warning("baostock 登录失败（已重试），跳过股息率补充")
        return

    try:
        enriched = 0
        dt = datetime.strptime(date, "%Y-%m-%d")
        year = dt.year

        for symbol in symbols:
            snap = snapshots.get(symbol)
            if snap is None or snap.dividend_yield is not None:
                continue

            bs_code = _to_baostock_code(symbol)
            try:
                rs = bs.query_dividend_data(
                    code=bs_code,
                    year=str(year - 1),
                    yearType="report",
                )
                data = rs.get_data() if hasattr(rs, 'get_data') else None
                if data is None or data.empty:
                    continue

                total_dividend = 0.0
                for _, row in data.iterrows():
                    try:
                        total_dividend += float(row.get("dividCashPsBeforeTax", 0) or 0)
                    except (ValueError, TypeError):
                        continue

                if total_dividend > 0 and snap.close > 0:
                    snap.dividend_yield = total_dividend / snap.close
                    enriched += 1
            except Exception:
                continue

        if enriched:
            logger.info(f"股息率: 补充 {enriched} 条")
    finally:
        old, sys.stdout = sys.stdout, io.StringIO()
        bs.logout()
        sys.stdout = old


def get_dividend_payments(symbols: list[str], year: int) -> dict[str, list[dict]]:
    """获取分红支付记录（用于模拟器现金入账）。

    Returns:
        {symbol: [{pay_date, cash_per_share, plan_explain}, ...]}
    """
    result: dict[str, list[dict]] = {}

    bs = _login_baostock()
    if bs is None:
        logger.warning("baostock 登录失败，无法获取分红支付数据")
        return result

    try:
        for symbol in symbols:
            bs_code = _to_baostock_code(symbol)

            # 查最近 3 年（当前年 + 前两年）
            for y in range(year - 2, year + 1):
                cache_key = f"{symbol}_{y}"
                if cache_key in _dividend_cache:
                    records = _dividend_cache[cache_key]
                else:
                    try:
                        old, sys.stdout = sys.stdout, io.StringIO()
                        rs = bs.query_dividend_data(
                            code=bs_code,
                            year=str(y),
                            yearType="report",
                        )
                        sys.stdout = old
                    except Exception:
                        sys.stdout = old if 'old' in dir() else sys.stdout
                        continue

                    data = rs.get_data() if hasattr(rs, 'get_data') else None
                    if data is None or data.empty:
                        _dividend_cache[cache_key] = []
                        continue

                    records = []
                    for _, row in data.iterrows():
                        pay_date = str(row.get("dividPayDate", ""))
                        cash = float(row.get("dividCashPsBeforeTax", 0) or 0)
                        if pay_date and cash > 0:
                            records.append({
                                "pay_date": pay_date,
                                "cash_per_share": cash,
                                "plan_explain": str(row.get("planExplain", "")),
                            })
                    _dividend_cache[cache_key] = records

                if records:
                    result.setdefault(symbol, []).extend(records)
    finally:
        old, sys.stdout = sys.stdout, io.StringIO()
        bs.logout()
        sys.stdout = old

    return result


def apply_dividends_to_positions(
    positions_by_trader: dict[int, dict[str, object]],  # {trader_id: {symbol: Position}}
    date: str,
    dividend_payments: dict[str, list[dict]],
) -> dict[int, float]:
    """在指定日期对持仓应用分红入账。

    Args:
        positions_by_trader: {trader_id: {symbol: Position}}
        date: 当前日期 YYYY-MM-DD
        dividend_payments: {symbol: [{pay_date, cash_per_share}, ...]}

    Returns:
        {trader_id: total_dividend_credited}
    """
    credited: dict[int, float] = {}

    for trader_id, positions in positions_by_trader.items():
        total = 0.0
        for symbol, pos in positions.items():
            payments = dividend_payments.get(symbol, [])
            for p in payments:
                if p["pay_date"] == date and pos.shares > 0:
                    cash = p["cash_per_share"] * pos.shares
                    total += cash
                    logger.info(
                        f"💰 分红入账: 操盘手{trader_id} {symbol} "
                        f"{pos.shares}股 × ¥{p['cash_per_share']:.2f}/股 = ¥{cash:.2f}"
                    )
        if total > 0:
            credited[trader_id] = round(total, 2)

    return credited
