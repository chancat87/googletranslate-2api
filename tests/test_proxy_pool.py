"""代理池测试 (v2.13.0): 轮换/冷却/健康分/脱敏 + provider 接线, 不发真实网络。"""

import asyncio
import time

import httpx
import pytest
from app.core import config as cfg
from app.core.key_pool import KeyPool
from app.core.proxy_pool import ProxyPool, normalize_proxy_url, parse_free_lines
from app.providers import googletranslate_provider as provider_mod
from app.providers.googletranslate_provider import GoogleTranslateProvider


def test_normalize_and_parse():
    assert normalize_proxy_url(" 1.2.3.4:8080 ").startswith("http://")
    assert normalize_proxy_url("http://user:pass@1.2.3.4:8080") is not None
    assert normalize_proxy_url("# comment") is None
    assert normalize_proxy_url("") is None
    lines = parse_free_lines("1.2.3.4:8080\nbad\nhttp://5.6.7.8:80\n")
    assert len(lines) == 2


def test_normalize_no_port_returns_none():
    assert normalize_proxy_url("http://onlyhost") is None


@pytest.mark.asyncio
async def test_entry_day_reset():
    pool = ProxyPool()
    pool.add_many(["http://a:80"], source="free")
    e = pool.entries[0]
    e.day_key = 0
    e.use_count = 5
    assert e.available(time.time()) is True
    assert e.use_count == 0


@pytest.mark.asyncio
async def test_pool_edge_noop_and_duplicate():
    pool = ProxyPool()
    assert await pool.acquire() is None
    await pool.mark_failure("http://x:1")
    await pool.mark_success("http://x:1")
    assert pool.add_many(["http://a:80"], source="free") == 1
    assert pool.add_many(["http://a:80"], source="free") == 0


@pytest.mark.asyncio
async def test_pool_rotation_cooldown_and_health():
    pool = ProxyPool()
    assert pool.add_many(["http://a:80", "http://b:80"], source="free") == 2
    first = await pool.acquire()
    second = await pool.acquire()
    assert {first, second} == {"http://a:80", "http://b:80"}
    # 全部用过一轮后进入冷却, acquire 仍返回最早结束冷却的
    await pool.mark_failure(first, rate_limited=True)
    pick = await pool.acquire()
    assert pick in ("http://a:80", "http://b:80")
    snap = pool.snapshot()
    assert snap["total"] == 2
    assert snap["free"] == 2


@pytest.mark.asyncio
async def test_pool_prefers_validated_free_proxy():
    pool = ProxyPool()
    pool.add_many(["http://a:80", "http://b:80"], source="free")
    await pool.mark_validated("http://b:80", True)
    assert await pool.acquire() == "http://b:80"
    by_url = {i["url"]: i for i in pool.snapshot()["items"]}
    assert by_url["b:80"]["validated"] is True

    pool2 = ProxyPool()
    pool2.add_many(["http://c:80"], source="free")
    await pool2.mark_validated("http://c:80", False)
    item = pool2.snapshot()["items"][0]
    assert item["validated"] is True
    assert item["health_score"] < 1.0


@pytest.mark.asyncio
async def test_pool_snapshot_redacts_credentials():
    pool = ProxyPool()
    pool.add_many(["http://user:secret@10.0.0.1:3128"], source="residential")
    item = pool.snapshot()["items"][0]
    assert "secret" not in item["url"]
    assert "10.0.0.1:3128" in item["url"]


@pytest.mark.asyncio
async def test_pool_reap_free():
    pool = ProxyPool()
    pool.add_many(["http://1.1.1.1:80"], source="free")
    e = pool.entries[0]
    e.added_at = time.time() - 20000
    e.last_used_at = 0
    assert pool.reap_free() == 1
    assert pool.enabled is False


class _FakePool:
    def __init__(self):
        self.calls = []

    @property
    def enabled(self):
        return True

    async def acquire(self):
        self.calls.append("acquire")
        return "http://p:8080"

    async def mark_failure(self, url, rate_limited=True):
        self.calls.append(("fail", url, rate_limited))

    async def mark_success(self, url):
        self.calls.append(("ok", url))


def _fake_resp(status: int, translated="bonjour"):
    class R:
        status_code = status
        request = None

        def json(self):
            return [[translated]]

    return R()


@pytest.mark.asyncio
async def test_provider_uses_and_marks_proxy():
    provider = GoogleTranslateProvider()
    fake = _FakePool()
    provider.proxy_pool = fake
    provider.key_pool = KeyPool(["k1"], cooldown_seconds=0)
    provider.circuit_breaker = None
    seen = {}

    async def _post(headers, payload, trace=None, proxy=None):
        seen["proxy"] = proxy
        return _fake_resp(200)

    provider._post_with_retry = _post  # type: ignore[method-assign]
    out = await provider._translate_uncached("hi", "auto", "zh-CN", True, None, "k")
    assert out == "bonjour"
    assert seen.get("proxy") == "http://p:8080"
    assert ("ok", "http://p:8080") in fake.calls


@pytest.mark.asyncio
async def test_provider_marks_proxy_failure_on_429():
    provider = GoogleTranslateProvider()
    fake = _FakePool()
    provider.proxy_pool = fake
    provider.key_pool = KeyPool(["k1"], cooldown_seconds=0)
    provider.circuit_breaker = None

    async def _post(headers, payload, trace=None, proxy=None):
        return _fake_resp(429)

    provider._post_with_retry = _post  # type: ignore[method-assign]
    with pytest.raises(httpx.HTTPStatusError):
        await provider._translate_uncached("hi", "auto", "zh-CN", True, None, "k")
    assert ("fail", "http://p:8080", True) in fake.calls


