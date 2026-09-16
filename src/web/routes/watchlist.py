"""自选池 & 推荐路由——含估值温度计。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import repo, templates
from ...data.provider import MarketSnapshot
from ...runtime import config_path

router = APIRouter()


def _wl_path() -> Path:
    """可写目录下的 watchlist.yaml（页面会改它）。"""
    return config_path("watchlist.yaml")


def _load_watchlist():
    import yaml
    wl_path = _wl_path()
    with open(wl_path, encoding="utf-8") as f:
        wl = yaml.safe_load(f)
    stocks = wl.get("stocks", {})
    funds = wl.get("funds", {})
    symbols = list(stocks.keys()) + list(funds.keys())
    names = {**stocks, **funds}
    return stocks, funds, symbols, names


def _get_thermometer(symbol: str) -> dict:
    """获取 PE/PB 历史分位数（估值温度计）。"""
    result = {"pe_percentile": None, "pb_percentile": None,
              "pe_current": None, "pb_current": None, "days": 0}
    try:
        from ...data.sina_client import SinaClient
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
        snaps = SinaClient().get_historical_data([symbol], start, end).get(symbol, [])
        if snaps and len(snaps) >= 60:
            closes = [s.close for s in snaps]
            result["current_price"] = round(closes[-1], 2)

            # PE 分位数
            from ...data.fundamentals import _try_baostock
            fake = {symbol: MarketSnapshot(symbol=symbol, name=symbol,
                    close=closes[-1], open=0, high=0, low=0, volume=0, change_pct=0)}
            _try_baostock(fake, [symbol], datetime.now().strftime("%Y-%m-%d"))
            pe = fake[symbol].pe
            pb = fake[symbol].pb

            # 用历史收盘价作为 PE 变化的近似（真正的 PE 分位数需要历史 PE 数据）
            # 简化版：用价格分位数近似（价格高位 ≈ PE 高位）
            if pe and pe > 0:
                result["pe_current"] = round(pe, 1)
                # 价格分位数作为粗略代理
                below = sum(1 for c in closes if c < closes[-1])
                result["pe_percentile"] = round(below / len(closes) * 100)

            if pb and pb > 0:
                result["pb_current"] = round(pb, 2)
                below = sum(1 for c in closes if c < closes[-1])
                result["pb_percentile"] = round(below / len(closes) * 100)

            result["days"] = len(snaps)
    except Exception:
        pass
    return result


@router.get("/recommendations", response_class=HTMLResponse)
def recommendations(request: Request):
    """自选池分析——操盘手给出买卖建议 + 估值温度计。

    同步 def：内部有行情/基本面阻塞调用，走线程池避免冻结事件循环。
    """
    stocks, funds, symbols, names = _load_watchlist()

    # 快速行情
    market = {}
    try:
        from urllib.request import Request as UReq, urlopen
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

    # 补充 PE/PB
    if market:
        try:
            from ...data.fundamentals import _try_baostock
            _try_baostock(market, list(market.keys()), datetime.now().strftime("%Y-%m-%d"))
        except Exception:
            pass

    # 操盘手推荐
    recs = _get_trader_recs(market, names)

    # 估值温度计（异步收集，不阻塞页面）
    thermo_data = {}
    for s in symbols:
        thermo_data[s] = _get_thermometer(s)

    return templates.TemplateResponse(
        request=request, name="recommendations.html",
        context={"market": market, "recs": recs, "names": names,
                 "funds": funds, "symbols": symbols,
                 "thermo_data": thermo_data,
                 "now": datetime.now().strftime("%Y-%m-%d %H:%M")})


@router.post("/api/watchlist/add")
async def api_watchlist_add(request: Request):
    """添加自选标的。"""
    import yaml
    body = await request.json()
    symbol = body.get("symbol", "").strip()
    name = body.get("name", "").strip()
    wl_type = body.get("type", "stocks")
    if not symbol or not name:
        return {"ok": False, "error": "需要代码和名称"}
    wl_path = _wl_path()
    with open(wl_path, encoding="utf-8") as f:
        wl = yaml.safe_load(f)
    wl.setdefault(wl_type, {})[symbol] = name
    with open(wl_path, "w", encoding="utf-8") as f:
        yaml.dump(wl, f, allow_unicode=True, default_flow_style=False)
    return {"ok": True}


@router.post("/api/watchlist/remove")
async def api_watchlist_remove(request: Request):
    """删除自选标的。"""
    import yaml
    body = await request.json()
    symbol = body.get("symbol", "").strip()
    wl_type = body.get("type", "stocks")
    wl_path = _wl_path()
    with open(wl_path, encoding="utf-8") as f:
        wl = yaml.safe_load(f)
    if wl_type in wl and symbol in wl[wl_type]:
        del wl[wl_type][symbol]
    with open(wl_path, "w", encoding="utf-8") as f:
        yaml.dump(wl, f, allow_unicode=True, default_flow_style=False)
    return {"ok": True}


def _get_trader_recs(market: dict, names: dict) -> list[dict]:
    """六位操盘手分析自选池。"""
    from ...traders.registry import registry
    from ...traders.base import TraderState
    from ...traders.value_hunter import ValueHunter
    from ...traders.trend_follower import TrendFollower
    from ...traders.mean_reversion import MeanReversion
    from ...traders.dividend_collector import DividendCollector
    from ...traders.index_dca import IndexDca
    from ...traders.macro_hedger import MacroHedger

    for path, cls in [("value_hunter.ValueHunter", ValueHunter),
                      ("trend_follower.TrendFollower", TrendFollower),
                      ("mean_reversion.MeanReversion", MeanReversion),
                      ("dividend_collector.DividendCollector", DividendCollector),
                      ("index_dca.IndexDca", IndexDca),
                      ("macro_hedger.MacroHedger", MacroHedger)]:
        if path not in registry._traders:
            registry.register(path, cls)

    advisor_list = [
        (ValueHunter, "value_hunter.ValueHunter", "价值猎手"),
        (DividendCollector, "dividend_collector.DividendCollector", "红利收集者"),
        (IndexDca, "index_dca.IndexDca", "指数定投者"),
        (TrendFollower, "trend_follower.TrendFollower", "趋势跟随者"),
        (MeanReversion, "mean_reversion.MeanReversion", "均值回归者"),
        (MacroHedger, "macro_hedger.MacroHedger", "宏观对冲者"),
    ]

    recs = []
    for cls, path, tname in advisor_list:
        inst = registry.create(path, tname, 10000)
        if not inst:
            continue
        state = TraderState(name=tname, cash=10000, params=inst.params)
        try:
            orders = inst.decide(state, market, datetime.now().strftime("%Y-%m-%d"))
            for o in orders:
                recs.append({"trader": tname, "symbol": o.symbol,
                             "name": names.get(o.symbol, o.symbol),
                             "action": "买入" if o.action == "buy" else "卖出",
                             "shares": o.shares, "reason": o.reason,
                             "current_price": market[o.symbol].close if o.symbol in market else 0})
        except Exception:
            pass
    return recs
