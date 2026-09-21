"""M2 缓存 key / M3 重试 / M4 熔断 / M5 批量 deadline — 离线单测。"""

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.core import config as cfg
from app.core.cache import cache_key
from app.core.circuit_breaker import CircuitBreaker
from app.core.rate_limit import RateLimiter, TokenBucket
from app.providers.googletranslate_provider import GoogleTranslateProvider
from fastapi import HTTPException


def _provider_with_mock_client():
    p = GoogleTranslateProvider()
    p.client = MagicMock()
    p.client.post = AsyncMock()  # await 兼容
    return p


def _resp(translated: str = "你好", status: int = 200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = [[translated]]
    r.text = translated
    r.request = MagicMock()
    return r


# ---------- M2: 缓存 key 跨进程稳定 ----------


class TestCacheKey:
    def test_stable_across_calls(self):
        assert cache_key("hello", "auto", "zh-CN") == cache_key("hello", "auto", "zh-CN")

    def test_matches_sha256_digest(self):
        expect = "auto:zh-CN:" + hashlib.sha256(b"hello").hexdigest()
        assert cache_key("hello", "auto", "zh-CN") == expect

    def test_differs_for_different_text_or_langs(self):
        assert cache_key("hello", "auto", "zh-CN") != cache_key("world", "auto", "zh-CN")
        assert cache_key("hello", "auto", "zh-CN") != cache_key("hello", "en", "zh-CN")
        assert cache_key("hello", "auto", "zh-CN") != cache_key("hello", "auto", "ja")

    def test_unicode_stable(self):
        assert cache_key("你好世界", "auto", "en") == cache_key("你好世界", "auto", "en")


# ---------- M3: 上游重试 ----------


class TestRetry:
    @pytest.mark.asyncio
    async def test_retries_503_then_success(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_BACKOFF_BASE", 0.0)
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_JITTER", 0.0)
        p = _provider_with_mock_client()
        p.client.post.side_effect = [_resp("x", 503), _resp("x", 503), _resp("你好")]
        out = await p._translate("hello", "auto", "zh-CN")
        assert "你好" in out
        assert p.client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_BACKOFF_BASE", 0.0)
        p = _provider_with_mock_client()
        p.client.post.return_value = _resp("err", 400)
        with pytest.raises(httpx.HTTPStatusError):
            await p._translate("hello", "auto", "zh-CN")
        assert p.client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_transport_error_then_success(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_BACKOFF_BASE", 0.0)
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_JITTER", 0.0)
        p = _provider_with_mock_client()
        p.client.post.side_effect = [httpx.ConnectError("boom"), _resp("你好")]
        out = await p._translate("hi", "auto", "zh-CN")
        assert "你好" in out
        assert p.client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_gives_up_after_max_attempts(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_BACKOFF_BASE", 0.0)
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_JITTER", 0.0)
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_ATTEMPTS", 2)
        p = _provider_with_mock_client()
        p.client.post.side_effect = httpx.ConnectError("boom")
        with pytest.raises(httpx.ConnectError):
            await p._translate("hi", "auto", "zh-CN")
        assert p.client.post.call_count == 2


# ---------- M4: 熔断器 ----------


class TestCircuitBreaker:
    def test_closed_allows(self):
        cb = CircuitBreaker(failure_threshold=3, window_seconds=60, open_seconds=30)
        assert cb.allow() is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, window_seconds=60, open_seconds=30)
        for _ in range(3):
            cb.record_failure()
        assert cb.allow() is False
        assert cb.is_open is True

    def test_success_resets(self):
        cb = CircuitBreaker(failure_threshold=2, window_seconds=60, open_seconds=30)
        cb.record_failure()
        cb.record_success()
        assert cb.allow() is True

    @pytest.mark.asyncio
    async def test_half_open_after_window(self):
        cb = CircuitBreaker(failure_threshold=2, window_seconds=60, open_seconds=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow() is False
        await asyncio.sleep(1.1)
        assert cb.allow() is True  # half-open 放行试探
        cb.record_failure()  # 试探失败 -> 立即重新熔断
        assert cb.allow() is False

    @pytest.mark.asyncio
    async def test_translate_fast_fails_when_open(self):
        p = _provider_with_mock_client()
        assert p.circuit_breaker is not None
        for _ in range(cfg.settings.CIRCUIT_FAILURE_THRESHOLD):
            p.circuit_breaker.record_failure()
        with pytest.raises(HTTPException) as e:
            await p._translate("hi", "auto", "zh-CN")
        assert e.value.status_code == 503
        p.client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_chat_completion_503_when_open(self):
        p = _provider_with_mock_client()
        for _ in range(cfg.settings.CIRCUIT_FAILURE_THRESHOLD):
            p.circuit_breaker.record_failure()
        with pytest.raises(HTTPException) as e:
            await p.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        assert e.value.status_code == 503

    @pytest.mark.asyncio
    async def test_probe_ready_false_when_open(self):
        p = _provider_with_mock_client()
        for _ in range(cfg.settings.CIRCUIT_FAILURE_THRESHOLD):
            p.circuit_breaker.record_failure()
        assert await p.probe_ready() is False


# ---------- M5: 批量整体 deadline ----------


class TestBatchDeadline:
    @pytest.mark.asyncio
    async def test_timeout_marks_partial(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "BATCH_DEADLINE_SECONDS", 1)

        async def _slow_post(url, **kwargs):
            payload = kwargs.get("json") or kwargs.get("data")
            text = payload[0][0][0]
            if text == "slow":
                await asyncio.sleep(5)
            return _resp("快")

        p = _provider_with_mock_client()
        p.client.post = _slow_post
        started = asyncio.get_event_loop().time()
        results = await p.translate_batch(["slow", "fast"], "auto", "zh-CN")
        elapsed = asyncio.get_event_loop().time() - started
        assert elapsed < 3, f"整体耗时应受 budget 约束, 实际 {elapsed:.1f}s"
        by_text = {r["text"]: r for r in results}
        assert by_text["slow"]["ok"] is False
        assert by_text["slow"]["error"] == "timeout"
        assert by_text["fast"]["ok"] is True

    @pytest.mark.asyncio
    async def test_all_success_within_budget(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "BATCH_DEADLINE_SECONDS", 10)
        p = _provider_with_mock_client()
        p.client.post.return_value = _resp("好")
        results = await p.translate_batch(["a", "b"], "auto", "zh-CN")
        assert all(r["ok"] and r["error"] is None for r in results)
        assert [r["text"] for r in results] == ["a", "b"]


# ---------- M6: 令牌桶限流 (单元) ----------


class TestTokenBucket:
    def test_capacity_instant(self):
        tb = TokenBucket(capacity=2, per_second=1.0)
        assert tb.consume() is True
        assert tb.consume() is True
        assert tb.consume() is False  # 容量耗尽

    def test_refill_after_time(self):
        tb = TokenBucket(capacity=1, per_second=10.0)
        assert tb.consume() is True
        import time

        time.sleep(0.15)  # 补充 >=1 令牌
        assert tb.consume() is True

    def test_limiter_key_isolation(self):
        rl = RateLimiter(capacity=1, per_second=0.0)
        assert rl.allow("a") is True
        assert rl.allow("a") is False
        assert rl.allow("b") is True

    def test_retry_after_positive_when_exhausted(self):
        tb = TokenBucket(capacity=1, per_second=1.0)
        assert tb.consume() is True
        assert tb.retry_after() > 0.5  # 需等待回填 1 个令牌

    def test_retry_after_zero_when_available(self):
        tb = TokenBucket(capacity=2, per_second=10.0)
        tb.consume()
        assert tb.retry_after() == 0.0  # 仍有令牌

    def test_limiter_retry_after_unknown_key(self):
        rl = RateLimiter(capacity=1, per_second=1.0)
        assert rl.retry_after("nope") == 0.0

    def test_retry_after_inf_when_no_refill(self):
        import math

        tb = TokenBucket(capacity=1, per_second=0.0)
        assert tb.consume() is True
        assert tb.consume() is False
        assert math.isinf(tb.retry_after())


def _cache_hit_count() -> float:
    """读取进程内 cache_hit_total 计数 (用于命中指标断言)。"""
    import re

    from app.core.metrics import metrics

    m = re.search(r"cache_hit_total ([\d.]+)", metrics.render().decode())
    return float(m.group(1)) if m else 0.0


class TestCacheNormalization:
    """3.C.3: 首尾空白归一化 -> 同文本不同空白共享缓存, 命中不打上游。"""

    @pytest.mark.asyncio
    async def test_translate_whitespace_normalized_key(self):
        p = _provider_with_mock_client()
        p.client.post.return_value = _resp("你好")
        await p._translate(" hello ", "auto", "zh-CN")
        await p._translate("hello", "auto", "zh-CN")  # strip 后缓存命中
        assert p.client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_stream_translate_whitespace_normalized_key(self):
        p = _provider_with_mock_client()
        p.client.post.return_value = _resp("你好")
        await p._stream_translate("  hello  ", "auto", "zh-CN")
        await p._stream_translate("hello", "auto", "zh-CN")
        assert p.client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_batch_whitespace_shared_cache(self):
        """批量条目带首尾空白与不带 -> 共享缓存, 只打一次上游 (3.C 验收)。"""
        p = _provider_with_mock_client()
        p.client.post.return_value = _resp("你好")
        results = await p.translate_batch([" hello ", "hello"], "auto", "zh-CN")
        assert all(r["ok"] and r["translated"] for r in results)
        assert p.client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_whitespace_cache_hit_metric(self):
        """命中后 cache_hit_total 增加 (命中率可观测)。"""
        p = _provider_with_mock_client()
        p.client.post.return_value = _resp("你好")
        before = _cache_hit_count()
        await p._translate("hello", "auto", "zh-CN")  # miss
        await p._translate(" hello ", "auto", "zh-CN")  # strip -> hit
        assert _cache_hit_count() == before + 1
