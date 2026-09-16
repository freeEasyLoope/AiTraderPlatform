"""Dashboard / 操盘手详情 / 股票详情路由。"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import repo, templates, build_symbol_names
from ...config import load_traders, load_settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _compute_market_env() -> dict:
    """同步计算市场环境——会阻塞在 baostock 上，只允许后台线程调用。"""
    try:
        from ...data.sina_client import SinaClient
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        snaps = SinaClient().get_historical_data(["510300"], start, end).get("510300", [])
        if len(snaps) < 40:
            return {"status": "unknown", "label": "数据不足", "needle_pos": 50,
                    "trend": "?", "volatility": "?", "index_price": 0.0,
                    "desc": "需要至少40个交易日数据"}

        closes = [s.close for s in snaps]
        current = closes[-1]
        ma20 = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else sum(closes) / len(closes)

        # 趋势判断
        if current > ma20 > ma60:
            status, label, needle_pos = "bull", "偏强上涨", 78
            trend_desc = "沪深300在20日/60日均线之上，处于上升趋势"
        elif current < ma20 < ma60:
            status, label, needle_pos = "bear", "偏弱下跌", 22
            trend_desc = "沪深300在20日/60日均线之下，处于下降趋势"
        else:
            status, label, needle_pos = "sideways", "震荡整理", 50
            trend_desc = "均线交织，市场方向不明，处于震荡格局"

        # 波动率
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        import math
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        vol = math.sqrt(variance) * math.sqrt(252) * 100

        # 60日涨跌幅
        change_60d = (current - closes[0]) / closes[0] * 100

        # 组合描述
        desc = f"{trend_desc}。近60日涨跌幅 {change_60d:+.1f}%，年化波动 {vol:.1f}%。"

        return {
            "status": status,
            "label": label,
            "needle_pos": needle_pos,
            "trend": f"{change_60d:+.1f}%",
            "volatility": f"{vol:.1f}%",
            "desc": desc,
            "index_price": round(current, 2),
        }
    except Exception:
        return {"status": "unknown", "label": "行情离线", "needle_pos": 50,
                "trend": "?", "volatility": "?", "index_price": 0.0,
                "desc": "无法获取指数数据，请检查数据源连接"}


# ── 市场环境缓存 ──
# 首屏绝不能等数据源：baostock 在境外/受限网络下无超时且会长时间阻塞，
# 同步等待会让平台探活 60s 超时。改为「先返回缓存，后台刷新」。
_MARKET_ENV_TTL = 600.0        # 成功结果缓存 10 分钟
_MARKET_ENV_RETRY = 60.0       # 无数据时最快 60 秒重试一次
_MARKET_ENV_DEADLINE = 180.0   # 后台刷新超时该时长视为卡死，允许重开
_MARKET_ENV_PLACEHOLDER = {
    "status": "unknown", "label": "行情加载中", "needle_pos": 50,
    "trend": "?", "volatility": "?", "index_price": 0.0,
    "desc": "正在后台获取指数数据…",
}
_market_env_state: dict = {
    "data": None, "ts": 0.0, "attempt_ts": 0.0, "refreshing": False, "token": None,
}
_market_env_guard = threading.Lock()


def _refresh_market_env() -> None:
    """触发一次后台刷新（单飞 + 死锁看门狗）。任何情况下都不阻塞调用方。"""
    now = time.time()
    with _market_env_guard:
        refreshing = _market_env_state["refreshing"]
        started_at = _market_env_state["attempt_ts"]
        has_data = _market_env_state["data"] is not None

        if refreshing and now - started_at < _MARKET_ENV_DEADLINE:
            return
        if refreshing:
            logger.warning("上次市场环境刷新超过 %.0fs 未返回，重开一次", _MARKET_ENV_DEADLINE)
        elif not has_data and now - started_at < _MARKET_ENV_RETRY:
            return

        token = object()
        _market_env_state["refreshing"] = True
        _market_env_state["attempt_ts"] = now
        _market_env_state["token"] = token

    def _work() -> None:
        try:
            data = _compute_market_env()
            if data.get("status") in ("bull", "bear", "sideways"):
                with _market_env_guard:
                    _market_env_state["data"] = data
                    _market_env_state["ts"] = time.time()
                logger.info("市场环境已刷新: %s", data.get("label"))
            else:
                logger.info("市场环境暂不可用: %s", data.get("desc"))
        except Exception:
            logger.exception("市场环境后台刷新异常")
        finally:
            with _market_env_guard:
                if _market_env_state["token"] is token:
                    _market_env_state["refreshing"] = False

    threading.Thread(target=_work, name="market-env", daemon=True).start()


def get_market_env() -> dict:
    """首屏用市场环境——立即返回，绝不等待数据源。"""
    now = time.time()
    with _market_env_guard:
        data = _market_env_state["data"]
        ts = _market_env_state["ts"]

    if data is not None and now - ts < _MARKET_ENV_TTL:
        return data

    _refresh_market_env()
    return data if data is not None else dict(_MARKET_ENV_PLACEHOLDER)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, group: str = ""):
    """统一总览仪表盘——短线+长线在一个页面。

    同步 def：FastAPI 会丢进线程池，页面里的行情拉取不会冻结事件循环。
    """
    traders = repo.get_traders(active_only=True)
    symbol_names = build_symbol_names()
    settings = load_settings()
    sim = settings["simulation"]
    short_capital = sim["short_capital"]
    long_capital = sim["long_capital"]
    total_capital = short_capital + long_capital

    # 市场环境（走缓存，不阻塞首屏）
    market_env = get_market_env()

    # 按组分类
    short_traders = []
    long_traders = []
    for t in traders:
        snaps = repo.get_snapshots(t.id, limit=1)
        tv = snaps[0].total_value if snaps else t.cash
        pnl_pct = ((tv - t.initial_capital) / t.initial_capital) * 100
        entry = {
            "id": t.id, "name": t.name, "strategy": t.strategy,
            "total_value": tv, "return_pct": pnl_pct,
            "cash": t.cash if snaps else t.initial_capital,
            "group": t.group,
        }
        if t.group == "short":
            short_traders.append(entry)
        else:
            long_traders.append(entry)

    # 排序
    short_traders.sort(key=lambda x: x["return_pct"], reverse=True)
    long_traders.sort(key=lambda x: x["return_pct"], reverse=True)

    # 组合计
    short_total_value = sum(t["total_value"] for t in short_traders)
    long_total_value = sum(t["total_value"] for t in long_traders)
    total_value = short_total_value + long_total_value
    short_return = (short_total_value - short_capital) / short_capital * 100
    long_return = (long_total_value - long_capital) / long_capital * 100
    total_return = (total_value - total_capital) / total_capital * 100

    # 最近交易
    recent = []
    for t in traders:
        for o in repo.get_orders(t.id, limit=8):
            recent.append({
                "trader": t.name, "trader_id": t.id, "symbol": o.symbol,
                "symbol_name": symbol_names.get(o.symbol, o.symbol),
                "type": o.type, "shares": o.shares, "price": o.price,
                "status": o.status, "reject_reason": o.reject_reason or "",
                "reason": o.reason or "", "date": o.created_at[:10],
            })
    recent.sort(key=lambda x: x["date"], reverse=True)
    recent = recent[:15]

    # 图表数据——按组
    chart_data_short = {}
    chart_data_long = {}
    for t in traders:
        snaps = repo.get_snapshots(t.id, limit=30)
        snaps.reverse()
        cd = {"dates": [s.date for s in snaps], "values": [round(s.total_value, 2) for s in snaps]}
        if t.group == "short":
            chart_data_short[t.name] = cd
        else:
            chart_data_long[t.name] = cd

    # 今日统计
    today = datetime.now().strftime("%Y-%m-%d")
    today_orders = sum(1 for r in recent if r["date"] == today)
    active_short = sum(1 for t in short_traders if abs(t["return_pct"]) > 0.001)
    active_long = sum(1 for t in long_traders if abs(t["return_pct"]) > 0.001)

    # 最佳/最差
    all_ranked = sorted(short_traders + long_traders, key=lambda x: x["return_pct"], reverse=True)
    best = all_ranked[0] if all_ranked else None
    worst = all_ranked[-1] if all_ranked else None

    # 初始展示哪个组（默认短线）
    show_group = group or "short"

    return templates.TemplateResponse(
        request=request, name="dashboard.html",
        context={
            "market_env": market_env,
            "short_traders": short_traders,
            "long_traders": long_traders,
            "short_total_value": round(short_total_value, 2),
            "long_total_value": round(long_total_value, 2),
            "total_value": round(total_value, 2),
            "short_return": round(short_return, 2),
            "long_return": round(long_return, 2),
            "total_return": round(total_return, 2),
            "short_capital": short_capital,
            "long_capital": long_capital,
            "today": today,
            "today_orders": today_orders,
            "active_short": active_short,
            "active_long": active_long,
            "recent": recent,
            "chart_data_short": json.dumps(chart_data_short),
            "chart_data_long": json.dumps(chart_data_long),
            "show_group": show_group,
            "best": best,
            "worst": worst,
            "all_ranked": all_ranked,
        })


@router.get("/api/stock/{symbol}")
def api_stock_detail(symbol: str):
    """股票详情 API——供前端弹窗使用（阻塞 IO，走线程池）。"""
    symbol_names = build_symbol_names()
    stock_name = symbol_names.get(symbol, symbol)

    price = None
    try:
        from urllib.request import Request as UReq, urlopen
        import re
        prefix = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
        req = UReq(f"http://hq.sinajs.cn/list={prefix}{symbol}",
                   headers={"Referer": "https://finance.sina.com.cn"})
        with urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("gbk", errors="replace")
        m = re.search(r'"(.+)"', raw)
        if m:
            parts = m.group(1).split(",")
            if len(parts) >= 6:
                price = {"close": float(parts[3]), "open": float(parts[1]),
                         "high": float(parts[4]), "low": float(parts[5]),
                         "change_pct": (float(parts[3]) - float(parts[2])) / float(parts[2])
                         if float(parts[2]) > 0 else 0}
    except Exception:
        pass

    pe = pb = None
    try:
        from ...data.fundamentals import _try_baostock
        from ...data.provider import MarketSnapshot
        curr = price["close"] if price else 0
        fake = {symbol: MarketSnapshot(symbol=symbol, name=stock_name,
                close=curr, open=0, high=0, low=0, volume=0, change_pct=0)}
        _try_baostock(fake, [symbol], datetime.now().strftime("%Y-%m-%d"))
        pe, pb = fake[symbol].pe, fake[symbol].pb
    except Exception:
        pass

    holders = []
    for t in repo.get_traders(active_only=True):
        pos = repo.get_position(t.id, symbol)
        if pos:
            holders.append({"trader_id": t.id, "trader_name": t.name,
                            "shares": pos.shares, "cost": pos.avg_cost})

    return {
        "symbol": symbol,
        "name": stock_name,
        "price": price,
        "pe": pe,
        "pb": pb,
        "holders": holders,
    }


@router.get("/trader/{trader_id}", response_class=HTMLResponse)
def trader_detail(request: Request, trader_id: int):
    """操盘手详情。"""
    t = repo.get_trader(trader_id)
    if not t:
        return HTMLResponse("Not Found", 404)

    symbol_names = build_symbol_names()
    snaps = repo.get_snapshots(t.id, limit=30)
    snaps.reverse()
    latest = snaps[-1] if snaps else None
    total_value = latest.total_value if latest else t.cash
    return_pct = ((total_value - t.initial_capital) / t.initial_capital) * 100

    # 快速获取持仓现价
    live_prices = {}
    positions = repo.get_positions(t.id)
    if positions:
        try:
            from urllib.request import Request as UReq, urlopen
            import re
            from ...data.sina_client import _sina_symbol
            p_symbols = [p.symbol for p in positions]
            sina_syms = [_sina_symbol(s) for s in p_symbols]
            url = "http://hq.sinajs.cn/list=" + ",".join(sina_syms)
            req = UReq(url, headers={"Referer": "https://finance.sina.com.cn"})
            with urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("gbk", errors="replace")
            for line in raw.strip().split("\n"):
                m = re.match(r'var hq_str_(\w+)="(.+)"', line.strip())
                if m:
                    code = m.group(1)[2:]
                    parts = m.group(2).split(",")
                    if len(parts) >= 4:
                        try:
                            price = float(parts[3])
                            if price > 0:
                                live_prices[code] = price
                        except ValueError:
                            pass
        except Exception:
            pass

    pos_data = []
    for p in positions:
        current = live_prices.get(p.symbol, 0)
        pnl = (current - p.avg_cost) * p.shares if current > 0 and p.avg_cost > 0 else 0
        pnl_pct = ((current - p.avg_cost) / p.avg_cost * 100) if current > 0 and p.avg_cost > 0 else 0
        pos_data.append({"symbol": p.symbol, "name": symbol_names.get(p.symbol, p.name or p.symbol),
                         "shares": p.shares, "avg_cost": p.avg_cost, "locked": p.locked_shares,
                         "current_price": current, "pnl": pnl, "pnl_pct": pnl_pct})

    orders = repo.get_orders(t.id, limit=50)
    order_data = [{"symbol": o.symbol, "symbol_name": symbol_names.get(o.symbol, o.symbol),
                   "type": o.type, "shares": o.shares, "price": o.price,
                   "status": o.status, "reason": o.reason or "",
                   "reject": o.reject_reason or "", "date": o.created_at[:10]} for o in orders]

    chart = {"dates": [s.date for s in snaps], "values": [round(s.total_value, 2) for s in snaps]}

    trader_configs = load_traders()
    params = {}
    for tc in trader_configs:
        if tc["name"] == t.name:
            params = tc.get("params", {})
            break

    # 计算持仓集中度
    pos_weights = []
    if total_value > 0 and positions:
        for p in positions:
            cur_p = live_prices.get(p.symbol, p.avg_cost)
            pct = (p.shares * cur_p) / total_value * 100
            pos_weights.append({"symbol": p.symbol, "name": symbol_names.get(p.symbol, p.symbol or p.symbol),
                                "weight": round(pct, 1)})
        pos_weights.sort(key=lambda x: x["weight"], reverse=True)

    return templates.TemplateResponse(
        request=request, name="trader.html",
        context={"trader": {"id": t.id, "name": t.name, "strategy": t.strategy,
                            "cash": t.cash, "initial_capital": t.initial_capital,
                            "total_value": total_value, "return_pct": return_pct, "params": params,
                            "group": t.group},
                 "positions": pos_data, "orders": order_data, "chart_data": json.dumps(chart),
                 "pos_weights": pos_weights})


@router.get("/stock/{symbol}", response_class=HTMLResponse)
def stock_detail(request: Request, symbol: str):
    """股票详情页。"""
    symbol_names = build_symbol_names()
    stock_name = symbol_names.get(symbol, symbol)

    # 快速行情
    price = None
    try:
        from urllib.request import Request as UReq, urlopen
        import re
        prefix = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
        req = UReq(f"http://hq.sinajs.cn/list={prefix}{symbol}",
                   headers={"Referer": "https://finance.sina.com.cn"})
        with urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("gbk", errors="replace")
        m = re.search(r'"(.+)"', raw)
        if m:
            parts = m.group(1).split(",")
            if len(parts) >= 6:
                price = {"close": float(parts[3]), "open": float(parts[1]),
                         "high": float(parts[4]), "low": float(parts[5]),
                         "change_pct": (float(parts[3]) - float(parts[2])) / float(parts[2])
                         if float(parts[2]) > 0 else 0}
    except Exception:
        pass

    # 历史走势
    chart_dates, chart_prices = [], []
    pe, pb = None, None
    try:
        from ...data.sina_client import SinaClient
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        hist = SinaClient().get_historical_data([symbol], start, end).get(symbol, [])
        if hist:
            base = datetime.now()
            for i, h in enumerate(hist[-30:]):
                d = base - timedelta(days=30 - i)
                chart_dates.append(d.strftime("%m-%d"))
                chart_prices.append(round(h.close, 2))
        # PE/PB
        from ...data.fundamentals import _try_baostock
        from ...data.provider import MarketSnapshot
        fake = {symbol: MarketSnapshot(symbol=symbol, name=stock_name,
                close=chart_prices[-1] if chart_prices else 0,
                open=0, high=0, low=0, volume=0, change_pct=0)}
        _try_baostock(fake, [symbol], datetime.now().strftime("%Y-%m-%d"))
        pe, pb = fake[symbol].pe, fake[symbol].pb
    except Exception:
        pass

    holders = []
    for t in repo.get_traders(active_only=True):
        pos = repo.get_position(t.id, symbol)
        if pos:
            buy_reason = ""
            for o in repo.get_orders(t.id, limit=100):
                if o.symbol == symbol and o.type == "buy" and o.reason:
                    buy_reason = o.reason
                    break
            holders.append({"trader_id": t.id, "trader_name": t.name,
                            "shares": pos.shares, "avg_cost": pos.avg_cost, "reason": buy_reason})

    # 估值分位数（简化版）
    pe_percentile = None
    pb_percentile = None
    try:
        from ...data.sina_client import SinaClient
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
        hist = SinaClient().get_historical_data([symbol], start, end).get(symbol, [])
        if hist and len(hist) >= 30:
            all_pes = []
            for h in hist:
                if hasattr(h, 'pe') and h.pe and h.pe > 0 and h.pe < 500:
                    all_pes.append(h.pe)
            if all_pes and pe and pe > 0:
                pe_percentile = round(sum(1 for p in all_pes if p < pe) / len(all_pes) * 100)
    except Exception:
        pass

    return templates.TemplateResponse(
        request=request, name="stock.html",
        context={"symbol": symbol, "name": stock_name, "price": price,
                 "pe": pe, "pb": pb, "pe_percentile": pe_percentile,
                 "holders": holders,
                 "chart_data": json.dumps({"dates": chart_dates, "prices": chart_prices}),
                 "all_holders": json.dumps([h["trader_name"] for h in holders])})
