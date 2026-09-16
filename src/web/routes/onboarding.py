"""新手向导路由——三步引导新用户找到适合自己的策略。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import templates, build_symbol_names

router = APIRouter()


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding(request: Request):
    """互动式新手向导页面。"""
    return templates.TemplateResponse(
        request=request, name="onboarding.html", context={})
