"""运行时适配层 —— 同一套代码同时跑本地和 PocketBay 容器。

部署平台只跑一个 web 进程、不提供 cron，可写状态放在持久卷 /data
（注入 POCKETBAY_DATA_DIR）。本模块统一解析可写路径、对齐时区、加载 .env。
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_CONFIG_DIR = PROJECT_ROOT / "config"

DEFAULT_TIMEZONE = "Asia/Shanghai"


def data_dir() -> Path:
    """可写数据根目录：平台注入 POCKETBAY_DATA_DIR=/data，本地回落仓库根。"""
    raw = os.environ.get("POCKETBAY_DATA_DIR") or os.environ.get("AITRADER_DATA_DIR")
    if raw:
        return Path(raw).expanduser()
    return PROJECT_ROOT


def is_managed_env() -> bool:
    """是否运行在托管平台——用于决定是否在 web 进程内启动调度器。"""
    return bool(os.environ.get("POCKETBAY_DATA_DIR"))


def apply_timezone() -> str:
    """把进程时区对齐到 A 股交易日。容器默认 UTC，会让 datetime.now() 错一天。"""
    tz = os.environ.get("TZ") or DEFAULT_TIMEZONE
    os.environ["TZ"] = tz
    if hasattr(time, "tzset"):  # Windows 无此函数，本地开发保持系统时区
        try:
            time.tzset()
        except (OSError, ValueError) as e:
            logger.warning("时区设置失败(%s): %s", tz, e)
    return tz


def load_env() -> None:
    """加载 .env。读取失败静默跳过——部署版默认不含任何密钥。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for candidate in (PROJECT_ROOT / ".env", data_dir() / ".env"):
        try:
            if candidate.exists():
                load_dotenv(candidate, override=False)
        except OSError as e:
            logger.warning("读取 %s 失败: %s", candidate, e)


def config_dir() -> Path:
    """包内只读配置目录。"""
    return SEED_CONFIG_DIR


def config_path(name: str) -> Path:
    """可写配置路径；首次运行时从包内 config/ 播种到可写目录。

    页面会改 traders.yaml / watchlist.yaml，写进容器层会随下次部署丢失。
    """
    target = data_dir() / "config" / name
    if target.exists():
        return target

    seed = SEED_CONFIG_DIR / name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if seed.exists():
            shutil.copyfile(seed, target)
            logger.info("配置已播种: %s", target)
    except OSError as e:
        logger.warning("配置播种失败(%s): %s，回退只读副本", name, e)
        return seed
    return target


def db_url(configured_path: str = "data/simulation.db") -> str:
    """数据库连接串。平台注入 DATABASE_URL 时优先，否则 SQLite 落可写目录。"""
    url = (os.environ.get("DATABASE_URL") or "").strip()
    # SQLAlchemy 2.0 已不接受 postgres:// 前缀
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    if url and url.startswith(("postgresql://", "postgresql+psycopg2://")):
        # 驱动未随包安装时不要硬连——回退 SQLite，否则会整站起不来
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            logger.warning("检测到 DATABASE_URL，但缺少对应驱动，已回退 SQLite 持久卷")
            url = ""
    if url:
        return url

    path = Path(configured_path)
    if not path.is_absolute():
        path = data_dir() / path
    return f"sqlite:///{path.as_posix()}"


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging(level: str = "INFO") -> None:
    """日志统一输出到 stdout——平台用运行日志做失败诊断。"""
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def run_with_timeout(fn, timeout: float, default=None):
    """在守护线程里执行 fn，超过 timeout 秒即放弃等待并返回 default。

    用于第三方数据源（baostock 等）不提供超时参数、网络不可达时可能无限阻塞的场景。
    超时的线程无法被强杀，会自行退出；调用方拿到 default 继续，不阻塞请求。
    """
    box: dict = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - 第三方库异常类型不可控
            box["error"] = e

    name = getattr(fn, "__name__", "call")
    worker = threading.Thread(target=_target, name=f"timeout-{name}", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        logger.warning("%s 超过 %.0fs 未返回，已放弃等待", name, timeout)
        return default
    if "error" in box:
        raise box["error"]
    return box.get("value", default)


# ── 数据源熔断 ──
# 意义：baostock 这类源不可达时不是"失败"，而是"永久挂起"。只靠超时的话，
# 每个请求都要先白等一个超时周期；熔断让后续请求立刻跳过，页面不再被拖慢。
_SOURCE_DOWN_UNTIL: dict[str, float] = {}
_SOURCE_GUARD = threading.Lock()
DEFAULT_SOURCE_COOLDOWN = 600.0


def source_available(name: str) -> bool:
    """数据源是否可用（熔断冷却期内返回 False）。"""
    with _SOURCE_GUARD:
        return time.time() >= _SOURCE_DOWN_UNTIL.get(name, 0.0)


def mark_source_down(name: str, cooldown: float = DEFAULT_SOURCE_COOLDOWN) -> None:
    """标记数据源不可用，冷却期内不再尝试。"""
    with _SOURCE_GUARD:
        _SOURCE_DOWN_UNTIL[name] = time.time() + cooldown
    logger.warning("数据源 %s 不可用，%.0f 秒内跳过", name, cooldown)


def mark_source_up(name: str) -> None:
    """数据源恢复正常，解除熔断。"""
    with _SOURCE_GUARD:
        if _SOURCE_DOWN_UNTIL.pop(name, None) is not None:
            logger.info("数据源 %s 已恢复", name)


# ── 日期格式归一化 ──
# 为什么必须收口：内部各数据源对日期格式要求不一致——
#   baostock 要求 "YYYY-MM-DD"（传 "YYYYMMDD" 会被拒：'日期格式不正确，请修改。'），
#   而筛选器历史上按 akshare 的紧凑格式 "YYYYMMDD" 传参。
# 更隐蔽的是 kline_http 用字符串比较过滤区间：紧凑格式与 "2024-01-02" 比较时
# 会因 ASCII 顺序（'0' > '-'）恒为 False，导致**整批数据被静默过滤掉**，
# 表现为"历史成交量全部取不到"而不是报错。统一在边界归一化，杜绝这类静默失败。
def normalize_date(value) -> str:
    """把日期归一化为 ISO "YYYY-MM-DD"。

    接受 str/date/datetime；无法识别时原样返回（由调用方自行处理）。
    """
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")

    s = str(value).strip()
    if not s:
        return ""
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s
