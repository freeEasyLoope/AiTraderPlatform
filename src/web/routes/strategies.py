"""策略实验室路由：回测 + 策略画像 + 参数调优。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import repo, templates, build_symbol_names
from ...config import load_traders, load_settings

router = APIRouter()


@router.get("/strategies", response_class=HTMLResponse)
async def strategies(request: Request):
    """策略实验室——回测、画像、参数对比。"""
    traders_config = load_traders()
    settings = load_settings()

    # 策略绩效数据
    traders = repo.get_traders(active_only=True)
    perf_data = []
    for t in traders:
        snaps = repo.get_snapshots(t.id, limit=60)
        # 最近 30 天
        recent_snaps = [s for s in snaps if s.date >= (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")]
        total_value = snaps[0].total_value if snaps else t.cash
        return_pct = ((total_value - t.initial_capital) / t.initial_capital) * 100

        # 计算波动率
        if len(recent_snaps) >= 5:
            returns = [recent_snaps[i].pnl_pct for i in range(len(recent_snaps)) if recent_snaps[i].pnl_pct != 0]
            if len(returns) >= 2:
                import math
                mean_r = sum(returns) / len(returns)
                variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
                volatility = math.sqrt(variance) * math.sqrt(252) * 100
            else:
                volatility = 0
        else:
            volatility = 0

        perf_data.append({
            "id": t.id,
            "name": t.name,
            "strategy": t.strategy,
            "group": t.group,
            "capital": t.initial_capital,
            "total_value": round(total_value, 2),
            "return_pct": round(return_pct, 2),
            "volatility": round(volatility, 2),
            "positions": len(repo.get_positions(t.id)),
            "trade_count": len(repo.get_orders(t.id, limit=100)),
            "cash": round(t.cash, 2),
        })

    # 按组分组
    short_traders = [p for p in perf_data if p["group"] == "short"]
    long_traders = [p for p in perf_data if p["group"] == "long"]

    # 短线 vs 长线总计
    short_total = sum(t["total_value"] for t in short_traders)
    long_total = sum(t["total_value"] for t in long_traders)
    short_capital = settings["simulation"]["short_capital"]
    long_capital = settings["simulation"]["long_capital"]

    # 自选标的供回测
    import yaml
    from ...runtime import config_path
    wl_path = config_path("watchlist.yaml")
    with open(wl_path, encoding="utf-8") as f:
        wl = yaml.safe_load(f)
    watchlist_symbols = []
    for s, n in {**wl.get("stocks", {}), **wl.get("funds", {})}.items():
        watchlist_symbols.append({"symbol": s, "name": n})

    return templates.TemplateResponse(
        request=request, name="strategies.html",
        context={
            "perf_data": perf_data,
            "short_traders": short_traders,
            "long_traders": long_traders,
            "short_total": round(short_total, 2),
            "long_total": round(long_total, 2),
            "short_capital": short_capital,
            "long_capital": long_capital,
            "short_return": round((short_total - short_capital) / short_capital * 100, 2),
            "long_return": round((long_total - long_capital) / long_capital * 100, 2),
            "watchlist_symbols": watchlist_symbols,
            "traders_config": traders_config,
        })


@router.post("/api/strategies/backtest")
async def api_backtest(request: Request):
    """执行历史回测——指定日期范围跑模拟。"""
    import logging
    logging.getLogger("src").setLevel(logging.WARNING)

    body = await request.json()
    start_date = body.get("start_date", "")
    end_date = body.get("end_date", "")
    trader_name = body.get("trader", "")
    param_overrides = body.get("params", {})

    if not start_date or not end_date:
        return {"ok": False, "error": "请选择起止日期"}

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

    # 数据源
    try:
        data = SinaClient()
        test = data.get_snapshot("600519")
        if not test or test.close <= 0:
            raise Exception("sina failed")
    except Exception:
        data = MockDataProvider()

    # 获取交易日列表
    from datetime import datetime as dt, timedelta
    d_start = dt.strptime(start_date, "%Y-%m-%d")
    d_end = dt.strptime(end_date, "%Y-%m-%d")
    trading_days = []
    current = d_start
    while current <= d_end:
        ds = current.strftime("%Y-%m-%d")
        if data.is_trading_day(ds):
            trading_days.append(ds)
        current += timedelta(days=1)

    if not trading_days:
        return {"ok": False, "error": f"{start_date}~{end_date} 无交易日"}

    # 如果指定了操盘手名，只跑指定的；否则跑全部活跃的
    all_traders = repo.get_traders(active_only=True)
    target_traders = [t for t in all_traders if not trader_name or t.name == trader_name]
    if not target_traders:
        return {"ok": False, "error": f"未找到操盘手: {trader_name}"}

    sim = Simulator(repo, data, registry)

    # 如果有参数覆盖，临时修改配置（跑完在 finally 里还原）
    restore_text: str | None = None
    cfg_file = None
    if param_overrides:
        import yaml
        from ...runtime import config_path
        cfg_file = config_path("traders.yaml")
        restore_text = cfg_file.read_text(encoding="utf-8")
        orig_config = yaml.safe_load(restore_text)
        for t_cfg in orig_config.get("traders", []):
            if t_cfg["name"] in [t.name for t in target_traders]:
                for k, v in param_overrides.items():
                    if k in t_cfg.get("params", {}):
                        t_cfg["params"][k] = v
        cfg_file.write_text(
            yaml.dump(orig_config, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

    try:
        # 逐日执行
        daily_values = {t.name: [] for t in target_traders}
        dates = []
        total_orders = 0
        total_filled = 0

        for day in trading_days:
            try:
                results = sim.run_daily(day)
                total_orders += sum(len(v) for v in results.values())
                total_filled += sum(sum(1 for o in v if o.status == "filled") for v in results.values())
                dates.append(day)
                for t in target_traders:
                    snaps = repo.get_snapshots(t.id, limit=1)
                    daily_values[t.name].append(round(snaps[0].total_value, 2) if snaps else t.initial_capital)
            except Exception as e:
                # 某天失败继续下一天
                dates.append(day + "⚠")
                for t in target_traders:
                    daily_values[t.name].append(None)

        # 汇总结果
        summary = []
        for t in target_traders:
            vals = [v for v in daily_values[t.name] if v is not None]
            if vals:
                final_val = vals[-1]
                ret = (final_val - t.initial_capital) / t.initial_capital * 100
                # 最大回撤
                peak = vals[0]
                max_dd = 0
                for v in vals:
                    if v > peak:
                        peak = v
                    dd = (v - peak) / peak * 100 if peak > 0 else 0
                    if dd < max_dd:
                        max_dd = dd
            else:
                final_val = t.initial_capital
                ret = 0
                max_dd = 0
            summary.append({
                "name": t.name,
                "initial": t.initial_capital,
                "final": round(final_val, 2),
                "return_pct": round(ret, 2),
                "max_drawdown": round(max_dd, 2),
            })

        return {
            "ok": True,
            "dates": dates,
            "values": daily_values,
            "summary": summary,
            "total_orders": total_orders,
            "total_filled": total_filled,
            "trading_days_count": len(trading_days),
        }
    finally:
        # 回测参数覆盖只是一次性试验，必须还原，否则污染 traders.yaml
        if restore_text is not None:
            cfg_file.write_text(restore_text, encoding="utf-8")
