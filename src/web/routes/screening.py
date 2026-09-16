"""选股漏斗 Web 页面 — 触发筛选、查看结果。"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse

from ..deps import templates

logger = logging.getLogger(__name__)

# 注意：本路由**不使用 prefix="/screening"**。
# 用 prefix + @router.get("/") 会把页面注册成 `/screening/`，导致 `/screening`
# 落到 Starlette 的尾斜杠重定向：线上实测返回
#     307 Location: http://aitrader--e.pocketbay.app/screening/
# 应用跑在平台 https 网关后面，生成的绝对 URL 是明文 http —— 页面在 https
# iframe 内，跟随该重定向会被浏览器按「混合内容」拦掉，表现就是
# 「点漏斗没反应/进不去」。这里把路径写成全量、与其它页面路由（/signals、
# /reports 等）保持一致，两个形态都直接 200，彻底不产生重定向。
router = APIRouter(tags=["screening"])

# 漏斗任务缓存（task_id -> result）
_pending_tasks: dict[str, dict] = {}


@router.get("/screening", response_class=HTMLResponse)
@router.get("/screening/", response_class=HTMLResponse, include_in_schema=False)
async def screening_page(request: Request):
    """漏斗页面 — 参数选择 + 结果展示。"""
    return templates.TemplateResponse(
        request=request, name="screening.html",
        context={"config": None, "result": None},
    )


@router.get("/screening/api/run")
async def api_run_screening(
    request: Request,
    universe: str = Query("hs300"),
    steps: str = Query("1"),
    timeout: int = Query(300, description="超时秒数（首次运行需等待行情拉取 ~3min，缓存 5min 后秒返）"),
):
    """触发漏斗筛选，在后台线程运行，不阻塞服务器。

    使用 asyncio.to_thread 将同步漏斗抛到线程池，
    超时后返回已收集到的部分结果。
    """
    from ...config import load_screening_config
    from ...screening.datasource import FunnelDataSource
    from ...screening.pipeline import ScreenPipeline

    cfg = load_screening_config()
    step_list = [int(s.strip()) for s in steps.split(",") if s.strip().isdigit()]
    cfg["active_steps"] = step_list

    # 选择可用的数据源
    data_provider = None
    try:
        from ...data.sina_client import SinaClient
        data_provider = SinaClient()
    except Exception:
        pass
    if data_provider is None:
        try:
            from ...data.akshare_client import AkshareClient
            data_provider = AkshareClient()
        except Exception:
            pass

    if data_provider is None:
        return JSONResponse({"ok": False, "error": "无可用的数据源"})

    data = FunnelDataSource(data_provider)
    pipeline = ScreenPipeline(data, config=cfg)

    # 在后台线程中运行，不阻塞事件循环
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(pipeline.run, universe=universe, steps=step_list),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return JSONResponse({
            "ok": False,
            "error": f"漏斗执行超时（>{timeout}s），请减少步骤或缩小标的池后重试",
            "hint": "建议先用 --steps 1 只做量价筛选（不依赖 akshare 网络），确认可访问后再加步骤",
        })

    # 构建响应
    passed = []
    for a in sorted(
        [a for a in result.assessments.values() if a.passed],
        key=lambda a: a.total_score,
        reverse=True,
    ):
        passed.append({
            "symbol": a.symbol,
            "name": a.name,
            "industry": a.industry,
            "total_score": round(a.total_score, 2),
            "pe": a.pe,
            "pb": a.pb,
            "market_cap": a.market_cap,
            "steps": [
                {"step": s.step, "passed": s.passed, "score": round(s.score, 2), "reason": s.reason}
                for s in a.steps
            ],
        })

    failed_count = sum(1 for a in result.assessments.values() if not a.passed)

    return JSONResponse({
        "ok": True,
        "date": result.date,
        "input_count": result.input_count,
        "output_count": result.output_count,
        "duration_ms": result.duration_ms,
        "step_stats": {
            str(k): v for k, v in result.step_stats.items()
        },
        "passed": passed[:50],
        "failed_count": failed_count,
        "errors": result.errors,
    })


@router.get("/screening/api/config")
async def api_get_config():
    """获取当前漏斗配置。"""
    from ...config import load_screening_config
    return JSONResponse({"ok": True, "config": load_screening_config()})
