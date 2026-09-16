"""实时行情的 HTTP 多源链 + 新浪线格式兼容层。

为什么需要它：新浪实时行情 `hq.sinajs.cn` 在部分托管节点会被拒——实测 PocketBay
节点返回 `403 Forbidden` 或直接连接超时（同一节点上 `quotes.sina.cn` 的 KLine 却是
通的），而全项目有 8 处直连它，一旦不可用整站实时行情全空、模拟交易还会回落 Mock
（写入虚构价格）。这与当年 baostock 的问题是同一形状：**单一数据源 + 多处独立调用**。

实测可行的替代是腾讯行情（PocketBay 节点可达，已验证）：
  1. https://qt.gtimg.cn/q=sh600519,sz000858         一次可批量，GBK，`v_sh600519="…"`
  2. https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,,,1,qfq
     响应里带 `qt` 节点，字段与上面完全一致（主机已在目标节点验证可达）

腾讯 `~` 分隔数组的字段位置（实测校准）：
  [1]名称 [2]代码 [3]当前价 [4]昨收 [5]今开 [6]成交量(手)
  [9]买一 [19]卖一 [30]时间(YYYYMMDDHHMMSS) [32]涨跌幅(%) [33]最高 [34]最低
  [35]价格/成交量/成交额 [38]换手率(%) [39]市盈率TTM [45]总市值(亿) [46]市净率

对外两个入口：
  - `fetch_realtime(symbols)` → `{symbol: MarketSnapshot}`，给 provider 用（带 PE/PB）；
  - `fetch_sina_format(symbols)` → 与 `hq.sinajs.cn` **完全一样的线格式**字符串。
    这样 8 处历史解析代码（都只读 parts[1..5]、parts[8]）零改动即可换源，
    不必为一个数据源失效去重写 8 段解析逻辑。
"""

from __future__ import annotations

import json
import logging
import urllib.request

from ..runtime import run_with_timeout
from .provider import MarketSnapshot

logger = logging.getLogger(__name__)

_SOURCE_TIMEOUT = 8.0
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_QT_COUNT = 60          # 单次批量请求的标的上限，避免 URL 过长
_SINA_FORMAT_FIELDS = 33  # 新浪解析侧要求 len(parts) >= 32


def _tx_symbol(symbol: str) -> str:
    """600519 -> sh600519（与新浪同一套前缀约定）。"""
    prefix = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
    return f"{prefix}{symbol}"


def _f(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _http_text(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Referer": "https://gu.qq.com/",
    })
    with urllib.request.urlopen(req, timeout=_SOURCE_TIMEOUT) as resp:
        return resp.read().decode("gbk", errors="replace")


def _parse_qt_payload(raw: str) -> dict[str, list[str]]:
    """解析 `v_sh600519="a~b~c"` 形式，返回 {symbol: [字段…]}。"""
    out: dict[str, list[str]] = {}
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        key = key.strip()
        if not key.startswith("v_"):
            continue
        code = key[2:].strip()          # sh600519
        body = value.strip().strip('"')
        if not body:
            continue
        fields = body.split("~")
        if len(fields) < 10:
            continue
        if code.startswith(("sh", "sz")):
            out[code[2:]] = fields
    return out


# ── 数据源 1：qt.gtimg.cn 批量 ──

def _tencent_qt_batch(symbols: list[str]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for i in range(0, len(symbols), _QT_COUNT):
        chunk = symbols[i:i + _QT_COUNT]
        url = "https://qt.gtimg.cn/q=" + ",".join(_tx_symbol(s) for s in chunk)
        merged.update(_parse_qt_payload(_http_text(url)))
    return merged


# ── 数据源 2：ifzq fqkline 里的 qt 节点（逐只） ──

def _tencent_ifzq_one(symbol: str) -> dict[str, list[str]]:
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={_tx_symbol(symbol)},day,,,1,qfq")
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"})
    with urllib.request.urlopen(req, timeout=_SOURCE_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    node = ((data or {}).get("data") or {}).get(_tx_symbol(symbol)) or {}
    qt = node.get("qt") or {}
    fields = qt.get(_tx_symbol(symbol))
    if not fields or len(fields) < 10:
        return {}
    return {symbol: [str(x) for x in fields]}


def _tencent_ifzq_batch(symbols: list[str]) -> dict[str, list[str]]:
    from concurrent.futures import ThreadPoolExecutor

    merged: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(symbols)), thread_name_prefix="rtq") as pool:
        for fut in [pool.submit(_tencent_ifzq_one, s) for s in symbols]:
            try:
                merged.update(fut.result())
            except Exception as e:
                logger.debug("腾讯 ifzq 实时取数失败: %s", e)
    return merged


_SOURCES = (
    ("腾讯批量", _tencent_qt_batch),
    ("腾讯单只", lambda syms: _tencent_ifzq_batch(syms)),
)


