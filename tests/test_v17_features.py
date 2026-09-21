"""v1.7.0 特性测试: Redis 分布式限流 / Redis trace / SSE 心跳 / 告警规则。"""

import asyncio
import contextlib
from pathlib import Path

import pytest
import redis.asyncio as real_aioredis
import yaml
from app.core.rate_limit import RateLimiter
from app.core.trace import TraceStore
from app.providers.googletranslate_provider import GoogleTranslateProvider
from fakeredis import aioredis as fakeredis_aioredis


def _fake_redis():
    return fakeredis_aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_redis_rate_limiter_allow_and_retry():
    rl = RateLimiter(
        capacity=2,
        per_second=10.0,
        backend="redis",
        redis_url="redis://unused",
        prefix="t:",
        ttl=60,
    )
    rl._client = _fake_redis()
    assert await rl.allow("ip:1") is True
    assert await rl.allow("ip:1") is True
    assert await rl.allow("ip:1") is False
    wait = await rl.retry_after("ip:1")
    assert wait > 0
    await rl.aclose()


@pytest.mark.asyncio
async def test_redis_rate_limiter_isolation_between_keys():
    rl = RateLimiter(capacity=1, per_second=0.0, backend="redis", redis_url="redis://unused")
    rl._client = _fake_redis()
    assert await rl.allow("ip:a") is True
    assert await rl.allow("ip:a") is False
    assert await rl.allow("ip:b") is True
    await rl.aclose()


@pytest.mark.asyncio
async def test_rate_limiter_fallback_memory_when_redis_broken():
    rl = RateLimiter(capacity=1, per_second=0.0, backend="redis", redis_url="redis://unused")
    rl._redis_broken = True  # 模拟 Redis 故障
    assert await rl.allow("ip:x") is True
    assert await rl.allow("ip:x") is False
    assert await rl.retry_after("nope") == 0.0
    await rl.aclose()


@pytest.mark.asyncio
async def test_redis_trace_roundtrip_recent_size():
    ts = TraceStore(maxlen=5, backend="redis", redis_url="redis://unused", prefix="g:", ttl=60)
    ts._client = _fake_redis()
    await ts.put("r1", {"request_id": "r1", "created_at": 1.0})
    await ts.put("r2", {"request_id": "r2", "created_at": 2.0})
    assert (await ts.get("r1"))["request_id"] == "r1"
    assert await ts.get("missing") is None
    recents = await ts.recent(10)
    assert [r["request_id"] for r in recents] == ["r2", "r1"]
    assert await ts.size() == 2
    await ts.aclose()


@pytest.mark.asyncio
async def test_redis_trace_evicts_oldest():
    ts = TraceStore(maxlen=2, backend="redis", redis_url="redis://unused", prefix="g:", ttl=60)
    ts._client = _fake_redis()
    await ts.put("r1", {"request_id": "r1", "created_at": 1.0})
    await ts.put("r2", {"request_id": "r2", "created_at": 2.0})
    await ts.put("r3", {"request_id": "r3", "created_at": 3.0})
    assert await ts.get("r1") is None
    assert await ts.get("r2") is not None
    assert await ts.get("r3") is not None
    await ts.aclose()


@pytest.mark.asyncio
async def test_trace_store_fallback_memory_when_redis_broken():
    ts = TraceStore(maxlen=3, backend="redis", redis_url="redis://unused")
    ts._redis_broken = True
    await ts.put("r1", {"request_id": "r1"})
    assert (await ts.get("r1"))["request_id"] == "r1"
    assert (await ts.recent(5))[0]["request_id"] == "r1"
    assert await ts.size() == 1
    await ts.aclose()


@pytest.mark.asyncio
async def test_heartbeat_injects_ping_and_keeps_content():
    async def inner():
        yield b"a"
        await asyncio.sleep(0.08)
        yield b"b"

    chunks = [c async for c in GoogleTranslateProvider._with_heartbeat(inner(), 0.02)]
    body = b"".join(chunks)
    assert b'{"type":"ping"}' in body
    assert chunks[0] == b"a"
    assert chunks[-1] == b"b"


@pytest.mark.asyncio
async def test_heartbeat_passthrough_when_disabled():
    async def inner():
        yield b"a"
        yield b"b"

    chunks = [c async for c in GoogleTranslateProvider._with_heartbeat(inner(), 0.0)]
    assert chunks == [b"a", b"b"]


def test_alerts_rules_valid_and_named():
    path = Path(__file__).resolve().parent.parent / "prometheus" / "alerts.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = data["groups"][0]["rules"]
    names = [r["alert"] for r in rules]
    assert len(rules) == 5
    assert len(set(names)) == len(names)
    assert "UpstreamAuthError" in names
    assert all("expr" in r and "annotations" in r for r in rules)


@pytest.mark.asyncio
async def test_rate_limiter_ensure_redis_success(monkeypatch):
    monkeypatch.setattr(real_aioredis, "from_url", lambda url, **kwargs: _fake_redis())
    rl = RateLimiter(capacity=2, per_second=10.0, backend="redis", redis_url="redis://x")
    assert await rl.allow("ip:new") is True
    assert rl._client is not None
    await rl.aclose()
    assert rl._client is None


@pytest.mark.asyncio
async def test_rate_limiter_redis_fallback_on_connect_error(monkeypatch):
    def _boom(url, **kwargs):
        raise ConnectionError("no redis")

    monkeypatch.setattr(real_aioredis, "from_url", _boom)
    rl = RateLimiter(capacity=1, per_second=0.0, backend="redis", redis_url="redis://x")
    assert await rl.allow("ip:a") is True
    assert await rl.allow("ip:a") is False
    assert await rl.retry_after("nope") == 0.0
    await rl.aclose()