@pytest.mark.asyncio
async def test_provider_marks_proxy_failure_on_500():
    provider = GoogleTranslateProvider()
    fake = _FakePool()
    provider.proxy_pool = fake
    provider.key_pool = KeyPool(["k1"], cooldown_seconds=0)
    provider.circuit_breaker = None

    async def _post(headers, payload, trace=None, proxy=None):
        return _fake_resp(500)

    provider._post_with_retry = _post  # type: ignore[method-assign]
    with pytest.raises(httpx.HTTPStatusError):
        await provider._translate_uncached("hi", "auto", "zh-CN", True, None, "k")
    assert ("fail", "http://p:8080", False) in fake.calls


@pytest.mark.asyncio
async def test_provider_rotates_proxy_on_transport_error():
    provider = GoogleTranslateProvider()
    fake = _FakePool()
    provider.proxy_pool = fake
    provider.key_pool = KeyPool(["k1"], cooldown_seconds=0)
    provider.circuit_breaker = None
    calls = {"post": 0}

    async def _post(headers, payload, trace=None, proxy=None):
        calls["post"] += 1
        if calls["post"] == 1:
            raise httpx.TransportError("boom")
        return _fake_resp(200)

    provider._post_with_retry = _post  # type: ignore[method-assign]
    out = await provider._translate_uncached("hi", "auto", "zh-CN", True, None, "k")
    assert out == "bonjour"
    assert fake.calls.count("acquire") == 2
    assert ("fail", "http://p:8080", False) in fake.calls


def test_pool_load_file_and_invalid_file(tmp_path):
    path = tmp_path / "p.txt"
    path.write_text("1.2.3.4:8080\n# comment\nhttp://user:pass@5.6.7.8:80\n", encoding="utf-8")
    pool = ProxyPool()
    assert pool.load_file(str(path)) == 2
    assert pool.load_file(str(tmp_path / "missing.txt")) == 0


@pytest.mark.asyncio
async def test_pool_prefer_source_and_page():
    pool = ProxyPool()
    pool.add_many(["http://a:80", "http://b:80"], source="free")
    pool.add_many(["http://c:8080"], source="residential")
    got = await pool.acquire(prefer_source="residential")
    assert got == "http://c:8080"
    snap = pool.snapshot(page=1, page_size=2)
    assert snap["total"] == 3
    assert len(snap["items"]) == 2
    assert snap["residential"] == 1


@pytest.mark.asyncio
async def test_pool_failure_cooldown_non_rate_limited():
    pool = ProxyPool()
    pool.add_many(["http://a:80"], source="free")
    url = await pool.acquire()
    await pool.mark_failure(url, rate_limited=False)
    e = pool.entries[0]
    assert e.cooldown_until > time.time()
    assert e.health_score < 1.0


@pytest.mark.asyncio
async def test_provider_initialize_proxy_pool(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg.settings, "PROXY_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "PROXY_FILE", str(tmp_path / "p.txt"))
    monkeypatch.setattr(cfg.settings, "PROXY_FREE_FETCH", False)
    provider = GoogleTranslateProvider()
    await provider.initialize()
    assert provider.proxy_pool is not None
    assert provider._proxy_sem is not None
    await provider.close()
    assert provider.proxy_pool is None
    assert provider._proxy_sem is None


@pytest.mark.asyncio
async def test_provider_proxy_fetch_task_cancelled(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg.settings, "PROXY_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "PROXY_FILE", str(tmp_path / "p.txt"))
    monkeypatch.setattr(cfg.settings, "PROXY_FREE_FETCH", True)

    async def _noop(pool):
        await asyncio.sleep(0.01)

    monkeypatch.setattr(provider_mod, "free_proxy_fetcher_loop", _noop)
    provider = GoogleTranslateProvider()
    await provider.initialize()
    assert provider._proxy_fetch_task is not None
    await asyncio.sleep(0.05)
    await provider.close()
    assert provider._proxy_fetch_task is None


class _FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.proxy = kwargs.get("proxy")
        self.closed = False

    async def post(self, url, headers=None, json=None):
        return _fake_resp(200)

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_post_with_retry_proxy_branch(monkeypatch):
    provider = GoogleTranslateProvider()
    provider.client = _FakeClient()
    clients = []
    monkeypatch.setattr(
        provider_mod.httpx,
        "AsyncClient",
        lambda **kw: clients.append(_FakeClient(**kw)) or clients[-1],
    )
    resp = await provider._post_with_retry({}, [["hi"]], proxy="http://p:1")
    assert resp.status_code == 200
    timeout = clients[0].kwargs["timeout"]
    assert timeout.read == cfg.settings.PROXY_REQUEST_TIMEOUT
    assert timeout.connect == cfg.settings.PROXY_CONNECT_TIMEOUT


@pytest.mark.asyncio
async def test_admin_proxy_endpoint():
    import main as main_mod
    from httpx import ASGITransport, AsyncClient

    pool = ProxyPool()
    pool.add_many(["http://u:p@10.0.0.2:80"], source="residential")
    main_mod.provider.proxy_pool = pool
    try:
        async with AsyncClient(
            transport=ASGITransport(app=main_mod.app), base_url="http://test"
        ) as c:
            r = await c.get("/v1/admin/proxy", headers={"Authorization": "Bearer 1"})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert "10.0.0.2:80" in data["items"][0]["url"]
    finally:
        main_mod.provider.proxy_pool = None
