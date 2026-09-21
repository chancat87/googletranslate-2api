"""内存 TTL-LRU 缓存 (P1.2) / Redis 共享缓存 (v1.6.0) + 跨进程稳定 key (M2)。

cachetools.TTLCache 自带容量上限 + 过期淘汰, 线程/协程安全读, 写入靠锁。
仅缓存翻译成功结果; 失败一律不缓存。

M2: 缓存 key 使用 sha256 摘要而不是 `hash(text)` —— Python 的 str.__hash__
受 PYTHONHASHSEED 随机化影响, 同一文本在不同进程/重启后 hash 值不同,
会导致多 worker 环境下缓存命中率≈0; 摘要 key 跨进程稳定。

v1.6.0: `CACHE_BACKEND=redis` 时使用 Redis 共享缓存 (统一前缀 + TTL),
多 worker / 多副本共用一份翻译缓存; Redis 不可用时自动回退进程内内存缓存。
"""

import contextlib
import hashlib

try:
    from cachetools import TTLCache

    _HAS_CACHE = True
except ImportError:  # pragma: no cover - 无 cachetools 时退化为无缓存, 不阻断功能
    _HAS_CACHE = False

from loguru import logger

from app.core.config import settings


class RedisCacheBackend:
    """异步 Redis 缓存后端: 统一前缀隔离命名空间, 过期时间取 CACHE_TTL。"""

    def __init__(self, client, prefix: str, ttl: int):
        self._client = client
        self._prefix = prefix
        self._ttl = max(1, ttl)

    async def get(self, key: str) -> str | None:
        value = await self._client.get(self._prefix + key)
        return value if isinstance(value, str) else None

    async def set(self, key: str, value: str) -> None:
        await self._client.set(self._prefix + key, value, ex=self._ttl)

    async def aclose(self) -> None:
        await self._client.aclose()


def make_cache():
    """按配置构造缓存实例; 关闭或无依赖时返回 None。"""
    if not settings.CACHE_ENABLED or not _HAS_CACHE:
        return None
    return TTLCache(maxsize=settings.CACHE_MAXSIZE, ttl=settings.CACHE_TTL)


async def make_redis_cache():
    """构造 Redis 共享缓存后端; 连接失败时告警并返回 None (调用方回退内存缓存)。"""
    if not settings.CACHE_ENABLED:
        return None
    client = None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await client.ping()
    except Exception as exc:
        logger.warning(f"Redis 缓存不可用, 回退内存缓存: {exc}")
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()
        return None
    assert client is not None
    return RedisCacheBackend(client, settings.CACHE_PREFIX, settings.CACHE_TTL)


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
