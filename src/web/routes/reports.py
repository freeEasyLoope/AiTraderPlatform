"""周报 & 操作中心路由。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import repo, templates
from ...config import load_traders
from ...storage.models import WeeklyReport
from ...analysis.llm_reporter import LLMReporter

router = APIRouter()


@router.get("/reports", response_class=HTMLResponse)
async def reports(request: Request):
    """周报历史。"""
    with repo.session() as s:
        reports_raw = s.query(WeeklyReport).order_by(WeeklyReport.id.desc()).limit(20).all()
        report_list = []
        for r in reports_raw:
            rankings = []
            try:
                rankings = json.loads(r.rankings) if r.rankings else []
            except json.JSONDecodeError:
                pass
            report_list.append({"week_start": r.week_start, "week_end": r.week_end,
                                "summary": r.summary or "", "rankings": rankings})

    return templates.TemplateResponse(
        request=request, name="reports.html", context={"reports": report_list})


@router.post("/api/control/trigger_report")
async def api_trigger_report():
    """即时生成 LLM 周报。"""
    try:
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        friday = monday + timedelta(days=4)
        reporter = LLMReporter(repo)
        report = reporter.generate(monday.strftime("%Y-%m-%d"), friday.strftime("%Y-%m-%d"))
        return {"ok": True, "week": f"{monday.strftime('%Y-%m-%d')}~{friday.strftime('%Y-%m-%d')}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
