"""基本面数据 — PE/PB/股息率。

数据源优先级:
1. baostock (免费无注册，PE/PB)
2. tushare (需注册+积分，更全)

baostock 历史 K 线接口可返回 peTTM、pbMRQ 字段。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def enrich_fundamentals(snapshots: dict, symbols: list[str], date: str) -> None:
    """为快照补充 PE/PB/股息率。

    优先 tushare（如果 token 可用且有权限），降级 baostock。
    """
    token = os.environ.get("TUSHARE_TOKEN", "")
    if token:
        success = _try_tushare(snapshots, symbols, date, token)
        if success:
            return
        logger.info("tushare 不可用，降级 baostock")

    # 降级：baostock
    _try_baostock(snapshots, symbols, date)


def _try_tushare(snapshots: dict, symbols: list[str], date: str, token: str) -> bool:
    """尝试通过 tushare 获取基本面数据。"""
    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()

        ts_codes = [_to_ts_code(s) for s in symbols]
        df = pro.daily_basic(
            ts_code=",".join(ts_codes),
            trade_date=date.replace("-", ""),
            fields="ts_code,pe,pb,dv_ratio",
        )

        if df is None or df.empty:
            return False

        for _, row in df.iterrows():
            symbol = _from_ts_code(row["ts_code"])
            snap = snapshots.get(symbol)
            if snap is None:
                continue

            snap.pe = _safe_float(row.get("pe"))
            snap.pb = _safe_float(row.get("pb"))
            dv = _safe_float(row.get("dv_ratio"))
            snap.dividend_yield = dv / 100.0 if dv else None

        logger.info(f"tushare: 补充 {len(df)} 条基本面数据")
        return True
    except Exception as e:
        logger.warning(f"tushare 基本面查询失败: {e}")
        return False


def _try_baostock(snapshots: dict, symbols: list[str], date: str) -> None:
    """通过 baostock 批量获取 PE/PB（带重试+缓存降级）。"""
    import baostock as bs
    import io
    import sys
    import time

    # 带重试的登录
    logged_in = False
    for attempt in range(3):
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            lg = bs.login()
        finally:
            sys.stdout = old
        if lg.error_code == "0":
            logged_in = True
            break
        if attempt < 2:
            time.sleep(1.0 * (2 ** attempt))
            logger.debug(f"baostock 登录重试 {attempt + 2}/3")

    if not logged_in:
        logger.warning(f"baostock 登录失败（已重试3次）: {lg.error_msg if 'lg' in dir() else 'unknown'}")
        return

    try:
        enriched = 0
        dt = datetime.strptime(date, "%Y-%m-%d")
        start = (dt - timedelta(days=10)).strftime("%Y-%m-%d")

        # 先尝试批量查询（对于 K 线数据每次只能查单只）
        for symbol in symbols:
            snap = snapshots.get(symbol)
            if snap is None or snap.pe is not None:
                continue

            bs_code = _to_baostock_code(symbol)
            try:
                old, sys.stdout = sys.stdout, io.StringIO()
                try:
                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        "date,peTTM,pbMRQ",
                        start_date=start,
                        end_date=date,
                        frequency="d",
                        adjustflag="2",
                    )
                finally:
                    sys.stdout = old
                data = rs.get_data() if hasattr(rs, 'get_data') else None
                if data is None or data.empty:
                    continue

                # 从最近一个有效 PE 的日期取
                for _, row in data[::-1].iterrows():
                    pe = _safe_float(row.get("peTTM"))
                    pb = _safe_float(row.get("pbMRQ"))
                    if pe:
                        snap.pe = pe
                        snap.pb = pb
                        enriched += 1
                        break
            except Exception as e:
                # 单只股票查询失败不影响其他
                logger.debug(f"baostock PE/PB 查询失败 {symbol}: {e}")
                continue

        if enriched:
            logger.info(f"baostock: 补充 {enriched}/{len(symbols)} 条基本面数据")
        else:
            logger.info(f"baostock: 0/{len(symbols)} 条数据（所有标的均无 PE 或已有缓存）")
    finally:
        old, sys.stdout = sys.stdout, io.StringIO()
        bs.logout()
        sys.stdout = old


def _to_ts_code(symbol: str) -> str:
    """600519 -> 600519.SH"""
    if symbol.startswith(("6", "5", "9", "68")):
        return f"{symbol}.SH"
    return f"{symbol}.SZ"


def _to_baostock_code(symbol: str) -> str:
    """600519 -> sh.600519"""
    if symbol.startswith(("6", "5", "9", "68")):
        return f"sh.{symbol}"
    return f"sz.{symbol}"


def _from_ts_code(ts_code: str) -> str:
    """600519.SH -> 600519"""
    return ts_code.split(".")[0]


def _safe_float(val) -> Optional[float]:
    """安全转 float，空值返回 None。"""
    if val is None:
        return None
    try:
        v = float(val)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None
