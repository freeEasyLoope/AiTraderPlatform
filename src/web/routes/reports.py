"""周报 & 操作中心路由。

「日志 & 周报」已合并进设置中心（/settings），/reports 作为旧链接兼容入口，
直接渲染组合页并默认落在「日志」标签。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import repo, templates
from ...config import load_settings
from ...storage.models import WeeklyReport
from ...analysis.llm_reporter import LLMReporter
from .settings import _build_settings_context

router = APIRouter()


def _ai_report_enabled() -> bool:
    """AI 周报功能开关（settings.yaml -> features.ai_report_enabled）。"""
    try:
        settings = load_settings()
        return bool((settings.get("features") or {}).get("ai_report_enabled", False))
    except Exception:
        return False


@router.get("/reports", response_class=HTMLResponse)
async def reports(request: Request):
    """旧链接兼容入口：渲染设置中心并默认打开「日志 & 周报」标签。"""
    return templates.TemplateResponse(
        request=request, name="settings.html",
        context=_build_settings_context(active_tab="logs"))


@router.post("/api/control/trigger_report")
async def api_trigger_report():
    """即时生成 LLM 周报。"""
    if not _ai_report_enabled():
        return {"ok": False, "error": "该功能暂未开通"}
    try:
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        friday = monday + timedelta(days=4)
        reporter = LLMReporter(repo)
        reporter.generate(monday.strftime("%Y-%m-%d"), friday.strftime("%Y-%m-%d"))
        return {"ok": True, "week": f"{monday.strftime('%Y-%m-%d')}~{friday.strftime('%Y-%m-%d')}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
