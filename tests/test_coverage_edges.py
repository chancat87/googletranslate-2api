"""覆盖率补齐: 针对 term-missing 报告的剩余缺口 (M1)。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import main as app_main
import pytest
from app.core import config as cfg
from app.core.cache import cache_key, cache_put, make_cache
from app.core.circuit_breaker import CircuitBreaker
from app.core.metrics import Metrics
from app.providers.googletranslate_provider import GoogleTranslateProvider
from fastapi import HTTPException


def _mk_provider():
    p = GoogleTranslateProvider()
    p.client = MagicMock()
    p.client.post = AsyncMock()
    return p


def _resp(translated: str = "你好", status: int = 200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = [[translated]]
    r.text = translated
    r.request = MagicMock()
    return r


def _sse_events(body: str):
    import json as _json

    events = []
    for line in body.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            events.append(_json.loads(line[6:]))
    return events


async def _drain(body_iterator) -> str:
    chunks = []
    async for c in body_iterator:
        chunks.append(c)
    return b"".join(chunks).decode("utf-8")


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
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app_main.provider.close()
    app_main.settings = saved


# ---------- provider 缺口 ----------


class TestProviderEdgeCoverage:
    @pytest.mark.asyncio
    async def test_initialize_raises_without_key(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEY", None)
        p = GoogleTranslateProvider()
        with pytest.raises(ValueError):
            await p.initialize()

    @pytest.mark.asyncio
    async def test_nonstream_generic_exception_500(self):
        p = _mk_provider()
        p._translate = AsyncMock(side_effect=ValueError("boom"))
        resp = await p.chat_completion(
            {"messages": [{"role": "user", "content": "hi"}], "stream": False}
        )
        assert resp.status_code == 500
        assert "internal_error" in resp.body.decode("utf-8")

    @pytest.mark.asyncio
    async def test_nonstream_transport_error_502(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_BACKOFF_BASE", 0.0)
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_JITTER", 0.0)
        p = _mk_provider()
        p.client.post.side_effect = httpx.ConnectError("boom")
        resp = await p.chat_completion(
            {"messages": [{"role": "user", "content": "hi"}], "stream": False}
        )
        assert resp.status_code == 502
        assert resp.body and "网络异常" in resp.body.decode("utf-8")

    @pytest.mark.asyncio
    async def test_nonstream_http_exception_passthrough(self):
        p = _mk_provider()
        p._translate = AsyncMock(side_effect=HTTPException(status_code=503, detail="熔断"))
        with pytest.raises(HTTPException) as e:
            await p.chat_completion(
                {"messages": [{"role": "user", "content": "hi"}], "stream": False}
            )
        assert e.value.status_code == 503

    @pytest.mark.asyncio
    async def test_stream_http_exception_chunk(self):
        """P3-5: 非白名单 detail 统一为通用文案, 不进入 SSE。"""
        p = _mk_provider()
        p._translate = AsyncMock(side_effect=HTTPException(status_code=503, detail="熔断"))
        resp = p._stream_response("hi", "auto", "zh-CN", "m")
        body = await _drain(resp.body_iterator)
        events = _sse_events(body)
        assert events[0]["choices"][0]["delta"]["content"] == "请求处理失败"
        assert "[DONE]" in body

    @pytest.mark.asyncio
    async def test_stream_http_exception_safe_detail_passthrough(self):
        """P3-5: 白名单内 detail (翻译服务暂时不可用) 正常透传。"""
        p = _mk_provider()
        p._translate = AsyncMock(
            side_effect=HTTPException(status_code=503, detail="翻译服务暂时不可用")
        )
        resp = p._stream_response("hi", "auto", "zh-CN", "m")
        body = await _drain(resp.body_iterator)
        events = _sse_events(body)
        assert events[0]["choices"][0]["delta"]["content"] == "翻译服务暂时不可用"

    @pytest.mark.asyncio
    async def test_stream_transport_error_chunk(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_BACKOFF_BASE", 0.0)
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_JITTER", 0.0)
        p = _mk_provider()
        p.client.post.side_effect = httpx.ConnectError("boom")
        resp = p._stream_response("hi", "auto", "zh-CN", "m")
        body = await _drain(resp.body_iterator)
        events = _sse_events(body)
        assert "网络异常" in events[0]["choices"][0]["delta"]["content"]

    @pytest.mark.asyncio
    async def test_stream_generic_error_chunk(self):
        p = _mk_provider()
        p._translate = AsyncMock(side_effect=ValueError("boom"))
        resp = p._stream_response("hi", "auto", "zh-CN", "m")
        body = await _drain(resp.body_iterator)
        events = _sse_events(body)
        assert events[0]["choices"][0]["delta"]["content"] == "内部服务器错误"

    @pytest.mark.asyncio
    async def test_stream_translate_cache_hit(self):
        p = _mk_provider()
        p.cache = make_cache()
        cache_put(p.cache, cache_key("hi", "auto", "zh-CN"), "你好")
        chunks = await p._stream_translate("hi", "auto", "zh-CN")
        assert chunks == ["你好"]
        p.client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_translate_batched_segment_failure(self):
        p = _mk_provider()
        p._translate = AsyncMock(side_effect=[ValueError("x"), "好"])
        out = await p._translate_batched("第一段。\n\n第二段。", "auto", "zh-CN")
        assert out == ["", "好"]

    @pytest.mark.asyncio
    async def test_translate_empty_result(self):
        p = _mk_provider()
        p.client.post.return_value = _resp("", 200)
        p.client.post.return_value.json.return_value = [[]]
        out = await p._translate("hi", "auto", "zh-CN")
        assert out == ""

    @pytest.mark.asyncio
    async def test_record_failure_without_breaker(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "CIRCUIT_BREAKER_ENABLED", False)
        p = GoogleTranslateProvider()
        assert p.circuit_breaker is None
        p._record_upstream_failure("500")  # 不抛错

    @pytest.mark.asyncio
    async def test_batch_two_slow_both_timeout(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "BATCH_DEADLINE_SECONDS", 1)

        async def _slow(url, **kwargs):
            await asyncio.sleep(5)
            return _resp("好")

        p = _mk_provider()
        p.client.post = _slow
        results = await p.translate_batch(["a", "b"], "auto", "zh-CN")
        assert all(r["ok"] is False and r["error"] == "timeout" for r in results)

    def test_brief_error_branches(self):
        req = httpx.Request("POST", "http://x")
        resp = httpx.Response(400, request=req)
        e = httpx.HTTPStatusError("400", request=req, response=resp)
        assert GoogleTranslateProvider._brief_error(e) == "upstream_400"
        assert GoogleTranslateProvider._brief_error(httpx.ConnectError("x")) == "upstream_network"
        assert GoogleTranslateProvider._brief_error(HTTPException(400, "bad param")) == "bad param"
        assert GoogleTranslateProvider._brief_error(RuntimeError("x")) == "RuntimeError"

    def test_extract_text_other_type(self):
        assert GoogleTranslateProvider._extract_text(123) == ""

    def test_detect_language_empty(self):
        j = GoogleTranslateProvider.detect_language("")
        assert j["scripts"] == [] and j["target_lang"] == "zh-CN"

    def test_parse_upstream_error_dict(self):
        r = MagicMock()
        r.json.return_value = {"code": 3, "msg": "x"}
        assert GoogleTranslateProvider()._parse_upstream_error(r, 400) == str(
            {"code": 3, "msg": "x"}
        )

    def test_log_upstream_error_parse_exception(self):
        """P3-3: 上游错误体解析抛非 ValueError 异常 -> 摘要为空, 仍记录状态码。"""
        import io

        from loguru import logger as _lg

        p = _mk_provider()
        r = MagicMock()
        r.json.side_effect = RuntimeError("boom")
        buf = io.StringIO()
        hid = _lg.add(
            buf, format="{message}", level="WARNING", enqueue=False, colorize=False, backtrace=False, diagnose=False
        )
        try:
            p._log_upstream_error(r, 500)
        finally:
            _lg.remove(hid)
        assert "上游返回 500" in buf.getvalue()
        assert "boom" not in buf.getvalue()


# ---------- main 缺口 ----------


class TestMainEdgeCoverage:
    def test_configure_logging_json_branch(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "LOG_FORMAT", "json")
        app_main._configure_logging()  # 覆盖 json 分支

    def test_configure_logging_text_branch(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "LOG_FORMAT", "text")
        app_main._configure_logging()  # 覆盖 text 分支

    def test_extract_bearer_token_malformed(self):
        assert app_main._extract_bearer_token("Basic abc") is None
        assert app_main._extract_bearer_token(None) is None
        assert app_main._extract_bearer_token("Bearer tok") == "tok"

    @pytest.mark.asyncio
    async def test_batch_blank_item_400(self, client):
        r = await client.post("/v1/translate/batch", json={"texts": ["  "], "target_lang": "zh-CN"})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_too_long_413(self, client, monkeypatch):
        monkeypatch.setattr(app_main.settings, "MAX_TEXT_LENGTH", 3)
        r = await client.post(
            "/v1/translate/batch", json={"texts": ["abcdef"], "target_lang": "zh-CN"}
        )
        assert r.status_code == 413

    @pytest.mark.asyncio
    async def test_batch_bad_source_lang_400(self, client):
        r = await client.post(
            "/v1/translate/batch",
            json={"texts": ["a"], "source_lang": "klingon", "target_lang": "zh-CN"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_unhandled_exception_envelope(self, monkeypatch):
        def boom(text):
            raise RuntimeError("boom")

        monkeypatch.setattr(app_main.provider, "detect_language", boom)
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app_main.app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/v1/translate/detect", json={"text": "hi"})
        assert r.status_code == 500
        assert r.json()["error"]["type"] == "internal_error"


# ---------- circuit breaker is_open 关闭态 ----------


def test_circuit_is_open_false_when_closed():
    cb = CircuitBreaker(failure_threshold=3, window_seconds=60, open_seconds=30)
    assert cb.is_open is False


# ---------- metrics 禁用态方法调用 ----------


def test_metrics_disabled_methods(monkeypatch):
    monkeypatch.setattr(cfg.settings, "METRICS_ENABLED", False)
    m = Metrics()
    m.translate_requests.labels("true", "started").inc()
    m.upstream_errors.labels(code="500").inc()
    m.cache_hits.inc()
    m.cache_misses.inc()
    m.rate_limited.labels(key_type="ip").inc()
    m.translate_duration.observe(0.1)
    assert m.render() == b"# metrics disabled\n"
