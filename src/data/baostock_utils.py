"""baostock 统一入口 — 带超时与熔断，静默登录/登出。

为什么必须收口：baostock 走私有 socket 协议且 **没有超时参数**。在托管平台
（透明代理环境）里 TCP 会被瞬间"接受"但拿不到任何响应，`bs.login()` 因此永久阻塞。
本项目有 7 处独立登录点，逐个裸调会让任何页面都可能被拖死。

统一用 `open_bs()`：
  - 首次调用带超时（默认 15s），超时即判定不可用；
  - 判定不可用后进入熔断冷却（默认 10 分钟），后续调用**立即返回 None**，
    不再每个请求白等一个超时周期；
  - 调用方拿到 None 直接放弃该数据源，页面正常降级渲染。

关于日志噪声：baostock 会往 stdout 直接 `print` 大量闲聊（"login success!"、
"日期格式不正确，请修改。" 一次调用能刷几十行）。旧代码用
`old, sys.stdout = sys.stdout, io.StringIO()` 临时重定向——**这个做法有害**：
一旦那次调用永久阻塞，重定向就永久生效，进程日志整段静音，线上反而看不到原因。
这里改用 `install_quiet_stdout()`：装一个常驻的**行过滤器**，只丢弃已知噪声行，
其余原样透传。它是幂等的、与线程存活无关，不存在"卡住就静音"的风险。
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager

from ..runtime import (
    mark_source_down,
    mark_source_up,
    run_with_timeout,
    source_available,
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "baostock"
LOGIN_TIMEOUT = 15.0

# baostock 直接 print 到 stdout 的闲聊行，逐条精确匹配（子串），避免误杀真实输出
_NOISE_MARKERS = (
    "login success!",
    "logout success!",
    "login fail",
    "logout fail",
    "日期格式不正确，请修改。",
    "网络接收错误",
)


def _is_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return any(m in stripped for m in _NOISE_MARKERS)


class _QuietStream:
    """按行过滤 stdout 的薄代理；非噪声内容原样透传。"""

    _aitrader_quiet = True

    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._buf = ""

    def write(self, s):
        if not isinstance(s, str):
            return self._wrapped.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if not _is_noise(line):
                self._wrapped.write(line + "\n")
        return len(s)

    def flush(self):
        if self._buf:
            if not _is_noise(self._buf):
                self._wrapped.write(self._buf)
            self._buf = ""
        try:
            self._wrapped.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


def install_quiet_stdout() -> None:
    """安装 baostock 噪声行过滤器（幂等）。

    会在 stdout 被 uvicorn/pytest 替换后自动重新包裹，所以每次登录前都可安全调用。
    """
    out = sys.stdout
    if getattr(out, "_aitrader_quiet", False):
        return
    if out is None:  # pythonw / 无控制台环境
        return
    try:
        sys.stdout = _QuietStream(out)
    except Exception:
        # 某些捕获器是只读代理，装不上就退回原样，不影响功能
        pass


def open_bs(timeout: float = LOGIN_TIMEOUT):
    """登录 baostock；不可用返回 None（调用方应直接放弃，不要重试）。"""
    if not source_available(SOURCE_NAME):
        return None

    install_quiet_stdout()

    def _login():
        import baostock as bs
        return bs.login()

    try:
        lg = run_with_timeout(_login, timeout, None)
    except Exception as e:
        logger.warning("baostock 登录异常: %s", e)
        lg = None

    if lg is None or getattr(lg, "error_code", "1") != "0":
        mark_source_down(SOURCE_NAME)
        return None

    mark_source_up(SOURCE_NAME)
    import baostock as bs
    return bs


def close_bs(bs) -> None:
    """登出；失败静默（连接已断时 logout 会抛）。"""
    try:
        bs.logout()
    except Exception:
        pass


@contextmanager
def bs_session(timeout: float = LOGIN_TIMEOUT):
    """baostock 会话上下文管理器；不可用时 **yield None** 而不是抛异常。

    usage:
        with bs_session() as bs:
            if bs is None:
                return
            rs = bs.query_...
    """
    bs = open_bs(timeout)
    try:
        yield bs
    finally:
        if bs is not None:
            close_bs(bs)
