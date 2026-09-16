"""运行时适配层 —— 同一套代码同时跑本地和 PocketBay 容器。

部署平台只跑一个 web 进程、不提供 cron，可写状态放在持久卷 /data
（注入 POCKETBAY_DATA_DIR）。本模块统一解析可写路径、对齐时区、加载 .env。
"""

from __future__ import annotations

import logging
import os
import shutil
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
