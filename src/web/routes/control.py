"""策略控制台 & 交易触发路由。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import repo, templates
from ...config import load_traders as _load_traders
from ...runtime import config_path


def _traders_config_path() -> Path:
    """可写目录下的 traders.yaml（页面会改它）。"""
    return config_path("traders.yaml")


router = APIRouter()


@router.get("/control", response_class=HTMLResponse)
async def control(request: Request):
    """策略控制台页面。"""
    traders = _load_traders()
    return templates.TemplateResponse(
        request=request, name="control.html",
        context={"traders": traders, "message": request.query_params.get("message", "")})


@router.post("/api/control/update")
async def api_update_params(request: Request):
    """更新策略参数。"""
    import yaml
    body = await request.json()
    trader_name = body.get("trader")
    param_name = body.get("param")
    new_value = body.get("value")
    if not all([trader_name, param_name, new_value is not None]):
        return {"ok": False, "error": "Missing fields"}

    config_path = _traders_config_path()
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    found = False
    for t in config.get("traders", []):
        if t["name"] == trader_name:
            if param_name in t.get("params", {}):
                old_val = t["params"][param_name]
                try:
                    t["params"][param_name] = type(old_val)(new_value)
                except (ValueError, TypeError):
                    t["params"][param_name] = new_value
                found = True
                break
    if not found:
        return {"ok": False, "error": f"Not found: {trader_name}.{param_name}"}

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    return {"ok": True}


@router.post("/api/control/trigger")
async def api_trigger_trade():
    """手动触发当日交易。"""
    from ...engine.simulator import Simulator
    from ...data.sina_client import SinaClient
    from ...data.mock_client import MockDataProvider
    from ...traders.registry import registry
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

    try:
        data = SinaClient()
        test = data.get_snapshot("600519")
        if not test or test.close <= 0:
            raise Exception("sina failed")
    except Exception:
        data = MockDataProvider()

    sim = Simulator(repo, data, registry)
    today = datetime.now().strftime("%Y-%m-%d")
    results = sim.run_daily(today)
    total_orders = sum(len(v) for v in results.values())
    filled = sum(sum(1 for o in v if o.status == "filled") for v in results.values())
    return {"ok": True, "date": today, "total_orders": total_orders, "filled": filled}


@router.post("/api/control/run_date")
async def api_run_date(request: Request):
    """对指定日期执行交易。"""
    from ...engine.simulator import Simulator
    from ...data.sina_client import SinaClient
    from ...data.mock_client import MockDataProvider
    from ...traders.registry import registry
    from ...traders.value_hunter import ValueHunter
    from ...traders.trend_follower import TrendFollower
    from ...traders.mean_reversion import MeanReversion
    from ...traders.dividend_collector import DividendCollector
    from ...traders.index_dca import IndexDca
    from ...traders.macro_hedger import MacroHedger

    body = await request.json()
    date = body.get("date", "")

    for path, cls in [("value_hunter.ValueHunter", ValueHunter),
                      ("trend_follower.TrendFollower", TrendFollower),
                      ("mean_reversion.MeanReversion", MeanReversion),
                      ("dividend_collector.DividendCollector", DividendCollector),
                      ("index_dca.IndexDca", IndexDca),
                      ("macro_hedger.MacroHedger", MacroHedger)]:
        if path not in registry._traders:
            registry.register(path, cls)

    try:
        data = SinaClient()
        test = data.get_snapshot("600519")
        if not test or test.close <= 0:
            raise Exception("sina failed")
    except Exception:
        data = MockDataProvider()

    sim = Simulator(repo, data, registry)
    results = sim.run_daily(date)
    total_orders = sum(len(v) for v in results.values())
    filled = sum(sum(1 for o in v if o.status == "filled") for v in results.values())
    return {"ok": True, "date": date, "total_orders": total_orders, "filled": filled}
