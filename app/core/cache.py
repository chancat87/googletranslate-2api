"""内存 TTL-LRU 缓存 (P1.2)。

cachetools.TTLCache 自带容量上限 + 过期淘汰, 线程/协程安全读, 写入靠锁。
仅缓存翻译成功结果; 失败一律不缓存。
"""
from typing import Optional, Tuple, Any

try:
    from cachetools import TTLCache
    _HAS_CACHE = True
except ImportError:  # ponytail: 无 cachetools 时退化为无缓存, 不阻断功能
    _HAS_CACHE = False

from app.core.config import settings


def make_cache():
    """按配置构造缓存实例; 关闭或无依赖时返回 None。"""
    if not settings.CACHE_ENABLED or not _HAS_CACHE:
        return None
    return TTLCache(maxsize=settings.CACHE_MAXSIZE, ttl=settings.CACHE_TTL)


def cache_key(text: str, source_lang: str, target_lang: str) -> str:
    return f"{source_lang}:{target_lang}:{hash(text)}"


def cache_get(cache, key: str) -> Optional[str]:
    if cache is None:
        return None
    return cache.get(key)


def cache_put(cache, key: str, value: str) -> None:
    if cache is None or not value:
        return
    cache[key] = value
