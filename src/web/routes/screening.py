"""选股漏斗 Web 页面 — 触发筛选、查看结果。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid

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
# 设计要点：漏斗筛选是**重网络**操作（akshare / baostock 拉取），首屏可能要 30s+，
# 远超平台网关的 HTTP 请求超时。若在前端请求内同步等待，网关会先返回 HTML 错误页，
# 浏览器 resp.json() 直接抛 `Unexpected token '<'`。
# 因此改成「立即返回 task_id + 后台线程跑 + 轮询 status」的异步模型：
#   ① POST/GET /screening/api/run   -> {"ok":true,"task_id":...}（毫秒级返回）
#   ② GET      /screening/api/status?task_id=... -> {status:"running"|"done"|"error", ...}
# 这样所有 HTTP 响应都短平快，且始终返回 JSON，绝不返回 HTML 错误页。
_pending_tasks: dict[str, dict] = {}
_TASK_TTL = 1800  # 任务结果保留 30 分钟


def _pick_data_provider():
    """按顺序尝试可用的数据源，返回首个可用的 provider；都不行返回 None。"""
    from ...data.sina_client import SinaClient
    from ...data.akshare_client import AkshareClient

    for cls in (SinaClient, AkshareClient):
        try:
            return cls()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"{cls.__name__} 不可用: {e}")
    return None


def _build_result_payload(result) -> dict:
    """把 ScreeningResult 序列化成前端需要的 JSON 结构。"""
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

    return {
        "date": result.date,
        "input_count": result.input_count,
        "output_count": result.output_count,
        "duration_ms": result.duration_ms,
        "step_stats": {str(k): v for k, v in result.step_stats.items()},
        "passed": passed[:50],
        "failed_count": failed_count,
        "errors": result.errors,
    }


def _run_task(task_id: str, universe: str, step_list: list[int], timeout: int):
    """后台线程：执行漏斗筛选，把结果/异常写回 _pending_tasks。"""
    try:
        from ...config import load_screening_config
        from ...screening.datasource import FunnelDataSource
        from ...screening.pipeline import ScreenPipeline

        cfg = load_screening_config()
        cfg["active_steps"] = step_list

        data_provider = _pick_data_provider()
        if data_provider is None:
            _pending_tasks[task_id] = {
                "status": "error",
                "error": "无可用的数据源（SinaClient / AkshareClient 均初始化失败）",
                "ts": time.time(),
            }
            return

        data = FunnelDataSource(data_provider)
        pipeline = ScreenPipeline(data, config=cfg)

        # 在线程内用带超时的线程实现等待（threading 没有 asyncio.wait_for）
        result_holder = {}
        exc_holder = {}

        def _target():
            try:
                result_holder["r"] = pipeline.run(universe=universe, steps=step_list)
            except Exception as e:  # noqa: BLE001
                exc_holder["e"] = e

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if "e" in exc_holder:
            raise exc_holder["e"]
        if t.is_alive():
            _pending_tasks[task_id] = {
                "status": "error",
                "error": f"漏斗执行超时（>{timeout}s），请减少步骤或缩小标的池后重试",
                "hint": "建议先用 steps=1 只做量价筛选，确认数据源可访问后再加步骤",
                "ts": time.time(),
            }
            return

        payload = _build_result_payload(result_holder["r"])
        payload["status"] = "done"
        payload["ok"] = True
        payload["ts"] = time.time()
        _pending_tasks[task_id] = payload

    except Exception as e:  # noqa: BLE001
        logger.exception("漏斗任务 %s 执行失败", task_id)
        _pending_tasks[task_id] = {
            "status": "error",
            "error": f"漏斗执行异常: {e}",
            "ts": time.time(),
        }


def _expire_old_tasks():
    now = time.time()
    expired = [k for k, v in _pending_tasks.items() if now - v.get("ts", 0) > _TASK_TTL]
    for k in expired:
        _pending_tasks.pop(k, None)


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
    timeout: int = Query(300, description="后台执行超时秒数（首屏需等待行情拉取，后台跑不占 HTTP 连接）"),
):
    """触发漏斗筛选（异步）。

    立即返回 task_id，漏斗在后台线程执行；前端用
    /screening/api/status?task_id= 轮询结果。任何异常都不会返回 HTML。
    """
    step_list = [int(s.strip()) for s in steps.split(",") if s.strip().isdigit()]
    if not step_list:
        return JSONResponse({"ok": False, "error": "步骤参数为空，请至少选择一步（如 1）"})

    task_id = uuid.uuid4().hex
    _expire_old_tasks()
    _pending_tasks[task_id] = {"status": "running", "ts": time.time()}

    threading.Thread(
        target=_run_task, args=(task_id, universe, step_list, timeout), daemon=True
    ).start()

    return JSONResponse({"ok": True, "task_id": task_id, "status": "running"})


@router.get("/screening/api/status")
async def api_screening_status(task_id: str = Query(...)):
    """轮询漏斗任务状态，始终返回 JSON。"""
    task = _pending_tasks.get(task_id)
    if task is None:
        return JSONResponse({"ok": False, "status": "unknown", "error": "任务不存在或已过期，请重新运行漏斗"})
    # running 时只回状态，done/error 时透传完整结果
    return JSONResponse(task)


@router.get("/screening/api/config")
async def api_get_config():
    """获取当前漏斗配置。"""
    from ...config import load_screening_config
    return JSONResponse({"ok": True, "config": load_screening_config()})
