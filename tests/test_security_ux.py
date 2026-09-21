"""M6 限流中间件 / M7 422 统一信封 / M16 语言检测 / 多 key 认证 — ASGI 集成。"""

from unittest.mock import AsyncMock, patch

import main as app_main
import pytest
from app.core import config as cfg
from app.core.rate_limit import RateLimiter
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("API_MASTER_KEY", "1")  # 关闭认证
    from app.core.config import Settings

    saved = app_main.settings
    app_main.settings = Settings()
    await app_main.provider.initialize()
    app_main.provider.reset_health()
    if app_main.provider.cache is not None:
        app_main.provider.cache.clear()
    transport = ASGITransport(app=app_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app_main.provider.close()
    app_main.settings = saved


# ---------- M6: 限流 ----------


@pytest.mark.asyncio
async def test_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setenv("API_MASTER_KEY", "1")
    monkeypatch.setattr(app_main, "rate_limiter", RateLimiter(capacity=2, per_second=0.001))
    monkeypatch.setattr(app_main.settings, "RATE_LIMIT_ENABLED", True)
    r1 = await client.get("/v1/models")
    r2 = await client.get("/v1/models")
    r3 = await client.get("/v1/models")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert r3.headers.get("Retry-After") == "1"
    body = r3.json()
    assert body["error"]["type"] == "rate_limit_error"


@pytest.mark.asyncio
async def test_rate_limit_by_key_dimension(client, monkeypatch):
    monkeypatch.setattr(app_main.settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(app_main, "rate_limiter", RateLimiter(capacity=1, per_second=0.001))
    headers = {"Authorization": "Bearer tok-1"}
    r1 = await client.get("/v1/models", headers=headers)
    r2 = await client.get("/v1/models", headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_skips_health(client, monkeypatch):
    monkeypatch.setattr(app_main, "rate_limiter", RateLimiter(capacity=1, per_second=0.001))
    monkeypatch.setattr(app_main.settings, "RATE_LIMIT_ENABLED", True)
    for _ in range(3):
        r = await client.get("/health")  # /health 在跳过清单
        assert r.status_code == 200


# ---------- M7: 422 统一信封 ----------


@pytest.mark.asyncio
async def test_422_unified_envelope(client):
    r = await client.post("/v1/chat/completions", json={"model": "x"})
    assert r.status_code == 422
    body = r.json()
    assert "error" in body
    assert body["error"]["type"] == "invalid_request_error"
    assert isinstance(body["error"]["detail"], list)


# ---------- M16: 语言检测 ----------


@pytest.mark.asyncio
async def test_detect_chinese(client):
    r = await client.post("/v1/translate/detect", json={"text": "你好世界"})
    assert r.status_code == 200
    j = r.json()
    assert j["object"] == "language_detection"
    assert "cjk_han" in j["scripts"]
    assert j["target_lang"] == "en"
    assert j["source"] == "script_heuristic"


@pytest.mark.asyncio
async def test_detect_latin(client):
    r = await client.post("/v1/translate/detect", json={"text": "Hello world"})
    assert r.status_code == 200
    j = r.json()
    assert j["scripts"] == []
    assert j["target_lang"] == "zh-CN"


@pytest.mark.asyncio
async def test_detect_empty_rejected(client):
    r = await client.post("/v1/translate/detect", json={"text": "  "})
    assert r.status_code == 400


# ---------- 多 key 认证 + 常量时间比较 ----------


@pytest.mark.asyncio
async def test_multi_key_auth(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("API_MASTER_KEY", "key-one,key-two")
    from app.core.config import Settings

    saved = app_main.settings
    app_main.settings = Settings()
    transport = ASGITransport(app=app_main.app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r_bad = await c.get("/v1/models", headers={"Authorization": "Bearer nope"})
            assert r_bad.status_code == 403
            r1 = await c.get("/v1/models", headers={"Authorization": "Bearer key-one"})
            assert r1.status_code == 200
            r2 = await c.get("/v1/models", headers={"Authorization": "Bearer key-two"})
            assert r2.status_code == 200
    finally:
        app_main.settings = saved


@pytest.mark.asyncio
async def test_auth_no_token_401(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("API_MASTER_KEY", "just-one")
    from app.core.config import Settings

    saved = app_main.settings
    app_main.settings = Settings()
    transport = ASGITransport(app=app_main.app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/v1/models")
            assert r.status_code == 401
    finally:
        app_main.settings = saved


# ---------- M12: 指标端点 ----------


@pytest.mark.asyncio
async def test_metrics_endpoint(client):
    with patch.object(
        app_main.provider.client, "post", new=AsyncMock(return_value=_resp_json("你好"))
    ):
        r = await client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello metrics"}],
                "stream": False,
            },
        )
        assert r.status_code == 200
        # 再次请求同一文本 -> 缓存命中
        await client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello metrics"}],
                "stream": False,
            },
        )
    m = await client.get("/metrics")
    assert m.status_code == 200
    text = m.text
    assert "translate_requests_total" in text
    assert 'stream="false"' in text
    assert "cache_hit_total" in text
    assert "cache_miss_total" in text


def _resp_json(translated: str):
    from unittest.mock import MagicMock

    r = MagicMock()
    r.status_code = 200
    r.json.return_value = [[translated]]
    r.text = translated
    r.request = MagicMock()
    return r


# ---------- metrics 禁用路径 ----------


def test_metrics_disabled_render(monkeypatch):
    monkeypatch.setattr(cfg.settings, "METRICS_ENABLED", False)
    from app.core.metrics import Metrics

    m = Metrics()
    assert m.enabled is False
    assert b"metrics disabled" in m.render()
