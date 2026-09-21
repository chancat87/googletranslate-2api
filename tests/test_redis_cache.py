"""Redis 共享缓存后端测试 (v1.6.0): fakeredis 模拟, 无需真实 Redis 服务。"""

import pytest
from app.core import cache as cache_mod
from app.core.cache import RedisCacheBackend, make_redis_cache
from app.providers import googletranslate_provider as provider_mod
from app.providers.googletranslate_provider import GoogleTranslateProvider
from fakeredis import aioredis as fakeredis_aioredis


def _fake_redis():
    return fakeredis_aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_redis_backend_roundtrip_prefix_ttl():
    client = _fake_redis()
    backend = RedisCacheBackend(client, "g2api:", 3600)
    await backend.set("en:zh-CN:abc", "hello")
    assert await backend.get("en:zh-CN:abc") == "hello"
    # 前缀隔离: 原始 key 带 g2api: 前缀
    assert await client.get("g2api:en:zh-CN:abc") == "hello"
    ttl = await client.ttl("g2api:en:zh-CN:abc")
    assert 0 < ttl <= 3600
    await backend.aclose()


@pytest.mark.asyncio
async def test_redis_backend_missing_key_returns_none():
    backend = RedisCacheBackend(_fake_redis(), "g2api:", 60)
    assert await backend.get("missing") is None
    await backend.aclose()


@pytest.mark.asyncio
async def test_redis_backend_lock_acquire_release():
    backend = RedisCacheBackend(_fake_redis(), "g2api:", 60)
    assert await backend.acquire_lock("k") is True
    assert await backend.acquire_lock("k") is False
    await backend.release_lock("k")
    assert await backend.acquire_lock("k") is True
    await backend.release_lock("k")
    await backend.release_lock("k")  # 无 token 时幂等
    await backend.aclose()


@pytest.mark.asyncio
async def test_provider_cache_methods_redis_backend():
    provider = GoogleTranslateProvider()
    provider.redis_cache = RedisCacheBackend(_fake_redis(), "g2api:", 60)
    assert await provider._cache_get("k") is None
    await provider._cache_put("k", "v")
    assert await provider._cache_get("k") == "v"
    await provider._cache_put("k", "")
    assert await provider._cache_get("k") == "v"  # 空值不覆盖缓存
    await provider.redis_cache.aclose()


@pytest.mark.asyncio
async def test_provider_cache_methods_memory_fallback():
    provider = GoogleTranslateProvider()
    provider.redis_cache = None
    provider.cache = cache_mod.make_cache()
    assert await provider._cache_get("k") is None
    await provider._cache_put("k", "v")
    assert await provider._cache_get("k") == "v"


@pytest.mark.asyncio
async def test_provider_close_with_redis():
    provider = GoogleTranslateProvider()
    provider.redis_cache = RedisCacheBackend(_fake_redis(), "g2api:", 60)
    await provider.close()
    assert provider.redis_cache is None


@pytest.mark.asyncio
async def test_provider_initialize_redis_fallback(monkeypatch):
    monkeypatch.setattr(cache_mod.settings, "CACHE_BACKEND", "redis")

    async def _no_redis():
        return None

    monkeypatch.setattr(provider_mod, "make_redis_cache", _no_redis)
    provider = GoogleTranslateProvider()
    await provider.initialize()
    assert provider.redis_cache is None  # Redis 不可用 -> 回退内存
    await provider.close()


@pytest.mark.asyncio
async def test_make_redis_cache_success_with_client_factory():
    backend = await make_redis_cache(client_factory=_fake_redis)
    assert backend is not None
    await backend.aclose()


@pytest.mark.asyncio
async def test_make_redis_cache_fallback_when_unreachable(monkeypatch):
    monkeypatch.setattr(cache_mod.settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    backend = await make_redis_cache()
    assert backend is None  # 连接失败 -> 优雅降级, 不抛异常


@pytest.mark.asyncio
async def test_make_redis_cache_disabled(monkeypatch):
    monkeypatch.setattr(cache_mod.settings, "CACHE_ENABLED", False)
    assert await make_redis_cache() is None
