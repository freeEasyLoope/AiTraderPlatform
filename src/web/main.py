"""FastAPI 应用入口——挂载路由模块。"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .routes.dashboard import router as dashboard_router
from .routes.control import router as control_router
from .routes.reports import router as reports_router
from .routes.watchlist import router as watchlist_router
from .routes.analysis import router as analysis_router
from .routes.strategies import router as strategies_router
from .routes.signal_briefing import router as signal_briefing_router
from .routes.risk_lab import router as risk_lab_router
from .routes.onboarding import router as onboarding_router
from .routes.challenge import router as challenge_router
from .routes.screening import router as screening_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动钩子：建表、播种操盘手，必要时在进程内启动调度器。

    PocketBay 只跑一个 web 进程且不提供 cron，定时交易必须在应用内调度。
    本地（未注入 POCKETBAY_DATA_DIR）默认不启动，避免与 run_daily.bat 重复下单。
    """
    from ..config import load_settings, load_traders
    from ..engine.scheduler import TradingScheduler
    from ..runtime import is_managed_env, setup_logging
    from .deps import repo

    settings = load_settings()
    setup_logging(settings.get("logging", {}).get("level", "INFO"))

    # 部署包不含本地 SQLite，线上首启必须自建表并创建操盘手账户，否则首屏是空看板
    repo.init_traders(load_traders())
    logger.info("数据库就绪: %s", repo.engine.url)

    scheduler = None
    sched_cfg = settings.get("scheduler", {}) or {}
    # 托管平台会注入 PORT（本地跑 web.py 不设 PORT），这是最可靠的「已在平台运行」信号：
    # 平台不提供 cron，定时交易只能在 web 进程内跑。
    deployed = bool(os.environ.get("PORT")) or is_managed_env()
    want_scheduler = (
        os.environ.get("AITRADER_DISABLE_SCHEDULER") != "1"
        and (bool(sched_cfg.get("run_in_web")) or deployed)
    )
    if want_scheduler:
        try:
            from ..analysis.llm_reporter import LLMReporter
            from ..engine.factory import build_simulator

            llm_cfg = settings.get("llm", {}) or {}
            reporter = LLMReporter(
                repo,
                model=llm_cfg.get("model", "claude-sonnet-4-6"),
                max_tokens=llm_cfg.get("max_tokens", 4096),
                temperature=llm_cfg.get("temperature", 0.3),
            )
            scheduler = TradingScheduler(build_simulator(repo), reporter=reporter)
            scheduler.start(
                trading_time=sched_cfg.get("trading_time", "21:00"),
                report_time=sched_cfg.get("weekly_report_time", "21:30"),
                report_day=sched_cfg.get("weekly_report_day", "fri"),
            )
            logger.info("进程内调度已启用（时区 %s）", os.environ.get("TZ", "?"))
        except Exception:
            # 定时任务装配失败不能拖垮 web 服务：平台探活失败 = 整站判定不可用
            scheduler = None
            logger.exception("进程内调度启用失败，本次以无调度模式启动")
    else:
        logger.info("进程内调度未启用（本地模式，可用 cli.py schedule 单独跑）")

    app.state.scheduler = scheduler

    yield

    if scheduler is not None:
        scheduler.stop()


app = FastAPI(title="AITrader Dashboard", lifespan=lifespan)

# ── 可选的简单密码保护（生产环境） ──
_AUTH_USERNAME = os.environ.get("AITRADER_USERNAME", "")
_AUTH_PASSWORD = os.environ.get("AITRADER_PASSWORD", "")


class SimpleAuthMiddleware(BaseHTTPMiddleware):
    """简单的 Basic Auth 中间件。仅在设置了 AITRADER_USERNAME 时生效。"""

    async def dispatch(self, request: Request, call_next):
        if not _AUTH_USERNAME:
            return await call_next(request)
        # 跳过 API 和健康检查
        if request.url.path.startswith("/api/") or request.url.path.startswith("/static/"):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        expected = f"Basic {_AUTH_USERNAME}:{_AUTH_PASSWORD}"
        import base64
        expected_b64 = base64.b64encode(f"{_AUTH_USERNAME}:{_AUTH_PASSWORD}".encode()).decode()

        if not auth.startswith("Basic ") or auth.split(" ", 1)[1] != expected_b64:
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Basic realm=\"AITrader\""},
            )

        return await call_next(request)


if _AUTH_USERNAME:
    app.add_middleware(SimpleAuthMiddleware)

# 静态文件
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 挂载路由
app.include_router(dashboard_router)
app.include_router(strategies_router)
app.include_router(signal_briefing_router)
app.include_router(risk_lab_router)
app.include_router(onboarding_router)
app.include_router(challenge_router)
app.include_router(screening_router)
app.include_router(control_router)
app.include_router(reports_router)
app.include_router(watchlist_router)
app.include_router(analysis_router)


# 健康检查探针是阻塞网络调用（baostock 不可达时可达 80s+），
# ① 用同步 def 让 FastAPI 丢进线程池，不冻结事件循环；
# ② 加 5 分钟缓存，避免每次开页面都重探。
_HEALTH_TTL_SECONDS = 300
_health_cache: dict = {"ts": 0.0, "data": None}


