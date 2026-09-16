"""每日信号简报路由。"""

from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import repo, templates, build_symbol_names
from ...runtime import config_path

router = APIRouter()


def _get_watchlist_market() -> dict:
    """获取自选池行情（复用逻辑）。"""
    import yaml
    wl_path = config_path("watchlist.yaml")
    with open(wl_path, encoding="utf-8") as f:
        wl = yaml.safe_load(f)
    stocks = wl.get("stocks", {})
    funds = wl.get("funds", {})
    symbols = list(stocks.keys()) + list(funds.keys())
    names = {**stocks, **funds}

    market = {}
    try:
        from urllib.request import Request as UReq, urlopen
        from ...data.provider import MarketSnapshot

        sina_syms = []
        for s in symbols:
            p = "sh" if s.startswith(("5", "6", "9")) else "sz"
            sina_syms.append(f"{p}{s}")
        url = "http://hq.sinajs.cn/list=" + ",".join(sina_syms)
        req = UReq(url, headers={"Referer": "https://finance.sina.com.cn"})
        with urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("gbk", errors="replace")
        for line in raw.strip().split("\n"):
            m = re.match(r'var hq_str_(\w+)="(.+)"', line.strip())
            if m:
                code = m.group(1)[2:]
                parts = m.group(2).split(",")
                if len(parts) >= 6:
                    try:
                        price = float(parts[3])
                        if price > 0:
                            market[code] = MarketSnapshot(
                                symbol=code, name=names.get(code, code),
                                close=price, open=float(parts[1]), high=float(parts[4]),
                                low=float(parts[5]), volume=float(parts[8]) * 100 if len(parts) > 8 else 0,
                                change_pct=(price - float(parts[2])) / float(parts[2]) if float(parts[2]) > 0 else 0)
                    except (ValueError, IndexError):
                        pass
    except Exception:
        pass

    # PE/PB
    if market:
        try:
            from ...data.fundamentals import _try_baostock
            _try_baostock(market, list(market.keys()), datetime.now().strftime("%Y-%m-%d"))
        except Exception:
            pass

    return market, names, symbols


@router.get("/signals", response_class=HTMLResponse)
def signal_briefing(request: Request):
    """每日信号简报页面（阻塞行情拉取，走线程池）。"""
    market, names, symbols = _get_watchlist_market()

    # 检测信号
    from ...analysis.signal_detector import detect_signals, generate_briefing_text
    signals = detect_signals(market) if market else []

    # 统计
    buy_count = sum(1 for s in signals if s["action"] == "买入")
    sell_count = sum(1 for s in signals if s["action"] == "卖出")

    # 按股票分组
    by_stock: dict[str, dict] = {}
    for s in signals:
        sym = s["symbol"]
        if sym not in by_stock:
            snap = market.get(sym)
            by_stock[sym] = {
                "symbol": sym, "name": s["name"],
                "price": s["current_price"],
                "change_pct": snap.change_pct if snap else 0,
                "pe": snap.pe if snap else None,
                "pb": snap.pb if snap else None,
                "signals": [],
            }
        by_stock[sym]["signals"].append(s)

    # 简报文本
    briefing_text = generate_briefing_text(signals) if signals else ""

    return templates.TemplateResponse(
        request=request, name="signal_briefing.html",
        context={
            "signals": signals,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "by_stock": by_stock,
            "briefing_text": briefing_text,
            "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "symbol_count": len(symbols),
        })
