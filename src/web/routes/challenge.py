"""模拟挑战模式路由——用户手动调参与 AI 操盘手同台竞技。"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import repo, templates, build_symbol_names

router = APIRouter()


@router.get("/challenge", response_class=HTMLResponse)
async def challenge(request: Request):
    """模拟挑战模式页面。"""
    traders = repo.get_traders(active_only=True)
    symbol_names = build_symbol_names()

    # 收集所有操盘手排行榜
    rankings = []
    for t in traders:
        snaps = repo.get_snapshots(t.id, limit=1)
        tv = snaps[0].total_value if snaps else t.cash
        pnl_pct = ((tv - t.initial_capital) / t.initial_capital) * 100
        rankings.append({
            "id": t.id, "name": t.name, "strategy": t.strategy,
            "total_value": round(tv, 2), "return_pct": round(pnl_pct, 2),
            "group": t.group,
        })
    rankings.sort(key=lambda x: x["return_pct"], reverse=True)

    # 检查是否已有"挑战者"（手动策略操盘手）
    challenger = None
    for t in traders:
        if "挑战者" in t.name:
            snaps = repo.get_snapshots(t.id, limit=1)
            tv = snaps[0].total_value if snaps else t.cash
            pnl_pct = ((tv - t.initial_capital) / t.initial_capital) * 100
            challenger = {
                "id": t.id, "name": t.name, "total_value": round(tv, 2),
                "return_pct": round(pnl_pct, 2), "cash": round(t.cash, 2),
            }
            # 获取持仓
            positions = []
            for p in repo.get_positions(t.id):
                positions.append({
                    "symbol": p.symbol,
                    "name": symbol_names.get(p.symbol, p.name or p.symbol),
                    "shares": p.shares, "avg_cost": round(p.avg_cost, 2),
                })
            challenger["positions"] = positions
            challenger["position_count"] = len(positions)
            break

    return templates.TemplateResponse(
        request=request, name="challenge.html",
        context={
            "rankings": rankings,
            "challenger": challenger,
            "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })


@router.post("/api/challenge/create")
async def api_create_challenger(request: Request):
    """创建一个手动挑战者操盘手。"""
    body = await request.json()
    name = body.get("name", "挑战者")

    # 检查是否已存在
    for t in repo.get_traders(active_only=False):
        if "挑战者" in t.name:
            return {"ok": True, "message": f"挑战者已存在: {t.name}", "trader_id": t.id}

    # 标记所有活跃操盘手
    traders = repo.get_traders(active_only=True)
    trader_count = len(traders)

    # 使用 SQLAlchemy 直接创建
    from ...storage.models import Trader
    with repo.session() as s:
        challenger = Trader(
            name=name,
            strategy="manual.ManualTrader",
            group="challenge",
            initial_capital=10000.0,
            cash=10000.0,
            active=1,
        )
        s.add(challenger)
        s.commit()
        challenger_id = challenger.id

    return {"ok": True, "message": f"挑战者已创建! ID={challenger_id}", "trader_id": challenger_id}


@router.get("/api/challenge/rankings")
async def api_challenge_rankings():
    """获取最新排行榜（含挑战者）。"""
    traders = repo.get_traders(active_only=True)
    rankings = []
    for t in traders:
        snaps = repo.get_snapshots(t.id, limit=1)
        tv = snaps[0].total_value if snaps else t.cash
        pnl_pct = ((tv - t.initial_capital) / t.initial_capital) * 100
        rankings.append({
            "name": t.name,
            "strategy": t.strategy,
            "total_value": round(tv, 2),
            "return_pct": round(pnl_pct, 2),
            "group": t.group,
        })
    rankings.sort(key=lambda x: x["return_pct"], reverse=True)
    return {"ok": True, "rankings": rankings}