def _fetch_fields(symbols: list[str]) -> dict[str, list[str]]:
    """依次尝试各源，返回第一个非空结果。

    单源预算随标的数放宽（ifzq 备源是逐只 8 线程并发），但仍有上限——
    这里不能出现"不受控的网络等待"，否则页面会被一个死源拖住。
    """
    budget = min(30.0, _SOURCE_TIMEOUT * (1 + (len(symbols) + 7) // 8))
    for name, fn in _SOURCES:
        try:
            got = run_with_timeout(lambda f=fn: f(symbols), budget, None)
        except Exception as e:
            logger.warning("实时行情 %s 源失败: %s", name, e)
            continue
        if got:
            return got
        logger.info("实时行情 %s 源无数据", name)
    return {}


def _to_snapshot(symbol: str, f: list[str]) -> MarketSnapshot | None:
    price = _f(f[3]) if len(f) > 3 else 0.0
    if price <= 0:
        return None
    prev_close = _f(f[4]) if len(f) > 4 else 0.0
    pe = _f(f[39]) if len(f) > 39 else 0.0
    pb = _f(f[46]) if len(f) > 46 else 0.0
    turnover = _f(f[38]) if len(f) > 38 else 0.0
    cap = _f(f[45]) if len(f) > 45 else 0.0
    return MarketSnapshot(
        symbol=symbol,
        name=(f[1] if len(f) > 1 else symbol),
        close=price,
        open=_f(f[5]) if len(f) > 5 else 0.0,
        high=_f(f[33]) if len(f) > 33 else price,
        low=_f(f[34]) if len(f) > 34 else price,
        volume=(_f(f[6]) * 100 if len(f) > 6 else 0.0),   # 手 → 股
        change_pct=((price - prev_close) / prev_close if prev_close > 0 else 0.0),
        pe=(pe or None),
        pb=(pb or None),
        turnover_rate=(turnover or None),
        total_market_cap=(cap * 1e8 if cap else None),     # 亿 → 元
    )


def fetch_realtime(symbols: list[str]) -> dict[str, MarketSnapshot]:
    """多源实时行情；全部失败返回空字典（调用方自行降级）。"""
    if not symbols:
        return {}
    fields = _fetch_fields(list(symbols))
    out: dict[str, MarketSnapshot] = {}
    for symbol in symbols:
        f = fields.get(symbol)
        if not f:
            continue
        snap = _to_snapshot(symbol, f)
        if snap is not None:
            out[symbol] = snap
    return out


# ── 新浪线格式兼容层 ──

def _sina_line(symbol: str, f: list[str]) -> str:
    """把腾讯字段重排成新浪 `hq_str_` 的逗号分隔格式。

    新浪下标约定（下游 8 处解析代码依赖的就是这些）：
      [0]名称 [1]今开 [2]昨收 [3]当前价 [4]最高 [5]最低
      [6]买一 [7]卖一 [8]成交量(手) [9]成交额(万元) [30]日期 [31]时间
    """
    parts = [""] * _SINA_FORMAT_FIELDS

    def g(i, default=""):
        return f[i] if len(f) > i and f[i] != "" else default

    stamp = g(30)
    date_str, time_str = "", ""
    if len(stamp) >= 14 and stamp.isdigit():
        date_str = f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
        time_str = f"{stamp[8:10]}:{stamp[10:12]}:{stamp[12:14]}"

    amount_yuan = 0.0
    combo = g(35)
    if combo.count("/") >= 2:
        amount_yuan = _f(combo.split("/")[2])

    parts[0] = g(1, symbol)
    parts[1] = g(5, "0")
    parts[2] = g(4, "0")
    parts[3] = g(3, "0")
    parts[4] = g(33, g(3, "0"))
    parts[5] = g(34, g(3, "0"))
    parts[6] = g(9, "0")
    parts[7] = g(19, "0")
    parts[8] = g(6, "0")
    parts[9] = ("%.4f" % (amount_yuan / 10000.0)) if amount_yuan else "0"
    parts[30] = date_str
    parts[31] = time_str
    parts[32] = "00"

    return 'var hq_str_%s="%s";' % (_tx_symbol(symbol), ",".join(parts))


def fetch_sina_format(symbols: list[str]) -> str:
    """返回与 `hq.sinajs.cn` 同格式的文本，供历史解析代码零改动复用。

    只在多源都失败时才回落新浪原站（并设界），保证换源不引入更差的结果。
    """
    if not symbols:
        return ""
    fields = _fetch_fields(list(symbols))
    if fields:
        return "\n".join(_sina_line(s, fields[s]) for s in symbols if s in fields)

    from .sina_client import fetch_sina_raw
    return fetch_sina_raw(symbols)
