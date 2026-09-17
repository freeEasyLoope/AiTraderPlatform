"""投资设置路由：自动投资 + 组合策略投资。

与「日志 & 周报」合并在同一设置中心（/settings），用 Tab 切换展示，
不再各自独立成页（解决 banner 选项过多、用户不知如何操作的问题）。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import repo, templates
from ...config import load_traders, load_settings
from ...runtime import config_path
from ...storage.models import WeeklyReport

router = APIRouter()

_DEFAULT_INVEST = {
    "auto_invest": {"enabled": True, "schedule": "daily", "trade_time": "21:00",
                    "base_amount": 1000, "max_positions": 6},
    "portfolio": {"enabled": False, "rebalance": "monthly", "risk_level": "balanced",
                  "allocation": {}},
}


def _invest_path() -> Path:
    return config_path("invest.yaml")


def load_invest() -> dict:
    """读取投资设置（与 config.load_invest 保持同源）。"""
    try:
        from ...config import load_invest as _load
        return _load()
    except Exception:
        return {k: dict(v) for k, v in _DEFAULT_INVEST.items()}


def _ai_report_enabled() -> bool:
    """AI 周报功能开关（settings.yaml -> features.ai_report_enabled）。"""
    try:
        settings = load_settings()
        return bool((settings.get("features") or {}).get("ai_report_enabled", False))
    except Exception:
        return False


def _load_reports() -> list:
    """读取最近 20 期周报（与 reports 路由同源）。"""
    try:
        with repo.session() as s:
            rows = s.query(WeeklyReport).order_by(WeeklyReport.id.desc()).limit(20).all()
            out = []
            for r in rows:
                rankings = []
                try:
                    rankings = json.loads(r.rankings) if r.rankings else []
                except json.JSONDecodeError:
                    pass
                out.append({"week_start": r.week_start, "week_end": r.week_end,
                            "summary": r.summary or "", "rankings": rankings})
            return out
    except Exception:
        return []


def _build_settings_context(active_tab: str = "invest") -> dict:
    """构造「设置中心」双标签页所需的全部上下文。"""
    cfg = load_invest()
    traders = load_traders()
    alloc = (cfg.get("portfolio") or {}).get("allocation", {})
    trader_alloc = []
    for t in traders:
        key = t.get("class", t.get("name"))
        trader_alloc.append({"name": t["name"], "key": key, "pct": alloc.get(key, 0)})
    return {
        "cfg": cfg,
        "traders": trader_alloc,
        "reports": _load_reports(),
        "ai_report_enabled": _ai_report_enabled(),
        "active_tab": active_tab,
    }


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """设置中心（投资设置 + 日志 & 周报 双标签）。"""
    active_tab = request.query_params.get("tab", "invest")
    if active_tab not in ("invest", "logs"):
        active_tab = "invest"
    return templates.TemplateResponse(
        request=request, name="settings.html",
        context=_build_settings_context(active_tab))


@router.post("/api/settings/update")
async def api_update_settings(request: Request):
    """保存投资设置，并归一化组合权重为 100%。"""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "请求体解析失败"}
    if not isinstance(body, dict):
        return {"ok": False, "error": "无效的配置数据"}

    auto = body.get("auto_invest", {}) or {}
    port = body.get("portfolio", {}) or {}
    clean = {
        "auto_invest": {
            "enabled": bool(auto.get("enabled", True)),
            "schedule": auto.get("schedule", "daily"),
            "trade_time": str(auto.get("trade_time", "21:00")),
            "base_amount": float(auto.get("base_amount", 0) or 0),
            "max_positions": int(auto.get("max_positions", 0) or 0),
        },
        "portfolio": {
            "enabled": bool(port.get("enabled", False)),
            "rebalance": port.get("rebalance", "monthly"),
            "risk_level": port.get("risk_level", "balanced"),
            "allocation": {},
        },
    }
    raw_alloc = port.get("allocation", {}) or {}
    total = 0.0
    for k, v in raw_alloc.items():
        try:
            val = float(v)
        except (TypeError, ValueError):
            val = 0.0
        clean["portfolio"]["allocation"][k] = val
        total += val
    if total > 0:
        clean["portfolio"]["allocation"] = {
            k: round(v / total * 100, 1) for k, v in clean["portfolio"]["allocation"].items()
        }

    path = _invest_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(clean, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except OSError as e:
        return {"ok": False, "error": f"写入失败: {e}"}
    return {"ok": True, "normalized": total > 0}