@pytest.mark.asyncio
async def test_rate_limiter_redis_method_failure_fallback():
    class Boom:
        async def aclose(self):
            return None

        def pipeline(self, transaction=True):
            raise ConnectionError("boom")

    rl = RateLimiter(capacity=1, per_second=1.0, backend="redis", redis_url="redis://x")
    rl._client = Boom()
    assert await rl.allow("ip:b") is True
    assert await rl.retry_after("nope") == 0.0
    assert rl._client is None  # 故障后清空连接
    await rl.aclose()


@pytest.mark.asyncio
async def test_rate_limiter_redis_retry_after_failure_except():
    class Boom:
        async def aclose(self):
            return None

        def pipeline(self, transaction=True):
            raise ConnectionError("boom")

    rl = RateLimiter(capacity=2, per_second=10.0, backend="redis", redis_url="redis://x")
    rl._client = Boom()
    assert await rl.retry_after("ip:c") == 0.0  # 命中 retry_after 故障分支后回退内存
    assert rl._client is None
    await rl.aclose()


@pytest.mark.asyncio
async def test_redis_rate_limiter_concurrent_allow_no_error():
    rl = RateLimiter(capacity=4, per_second=10.0, backend="redis", redis_url="redis://x")
    rl._client = _fake_redis()
    results = await asyncio.gather(*(rl.allow("ip:race") for _ in range(4)))
    assert results.count(True) == 4
    await rl.aclose()


@pytest.mark.asyncio
async def test_trace_ensure_redis_success(monkeypatch):
    monkeypatch.setattr(real_aioredis, "from_url", lambda url, **kwargs: _fake_redis())
    ts = TraceStore(maxlen=3, backend="redis", redis_url="redis://x")
    await ts.put("r1", {"request_id": "r1", "created_at": 1.0})
    assert (await ts.get("r1"))["request_id"] == "r1"
    assert ts._client is not None
    await ts.aclose()


@pytest.mark.asyncio
async def test_trace_redis_fallback_on_connect_error(monkeypatch):
    def _boom(url, **kwargs):
        raise ConnectionError("no redis")

    monkeypatch.setattr(real_aioredis, "from_url", _boom)
    ts = TraceStore(maxlen=3, backend="redis", redis_url="redis://x")
    await ts.put("r1", {"request_id": "r1"})
    assert (await ts.get("r1"))["request_id"] == "r1"
    assert (await ts.recent(5))[0]["request_id"] == "r1"
    assert await ts.size() == 1
    await ts.aclose()


@pytest.mark.asyncio
async def test_trace_redis_method_failure_fallback():
    def boom_client(method: str):
        inner = _fake_redis()

        class Boom:
            async def aclose(self):
                return await inner.aclose()

            def __getattr__(self, name):
                return getattr(inner, name)

        async def _raise(*a, **k):
            raise ConnectionError("boom")

        setattr(Boom, method, _raise)
        return Boom()

    put_store = TraceStore(maxlen=3, backend="redis", redis_url="redis://x")
    put_store._client = boom_client("zadd")
    await put_store.put("r1", {"request_id": "r1"})
    assert (await put_store.get("r1"))["request_id"] == "r1"
    await put_store.aclose()

    get_store = TraceStore(maxlen=3, backend="redis", redis_url="redis://x")
    get_store._client = boom_client("get")
    await get_store.put("r1", {"request_id": "r1"})
    assert await get_store.get("r1") is None  # Redis 记录存在但读取抛错 -> 回退内存(空)
    await get_store.aclose()

    recent_store = TraceStore(maxlen=3, backend="redis", redis_url="redis://x")
    recent_store._client = boom_client("zrevrange")
    await recent_store.put("r1", {"request_id": "r1"})
    assert await recent_store.recent(5) == []
    await recent_store.aclose()

    size_store = TraceStore(maxlen=3, backend="redis", redis_url="redis://x")
    size_store._client = boom_client("zcard")
    await size_store.put("r1", {"request_id": "r1"})
    assert await size_store.size() == 0
    await size_store.aclose()


@pytest.mark.asyncio
async def test_rate_limiter_watch_conflict_retries():
    """并发写同一 bucket 会触发 WATCH 冲突, 验证重试分支可用 (fakeredis 乐观锁)。"""
    rl = RateLimiter(capacity=20, per_second=100.0, backend="redis", redis_url="redis://x")
    rl._client = _fake_redis()
    results = await asyncio.gather(*(rl.allow("ip:watch") for _ in range(20)))
    assert results.count(True) == 20
    await rl.aclose()


@pytest.mark.asyncio
async def test_heartbeat_survives_inner_exception():
    async def inner():
        raise RuntimeError("inner boom")

    chunks = [c async for c in GoogleTranslateProvider._with_heartbeat(inner(), 0.05)]
    assert chunks == []


@pytest.mark.asyncio
async def test_heartbeat_inner_cancelled_error_propagates_to_suppress():
    async def inner():
        raise asyncio.CancelledError()

    chunks = [c async for c in GoogleTranslateProvider._with_heartbeat(inner(), 0.05)]
    assert chunks == []


@pytest.mark.asyncio
async def test_heartbeat_cancel_consumer_cleans_pump():
    async def inner():
        await asyncio.sleep(1.0)
        yield b"late"

    async def consume():
        return [c async for c in GoogleTranslateProvider._with_heartbeat(inner(), 0.05)]

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.12)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
