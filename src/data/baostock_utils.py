"""baostock 工具 — 静默登录/登出。"""

from __future__ import annotations

import io
import sys
from contextlib import contextmanager


@contextmanager
def bs_session():
    """baostock 静默会话上下文管理器。

    usage:
        with bs_session() as bs:
            rs = bs.query_history_k_data_plus(...)
            data = rs.get_data()
    """
    import baostock as bs

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
        yield bs
    finally:
        bs.logout()
        sys.stdout = old_stdout
