"""限流 (M6 + v1.7.0 分布式后端)。

- memory: 进程内令牌桶 (默认), 有界 LRU, 防止随机 key 撑爆内存。
- redis: 多 worker/多副本共享令牌桶 (Lua 原子脚本), Redis 故障时自动回退内存并告警。
"""

import threading
import time
from collections import OrderedDict
from typing import Any

from loguru import logger

from app.core.config import settings


class TokenBucket:
    """令牌桶: 以固定速率补充令牌, 容量上限。"""

    def __init__(self, capacity: int, per_second: float) -> None:
        self.capacity = max(1, capacity)
        self.per_second = max(0.0, per_second)
        self._tokens = float(capacity)
        self._updated = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self._updated
        self._updated = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.per_second)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def retry_after(self) -> float:
        """还需等待多少秒才能获得 1 个令牌 (供 429 Retry-After 头, P3-8)。"""
        now = time.monotonic()
        elapsed = now - self._updated
        self._updated = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.per_second)
        if self._tokens >= 1.0:
            return 0.0
        if self.per_second <= 0:
            return float("inf")
        return (1.0 - self._tokens) / self.per_second


class MemoryRateLimiter:
    """按 key 隔离的多桶限流器 (有界, LRU 淘汰)。"""

    def __init__(self, capacity: int, per_second: float, max_keys: int = 10000) -> None:
        self._capacity = capacity
        self._per_second = per_second
        self._max_keys = max(1, max_keys)
        self._buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._max_keys:
                    self._buckets.popitem(last=False)
                bucket = TokenBucket(self._capacity, self._per_second)
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)
            return bucket.consume()

    def retry_after(self, key: str) -> float:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return 0.0
            self._buckets.move_to_end(key)
            return bucket.retry_after()


class RateLimiter:
    """限流门面: memory 默认; redis 后端多副本共享, 故障自动回退内存。"""

    def __init__(
        self,
        capacity: int,
        per_second: float,
        max_keys: int = 10000,
        backend: str | None = None,
        redis_url: str | None = None,
        prefix: str | None = None,
        ttl: int | None = None,
    ) -> None:
        self._capacity = max(1, capacity)
        self._per_second = max(0.0, per_second)
        self._memory = MemoryRateLimiter(self._capacity, self._per_second, max_keys)
        self._backend = (backend or settings.RATE_LIMIT_BACKEND or "memory").lower()
        self._redis_url = redis_url or settings.RATE_LIMIT_REDIS_URL or settings.REDIS_URL
        self._prefix = prefix or settings.RATE_LIMIT_PREFIX
        self._ttl = int(ttl or settings.RATE_LIMIT_TTL or 3600)
        self._client: Any = None
        self._redis_broken = False
        self._init_lock = threading.Lock()

    async def _ensure_redis(self) -> None:
        if self._client is not None or self._redis_broken:
            return
        with self._init_lock:
            if self._client is not None or self._redis_broken:
                return
            import redis.asyncio as aioredis

            client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            await client.ping()
            self._client = client

    async def allow(self, key: str) -> bool:
        """消费 1 个令牌; 返回是否放行。"""
        if self._backend == "redis" and not self._redis_broken:
            try:
                await self._ensure_redis()
                if self._client is not None:
                    return await self._redis_allow(key)
            except Exception as exc:
                self._redis_broken = True
                if self._client is not None:
                    with _suppress():
                        await self._client.aclose()
                    self._client = None
                logger.warning(f"Redis 限流不可用, 回退内存限流: {exc}")
        return self._memory.allow(key)

    async def retry_after(self, key: str) -> float:
        """该 key 距可放行还需等待的秒数 (P3-8)。"""
        if self._backend == "redis" and not self._redis_broken:
            try:
                await self._ensure_redis()
                if self._client is not None:
                    return await self._redis_retry_after(key)
            except Exception as exc:
                self._redis_broken = True
                if self._client is not None:
                    with _suppress():
                        await self._client.aclose()
                    self._client = None
                logger.warning(f"Redis 限流不可用, 回退内存限流: {exc}")
        return self._memory.retry_after(key)

    async def _redis_allow(self, key: str) -> bool:
        """Redis 事务版令牌桶: WATCH + MULTI/EXEC 原子读改写, 冲突重试。"""
        from redis import exceptions as redis_exc

        client = self._client
        assert client is not None
        tokens_key = f"{self._prefix}{key}:t"
        ts_key = f"{self._prefix}{key}:ts"
        now = time.time()
        while True:
            try:
                async with client.pipeline(transaction=True) as pipe:
                    await pipe.watch(tokens_key, ts_key)
                    tokens_raw = await pipe.get(tokens_key)
                    ts_raw = await pipe.get(ts_key)
                    tokens = float(tokens_raw) if tokens_raw is not None else float(self._capacity)
                    ts = float(ts_raw) if ts_raw is not None else now
                    elapsed = max(0.0, now - ts)
                    tokens = min(float(self._capacity), tokens + elapsed * self._per_second)
                    allowed = tokens >= 1.0
                    if allowed:
                        tokens -= 1.0
                    pipe.multi()
                    pipe.set(tokens_key, str(tokens), ex=self._ttl)
                    pipe.set(ts_key, str(now), ex=self._ttl)
                    await pipe.execute()
                    return allowed
            except redis_exc.WatchError:
                continue

    async def _redis_retry_after(self, key: str) -> float:
        """Redis 事务版读取回填后剩余等待秒数。"""
        from redis import exceptions as redis_exc

        client = self._client
        assert client is not None
        tokens_key = f"{self._prefix}{key}:t"
        ts_key = f"{self._prefix}{key}:ts"
        now = time.time()
        while True:
            try:
                async with client.pipeline(transaction=True) as pipe:
                    await pipe.watch(tokens_key, ts_key)
                    tokens_raw = await pipe.get(tokens_key)
                    ts_raw = await pipe.get(ts_key)
                    tokens = float(tokens_raw) if tokens_raw is not None else float(self._capacity)
                    ts = float(ts_raw) if ts_raw is not None else now
                    elapsed = max(0.0, now - ts)
                    tokens = min(float(self._capacity), tokens + elapsed * self._per_second)
                    if tokens >= 1.0:
                        return 0.0
                    if self._per_second <= 0:
                        return float("inf")
                    return (1.0 - tokens) / self._per_second
            except redis_exc.WatchError:
                continue

    async def aclose(self) -> None:
        if self._client is not None:
            with _suppress():
                await self._client.aclose()
            self._client = None


def _suppress():
    import contextlib

    return contextlib.suppress(Exception)
