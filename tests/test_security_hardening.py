"""3.B 安全加固验收: 弱 key 启动告警 / 403-429 上游告警与指标 / 错误响应保洁。"""

import re
from unittest.mock import AsyncMock, MagicMock

import httpx
import main as app_main
import pytest
from app.core import config as cfg
from app.core.metrics import metrics
from app.core.rate_limit import RateLimiter
from app.providers.googletranslate_provider import GoogleTranslateProvider
from fastapi import HTTPException


def _metric_value(text: str, name: str, **labels) -> float:
    lab = ",".join(f'{k}="{v}"' for k, v in labels.items())
    m = re.search(rf"{name}\{{{lab}\}} ([\d.]+)", text)
    return float(m.group(1)) if m else 0.0


def _mk_provider():
    p = GoogleTranslateProvider()
    p.client = MagicMock()
    p.client.post = AsyncMock()
    return p


def _resp(status: int, translated: str = "x"):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = [[translated]]
    r.text = translated
    r.request = MagicMock()
    return r


# ---------- 3.B.2 启动弱 key 告警 ----------


class TestWeakMasterKeyWarning:
    def test_default_example_key_rejected(self, capsys, monkeypatch):
        """P1-1: 命中公开示例默认 key 且未显式放行 -> 拒绝启动。"""
        monkeypatch.setattr(
            cfg.settings, "API_MASTER_KEY", "sk-googletranslate-2api-default-key-please-change-me"
        )
        monkeypatch.setattr(cfg.settings, "ALLOW_WEAK_API_KEY", False)
        with pytest.raises(RuntimeError):
            app_main._check_weak_api_key()

    def test_default_example_key_warns_when_allowed(self, capsys, monkeypatch):
        monkeypatch.setattr(
            cfg.settings, "API_MASTER_KEY", "sk-googletranslate-2api-default-key-please-change-me"
        )
        monkeypatch.setattr(cfg.settings, "ALLOW_WEAK_API_KEY", True)
        app_main._check_weak_api_key()
        assert "已显式放行" in capsys.readouterr().out

    def test_short_key_warns(self, capsys, monkeypatch):
        monkeypatch.setattr(cfg.settings, "API_MASTER_KEY", "short")
        app_main._check_weak_api_key()
        assert "长度偏短" in capsys.readouterr().out

    def test_auth_disabled_warns(self, capsys, monkeypatch):
        monkeypatch.setattr(cfg.settings, "API_MASTER_KEY", None)
        app_main._check_weak_api_key()
        out = capsys.readouterr().out
        assert "认证已关闭" in out

    def test_strong_key_no_warning(self, capsys, monkeypatch):
        monkeypatch.setattr(cfg.settings, "API_MASTER_KEY", "aVeryStrongRandomKey123!")
        app_main._check_weak_api_key()
        assert "过弱" not in capsys.readouterr().out

    def test_low_entropy_key_warns(self, capsys, monkeypatch):
        """P3-1: 字符多样性过低 (全相同字符) 即使长度达标也告警。"""
        monkeypatch.setattr(cfg.settings, "API_MASTER_KEY", "aaaaaaaaaaaaaaaa")
        app_main._check_weak_api_key()
        assert "多样性" in capsys.readouterr().out


# ---------- 3.B.5 上游 403/429 告警 + 指标 ----------


class TestUpstreamAuthAlerts:
    @pytest.mark.asyncio
    async def test_403_logs_error_and_increments_metric(self, capsys):
        p = _mk_provider()
        p.client.post.return_value = _resp(403)
        before = _metric_value(
            metrics.render().decode(), "translate_upstream_errors_total", code="403"
        )
        with pytest.raises(httpx.HTTPStatusError):
            await p._translate("hi", "auto", "zh-CN")
        after = _metric_value(
            metrics.render().decode(), "translate_upstream_errors_total", code="403"
        )
        assert after == before + 1
        assert p.client.post.call_count == 1  # 403 不重试
        out = capsys.readouterr().out
        assert "403" in out and "GOOGLE_API_KEY" in out

    @pytest.mark.asyncio
    async def test_429_logs_warning_and_increments_metric(self, capsys, monkeypatch):
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_ATTEMPTS", 1)
        p = _mk_provider()
        p.client.post.return_value = _resp(429)
        before = _metric_value(
            metrics.render().decode(), "translate_upstream_errors_total", code="429"
        )
        with pytest.raises(httpx.HTTPStatusError):
            await p._translate("hi", "auto", "zh-CN")
        after = _metric_value(
            metrics.render().decode(), "translate_upstream_errors_total", code="429"
        )
        assert after == before + 1
        out = capsys.readouterr().out
        assert "429" in out and "频率限制" in out


# ---------- 3.B.6 错误响应保洁 ----------


