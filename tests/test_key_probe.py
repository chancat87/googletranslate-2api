"""v2.9.0: Key 可用性自检 (provider 探测 + 管理 API)。"""

import httpx
import main as main_mod
import pytest
from app.core.key_pool import KeyPool, key_hash
from app.providers.googletranslate_provider import GoogleTranslateProvider
from httpx import ASGITransport, AsyncClient


class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeClient:
    def __init__(self, status_code=200, exc=None):
        self.status = status_code
        self.exc = exc

    async def post(self, *args, **kwargs):
        if self.exc:
            raise self.exc
        return _FakeResp(self.status)


@pytest.mark.asyncio
async def test_provider_probe_key_ok():
    provider = GoogleTranslateProvider()
    provider.client = _FakeClient(status_code=200)
    result = await provider.probe_key("k-ok")
    assert result == {"http_status": 200, "ok": True}


@pytest.mark.asyncio
async def test_provider_probe_key_transport_error():
    provider = GoogleTranslateProvider()
    provider.client = _FakeClient(exc=httpx.ConnectError("boom"))
    result = await provider.probe_key("k-net")
    assert result["ok"] is False
    assert result["error"] == "transport"


@pytest.mark.asyncio
async def test_provider_probe_key_uninitialized():
    provider = GoogleTranslateProvider()
    provider.client = None
    result = await provider.probe_key("k")
    assert result == {"ok": False, "error": "uninitialized"}


@pytest.mark.asyncio
async def test_admin_keys_probe(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "admin-master-key-1234567890")
    monkeypatch.setattr(main_mod.provider, "key_pool", KeyPool(["k-1", "k-2"], cooldown_seconds=0))

    async def fake_probe(key):
        return {"ok": key == "k-1", "http_status": 200 if key == "k-1" else 400}

    monkeypatch.setattr(main_mod.provider, "probe_key", fake_probe)
    h = {"Authorization": "Bearer admin-master-key-1234567890"}
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.post("/v1/admin/keys/probe", headers=h)
        assert r.status_code == 200
        body = r.json()
        by_hash = {item["key_hash"]: item for item in body["results"]}
        assert body["count"] == 2
        assert by_hash[key_hash("k-1")]["ok"] is True
        assert by_hash[key_hash("k-2")]["ok"] is False


@pytest.mark.asyncio
async def test_admin_keys_probe_requires_pool(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "admin-master-key-1234567890")
    monkeypatch.setattr(main_mod.provider, "key_pool", None)
    h = {"Authorization": "Bearer admin-master-key-1234567890"}
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.post("/v1/admin/keys/probe", headers=h)
        assert r.status_code == 400
