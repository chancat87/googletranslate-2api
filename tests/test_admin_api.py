"""v2.0.0 管理 API / Key 池运维 / 管理面板测试。"""

import main as main_mod
import pytest
from app.core.key_pool import KeyPool, key_hash
from app.core.metrics import metrics
from app.core.usage_store import UsageStore
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


@pytest.mark.asyncio
async def test_admin_usage_metrics_and_store(monkeypatch, tmp_path):
    _setup(monkeypatch)
    metrics.translate_requests.labels(stream="false", result="started").inc()
    metrics.requests_by_key.labels(key="abc12345", result="ok").inc()
    monkeypatch.setattr(main_mod.provider, "usage_store", UsageStore(str(tmp_path / "u.db")))
    await main_mod.provider.usage_store.record("abc12345", requests=7, chars_in=10, chars_out=8)
    h = {"Authorization": f"Bearer {MASTER}"}
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.get("/v1/admin/usage", headers=h)
        body = r.json()
        assert any(k["key_hash"] == "abc12345" for k in body["per_key"])
        assert any(s["key_hash"] == "abc12345" and s["requests"] == 7 for s in body["store"])


@pytest.mark.asyncio
async def test_admin_keys_guards(monkeypatch):
    _setup(monkeypatch)
    h = {"Authorization": f"Bearer {MASTER}"}
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        monkeypatch.setattr(main_mod.provider, "key_pool", None)
        r = await c.post("/v1/admin/keys", headers=h, json={"key": "k"})
        assert r.status_code == 400  # key_pool 未初始化
        r = await c.delete("/v1/admin/keys/00000000", headers=h)
        assert r.status_code == 400

        monkeypatch.setattr(main_mod.provider, "key_pool", KeyPool(["k1"], cooldown_seconds=0))
        r = await c.post("/v1/admin/keys", headers=h, json={"key": "k1"})
        assert r.status_code == 400  # 已存在


@pytest.mark.asyncio
async def test_admin_keys_bulk_import(monkeypatch):
    _setup(monkeypatch)
    h = {"Authorization": f"Bearer {MASTER}"}
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.post(
            "/v1/admin/keys/bulk",
            headers=h,
            json={"keys": ["k-b", "k-c", "k-b", ""]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["added"] == [key_hash("k-b"), key_hash("k-c")]
        assert body["skipped"] == [key_hash("k-b")]
        assert body["count"] == 3


@pytest.mark.asyncio
async def test_admin_keys_bulk_requires_pool(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(main_mod.provider, "key_pool", None)
    h = {"Authorization": f"Bearer {MASTER}"}
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.post(
            "/v1/admin/keys/bulk",
            headers=h,
            json={"keys": ["k-x"]},
        )
        assert r.status_code == 400


def test_metric_samples_parse_and_disabled(monkeypatch):
    class _R:
        enabled = True

        def render(self):
            return b'x{"a"="1"} 1\ny{"b"="2"} 2\ny{"c"="bad"} nope\n'

    monkeypatch.setattr(main_mod.metrics, "render", _R().render)
    monkeypatch.setattr(main_mod.metrics, "enabled", True)
    samples = main_mod._metric_samples("y")
    assert [v for _, v in samples] == [2.0]  # 只保留可解析数值
    monkeypatch.setattr(main_mod.metrics, "enabled", False)
    assert main_mod._metric_samples("y") == []
