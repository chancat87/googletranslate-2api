"""内存 TTL-LRU 缓存 (P1.2) + 跨进程稳定 key (M2)。

cachetools.TTLCache 自带容量上限 + 过期淘汰, 线程/协程安全读, 写入靠锁。
仅缓存翻译成功结果; 失败一律不缓存。

M2: 缓存 key 使用 sha256 摘要而不是 `hash(text)` —— Python 的 str.__hash__
受 PYTHONHASHSEED 随机化影响, 同一文本在不同进程/重启后 hash 值不同,
会导致多 worker 环境下缓存命中率≈0; 摘要 key 跨进程稳定。
"""

import hashlib

try:
    from cachetools import TTLCache

    _HAS_CACHE = True
except ImportError:  # pragma: no cover - 无 cachetools 时退化为无缓存, 不阻断功能
    _HAS_CACHE = False

from app.core.config import settings


def make_cache():
    """按配置构造缓存实例; 关闭或无依赖时返回 None。"""
    if not settings.CACHE_ENABLED or not _HAS_CACHE:
        return None
    return TTLCache(maxsize=settings.CACHE_MAXSIZE, ttl=settings.CACHE_TTL)


def cache_key(text: str, source_lang: str, target_lang: str) -> str:
    """稳定缓存 key: 语言对 + 文本 sha256 摘要。"""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{source_lang}:{target_lang}:{digest}"


def cache_get(cache, key: str) -> str | None:
    if cache is None:
        return None
    return cache.get(key)


def cache_put(cache, key: str, value: str) -> None:
    if cache is None or not value:
        return
    cache[key] = value
