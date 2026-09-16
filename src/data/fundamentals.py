"""基本面数据 — PE/PB/股息率。

数据源优先级:
1. baostock (免费无注册，PE/PB)
2. tushare (需注册+积分，更全)

baostock 历史 K 线接口可返回 peTTM、pbMRQ 字段。
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

from ..runtime import normalize_date

logger = logging.getLogger(__name__)

# ── PE/PB 缓存 ──
# PE/PB 来自日线，日内不会变化。缓存后同一批标的的第二次访问无需联网。
# 负缓存（pe=None）同样重要：ETF 之类天生没有 PE，不记住就会每次访问都白查一遍。
_PE_PB_CACHE: dict[str, tuple[float, Optional[float], Optional[float]]] = {}
_PE_PB_TTL = 3600.0
# 单次调用的墙钟上限：baostock 一次只能查一只标的，不设界时页面耗时随标的数线性增长
_PE_PB_BUDGET = 15.0


def _pe_pb_from_cache(symbol: str):
    item = _PE_PB_CACHE.get(symbol)
    if item is None:
        return None
    ts, pe, pb = item
    if time.time() - ts > _PE_PB_TTL:
        _PE_PB_CACHE.pop(symbol, None)
        return None
    return pe, pb


def _pe_pb_to_cache(symbol: str, pe, pb) -> None:
    _PE_PB_CACHE[symbol] = (time.time(), pe, pb)


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


def _try_baostock(snapshots: dict, symbols: list[str], date: str,
                  budget: float = _PE_PB_BUDGET) -> None:
    """通过 baostock 批量获取 PE/PB（带跨请求缓存 + 墙钟预算）。

    登录统一走 `baostock_utils.open_bs`：带超时 + 熔断。原实现带 3 次重试，
    在数据源不可达时会变成"3 × 永久挂起"，反而把页面拖死。

    性能：baostock 的 K 线接口一次只能查一只，N 只标的 = N 次串行往返（实测 ~1s/只），
    自带缓存的页面也会因此变慢。这里做两件事：
      1. 按 symbol 缓存 PE/PB（含**负缓存**）——ETF 之类天生没有 PE 的标的
         不再每次访问都打一次空枪；
      2. 加墙钟预算 `budget`，超出即停止后续查询，页面耗时不再随标的数线性膨胀。
    缓存全部命中的情况下**根本不登录**，页面耗时降到毫秒级。
    """
    from .baostock_utils import close_bs, open_bs

    # ① 先吃缓存，只把真正需要联网的标的挑出来
    pending: list[str] = []
    for symbol in symbols:
        snap = snapshots.get(symbol)
        if snap is None or snap.pe is not None:
            continue
        cached = _pe_pb_from_cache(symbol)
        if cached is None:
            pending.append(symbol)
        elif cached[0]:
            snap.pe, snap.pb = cached

    if not pending:
        return

    bs = open_bs()
    if bs is None:
        logger.info("baostock 不可用，跳过 PE/PB 补充")
        return

    try:
        enriched = 0
        date = normalize_date(date)
        dt = datetime.strptime(date, "%Y-%m-%d")
        start = (dt - timedelta(days=10)).strftime("%Y-%m-%d")
        deadline = time.time() + budget
        skipped = 0

        # ② K 线接口每次只能查单只
        for symbol in pending:
            if time.time() >= deadline:
                skipped = len(pending) - pending.index(symbol)
                logger.info("baostock: PE/PB 预算 %.0fs 用尽，剩余 %d 只本轮跳过",
                            budget, skipped)
                break

            bs_code = _to_baostock_code(symbol)
            try:
                # 不再替换全局 sys.stdout：查询一旦阻塞，全局重定向会永久生效，
                # 进程日志整段静音，线上反而看不到原因。
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,peTTM,pbMRQ",
                    start_date=start,
                    end_date=date,
                    frequency="d",
                    adjustflag="2",
                )
                data = rs.get_data() if hasattr(rs, 'get_data') else None
                if data is None or data.empty:
                    _pe_pb_to_cache(symbol, None, None)
                    continue

                # 从最近一个有效 PE 的日期取
                hit = False
                for _, row in data[::-1].iterrows():
                    pe = _safe_float(row.get("peTTM"))
                    pb = _safe_float(row.get("pbMRQ"))
                    if pe:
                        snap = snapshots.get(symbol)
                        if snap is not None:
                            snap.pe = pe
                            snap.pb = pb
                        _pe_pb_to_cache(symbol, pe, pb)
                        enriched += 1
                        hit = True
                        break
                if not hit:
                    _pe_pb_to_cache(symbol, None, None)
            except Exception as e:
                # 单只股票查询失败不影响其他
                logger.debug(f"baostock PE/PB 查询失败 {symbol}: {e}")
                continue

        if enriched:
            logger.info(f"baostock: 补充 {enriched}/{len(pending)} 条基本面数据")
        else:
            logger.info(f"baostock: 0/{len(pending)} 条数据（无 PE 或已有缓存）")
    finally:
        close_bs(bs)


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
