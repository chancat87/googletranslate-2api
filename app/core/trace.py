"""请求链路摘要 (阶段 1.2 + v1.7.0 集中化)。

- 非流式: 响应头 X-Trace-Summary (单行摘要) + 存储可查。
- 流式: 响应头 X-Trace-Id, 客户端可凭该 ID 查 /v1/traces/{request_id}。
- memory: 进程内环形缓冲 (默认)。
- redis: 多 worker/多副本集中可查 (SET 记录 + ZSET 时间序), 故障回退内存。
- 隐私: 只存元数据, 不含请求原文与明文 Key。
"""

import contextlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any

from loguru import logger

from app.core.config import settings


class TraceStore:
    """链路摘要存储门面: memory 默认, redis 后端可配。"""

    def __init__(
        self,
        maxlen: int = 512,
        backend: str | None = None,
        redis_url: str | None = None,
        prefix: str | None = None,
        ttl: int | None = None,
    ) -> None:
        self.maxlen = maxlen
        self._backend = (backend or settings.TRACE_BACKEND or "memory").lower()
        self._redis_url = redis_url or settings.REDIS_URL
        self._prefix = prefix or settings.TRACE_PREFIX
        self._ttl = int(ttl or settings.TRACE_TTL or 3600)
        self._data: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()
        self._client: Any = None
        self._redis_broken = False

    async def _ensure_redis(self) -> None:
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

    async def put(self, request_id: str, record: dict) -> None:
        """写入一条链路摘要 (只含元数据)。"""
        if self._backend == "redis" and not self._redis_broken:
            try:
                await self._ensure_redis()
                if self._client is not None:
                    score = float(record.get("created_at") or time.time())
                    await self._client.zadd(f"{self._prefix}index", {request_id: score})
                    await self._client.set(
                        f"{self._prefix}rec:{request_id}",
                        json.dumps(record, ensure_ascii=False),
                        ex=self._ttl,
                    )
                    trim_ids = await self._client.zrange(
                        f"{self._prefix}index", 0, -self.maxlen - 1
                    )
                    if trim_ids:
                        await self._client.zrem(f"{self._prefix}index", *trim_ids)
                        await self._client.delete(*[f"{self._prefix}rec:{rid}" for rid in trim_ids])
                    return
            except Exception as exc:
                self._redis_broken = True
                if self._client is not None:
                    with contextlib.suppress(Exception):
                        await self._client.aclose()
                    self._client = None
                logger.warning(f"Redis trace 不可用, 回退内存存储: {exc}")
        with self._lock:
            self._data[request_id] = record
            self._data.move_to_end(request_id)
            while len(self._data) > self.maxlen:
                self._data.popitem(last=False)

    async def get(self, request_id: str) -> dict | None:
        """按 request_id 读取; 不存在返回 None。"""
        if self._backend == "redis" and not self._redis_broken:
            try:
                await self._ensure_redis()
                if self._client is not None:
                    raw = await self._client.get(f"{self._prefix}rec:{request_id}")
                    return json.loads(raw) if raw else None
            except Exception as exc:
                self._redis_broken = True
                if self._client is not None:
                    with contextlib.suppress(Exception):
                        await self._client.aclose()
                    self._client = None
                logger.warning(f"Redis trace 不可用, 回退内存存储: {exc}")
        with self._lock:
            rec = self._data.get(request_id)
            return dict(rec) if rec else None

    async def recent(self, limit: int = 50) -> list[dict]:
        """按时间倒序返回最近 limit 条 (供管理面板)。"""
        limit = max(1, min(int(limit), 200))
        if self._backend == "redis" and not self._redis_broken:
            try:
                await self._ensure_redis()
                if self._client is not None:
                    ids = await self._client.zrevrange(f"{self._prefix}index", 0, limit - 1)
                    if not ids:
                        return []
                    raws = await self._client.mget([f"{self._prefix}rec:{rid}" for rid in ids])
                    out: list[dict] = []
                    for raw in raws:
                        if raw:
                            try:
                                out.append(json.loads(raw))
                            except (ValueError, TypeError):
                                continue
                    return out
            except Exception as exc:
                self._redis_broken = True
                if self._client is not None:
                    with contextlib.suppress(Exception):
                        await self._client.aclose()
                    self._client = None
                logger.warning(f"Redis trace 不可用, 回退内存存储: {exc}")
        with self._lock:
            items = list(self._data.values())
            return [dict(x) for x in reversed(items[-limit:])]

    async def size(self) -> int:
        if self._backend == "redis" and not self._redis_broken:
            try:
                await self._ensure_redis()
                if self._client is not None:
                    return int(await self._client.zcard(f"{self._prefix}index"))
            except Exception as exc:
                self._redis_broken = True
                if self._client is not None:
                    with contextlib.suppress(Exception):
                        await self._client.aclose()
                    self._client = None
                logger.warning(f"Redis trace 不可用, 回退内存存储: {exc}")
        with self._lock:
            return len(self._data)

    async def aclose(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
            self._client = None

    def __len__(self) -> int:
        """内存后端长度 (兼容旧测试/调用)。"""
        with self._lock:
            return len(self._data)


def format_trace_summary(trace: dict) -> str:
    """压缩为单行人类可读摘要 (供 X-Trace-Summary 响应头)。"""
    parts = ["cache=hit" if trace.get("cache_hit") else "cache=miss"]
    status = trace.get("upstream_status")
    if status:
        parts.append(f"upstream={status}")
    duration = trace.get("duration_ms")
    if duration is not None:
        parts.append(f"{duration}ms")
    used_key = trace.get("used_key")
    if used_key:
        parts.append(f"key={used_key}")
    retries = trace.get("retries") or 0
    if retries:
        parts.append(f"retries={retries}")
    if trace.get("circuit_open"):
        parts.append("circuit=open")
    return " ".join(parts)
