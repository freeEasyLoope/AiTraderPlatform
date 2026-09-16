"""历史日线的 HTTP 数据源链。

为什么需要它：baostock 走私有 socket 协议、没有超时参数。在托管平台（透明代理
环境）里 TCP 会被瞬间"接受"但拿不到任何数据，`bs.login()` 因此永久阻塞——实测
直接导致部署探活失败、页面卡死。HTTP 端点可以设超时、可快速失败、可多源互备。

数据源优先级（已实测口径）：
  1. 新浪 KLine  —— 与 baostock(adjustflag=2) 在 510300 上逐项一致，volume 比值 1.000
  2. 腾讯 fqkline —— 前复权；成交量单位是「手」，需 ×100 折算成股
  3. baostock     —— 兜底（由调用方设界）
"""

from __future__ import annotations

import json
import logging
import urllib.request

from ..runtime import run_with_timeout
from .provider import MarketSnapshot

logger = logging.getLogger(__name__)

_PER_SOURCE_TIMEOUT = 12.0
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
# 请求足够长的窗口，再按区间过滤——避免为区间分页而多发请求
_SINA_COUNT = 1023
_TENCENT_COUNT = 1000


def _sina_symbol(symbol: str) -> str:
    """复用 sina_client 的代码转换（延迟导入避免循环依赖）。"""
    from .sina_client import _sina_symbol as _conv
    return _conv(symbol)


def _http_json(url: str, headers: dict) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **headers})
    with urllib.request.urlopen(req, timeout=_PER_SOURCE_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _bar(date: str, open_: str, high: str, low: str, close: str, volume: str) -> dict:
    return {
        "date": str(date)[:10],
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume or 0),
    }


def _fetch_sina(sina_sym: str, start: str, end: str) -> list[dict]:
    """新浪 KLine：返回 [{day, open, high, low, close, volume}, ...]（不复权，单位=股）。"""
    url = ("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
           f"?symbol={sina_sym}&scale=240&ma=no&datalen={_SINA_COUNT}")
    data = _http_json(url, {"Referer": "https://finance.sina.com.cn/"})
    bars = []
    for it in data or []:
        try:
            bars.append(_bar(it["day"], it["open"], it["high"], it["low"], it["close"],
                             it.get("volume", 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return bars


def _fetch_tencent(sina_sym: str, start: str, end: str) -> list[dict]:
    """腾讯 fqkline：qfqday 元素为 [date, open, close, high, low, volume(手), ...]。"""
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={sina_sym},day,,,{_TENCENT_COUNT},qfq")
    data = _http_json(url, {"Referer": "https://gu.qq.com/"})
    node = ((data or {}).get("data") or {}).get(sina_sym) or {}
    rows = node.get("qfqday") or node.get("day") or []
    bars = []
    for arr in rows:
        try:
            bars.append(_bar(arr[0], arr[1], arr[3], arr[4], arr[2], float(arr[5]) * 100))
        except (IndexError, TypeError, ValueError):
            continue
    return bars


_SOURCES = (("新浪", _fetch_sina), ("腾讯", _fetch_tencent))


def _to_snapshots(symbol: str, bars: list[dict]) -> list[MarketSnapshot]:
    """转成 MarketSnapshot 并回填 change_pct（matcher 的涨跌停判定依赖它）。"""
    snaps = []
    prev_close = None
    for b in bars:
        change_pct = 0.0
        if prev_close:
            change_pct = (b["close"] - prev_close) / prev_close
        snaps.append(MarketSnapshot(
            symbol=symbol, name="",
            close=b["close"], open=b["open"], high=b["high"], low=b["low"],
            volume=b["volume"], change_pct=change_pct,
        ))
        prev_close = b["close"]
    return snaps


def fetch_history(symbol: str, start_date: str, end_date: str) -> list[MarketSnapshot]:
    """按优先级依次尝试 HTTP 源，全部失败返回空列表（由调用方决定是否兜底）。"""
    sina_sym = _sina_symbol(symbol)
    for name, fn in _SOURCES:
        try:
            bars = run_with_timeout(lambda f=fn: f(sina_sym, start_date, end_date),
                                    _PER_SOURCE_TIMEOUT, None)
        except Exception as e:
            logger.warning("历史日线 %s ← %s 源失败: %s", symbol, name, e)
            continue
        if not bars:
            logger.info("历史日线 %s ← %s 源无数据", symbol, name)
            continue
        picked = [b for b in bars if start_date <= b["date"] <= end_date]
        if not picked:
            logger.info("历史日线 %s ← %s 源区间内无数据（%s~%s）", symbol, name, start_date, end_date)
            continue
        logger.debug("历史日线 %s ← %s（%d 根）", symbol, name, len(picked))
        return _to_snapshots(symbol, picked)
    return []


_BATCH_WORKERS = 8


def fetch_history_batch(
    symbols: list[str], start_date: str, end_date: str
) -> dict[str, list[MarketSnapshot]]:
    """并发批量取历史日线。

    单标的一次请求是 HTTP 源的固有代价（baostock 曾用一次登录批量查），
    所以这里用线程池把 N 次串行等待压成 N/8 —— 否则选股 90 只要等 17s+。
    """
    if not symbols:
        return {}
    if len(symbols) == 1:
        return {symbols[0]: fetch_history(symbols[0], start_date, end_date)}

    from concurrent.futures import ThreadPoolExecutor

    out: dict[str, list[MarketSnapshot]] = {}
    with ThreadPoolExecutor(max_workers=min(_BATCH_WORKERS, len(symbols)),
                            thread_name_prefix="kline") as pool:
        futures = {pool.submit(fetch_history, s, start_date, end_date): s for s in symbols}
        for fut in futures:
            symbol = futures[fut]
            try:
                out[symbol] = fut.result()
            except Exception as e:
                logger.warning("历史日线 %s 并发取数异常: %s", symbol, e)
                out[symbol] = []
    return out
