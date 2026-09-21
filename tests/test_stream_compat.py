"""M8 include_usage / M9 模型别名 / M10 取消传播 / M17 段落切分。"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import main as app_main
import pytest
from app.core import config as cfg
from app.providers.googletranslate_provider import GoogleTranslateProvider
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("API_MASTER_KEY", "1")
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


def _resp(translated: str = "你好"):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = [[translated]]
    r.text = translated
    r.request = MagicMock()
    return r


def _parse_sse(body: str):
    events = []
    for line in body.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            events.append(json.loads(line[6:]))
    return events


# ---------- M8: stream_options.include_usage ----------


@pytest.mark.asyncio
async def test_include_usage_emits_usage_chunk(client):
    with patch.object(
        app_main.provider.client, "post", new=AsyncMock(return_value=_resp("你好世界"))
    ):
        r = await client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "stream_options": {"include_usage": True},
            },
        )
    assert r.status_code == 200
    events = _parse_sse(r.content.decode("utf-8"))
    usage_events = [e for e in events if "usage" in e]
    assert len(usage_events) == 1
    ue = usage_events[0]
    assert ue["choices"] == []
    assert ue["usage"]["total_tokens"] > 0
    assert ue["usage"]["estimate"] is True


@pytest.mark.asyncio
async def test_no_usage_chunk_by_default(client):
    with patch.object(app_main.provider.client, "post", new=AsyncMock(return_value=_resp("你好"))):
        r = await client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
    events = _parse_sse(r.content.decode("utf-8"))
    assert all("usage" not in e for e in events)


# ---------- M9: 模型别名 ----------


class TestModelAlias:
    def test_resolve_unknown_passthrough(self):
        assert GoogleTranslateProvider._resolve_model("gpt-4") == "gpt-4"

    def test_resolve_alias(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "MODEL_ALIASES", {"gpt-3.5-turbo": "google-translate"})
        assert GoogleTranslateProvider._resolve_model("gpt-3.5-turbo") == "google-translate"

    def test_resolve_empty_uses_default(self):
        assert GoogleTranslateProvider._resolve_model("") == "google-translate"

    @pytest.mark.asyncio
    async def test_chat_completion_uses_alias(self, client, monkeypatch):
        monkeypatch.setattr(cfg.settings, "MODEL_ALIASES", {"gpt-3.5-turbo": "google-translate"})
        with patch.object(
            app_main.provider.client, "post", new=AsyncMock(return_value=_resp("你好"))
        ):
            r = await client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "hi"}],
                    "model": "gpt-3.5-turbo",
                    "stream": False,
                },
            )
        assert r.status_code == 200
        assert r.json()["model"] == "google-translate"


# ---------- M10: 取消 / 关闭传播 ----------


class TestCancelPropagation:
    @pytest.mark.asyncio
    async def test_generator_exit_propagates(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_BACKOFF_BASE", 0.0)
        p = GoogleTranslateProvider()
        p.client = MagicMock()
        p.client.post = AsyncMock(return_value=_resp("你好"))
        p.cache = None
        resp = p._stream_response("hello", "auto", "zh-CN", "google-translate")
        gen = resp.body_iterator
        await gen.__anext__()  # 拿到第一个 chunk
        with pytest.raises(GeneratorExit):
            await gen.athrow(GeneratorExit)

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        p = GoogleTranslateProvider()
        p.client = MagicMock()
        p.client.post = AsyncMock(return_value=_resp("你好"))
        p.cache = None
        resp = p._stream_response("hello", "auto", "zh-CN", "google-translate")
        gen = resp.body_iterator
        await gen.__anext__()
        with pytest.raises(asyncio.CancelledError):
            await gen.athrow(asyncio.CancelledError)


# ---------- M17: 段落优先切分 ----------


class TestSplitForChunks:
    def test_paragraph_split_preferred(self):
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        parts = GoogleTranslateProvider._split_for_chunks(text)
        assert len(parts) == 3
        assert parts[0] == "第一段内容。"

    def test_single_paragraph_falls_back_to_sentences(self):
        text = "Hello world. Good morning. How are you?"
        parts = GoogleTranslateProvider._split_for_chunks(text)
        assert len(parts) >= 3

    def test_blank_input(self):
        assert GoogleTranslateProvider._split_for_chunks("") == []
