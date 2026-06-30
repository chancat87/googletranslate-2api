"""API 集成测试 — ASGI transport + mock 上游 httpx, 离线可运行。"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import main as app_main


def _mock_upstream_response(translated_html: str = "<b>你好世界</b>", status: int = 200):
    """构造一个假的 httpx.Response。"""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = [[translated_html]]
    resp.text = translated_html
    resp.request = MagicMock()
    return resp


@pytest.fixture
async def client(monkeypatch):
    """启动 app, mock 掉上游 Google 调用。

    保存并还原全局 settings, 避免测试间状态污染。
    每次清空 provider 缓存, 避免缓存命中绕过 mock。
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("API_MASTER_KEY", "1")  # 关闭认证, 专注功能
    from app.core.config import Settings
    saved_settings = app_main.settings
    app_main.settings = Settings()
    await app_main.provider.initialize()
    # 清缓存, 隔离测试 (缓存命中会绕过 mock 上游)
    if app_main.provider.cache is not None:
        app_main.provider.cache.clear()
    transport = ASGITransport(app=app_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app_main.provider.close()
    app_main.settings = saved_settings  # 还原, 防止污染后续测试


# ---------- 系统端点 ----------

@pytest.mark.asyncio
async def test_root(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "message" in r.json()


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    assert "version" in j


@pytest.mark.asyncio
async def test_models(client):
    r = await client.get("/v1/models")
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "list"
    assert any(m["id"] == "google-translate" for m in data["data"])


@pytest.mark.asyncio
async def test_openapi_docs_available(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    # 关键路径必须出现在 OpenAPI spec
    assert "/v1/chat/completions" in spec["paths"]
    assert "/health" in spec["paths"]


# ---------- 流式翻译 ----------

@pytest.mark.asyncio
async def test_stream_translate(client):
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(return_value=_mock_upstream_response("你好世界"))):
        r = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hello world"}]
        })
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.content.decode("utf-8")
    assert "chat.completion.chunk" in body
    assert "[DONE]" in body
    # 解析出 delta content
    chunks = []
    for line in body.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            d = json.loads(line[6:])
            dc = d["choices"][0]["delta"].get("content", "")
            if dc:
                chunks.append(dc)
    assert "你好" in "".join(chunks)


@pytest.mark.asyncio
async def test_stream_finish_reason_stop(client):
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(return_value=_mock_upstream_response("x"))):
        r = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}]
        })
    body = r.content.decode("utf-8")
    fr = [json.loads(l[6:])["choices"][0]["finish_reason"]
          for l in body.splitlines()
          if l.startswith("data: ") and l != "data: [DONE]"
          and json.loads(l[6:])["choices"][0]["finish_reason"]]
    assert fr == ["stop"]


# ---------- 非流式翻译 ----------

@pytest.mark.asyncio
async def test_nonstream_translate(client):
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(return_value=_mock_upstream_response("你好世界"))):
        r = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hello world"}],
            "stream": False,
        })
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    j = r.json()
    assert j["object"] == "chat.completion"
    assert j["choices"][0]["message"]["role"] == "assistant"
    assert "你好" in j["choices"][0]["message"]["content"]
    assert j["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_nonstream_default_model_not_null(client):
    """回归: 不传 model 时响应 model 字段必须是默认模型字符串, 不能是 null。

    之前 model_dump(exclude_none=False) 把 None 透传, 导致响应 model=null,
    破坏 OpenAI 类型契约 (model 应为 str)。
    """
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(return_value=_mock_upstream_response("你好"))):
        r = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        })
    assert r.status_code == 200
    model = r.json().get("model")
    assert model is not None, "model 字段不能为 null"
    assert isinstance(model, str)
    assert model == "google-translate"


@pytest.mark.asyncio
async def test_nonstream_with_explicit_langs(client):
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(return_value=_mock_upstream_response("こんにちは"))):
        r = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "good morning"}],
            "source_lang": "en",
            "target_lang": "ja",
            "stream": False,
        })
    assert r.status_code == 200
    assert "こんにちは" in r.json()["choices"][0]["message"]["content"]


@pytest.mark.asyncio
async def test_nonstream_content_list_segments(client):
    """OpenAI 多段 content 数组应被正确提取。"""
    captured = {}

    async def _capture_post(*args, **kwargs):
        captured["payload"] = kwargs.get("json")
        return _mock_upstream_response("result")

    with patch.object(app_main.provider.client, "post", new=_capture_post):
        r = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user",
                          "content": [{"type": "text", "text": "hello "},
                                      {"type": "text", "text": "world"}]}],
            "stream": False,
        })
    assert r.status_code == 200
    # 验证 provider 收到了拼接后的 "hello world"
    assert captured["payload"][0][0][0] == "hello world"


# ---------- 错误路径 (状态码语义) ----------

@pytest.mark.asyncio
async def test_err_missing_messages(client):
    r = await client.post("/v1/chat/completions", json={"model": "x"})
    assert r.status_code == 422  # Pydantic 校验失败


@pytest.mark.asyncio
async def test_err_empty_content(client):
    r = await client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": ""}]
    })
    assert r.status_code == 400
    assert "error" in r.json()


@pytest.mark.asyncio
async def test_err_no_user_message(client):
    r = await client.post("/v1/chat/completions", json={
        "messages": [{"role": "system", "content": "hi"}]
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_err_bad_lang(client):
    r = await client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "hi"}],
        "target_lang": "klingon",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_err_upstream_nonstream_returns_502(client):
    import httpx
    bad = _mock_upstream_response("err", status=400)
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(side_effect=httpx.HTTPStatusError(
                          "400", request=bad.request, response=bad))):
        r = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "unique-502-text"}],
            "stream": False,
        })
    assert r.status_code == 502
    assert r.json()["error"]["type"] == "upstream_error"


@pytest.mark.asyncio
async def test_err_upstream_stream_returns_chunk(client):
    """流式下上游错误以 error chunk 形式返回, HTTP 仍 200。"""
    import httpx
    bad = _mock_upstream_response("err", status=400)
    with patch.object(app_main.provider.client, "post",
                      new=AsyncMock(side_effect=httpx.HTTPStatusError(
                          "400", request=bad.request, response=bad))):
        r = await client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "unique-stream-err-text"}],
        })
    assert r.status_code == 200  # SSE 已建立
    body = r.content.decode("utf-8")
    # 新实现: 错误 chunk 文案为 "翻译服务暂时不可用" (json 转义为 \uXXXX)
    assert "chat.completion.chunk" in body
    assert "finish_reason" in body  # 含 stop 标记
    assert "[DONE]" in body


# ---------- 认证 ----------

@pytest.mark.asyncio
async def test_auth_rejects_bad_token(monkeypatch):
    """API_MASTER_KEY 非 1 时, 错误 token 返回 403。"""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("API_MASTER_KEY", "secret-real-key")
    from app.core.config import Settings
    saved_settings = app_main.settings
    app_main.settings = Settings()
    await app_main.provider.initialize()
    transport = ASGITransport(app=app_main.app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # 无 token
            r = await c.get("/v1/models")
            assert r.status_code == 401
            # 错 token
            r = await c.get("/v1/models", headers={"Authorization": "Bearer wrong"})
            assert r.status_code == 403
            # 正确 token
            r = await c.get("/v1/models", headers={"Authorization": "Bearer secret-real-key"})
            assert r.status_code == 200
    finally:
        await app_main.provider.close()
        app_main.settings = saved_settings  # 还原认证配置, 避免污染其它测试
