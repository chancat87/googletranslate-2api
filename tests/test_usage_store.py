"""v2.1.0 用量存储 / 配额联动测试。"""

import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core import config as cfg
from app.core.key_pool import KeyPool, key_hash
from app.core.usage_store import UsageStore
from app.providers.googletranslate_provider import GoogleTranslateProvider


def _mk_provider():
    p = GoogleTranslateProvider()
    p.client = MagicMock()
    p.client.post = AsyncMock()
    return p


def _resp(status: int, translated: str = "ok"):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = [[translated]]
    r.text = translated
    r.request = MagicMock()
    return r


def test_usage_store_sqlite_optimizations(tmp_path):
    """v2.12.4: PRAGMA(WAL/busy_timeout/temp_store) 与 day 索引生效。"""
    db = str(tmp_path / "opt.db")
    store = UsageStore(db)
    conn = store._connect()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
        assert conn.execute("PRAGMA temp_store").fetchone()[0] == 2
    finally:
        conn.close()
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_usage_day'"
        ).fetchall()
        assert rows, "idx_usage_day 索引缺失"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_usage_store_record_and_totals(tmp_path):
    store = UsageStore(str(tmp_path / "u.db"))
    await store.record("hash1", requests=2, chars_in=10, chars_out=8)
    await store.record("hash1", requests=1, errors=1, chars_in=5, chars_out=4)
    await store.record("hash2", requests=3)
    today = await store.today("hash1")
    assert today["requests"] == 3
    assert today["errors"] == 1
    assert today["chars_in"] == 15
    totals = await store.totals()
    by_hash = {t["key_hash"]: t for t in totals}
    assert by_hash["hash1"]["requests"] == 3
    assert by_hash["hash2"]["requests"] == 3
    assert await store.quota_exceeded("hash1", quota=3) is True
    assert await store.quota_exceeded("hash1", quota=4) is False
    assert await store.quota_exceeded("hash1", quota=0) is False
    store.close()


@pytest.mark.asyncio
async def test_provider_quota_skips_exhausted_key(tmp_path):
    cfg.settings.USAGE_DAY_QUOTA = 1
    p = _mk_provider()
    p.key_pool = KeyPool(["k1", "k2"], cooldown_seconds=0)
    p.usage_store = UsageStore(str(tmp_path / "u.db"))
    await p.usage_store.record(key_hash("k1"), requests=1)
    p.client.post.return_value = _resp(200, "你好")
    trace: dict = {}
    out = await p._translate("hello", "auto", "zh-CN", trace=trace)
    assert out == "你好"
    assert trace["used_key"] == key_hash("k2")  # k1 配额已满, 自动切 k2
    p.usage_store.close()


@pytest.mark.asyncio
async def test_provider_quota_all_exhausted_returns_429(tmp_path):
    from fastapi import HTTPException

    cfg.settings.USAGE_DAY_QUOTA = 1
    p = _mk_provider()
    p.key_pool = KeyPool(["k1", "k2"], cooldown_seconds=0)
    p.usage_store = UsageStore(str(tmp_path / "u.db"))
    await p.usage_store.record(key_hash("k1"), requests=1)
    await p.usage_store.record(key_hash("k2"), requests=1)
    p.client.post.return_value = _resp(200, "x")
    with pytest.raises(HTTPException) as ei:
        await p._translate("hello", "auto", "zh-CN")
    assert ei.value.status_code == 429
    p.usage_store.close()


@pytest.mark.asyncio
async def test_provider_initialize_and_close_usage_store(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg.settings, "USAGE_STORE_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "USAGE_DB_PATH", str(tmp_path / "u.db"))
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "k1")
    p = GoogleTranslateProvider()
    await p.initialize()
    assert p.usage_store is not None
    await p.close()
