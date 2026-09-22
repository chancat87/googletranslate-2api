"""缓存 stampede 防护 (v2.2.0): 并发同文只打一次上游, Redis 后端跨进程门闩。"""

import asyncio

import pytest
from app.core import cache as cache_mod
from app.core.cache import RedisCacheBackend
from app.core.key_pool import KeyPool
from app.providers import googletranslate_provider as provider_mod
from app.providers.googletranslate_provider import GoogleTranslateProvider
from fakeredis import aioredis as fakeredis_aioredis


class _FakeResponse:
    status_code = 200

    def json(self):
        return None


def _make_provider(monkeypatch):
    provider = GoogleTranslateProvider()
    provider.redis_cache = None
    provider.cache = cache_mod.make_cache()
    provider.key_pool = KeyPool(["dummy-key"])
    provider.circuit_breaker = None
    provider.usage_store = None
    if monkeypatch is None:
        provider._clean_response = lambda _data: "bonjour"  # type: ignore[method-assign]
    else:
        monkeypatch.setattr(provider, "_clean_response", lambda _data: "bonjour")
    return provider


@pytest.mark.asyncio
async def test_singleflight_same_key_calls_upstream_once(monkeypatch):
    provider = _make_provider(monkeypatch)
    calls = 0

    async def fake_post(headers, payload, trace=None, proxy=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return _FakeResponse()

    monkeypatch.setattr(provider, "_post_with_retry", fake_post)

    traces = [{"cache_hit": None} for _ in range(20)]
    results = await asyncio.gather(
        *(provider._translate("Hello", "en", "zh-CN", trace=traces[i]) for i in range(20))
    )
    assert calls == 1
    assert set(results) == {"bonjour"}
    assert sum(t["cache_hit"] is True for t in traces) == 19
    assert await provider._cache_get(cache_mod.cache_key("Hello", "en", "zh-CN")) == "bonjour"


@pytest.mark.asyncio
async def test_singleflight_different_keys_are_isolated(monkeypatch):
    provider = _make_provider(monkeypatch)
    calls = 0

    async def fake_post(headers, payload, trace=None, proxy=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return _FakeResponse()

    monkeypatch.setattr(provider, "_post_with_retry", fake_post)

    await asyncio.gather(
        provider._translate("Hello", "en", "zh-CN"),
        provider._translate("World", "en", "zh-CN"),
    )
    assert calls == 2


@pytest.mark.asyncio
async def test_singleflight_redis_backend_cross_process_gate(monkeypatch):
    client = fakeredis_aioredis.FakeRedis(decode_responses=True)
    backend1 = RedisCacheBackend(client, "g2api:", 60)
    backend2 = RedisCacheBackend(client, "g2api:", 60)
    provider1 = _make_provider(monkeypatch)
    provider2 = _make_provider(monkeypatch)
    provider1.redis_cache = backend1
    provider1.cache = None
    provider2.redis_cache = backend2
    provider2.cache = None
    calls = 0

    async def fake_post(headers, payload, trace=None, proxy=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.03)
        return _FakeResponse()

    monkeypatch.setattr(provider1, "_post_with_retry", fake_post)
    monkeypatch.setattr(provider2, "_post_with_retry", fake_post)

    trace1 = {"cache_hit": None}
    trace2 = {"cache_hit": None}
    await asyncio.gather(
        provider1._translate("Hello", "en", "zh-CN", trace=trace1),
        provider2._translate("Hello", "en", "zh-CN", trace=trace2),
    )
    assert calls == 1
    assert sorted([trace1["cache_hit"], trace2["cache_hit"]]) == [False, True]
    assert await backend1.get(cache_mod.cache_key("Hello", "en", "zh-CN")) == "bonjour"
    await backend1.aclose()
    await backend2.aclose()


@pytest.mark.asyncio
async def test_singleflight_lock_reuses_existing_lock():
    provider = _make_provider(None)
    lock1 = provider._singleflight_lock("k")
    lock2 = provider._singleflight_lock("k")
    assert lock1 is lock2


def test_singleflight_lock_evicts_oldest_when_bounded():
    provider = _make_provider(None)
    for i in range(provider_mod._SINGLEFLIGHT_MAX_KEYS + 1):
        provider._singleflight_lock(f"k{i}")
    assert len(provider._inflight_locks) == provider_mod._SINGLEFLIGHT_MAX_KEYS


@pytest.mark.asyncio
async def test_wait_for_redis_lock_returns_false_on_error(monkeypatch):
    provider = _make_provider(None)
    backend = RedisCacheBackend(fakeredis_aioredis.FakeRedis(decode_responses=True), "g2api:", 60)
    provider.redis_cache = backend

    async def boom(key, ttl=30):
        raise RuntimeError("boom")

    monkeypatch.setattr(backend, "acquire_lock", boom)
    assert await provider._wait_for_redis_lock("k") is False
    await backend.aclose()


@pytest.mark.asyncio
async def test_wait_for_redis_lock_times_out(monkeypatch):
    provider = _make_provider(None)
    backend = RedisCacheBackend(fakeredis_aioredis.FakeRedis(decode_responses=True), "g2api:", 60)
    provider.redis_cache = backend

    async def never(key, ttl=30):
        return False

    monkeypatch.setattr(backend, "acquire_lock", never)
    calls = {"n": 0}

    def fake_monotonic():
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else 100.0

    monkeypatch.setattr(provider_mod.time, "monotonic", fake_monotonic)
    assert await provider._wait_for_redis_lock("k") is False
    await backend.aclose()


@pytest.mark.asyncio
async def test_singleflight_release_lock_failure_is_suppressed(monkeypatch):
    provider = _make_provider(monkeypatch)
    backend = RedisCacheBackend(fakeredis_aioredis.FakeRedis(decode_responses=True), "g2api:", 60)
    provider.redis_cache = backend
    provider.cache = None

    async def boom(key):
        raise RuntimeError("release boom")

    monkeypatch.setattr(backend, "release_lock", boom)

    async def fake_post(headers, payload, trace=None, proxy=None):
        return _FakeResponse()

    monkeypatch.setattr(provider, "_post_with_retry", fake_post)
    result = await provider._translate("Hello", "en", "zh-CN")
    assert result == "bonjour"
    await backend.aclose()
