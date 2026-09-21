"""v2.0.0 管理 API / Key 池运维 / 管理面板测试。"""

import main as main_mod
import pytest
from app.core.key_pool import KeyPool, key_hash
from httpx import ASGITransport, AsyncClient

MASTER = "admin-master-key-1234567890"


def _setup(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", MASTER)
    monkeypatch.setattr(main_mod.provider, "key_pool", KeyPool(["k-aaa"], cooldown_seconds=60))
    monkeypatch.setattr(main_mod.provider, "redis_cache", None)


@pytest.mark.asyncio
async def test_key_pool_add_remove_by_hash():
    pool = KeyPool(["k1"], cooldown_seconds=0)
    assert pool.add_key("k2") is True
    assert pool.add_key(" k2 ") is False  # 已存在
    assert pool.add_key("   ") is False  # 非法
    assert len(pool) == 2
    assert pool.remove_key_by_hash(key_hash("k2")) is True
    assert pool.remove_key_by_hash(key_hash("k2")) is False
    assert len(pool) == 1


@pytest.mark.asyncio
async def test_admin_requires_auth(monkeypatch):
    _setup(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.get("/v1/admin/overview")
        assert r.status_code == 401
        r = await c.get("/v1/admin/keys", headers={"Authorization": f"Bearer {MASTER}"})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_overview_and_usage(monkeypatch):
    _setup(monkeypatch)
    h = {"Authorization": f"Bearer {MASTER}"}
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.get("/v1/admin/overview", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == main_mod.settings.APP_VERSION
        assert body["cache"]["active"] == "memory"
        assert body["key_pool"]["count"] == 1
        assert "traces_size" in body

        r = await c.get("/v1/admin/usage", headers=h)
        assert r.status_code == 200
        assert "per_key" in r.json()


@pytest.mark.asyncio
async def test_admin_keys_crud(monkeypatch):
    _setup(monkeypatch)
    h = {"Authorization": f"Bearer {MASTER}"}
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.post("/v1/admin/keys", headers=h, json={"key": "k-new"})
        assert r.status_code == 200
        added = r.json()
        assert added["key_hash"] == key_hash("k-new")
        assert added["count"] == 2

        r = await c.get("/v1/admin/keys", headers=h)
        hashes = [k["key_hash"] for k in r.json()["keys"]]
        assert key_hash("k-new") in hashes

        r = await c.delete(f"/v1/admin/keys/{key_hash('k-new')}", headers=h)
        assert r.status_code == 200

        r = await c.delete("/v1/admin/keys/00000000", headers=h)
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_traces_and_ui(monkeypatch):
    _setup(monkeypatch)
    h = {"Authorization": f"Bearer {MASTER}"}
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        await main_mod.provider.trace_store.put("t1", {"request_id": "t1", "result": "success"})
        r = await c.get("/v1/admin/traces?limit=10", headers=h)
        assert r.status_code == 200
        ids = [t["request_id"] for t in r.json()["traces"]]
        assert "t1" in ids

        r = await c.get("/admin")
        assert r.status_code == 200
        assert "管理面板" in r.text