@app.get("/api/health")
def api_health():
    """数据源健康检查（带缓存）。"""
    import os
    import time as _time

    now = _time.time()
    cached = _health_cache["data"]
    if cached is not None and now - _health_cache["ts"] < _HEALTH_TTL_SECONDS:
        return cached

    health = {"sina": False, "baostock": False, "tushare": False}
    from ..runtime import run_with_timeout

    def _probe_sina() -> bool:
        from ..data.sina_client import SinaClient
        snap = SinaClient().get_snapshot("600519")
        return snap is not None and snap.close > 0

    def _probe_baostock() -> bool:
        import baostock as bs
        lg = bs.login()
        ok = lg.error_code == "0"
        if ok:
            bs.logout()
        return ok

    # 两个数据源都不接受超时参数（baostock 不可达时可阻塞 80s+），统一设界，
    # 否则探活请求会一直挂着——单进程容器里足以让平台判定服务不可用。
    try:
        health["sina"] = bool(run_with_timeout(_probe_sina, 10, False))
    except Exception:
        pass
    try:
        health["baostock"] = bool(run_with_timeout(_probe_baostock, 8, False))
    except Exception:
        pass
    try:
        token = os.environ.get("TUSHARE_TOKEN", "")
        if token:
            import tushare as ts
            ts.set_token(token)
            health["tushare"] = True
    except Exception:
        pass

    _health_cache["ts"] = now
    _health_cache["data"] = health
    return health


@app.get("/api/news/{symbol}")
def api_stock_news(symbol: str, days: int = 5):
    """获取个股新闻/公告。"""
    from ..data.news_client import get_stock_news
    news = get_stock_news(symbol, days=days)
    return {"ok": True, "news": news}


# 连通性体检目标：固定清单、不接受入参，避免变成 SSRF 跳板。
# 排查"线上拿不到行情"时按 DNS → TCP → 真实数据 三层定位。
_DIAG_TARGETS = [
    ("example.com", 443, "国际站点基线（验证出网是否可用）"),
    ("hq.sinajs.cn", 80, "新浪实时行情"),
    ("quotes.money.163.com", 80, "网易历史日线"),
    ("push2his.eastmoney.com", 443, "东方财富（akshare 路径）"),
    ("public-api.baostock.com", 10030, "baostock 服务端口（真实端点）"),
    ("api.tushare.pro", 443, "tushare"),
    ("query1.finance.yahoo.com", 443, "Yahoo Finance（A股代码 600519.SS，境外备用候选）"),
]

# 应用层探针：TCP 秒连不算通，必须读到真实响应体。
_UA = {"User-Agent": "Mozilla/5.0"}
_DIAG_HTTP = [
    ("https://example.com", dict(_UA), "出网基线（有响应体=沙箱能出网）"),
    ("http://hq.sinajs.cn/list=sh600519",
     {**_UA, "Referer": "https://finance.sina.com.cn"}, "新浪实时行情（应返回 hq_str_sh600519=…）"),
    ("http://quotes.money.163.com/service/chddata.html"
     "?code=0600519&start=20260901&end=20260916&fields=TCLOSE", dict(_UA), "网易历史日线"),
    ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
     "?secid=1.600519&fields1=f1&fields2=f51,f53&klt=101&fqt=1&lmt=5", dict(_UA),
     "东方财富日线（akshare 同源）"),
    ("https://query1.finance.yahoo.com/v8/finance/chart/600519.SS?range=1mo&interval=1d",
     dict(_UA), "Yahoo 的 A 股日线（境外备用候选）"),
]


@app.get("/api/diag")
def api_diag():
    """数据源连通性体检：DNS → TCP → 真实 HTTP 取数，三层定位。

    注意：托管沙箱普遍走透明代理，TCP 会「秒连成功」但数据并不真的通。
    所以只信第三层——能读到真实响应体才算通。
    """
    import socket
    import time as _time
    import urllib.request

    from ..runtime import run_with_timeout

    hosts = []
    for host, port, label in _DIAG_TARGETS:
        item: dict = {"host": host, "port": port, "label": label}

        def _dns(h: str = host, p: int = port) -> bool:
            socket.getaddrinfo(h, p, proto=socket.IPPROTO_TCP)
            return True

        t0 = _time.time()
        try:
            item["dns"] = "ok" if run_with_timeout(_dns, 6, False) else "timeout"
        except Exception as e:
            item["dns"] = f"fail:{type(e).__name__}"
        item["dns_ms"] = round((_time.time() - t0) * 1000)

        def _tcp(h: str = host, p: int = port) -> bool:
            with socket.create_connection((h, p), timeout=5):
                return True

        t0 = _time.time()
        try:
            item["tcp"] = "ok" if run_with_timeout(_tcp, 7, False) else "timeout"
        except Exception as e:
            item["tcp"] = f"fail:{type(e).__name__}"
        item["tcp_ms"] = round((_time.time() - t0) * 1000)
        hosts.append(item)

    def _http(url: str, headers: dict) -> dict:
        from urllib.error import HTTPError
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read(300)
                return {"status": resp.status, "bytes": len(body),
                        "body": body.decode("utf-8", "replace")[:120]}
        except HTTPError as e:
            body = e.read(200)
            return {"status": e.code, "bytes": len(body),
                    "body": body.decode("utf-8", "replace")[:120]}

    http = []
    for url, headers, label in _DIAG_HTTP:
        t0 = _time.time()
        try:
            got = run_with_timeout(lambda u=url, h=headers: _http(u, h), 12, None)
        except Exception as e:
            got = {"error": f"{type(e).__name__}: {e}"[:120]}
        if got is None:
            got = {"error": "timeout(12s) — 连接建立了但拿不到响应体"}
        got["ms"] = round((_time.time() - t0) * 1000)
        got["label"] = label
        got["url"] = url
        http.append(got)

    return {"ok": True, "hosts": hosts, "http": http}
