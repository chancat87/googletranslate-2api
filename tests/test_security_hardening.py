"""3.B 安全加固验收: 弱 key 启动告警 / 403-429 上游告警与指标 / 错误响应保洁。"""

import re
from unittest.mock import AsyncMock, MagicMock

import httpx
import main as app_main
import pytest
from app.core import config as cfg
from app.core.metrics import metrics
from app.providers.googletranslate_provider import GoogleTranslateProvider


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
    def test_default_example_key_warns(self, capsys, monkeypatch):
        monkeypatch.setattr(
            cfg.settings, "API_MASTER_KEY", "sk-googletranslate-2api-default-key-please-change-me"
        )
        app_main._check_weak_api_key()
        out = capsys.readouterr().out
        assert "API_MASTER_KEY" in out and "过弱" in out

    def test_short_key_warns(self, capsys, monkeypatch):
        monkeypatch.setattr(cfg.settings, "API_MASTER_KEY", "short")
        app_main._check_weak_api_key()
        assert "过弱" in capsys.readouterr().out

    def test_auth_disabled_warns(self, capsys, monkeypatch):
        monkeypatch.setattr(cfg.settings, "API_MASTER_KEY", None)
        app_main._check_weak_api_key()
        out = capsys.readouterr().out
        assert "认证已关闭" in out

    def test_strong_key_no_warning(self, capsys, monkeypatch):
        monkeypatch.setattr(cfg.settings, "API_MASTER_KEY", "aVeryStrongRandomKey123!")
        app_main._check_weak_api_key()
        assert "过弱" not in capsys.readouterr().out


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
