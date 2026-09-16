"""风险实验室路由——历史情景压力测试。"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import repo, templates, build_symbol_names

router = APIRouter()


@router.get("/risk-lab", response_class=HTMLResponse)
async def risk_lab(request: Request):
    """风险实验室——历史危机情景模拟。"""
    from ...analysis.risk_scenarios import load_scenarios

    scenarios = load_scenarios()
    symbol_names = build_symbol_names()

    # 获取所有操盘手的持仓（去重合并）
    all_positions: dict[str, dict] = {}
    for t in repo.get_traders(active_only=True):
        for p in repo.get_positions(t.id):
            if p.shares <= 0:
                continue
            sym = p.symbol
            if sym in all_positions:
                all_positions[sym]["shares"] += p.shares
                all_positions[sym]["holders"].append(t.name)
            else:
                all_positions[sym] = {
                    "symbol": sym,
                    "name": symbol_names.get(sym, p.name or sym),
                    "shares": p.shares,
                    "avg_cost": p.avg_cost,
                    "holders": [t.name],
                }

    # 获取实时价格
    live_prices = {}
    if all_positions:
        try:
            from urllib.request import Request as UReq, urlopen
            import re
            from ...data.sina_client import _sina_symbol
            syms = list(all_positions.keys())
            sina_syms = [_sina_symbol(s) for s in syms]
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

    # 构建持仓数据（含市值）
    positions_data = []
    total_market_value = 0.0
    for sym, pos in all_positions.items():
        price = live_prices.get(sym, pos["avg_cost"])
        mv = pos["shares"] * price
        total_market_value += mv
        positions_data.append({
            "symbol": sym,
            "name": pos["name"],
            "shares": pos["shares"],
            "current_price": round(price, 2),
            "market_value": round(mv, 2),
            "holders": pos["holders"],
        })

    return templates.TemplateResponse(
        request=request, name="risk_lab.html",
        context={
            "scenarios": scenarios,
            "positions_data": positions_data,
            "total_market_value": round(total_market_value, 2),
            "position_count": len(positions_data),
            "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })


@router.post("/api/risk-lab/simulate")
async def api_simulate_scenario(request: Request):
    """对指定场景执行压力测试。"""
    body = await request.json()
    scenario_id = body.get("scenario_id", "")

    from ...analysis.risk_scenarios import load_scenarios, simulate_scenario

    scenarios = load_scenarios()
    scenario = None
    for s in scenarios:
        if s["id"] == scenario_id:
            scenario = s
            break

    if not scenario:
        return {"ok": False, "error": f"未找到场景: {scenario_id}"}

    # 收集持仓
    symbol_names = build_symbol_names()
    all_positions: dict[str, dict] = {}
    for t in repo.get_traders(active_only=True):
        for p in repo.get_positions(t.id):
            if p.shares <= 0:
                continue
            sym = p.symbol
            if sym in all_positions:
                all_positions[sym]["shares"] += p.shares
            else:
                all_positions[sym] = {
                    "symbol": sym,
                    "name": symbol_names.get(sym, p.name or sym),
                    "shares": p.shares,
                    "avg_cost": p.avg_cost,
                }

    # 获取实时价格
    live_prices = {}
    if all_positions:
        try:
            from urllib.request import Request as UReq, urlopen
            import re
            from ...data.sina_client import _sina_symbol
            syms = list(all_positions.keys())
            sina_syms = [_sina_symbol(s) for s in syms]
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

    positions = []
    for sym, pos in all_positions.items():
        price = live_prices.get(sym, pos["avg_cost"])
        mv = pos["shares"] * price
        positions.append({
            "symbol": sym,
            "name": pos["name"],
            "shares": pos["shares"],
            "current_price": round(price, 2),
            "market_value": round(mv, 2),
        })

    result = simulate_scenario(positions, scenario)
    return {"ok": True, "result": result}
