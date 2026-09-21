"""阶段 1.1 多 Key 池 / 阶段 1.2 链路摘要 / 阶段 2.1 Key 维度指标 — 测试。"""

import re
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.core import config as cfg
from app.core.key_pool import KeyPool, key_hash
from app.core.metrics import Metrics, metrics
from app.core.trace import TraceStore, format_trace_summary
from app.providers.googletranslate_provider import GoogleTranslateProvider


def _metric_value(text: str, name: str, **labels) -> float:
    lab = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    pattern = name + "{" + lab + "} ([0-9.]+)" if labels else name + " ([0-9.]+)"
    m = re.search(pattern, text)
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


# ---------- KeyPool 单元 ----------


class TestKeyHash:
    def test_stable_and_short(self):
        assert key_hash("k1") == key_hash("k1")
        assert len(key_hash("k1")) == 8
        assert key_hash("k1") != key_hash("k2")


class TestKeyPool:
    def test_round_robin_rotation(self):
        pool = KeyPool(["a", "b", "c"])
        assert pool.next() == "a"
        assert pool.next() == "b"
        assert pool.next() == "c"
        assert pool.next() == "a"

    def test_mark_failed_skips_key_until_cooldown(self):
        fake_now = [100.0]
        pool = KeyPool(["a", "b"], cooldown_seconds=60.0, now=lambda: fake_now[0])
        assert pool.next() == "a"
        pool.mark_failed("a")
        assert pool.available_count() == 1
        assert pool.next() == "b"  # 冷却期跳过 a
        fake_now[0] = 200.0
        assert pool.available_count() == 2
        assert pool.next() == "a"  # 到期后恢复

    def test_all_in_cooldown_returns_earliest(self):
        fake_now = [100.0]
        pool = KeyPool(["a", "b"], cooldown_seconds=60.0, now=lambda: fake_now[0])
        pool.mark_failed("a")
        pool.mark_failed("b")
        assert pool.available_count() == 0
        assert pool.next() == "a"  # 全部冷却 -> 尽力返回最早到期者

    def test_mark_success_clears_cooldown(self):
        fake_now = [100.0]
        pool = KeyPool(["a", "b"], cooldown_seconds=60.0, now=lambda: fake_now[0])
        pool.mark_failed("a")
        pool.mark_success("a")
        assert pool.available_count() == 2

    def test_status_shape(self):
        fake_now = [100.0]
        pool = KeyPool(["a"], cooldown_seconds=60.0, now=lambda: fake_now[0])
        st = pool.status()
        assert st[0]["state"] == "ok"
        pool.mark_failed("a")
        st = pool.status()
        assert st[0]["state"] == "cooldown"
        assert st[0]["cooldown_seconds_left"] == 60.0
        assert st[0]["key_hash"] == key_hash("a")

    def test_empty_pool(self):
        pool = KeyPool([])
        assert len(pool) == 0
        assert pool.next() is None
        assert pool.available_count() == 0
        assert pool.status() == []


# ---------- TraceStore 单元 ----------


class TestTraceStore:
    def test_put_get(self):
        s = TraceStore(maxlen=2)
        s.put("r1", {"a": 1})
        assert s.get("r1") == {"a": 1}
        assert s.get("missing") is None

    def test_overflow_evicts_oldest(self):
        s = TraceStore(maxlen=2)
        s.put("r1", {"n": 1})
        s.put("r2", {"n": 2})
        s.put("r3", {"n": 3})
        assert s.get("r1") is None
        assert s.get("r2") == {"n": 2}
        assert s.get("r3") == {"n": 3}
        assert len(s) == 2

    def test_put_updates_moves_to_end(self):
        s = TraceStore(maxlen=2)
        s.put("r1", {"n": 1})
        s.put("r2", {"n": 2})
        s.put("r1", {"n": 11})  # 重放更新, 不淘汰
        assert len(s) == 2
        assert s.get("r1") == {"n": 11}
        assert s.get("r2") == {"n": 2}


