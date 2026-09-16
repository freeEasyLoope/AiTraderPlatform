"""内存 TTL 缓存 — 避免同一天重复调用 akshare API。"""

from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable


class TtlCache:
    """简单的内存缓存，带 per-key 过期时间。"""

    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}  # key -> (expiry_ts, value)

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expiry, value = entry
        if time.monotonic() > expiry:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# 模块级单例
_funnel_cache = TtlCache()


def ttl_cache(ttl_seconds: int):
    """装饰器：缓存函数返回值 ttl_seconds 秒。

    缓存 key = 函数名 + 参数，适用于数据获取函数。
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 构建缓存 key（排除 self 参数）
            cache_args = args[1:] if args and hasattr(args[0], '__dict__') else args
            key_parts = [func.__name__]
            for a in cache_args:
                if isinstance(a, list):
                    # 股票列表只取前 3 个 + 长度做 key（列表本身可能很长）
                    key_parts.append(f"list({len(a)}):{a[:3]}")
                else:
                    key_parts.append(str(a))
            for k in sorted(kwargs):
                key_parts.append(f"{k}={kwargs[k]}")
            key = ":".join(key_parts)

            cached = _funnel_cache.get(key)
            if cached is not None:
                return cached

            result = func(*args, **kwargs)
            _funnel_cache.set(key, result, ttl_seconds)
            return result

        return wrapper

    return decorator
