"""P1 / P2 新增功能测试 — 离线, mock 上游。

覆盖:
- P1.2 缓存命中
- P1.5 /ready 就绪探针
- P1.6 输入长度上限 (413)
- P2.2 批量翻译端点
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import main as app_main


def _mock_upstream_response(translated_html: str = "<b>你好</b>", status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = [[translated_html]]
    resp.text = translated_html
    resp.request = MagicMock()
    return resp


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("API_MASTER_KEY", "1")
    from app.core.config import Settings
    saved = app_main.settings
    app_main.settings = Settings()
    # 每次用新缓存, 避免测试间污染
    from app.core import cache as cache_mod
    app_main.provider.cache = cache_mod.make_cache()
    await app_main.provider.initialize()
    transport = ASGITransport(app=app_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app_main.provider.close()
    app_main.settings = saved


# ---------- P1.6 长度上限 ----------

@pytest.mark.asyncio
async def test_p16_text_too_long_returns_413(client, monkeypatch):
    # 改 provider 实际读取的 settings 单例 (app.core.config.settings)
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "MAX_TEXT_LENGTH", 10)
    long_text = "x" * 100
    r = await client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": long_text}],
        "stream": False,
    })
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_p16_within_limit_passes(client):
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(return_value=_mock_upstream_response("你好"))):
        r = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        })
    assert r.status_code == 200


# ---------- P1.2 缓存 ----------

@pytest.mark.asyncio
async def test_p12_cache_hit_skips_upstream(client):
    """第二次同文本请求, 上游 post 应只被调用一次。"""
    post_mock = AsyncMock(return_value=_mock_upstream_response("你好世界"))
    with patch.object(app_main.provider.client, "post", new=post_mock):
        r1 = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hello world"}],
            "stream": False,
        })
        r2 = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hello world"}],
            "stream": False,
        })
    assert r1.status_code == 200 and r2.status_code == 200
    assert post_mock.await_count == 1  # 第二次命中缓存, 不打上游


# ---------- P1.5 /ready ----------

@pytest.mark.asyncio
async def test_p15_ready_ok_when_upstream_up(client):
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(return_value=_mock_upstream_response("你好"))):
        r = await client.get("/ready")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_p15_ready_503_when_upstream_down(client):
    import httpx
    bad = _mock_upstream_response("err", status=500)
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(side_effect=httpx.HTTPStatusError(
                          "500", request=bad.request, response=bad))):
        r = await client.get("/ready")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_p15_health_always_200(client):
    r = await client.get("/health")
    assert r.status_code == 200


# ---------- P2.2 批量翻译 ----------

@pytest.mark.asyncio
async def test_p22_batch_translate(client):
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(return_value=_mock_upstream_response("你好"))):
        r = await client.post("/v1/translate/batch", json={
            "texts": ["hello", "world", "foo"],
            "target_lang": "zh-CN",
        })
    assert r.status_code == 200
    j = r.json()
    assert j["count"] == 3
    assert all(item["ok"] for item in j["data"])
    assert all("你好" in item["translated"] for item in j["data"])


@pytest.mark.asyncio
async def test_p22_batch_empty_rejected(client):
    r = await client.post("/v1/translate/batch", json={"texts": [], "target_lang": "zh-CN"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_p22_batch_over_limit_rejected(client, monkeypatch):
    # fixture 已把 app_main.settings 换成新 Settings, 路由读的是它
    monkeypatch.setattr(app_main.settings, "BATCH_MAX_ITEMS", 2)
    r = await client.post("/v1/translate/batch", json={
        "texts": ["a", "b", "c"], "target_lang": "zh-CN",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_p22_batch_bad_lang(client):
    r = await client.post("/v1/translate/batch", json={
        "texts": ["a"], "target_lang": "klingon",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_p22_batch_single_failure_does_not_break(client):
    """单条上游失败不影响其他条目。"""
    import httpx
    bad = _mock_upstream_response("err", status=500)
    call_count = {"n": 0}

    async def _flaky(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise httpx.HTTPStatusError("500", request=bad.request, response=bad)
        return _mock_upstream_response("你好")

    with patch.object(app_main.provider.client, "post", new=_flaky):
        r = await client.post("/v1/translate/batch", json={
            "texts": ["a", "b", "c"], "target_lang": "zh-CN",
        })
    j = r.json()
    assert r.status_code == 200
    assert j["count"] == 3
    oks = [item["ok"] for item in j["data"]]
    assert oks.count(False) == 1  # 仅第二条失败


# ---------- P2.4 request_id ----------

@pytest.mark.asyncio
async def test_p24_request_id_header(client):
    r = await client.get("/health", headers={"X-Request-Id": "fixed-trace-123"})
    assert r.headers.get("X-Request-Id") == "fixed-trace-123"


@pytest.mark.asyncio
async def test_p24_request_id_auto_generated(client):
    r = await client.get("/health")
    rid = r.headers.get("X-Request-Id", "")
    assert rid.startswith("req-")


# ---------- P1.1 切句流式 (默认关, 开启后分批) ----------

@pytest.mark.asyncio
async def test_p11_chunked_stream_when_enabled(client, monkeypatch):
    """STREAM_CHUNK_ENABLED 开启 + 长文本 → 多句分批, 每批一个 chunk。"""
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "STREAM_CHUNK_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "STREAM_CHUNK_THRESHOLD", 5)  # 短阈值易触发
    # 三句
    text = "Hello world. Good morning. How are you?"
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(return_value=_mock_upstream_response("句"))):
        r = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": text}],
        })
    body = r.content.decode("utf-8")
    # 多个 content chunk (非仅一个), 证明分批
    content_chunks = [l for l in body.splitlines()
                      if l.startswith("data: ") and l != "data: [DONE]"]
    assert len(content_chunks) >= 3  # 3 句 + 1 stop = 4


# ---------- cache 无依赖兜底 ----------

def test_cache_make_returns_none_when_disabled():
    from app.core import cache as cache_mod
    from app.core import config as cfg
    orig = cfg.settings.CACHE_ENABLED
    cfg.settings.CACHE_ENABLED = False
    try:
        assert cache_mod.make_cache() is None
        # get/put 在 None cache 上不抛错
        assert cache_mod.cache_get(None, "k") is None
        cache_mod.cache_put(None, "k", "v")
    finally:
        cfg.settings.CACHE_ENABLED = orig


def test_cache_get_put_roundtrip():
    from app.core import cache as cache_mod
    c = cache_mod.make_cache()
    assert c is not None
    cache_mod.cache_put(c, "key1", "value1")
    assert cache_mod.cache_get(c, "key1") == "value1"
    assert cache_mod.cache_get(c, "missing") is None
    # 空值不缓存
    cache_mod.cache_put(c, "empty", "")
    assert cache_mod.cache_get(c, "empty") is None