class TestFormatTraceSummary:
    def test_full_fields(self):
        s = format_trace_summary(
            {
                "cache_hit": False,
                "upstream_status": 200,
                "duration_ms": 42,
                "used_key": "abc123",
                "retries": 2,
                "circuit_open": False,
            }
        )
        assert s == "cache=miss upstream=200 42ms key=abc123 retries=2"

    def test_cache_hit_minimal(self):
        s = format_trace_summary({"cache_hit": True, "used_key": None})
        assert s == "cache=hit"

    def test_circuit_open_flag(self):
        s = format_trace_summary({"cache_hit": False, "circuit_open": True})
        assert s == "cache=miss circuit=open"


# ---------- 阶段 1.1 多 Key 池 failover ----------


class TestKeyFailover:
    @pytest.mark.asyncio
    async def test_403_switches_to_next_key(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "bad-key-1,good-key-2")
        monkeypatch.setattr(cfg.settings, "KEY_FAILOVER_COOLDOWN_SECONDS", 0)
        p = _mk_provider()
        p.client.post.side_effect = [_resp(403), _resp(200, "你好")]
        before = _metric_value(metrics.render().decode(), "translate_key_switches_total")
        out = await p._translate("hi", "auto", "zh-CN")
        after = _metric_value(metrics.render().decode(), "translate_key_switches_total")
        assert "你好" in out
        assert p.client.post.call_count == 2
        assert after == before + 1
        # 请求头确实切到第二个 Key
        headers0 = p.client.post.call_args_list[0].kwargs["headers"]
        headers1 = p.client.post.call_args_list[1].kwargs["headers"]
        assert headers0["x-goog-api-key"] == "bad-key-1"
        assert headers1["x-goog-api-key"] == "good-key-2"
        # Key 维度请求计数: 成功记到 good-key-2
        text = metrics.render().decode()
        assert (
            _metric_value(
                text,
                "translate_requests_by_key_hash_total",
                key=key_hash("good-key-2"),
                result="ok",
            )
            == 1.0
        )
        # Key 维度错误计数: bad-key-1 记 403
        assert (
            _metric_value(
                text,
                "translate_upstream_errors_by_key_hash_total",
                key=key_hash("bad-key-1"),
                code="403",
            )
            == 1.0
        )

    @pytest.mark.asyncio
    async def test_all_keys_fail_raises_and_metrics(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "bad-1,bad-2")
        monkeypatch.setattr(cfg.settings, "KEY_FAILOVER_COOLDOWN_SECONDS", 0)
        p = _mk_provider()
        p.client.post.return_value = _resp(403)
        with pytest.raises(httpx.HTTPStatusError) as ei:
            await p._translate("hi", "auto", "zh-CN")
        assert ei.value.response.status_code == 403
        assert p.client.post.call_count == 2  # 每个 Key 各试一次
        text = metrics.render().decode()
        assert (
            _metric_value(
                text,
                "translate_upstream_errors_by_key_hash_total",
                key=key_hash("bad-1"),
                code="403",
            )
            == 1.0
        )
        assert (
            _metric_value(
                text,
                "translate_requests_by_key_hash_total",
                key=key_hash("bad-2"),
                result="error",
            )
            == 1.0
        )

    @pytest.mark.asyncio
    async def test_400_invalid_key_switches_to_next_key(self, monkeypatch):
        # 真实上游对无效 key 返回 400 (厂商语义, 实测), 必须换 Key
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "bad400-1,good-400-2")
        monkeypatch.setattr(cfg.settings, "KEY_FAILOVER_COOLDOWN_SECONDS", 0)
        p = _mk_provider()
        p.client.post.side_effect = [_resp(400, "API key not valid"), _resp(200, "你好")]
        out = await p._translate("hi", "auto", "zh-CN")
        assert "你好" in out
        assert p.client.post.call_count == 2
        text = metrics.render().decode()
        assert (
            _metric_value(
                text,
                "translate_upstream_errors_by_key_hash_total",
                key=key_hash("bad400-1"),
                code="400",
            )
            == 1.0
        )

    @pytest.mark.asyncio
    async def test_transport_failover_switches_key(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "bad-net-1,good-2")
        monkeypatch.setattr(cfg.settings, "KEY_FAILOVER_COOLDOWN_SECONDS", 0)
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_ATTEMPTS", 1)
        p = _mk_provider()
        p.client.post.side_effect = [httpx.ConnectError("boom"), _resp(200, "你好")]
        out = await p._translate("hi", "auto", "zh-CN")
        assert "你好" in out
        assert p.client.post.call_count == 2
        text = metrics.render().decode()
        assert (
            _metric_value(
                text,
                "translate_upstream_errors_by_key_hash_total",
                key=key_hash("bad-net-1"),
                code="transport",
            )
            == 1.0
        )

    @pytest.mark.asyncio
    async def test_key_pool_gauge_after_failover(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "bad-1,good-2")
        monkeypatch.setattr(cfg.settings, "KEY_FAILOVER_COOLDOWN_SECONDS", 60)
        p = _mk_provider()
        p.client.post.side_effect = [_resp(403), _resp(200, "你好")]
        await p._translate("hi", "auto", "zh-CN")
        text = metrics.render().decode()
        # good-2 可用; bad-1 冷却
        assert (
            _metric_value(
                text,
                "translate_key_pool_status",
                key=key_hash("good-2"),
                state="ok",
            )
            == 1.0
        )
        assert (
            _metric_value(
                text,
                "translate_key_pool_status",
                key=key_hash("bad-1"),
                state="cooldown",
            )
            == 1.0
        )

    @pytest.mark.asyncio
    async def test_5xx_non_failover_raises_directly(self, monkeypatch):
        # 5xx 不属于换 Key 集合: 重试耗尽后直接抛 HTTPStatusError (维持既有 5xx 语义)
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "k-5xx")
        monkeypatch.setattr(cfg.settings, "UPSTREAM_RETRY_ATTEMPTS", 1)
        p = _mk_provider()
        p.client.post.return_value = _resp(500)
        with pytest.raises(httpx.HTTPStatusError) as ei:
            await p._translate("hi", "auto", "zh-CN")
        assert ei.value.response.status_code == 500
        assert p.client.post.call_count == 1
        text = metrics.render().decode()
        assert (
            _metric_value(
                text,
                "translate_upstream_errors_by_key_hash_total",
                key=key_hash("k-5xx"),
                code="500",
            )
            == 1.0
        )

    @pytest.mark.asyncio
    async def test_lazy_pool_creation_single_key(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "only-key")
        p = _mk_provider()
        assert p.key_pool is None
        p.client.post.return_value = _resp(200, "你好")
        out = await p._translate("hi", "auto", "zh-CN")
        assert "你好" in out
        assert p.key_pool is not None and len(p.key_pool) == 1
        assert p.client.post.call_count == 1

    def test_sync_key_pool_metrics_noop_when_none(self):
        p = GoogleTranslateProvider()
        assert p.key_pool is None
        p._sync_key_pool_metrics()  # 无池时 no-op, 不抛错