class TestErrorSanitization:
    @pytest.mark.asyncio
    async def test_nonstream_500_does_not_leak_exception(self):
        import json as _json

        p = _mk_provider()
        p._translate = AsyncMock(side_effect=ValueError("boom-secret-internal"))
        resp = await p.chat_completion(
            {"messages": [{"role": "user", "content": "hi"}], "stream": False}
        )
        assert resp.status_code == 500
        body = resp.body.decode("utf-8")
        assert "boom-secret-internal" not in body
        assert "ValueError" not in body
        j = _json.loads(body)
        assert j["error"]["type"] == "internal_error"

    @pytest.mark.asyncio
    async def test_stream_error_chunk_is_generic(self):
        import json as _json

        p = _mk_provider()
        p._translate = AsyncMock(side_effect=ValueError("boom-secret-internal"))
        resp = p._stream_response("hi", "auto", "zh-CN", "m")
        chunks = []
        async for c in resp.body_iterator:
            chunks.append(c)
        body = b"".join(chunks).decode("utf-8")
        assert "boom-secret-internal" not in body
        contents = []
        for line in body.splitlines():
            if line.startswith("data: ") and line != "data: [DONE]":
                ev = _json.loads(line[6:])
                if ev.get("choices"):
                    contents.append(ev["choices"][0]["delta"].get("content", ""))
        assert "内部服务器错误" in "".join(contents)


@pytest.fixture
async def client(monkeypatch):
    """ASGI 客户端 (认证关闭), 供限流/头相关测试使用。"""
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


class TestReviewSecurityFixes:
    """3.B 审查修复 (P2-1/P2-2/P2-3/P2-4/P3-9) 验收。"""

    @pytest.mark.asyncio
    async def test_initialize_raises_on_placeholder_key(self, monkeypatch):
        """P3-9: GOOGLE_API_KEY 为示例占位符 -> 拒绝启动。"""
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEY", "在这里填入你的谷歌翻译 API Key")
        from app.providers.googletranslate_provider import GoogleTranslateProvider

        with pytest.raises(ValueError):
            await GoogleTranslateProvider().initialize()

    @pytest.mark.asyncio
    async def test_non_ascii_token_returns_401_not_500(self, monkeypatch):
        """P2-1: 非 ASCII token 不得触发 compare_digest TypeError -> 500 (直接调用依赖)。"""
        monkeypatch.setattr(cfg.settings, "API_MASTER_KEY", "strong-key-1234567890")
        with pytest.raises(HTTPException) as e:
            await app_main.verify_api_key("Bearer 中文token")
        assert e.value.status_code == 401

    @pytest.mark.asyncio
    async def test_403_nonstream_maps_to_auth_error(self):
        """P2-4: 403 -> 502 + type=upstream_auth_error (可区分永久凭证错误)。"""
        import json as _json

        p = _mk_provider()
        p.client.post.return_value = _resp(403)
        resp = await p.chat_completion(
            {"messages": [{"role": "user", "content": "hi"}], "stream": False}
        )
        assert resp.status_code == 502
        j = _json.loads(resp.body)
        assert j["error"]["type"] == "upstream_auth_error"
        assert "API Key" in j["error"]["message"]

    @pytest.mark.asyncio
    async def test_403_stream_chunk_mentions_api_key(self):
        p = _mk_provider()
        p.client.post.return_value = _resp(403)
        resp = p._stream_response("hi", "auto", "zh-CN", "m")
        chunks = []
        async for c in resp.body_iterator:
            chunks.append(c)
        body = b"".join(chunks).decode("utf-8")
        assert "API Key" in body

    @pytest.mark.asyncio
    async def test_rate_limiter_bounded_eviction(self):
        """P2-2: 限流桶有界, 超出 max_keys 淘汰最旧。"""
        rl = RateLimiter(capacity=1, per_second=0.001, max_keys=2)
        assert await rl.allow("a") is True
        assert await rl.allow("b") is True
        assert await rl.allow("c") is True  # 触发淘汰 a
        assert await rl.allow("a") is True  # a 被淘汰后重新建桶
        assert len(rl._memory._buckets) == 2  # 内存有界
        await rl.aclose()

    @pytest.mark.asyncio
    async def test_xff_dimension_when_trusted(self, client, monkeypatch):
        """P2-3: TRUST_PROXY_HEADER=true 时按 X-Forwarded-For 首跳隔离。"""
        monkeypatch.setattr(app_main.settings, "RATE_LIMIT_ENABLED", True)
        monkeypatch.setattr(app_main, "rate_limiter", RateLimiter(1, 0.001, 100))
        monkeypatch.setattr(app_main.settings, "TRUST_PROXY_HEADER", True)
        h1 = {"X-Forwarded-For": "1.1.1.1"}
        h2 = {"X-Forwarded-For": "2.2.2.2"}
        r1 = await client.get("/v1/models", headers=h1)
        r2 = await client.get("/v1/models", headers=h1)
        r3 = await client.get("/v1/models", headers=h2)
        assert r1.status_code == 200
        assert r2.status_code == 429
        assert r3.status_code == 200

    @pytest.mark.asyncio
    async def test_xff_ignored_when_untrusted(self, client, monkeypatch):
        """P2-3: TRUST_PROXY_HEADER=false (默认) 忽略 XFF。"""
        monkeypatch.setattr(app_main.settings, "RATE_LIMIT_ENABLED", True)
        monkeypatch.setattr(app_main, "rate_limiter", RateLimiter(1, 0.001, 100))
        monkeypatch.setattr(app_main.settings, "TRUST_PROXY_HEADER", False)
        r1 = await client.get("/v1/models", headers={"X-Forwarded-For": "1.1.1.1"})
        r2 = await client.get("/v1/models", headers={"X-Forwarded-For": "2.2.2.2"})
        assert r1.status_code == 200
        assert r2.status_code == 429  # 同一 client 共享桶