# ---------- 配置与初始化 ----------


class TestEffectiveKeys:
    def test_prefers_pool_and_falls_back(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "a, b ,c")
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEY", "legacy")
        p = GoogleTranslateProvider()
        assert p._effective_keys() == ["a", "b", "c"]
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", None)
        assert p._effective_keys() == ["legacy"]
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", " , ")
        assert p._effective_keys() == ["legacy"]  # 空池回退单 Key

    @pytest.mark.asyncio
    async def test_initialize_builds_pool(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "k1,k2")
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEY", None)
        p = GoogleTranslateProvider()
        await p.initialize()
        assert p.key_pool is not None and len(p.key_pool) == 2
        await p.close()

    @pytest.mark.asyncio
    async def test_initialize_rejects_placeholder_in_pool(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "在这里填入你的谷歌翻译 API Key")
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEY", None)
        p = GoogleTranslateProvider()
        with pytest.raises(ValueError):
            await p.initialize()


# ---------- 阶段 1.2 链路摘要 ----------


class TestTraceIntegration:
    @pytest.mark.asyncio
    async def test_nonstream_trace_header(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "single-key")
        p = _mk_provider()
        p.client.post.return_value = _resp(200, "你好")
        resp = await p.chat_completion(
            {"messages": [{"role": "user", "content": "hi"}], "stream": False}
        )
        assert resp.status_code == 200
        summary = resp.headers.get("X-Trace-Summary", "")
        assert summary.startswith("cache=miss")
        assert "upstream=200" in summary
        assert "key=" in summary and "ms" in summary

    @pytest.mark.asyncio
    async def test_stream_trace_id_and_store(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "single-key")
        p = _mk_provider()
        p.client.post.return_value = _resp(200, "你好")
        resp = await p.chat_completion(
            {"messages": [{"role": "user", "content": "hi"}], "stream": True}
        )
        tid = resp.headers.get("X-Trace-Id")
        assert tid and tid.startswith("chatcmpl-")
        body = b"".join([chunk async for chunk in resp.body_iterator])
        assert b"[DONE]" in body
        rec = p.trace_store.get(tid)
        assert rec is not None
        assert rec["result"] == "success"
        assert rec["upstream_status"] == 200
        assert rec["used_key"] == key_hash("single-key")

    @pytest.mark.asyncio
    async def test_trace_cache_hit_flag(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "single-key")
        p = _mk_provider()
        p.client.post.return_value = _resp(200, "你好")
        trace1: dict = {}
        await p._translate("hello", "auto", "zh-CN", trace=trace1)
        trace2: dict = {}
        await p._translate("hello", "auto", "zh-CN", trace=trace2)
        assert trace1["cache_hit"] is False
        assert trace2["cache_hit"] is True
        assert trace2.get("used_key") is None  # 缓存命中不打上游, 无 Key

    @pytest.mark.asyncio
    async def test_traces_endpoint_get_and_404(self, monkeypatch):
        monkeypatch.setenv("API_MASTER_KEY", "1")  # 关闭认证
        import main as m

        m.provider.trace_store.put("trace-abc", {"request_id": "trace-abc", "result": "success"})
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=m.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/v1/traces/trace-abc")
            assert r.status_code == 200
            assert r.json()["result"] == "success"
            r2 = await c.get("/v1/traces/nope")
            assert r2.status_code == 404


# ---------- 覆盖率补齐: keys 属性 / 未知 key no-op / NullMetric.set ----------


class TestKeyPoolExtra:
    def test_keys_property_and_unknown_marks(self):
        pool = KeyPool(["a", "b"])
        assert pool.keys == ["a", "b"]
        pool.mark_failed("nope")  # 未知 key no-op
        pool.mark_success("nope")
        assert pool.available_count() == 2


def test_null_metric_set_noop(monkeypatch):
    monkeypatch.setattr(cfg.settings, "METRICS_ENABLED", False)
    m = Metrics()
    m.key_pool_status.labels(key="x", state="ok").set(1)
    m.requests_by_key.labels(key="x", result="ok").inc()
    assert m.render() == b"# metrics disabled\n"


# ---------- 覆盖率补齐: 流式缓存命中 trace / 冷却期复用 Key 的 break ----------


class TestCoverageGaps:
    @pytest.mark.asyncio
    async def test_stream_translate_cache_hit_trace(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "single-key")
        p = _mk_provider()
        p.client.post.return_value = _resp(200, "你好")
        t1: dict = {}
        await p._stream_translate("hi", "auto", "zh-CN", trace=t1)
        t2: dict = {}
        await p._stream_translate("hi", "auto", "zh-CN", trace=t2)
        assert t1["cache_hit"] is False
        assert t2["cache_hit"] is True

    @pytest.mark.asyncio
    async def test_empty_pool_breaks_loop(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", None)
        monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEY", None)
        p = _mk_provider()
        with pytest.raises(RuntimeError):
            await p._translate("hi", "auto", "zh-CN")
        assert p.client.post.call_count == 0  # 空池: 无 Key 可配 -> break
