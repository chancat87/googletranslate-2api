"""将 Google Translate 的 translateHtml 上游适配为 OpenAI Chat Completions 兼容 API。

包含 (v1.2.0 新增):
- M3  上游重试: 指数退避 + 抖动 (仅网络异常 / 429 / 5xx)
- M4  熔断器: 滑动窗口, 上游持续故障时快速失败
- M5  批量翻译整体 deadline, 超时条目标记 error=timeout
- M8  stream_options.include_usage 支持
- M9  模型别名 MODEL_ALIASES
- M10 流式请求取消/结束时资源释放 (try/finally + 传播 CancelledError/GeneratorExit)
- M12 Prometheus 指标埋点 (请求 / 上游错误 / 缓存命中)
- M16 /v1/translate/detect 轻量语言推断
- M17 长文本分段 (段落优先, 单段落回退到句子) 渐进流
"""

import asyncio
import random
import re
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from markdownify import markdownify as md

from app.core.cache import cache_get, cache_key, cache_put, make_cache
from app.core.circuit_breaker import CircuitBreaker
from app.core.config import settings
from app.core.key_pool import KeyPool, key_hash
from app.core.languages import auto_detect_target, is_supported
from app.core.metrics import metrics
from app.core.trace import TraceStore, format_trace_summary
from app.providers.base_provider import BaseProvider
from app.utils.sse_utils import (
    DONE_CHUNK,
    create_chat_completion,
    create_chat_completion_chunk,
    create_chat_completion_usage_chunk,
    create_sse_data,
)

# 句子切分: 保留标点 (M17 退路)
_SENT_SPLIT_RE = re.compile(r"(?<=[。!?\.!?])\s*")
# 段落切分: 空行分隔 (M17 优先, 跨段上下文损失小于按句切分)
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")

_RETRYABLE_STATUS = (429, 500, 502, 503, 504)

# 阶段 1.1: 凭证/配额类错误 -> 换 Key 重试。
# 真实上游 (translate-pa) 对无效 key 返回 400 "API key not valid" (实测 2026-09-21),
# 其余 401 未认证 / 403 无效 / 429 配额。
_KEY_FAILOVER_STATUS = (400, 401, 403, 429)

# P3-5: 可进入 SSE 内容的白名单 detail (其余统一为通用文案, 防未来误带上游/用户文本)
_SSE_SAFE_DETAILS = frozenset({"翻译服务暂时不可用"})
_TRANSPORT_ERRORS = (httpx.TransportError, httpx.TimeoutException)


class GoogleTranslateProvider(BaseProvider):
    """将 Google Translate 翻译接口适配为 OpenAI Chat Completions 流式响应。"""

    BASE_URL = "https://translate-pa.googleapis.com/v1/translateHtml"

    def __init__(self):
        self.client: httpx.AsyncClient | None = None
        self.cache = make_cache()
        self.circuit_breaker: CircuitBreaker | None = None
        # 阶段 1.1: 多 Key 池 (initialize 时创建; _translate 惰性兜底)
        self.key_pool: KeyPool | None = None
        # 阶段 1.2: 链路摘要环形缓冲 (只存元数据, 不含原文与明文 Key)
        self.trace_store = TraceStore(settings.TRACE_STORE_MAXLEN)
        if settings.CIRCUIT_BREAKER_ENABLED:
            self.circuit_breaker = CircuitBreaker(
                failure_threshold=settings.CIRCUIT_FAILURE_THRESHOLD,
                window_seconds=settings.CIRCUIT_WINDOW_SECONDS,
                open_seconds=settings.CIRCUIT_OPEN_SECONDS,
            )

    async def initialize(self):
        keys = self._effective_keys()
        if not keys:
            raise ValueError("GOOGLE_API_KEY / GOOGLE_API_KEYS 未在 .env 文件中配置。")
        if any("在这里填入" in k for k in keys):
            raise ValueError("GOOGLE_API_KEY 仍是示例占位符, 请填入真实 Key 后启动。")
        # 3.D.5 / v1.5.1: 显式连接池限制; HTTPX_MAX_CONNECTIONS=0 时自动按批量并发推导
        pool_conns = max(0, settings.HTTPX_MAX_CONNECTIONS) or max(
            10, settings.BATCH_MAX_CONCURRENCY + 5
        )
        pool_keepalive = max(0, settings.HTTPX_MAX_KEEPALIVE_CONNECTIONS) or max(
            5, settings.BATCH_MAX_CONCURRENCY
        )
        self.client = httpx.AsyncClient(
            timeout=settings.API_REQUEST_TIMEOUT,
            limits=httpx.Limits(
                max_connections=pool_conns,
                max_keepalive_connections=pool_keepalive,
            ),
        )
        # 每次初始化重建缓存, 避免跨测试/重启的脏数据
        self.cache = make_cache()
        self.key_pool = KeyPool(keys, cooldown_seconds=settings.KEY_FAILOVER_COOLDOWN_SECONDS)
        self.reset_health()

    async def close(self):
        if self.client:
            await self.client.aclose()

    def reset_health(self):
        """复位熔断器 (测试隔离 / 配置变更后用)。"""
        if self.circuit_breaker:
            self.circuit_breaker.record_success()

    def _effective_keys(self) -> list[str]:
        """解析 GOOGLE_API_KEYS (逗号分隔池); 未设置时回退 GOOGLE_API_KEY (向后兼容)。"""
        pool_raw = (settings.GOOGLE_API_KEYS or "").strip()
        if pool_raw:
            keys = [k.strip() for k in pool_raw.split(",") if k.strip()]
            if keys:
                return keys
        # 池为空/只含分隔符时回退单 Key (向后兼容)
        single = (settings.GOOGLE_API_KEY or "").strip()
        return [single] if single else []

    # --- 主流程: 校验 -> 熔断检查 -> 翻译 -> 按 stream 决定流式 / 非流式 ---
    async def chat_completion(self, request_data: dict[str, Any]):
        text_to_translate, source_lang, target_lang = self._validate_and_extract(request_data)
        model_name = self._resolve_model(request_data.get("model") or settings.DEFAULT_MODEL)
        stream = bool(request_data.get("stream", True))

        if self.circuit_breaker and not self.circuit_breaker.allow():
            logger.warning("熔断器打开, 快速失败")
            raise HTTPException(status_code=503, detail="翻译服务暂时不可用")

        metrics.translate_requests.labels(stream=str(stream).lower(), result="started").inc()

        include_usage = self._get_include_usage(request_data)
        if stream:
            return self._stream_response(
                text_to_translate, source_lang, target_lang, model_name, include_usage=include_usage
            )
        return await self._non_stream_response(
            text_to_translate, source_lang, target_lang, model_name
        )

    # --- 非流式: 单次完整 JSON (OpenAI chat.completion 格式) ---
    async def _non_stream_response(
        self, text: str, source_lang: str, target_lang: str, model_name: str
    ) -> JSONResponse:
        # 阶段 1.2: 链路摘要 (非流式走 X-Trace-Summary 头 + 环形缓冲)
        request_id = f"chatcmpl-{uuid.uuid4()}"
        trace = self._new_trace(request_id)
        started = time.perf_counter()
        try:
            markdown_text = await self._translate(text, source_lang, target_lang, trace=trace)
            completion = create_chat_completion(request_id, model_name, markdown_text, text)
            self._store_trace(trace, started, "success")
            response = JSONResponse(content=completion)
            response.headers["X-Trace-Summary"] = format_trace_summary(trace)
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                # P2-4: 403 是永久性凭证错误, 用独立语义暴露, 便于监控区分
                logger.error("上游返回 403: GOOGLE_API_KEY 无效或已失效")
                self._store_trace(trace, started, "error", error="upstream_auth_error")
                return JSONResponse(
                    status_code=502,
                    content={
                        "error": {
                            "message": "上游 API Key 无效或已失效",
                            "type": "upstream_auth_error",
                        }
                    },
                    headers={"X-Trace-Summary": format_trace_summary(trace)},
                )
            logger.error(f"上游返回非 200 (src={source_lang} tgt={target_lang})")
            self._store_trace(trace, started, "error", error="upstream_error")
            return JSONResponse(
                status_code=502,
                content={"error": {"message": "翻译服务暂时不可用", "type": "upstream_error"}},
                headers={"X-Trace-Summary": format_trace_summary(trace)},
            )
        except _TRANSPORT_ERRORS:
            logger.error(f"上游网络错误 (src={source_lang} tgt={target_lang})")
            self._store_trace(trace, started, "error", error="upstream_network")
            return JSONResponse(
                status_code=502,
                content={"error": {"message": "翻译服务网络异常", "type": "upstream_error"}},
                headers={"X-Trace-Summary": format_trace_summary(trace)},
            )
        except HTTPException:
            self._store_trace(trace, started, "error", error="http_exception")
            raise
        except Exception:
            logger.exception("处理翻译请求时发生错误")
            self._store_trace(trace, started, "error", error="internal_error")
            return JSONResponse(
                status_code=500,
                content={"error": {"message": "内部服务器错误", "type": "internal_error"}},
                headers={"X-Trace-Summary": format_trace_summary(trace)},
            )

    def _stream_response(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        model_name: str,
        include_usage: bool = False,
    ) -> StreamingResponse:
        # 阶段 1.2: request_id 在函数级生成, 供 X-Trace-Id 响应头与链路摘要查询
        request_id = f"chatcmpl-{uuid.uuid4()}"
        trace = self._new_trace(request_id)
        started = time.perf_counter()

        async def stream_generator() -> AsyncGenerator[bytes, None]:
            try:
                chunks_to_send = await self._stream_translate(
                    text, source_lang, target_lang, trace=trace
                )
                joined = "".join(chunks_to_send)
                for piece in chunks_to_send:
                    chunk = create_chat_completion_chunk(request_id, model_name, piece)
                    yield create_sse_data(chunk)
                final_chunk = create_chat_completion_chunk(request_id, model_name, "", "stop")
                yield create_sse_data(final_chunk)
                if include_usage:
                    yield create_sse_data(
                        create_chat_completion_usage_chunk(request_id, model_name, text, joined)
                    )
                yield DONE_CHUNK
                self._store_trace(trace, started, "success")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    logger.error("上游返回 403: GOOGLE_API_KEY 无效或已失效")
                    err_text = "上游 API Key 无效或已失效"
                    self._store_trace(trace, started, "error", error="upstream_auth_error")
                else:
                    logger.error(f"上游返回非 200 (src={source_lang} tgt={target_lang})")
                    err_text = "翻译服务暂时不可用"
                    self._store_trace(trace, started, "error", error="upstream_error")
                error_chunk = create_chat_completion_chunk(request_id, model_name, err_text, "stop")
                yield create_sse_data(error_chunk)
                yield DONE_CHUNK
            except HTTPException as exc:
                logger.warning(f"流式请求被 HTTP 异常中断: {exc.detail}")
                detail = str(exc.detail)
                if detail not in _SSE_SAFE_DETAILS:
                    detail = "请求处理失败"  # P3-5: 非白名单 detail 一律通用化, 不进 SSE
                error_chunk = create_chat_completion_chunk(request_id, model_name, detail, "stop")
                yield create_sse_data(error_chunk)
                yield DONE_CHUNK
                self._store_trace(trace, started, "error", error="http_exception")
            except _TRANSPORT_ERRORS:
                logger.error(f"上游网络错误 (src={source_lang} tgt={target_lang})")
                error_chunk = create_chat_completion_chunk(
                    request_id, model_name, "翻译服务网络异常", "stop"
                )
                yield create_sse_data(error_chunk)
                yield DONE_CHUNK
                self._store_trace(trace, started, "error", error="upstream_network")
            except Exception:
                logger.exception("处理翻译请求时发生错误")
                error_chunk = create_chat_completion_chunk(
                    request_id, model_name, "内部服务器错误", "stop"
                )
                yield create_sse_data(error_chunk)
                yield DONE_CHUNK
                self._store_trace(trace, started, "error", error="internal_error")
            finally:
                # M10: 流结束 / 客户端断开 (GeneratorExit/CancelledError 走 BaseException,
                # 不会被子类 except Exception 吞掉) 时, 在此释放上下文并留日志。
                logger.debug(f"stream closed (request_id={request_id})")

        response = StreamingResponse(stream_generator(), media_type="text/event-stream")
        response.headers["X-Trace-Id"] = request_id
        return response

    @staticmethod
    def _get_include_usage(request_data: dict[str, Any]) -> bool:
        """解析 OpenAI stream_options.include_usage (M8)。"""
        options = request_data.get("stream_options")
        if isinstance(options, dict):
            return bool(options.get("include_usage"))
        return False

    @staticmethod
    def _resolve_model(name: str) -> str:
        """模型别名解析 (M9): MODEL_ALIASES.get(name, name)。"""
        if not name:
            return settings.DEFAULT_MODEL
        return settings.MODEL_ALIASES.get(name, name)

    # --- 翻译分发: 缓存命中直接返回; 长文本可选分段 (P1.1 + P1.2 + M17) ---
    async def _stream_translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        trace: dict[str, Any] | None = None,
    ) -> list[str]:
        text = text.strip()  # 3.C.3: 仅 strip 首尾空白, 归一化缓存 key
        key = cache_key(text, source_lang, target_lang)
        cached = cache_get(self.cache, key)
        if cached is not None:
            logger.debug("cache hit")
            metrics.cache_hits.inc()
            if trace is not None:
                trace["cache_hit"] = True
            return [cached]

        metrics.cache_misses.inc()
        if trace is not None:
            trace["cache_hit"] = False
        # 默认整段翻译; 长文本且开启分段时分批
        if settings.STREAM_CHUNK_ENABLED and len(text) > settings.STREAM_CHUNK_THRESHOLD:
            return await self._translate_batched(text, source_lang, target_lang, trace=trace)
        whole = await self._translate(text, source_lang, target_lang, trace=trace)
        return [whole] if whole else []

    async def _translate_batched(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        trace: dict[str, Any] | None = None,
    ) -> list[str]:
        """按段切分, 逐批翻译; 失败的批次以空串占位, 不中断整体。

        M17: 优先按空行切段 (保留段落语义); 单段文本回退为按句切分。
        切段会丢失跨段上下文, 默认关闭 (STREAM_CHUNK_ENABLED=False)。
        """
        segments = self._split_for_chunks(text)
        results: list[str] = []
        for seg in segments:
            try:
                out = await self._translate(seg, source_lang, target_lang, trace=trace)
                results.append(out or "")
            except Exception:
                logger.warning("批次翻译失败, 跳过该段")
                results.append("")
        return results

    @staticmethod
    def _split_for_chunks(text: str) -> list[str]:
        """M17: 段落优先; 无段落分隔时回退到句子切分。"""
        paragraphs = [p for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
        if len(paragraphs) > 1:
            return paragraphs
        return [s for s in _SENT_SPLIT_RE.split(text) if s.strip()]

    # --- 调用上游并清理结果 (共享给流式 / 非流式 / 批量) ---
    async def _translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        record_health: bool = True,
        trace: dict[str, Any] | None = None,
    ) -> str:
        text = text.strip()  # 3.C.3: 仅 strip 首尾空白, 归一化缓存 key
        key = cache_key(text, source_lang, target_lang)
        cached = cache_get(self.cache, key)
        if cached is not None:
            logger.debug("cache hit")
            metrics.cache_hits.inc()
            if trace is not None:
                trace["cache_hit"] = True
            return cached
        metrics.cache_misses.inc()
        if trace is not None:
            trace["cache_hit"] = False

        if self.circuit_breaker and not self.circuit_breaker.allow():
            raise HTTPException(status_code=503, detail="翻译服务暂时不可用")

        # 阶段 1.1: 多 Key 池 — 403/429/transport 自动切换到下一 Key, 全部耗尽才失败
        if self.key_pool is None:
            self.key_pool = KeyPool(
                self._effective_keys(),
                cooldown_seconds=settings.KEY_FAILOVER_COOLDOWN_SECONDS,
            )
        pool = self.key_pool
        payload = self._prepare_payload(text, source_lang, target_lang)
        last_resp: httpx.Response | None = None
        last_transport: BaseException | None = None
        used_keys: list[str] = []
        for _ in range(max(1, len(pool))):
            gk = pool.next()
            if gk is None or gk in used_keys:
                break
            used_keys.append(gk)
            if len(used_keys) > 1:
                metrics.key_switches.inc()
            logger.info(
                f"向上游发送翻译请求: src={source_lang} tgt={target_lang} key={key_hash(gk)}"
            )
            headers = self._prepare_headers(gk)
            try:
                response = await self._post_with_retry(headers, payload, trace=trace)
            except _TRANSPORT_ERRORS as exc:
                last_transport = exc
                pool.mark_failed(gk)
                metrics.errors_by_key.labels(key=key_hash(gk), code="transport").inc()
                if record_health:
                    self._record_upstream_failure("transport")
                continue
            if response.status_code in _KEY_FAILOVER_STATUS:
                # Key 凭证/配额失效: 标记失败并切换到下一 Key
                pool.mark_failed(gk)
                metrics.errors_by_key.labels(key=key_hash(gk), code=str(response.status_code)).inc()
                if record_health:
                    self._record_upstream_failure(str(response.status_code))
                last_resp = response
                continue
            if response.status_code != 200:
                if record_health:
                    self._record_upstream_failure(str(response.status_code))
                metrics.errors_by_key.labels(key=key_hash(gk), code=str(response.status_code)).inc()
                self._log_upstream_error(response, response.status_code)
                raise httpx.HTTPStatusError(
                    f"上游状态码 {response.status_code}",
                    request=response.request,
                    response=response,
                )
            if record_health and self.circuit_breaker:
                self.circuit_breaker.record_success()
            pool.mark_success(gk)
            if trace is not None:
                trace["used_key"] = key_hash(gk)
                trace["upstream_status"] = response.status_code
            markdown_text = self._clean_response(response.json())
            if not markdown_text:
                logger.warning("上游返回空翻译结果")
            else:
                cache_put(self.cache, key, markdown_text)
            metrics.requests_by_key.labels(key=key_hash(gk), result="ok").inc()
            self._sync_key_pool_metrics()
            return markdown_text

        # 全部 Key 失败: 保留最后一次响应语义, 否则抛最后一个网络错误
        if trace is not None:
            trace["used_key"] = key_hash(used_keys[-1]) if used_keys else None
            trace["upstream_status"] = last_resp.status_code if last_resp is not None else None
        if used_keys:
            metrics.requests_by_key.labels(key=key_hash(used_keys[-1]), result="error").inc()
        self._sync_key_pool_metrics()
        if last_resp is not None:
            self._log_upstream_error(last_resp, last_resp.status_code)
            raise httpx.HTTPStatusError(
                f"上游状态码 {last_resp.status_code}", request=last_resp.request, response=last_resp
            )
        if last_transport is not None:
            raise last_transport
        raise RuntimeError("没有可用的上游 Key")  # pragma: no cover - 防御性

    def _record_upstream_failure(self, code: str) -> None:
        """记录上游失败: 指标 + 告警日志 + 熔断计数 (仅 429/5xx/transport 计入熔断)。"""
        metrics.upstream_errors.labels(code=code).inc()
        if code == "403":
            logger.error("上游返回 403: GOOGLE_API_KEY 无效或已失效, 请检查并轮换 key")
        elif code == "429":
            logger.warning("上游返回 429: 触发 Google 频率限制, 已进入退避重试")
        elif code == "transport":
            logger.error("上游网络错误 (连接/超时)")
        else:
            logger.warning(f"上游返回非预期状态 {code}")
        if self.circuit_breaker is None:
            return
        if code == "transport" or code in ("429", "500", "502", "503", "504"):
            self.circuit_breaker.record_failure()

    async def _post_with_retry(
        self, headers: dict[str, str], payload: Any, trace: dict[str, Any] | None = None
    ) -> httpx.Response:
        """M3: 指数退避 + 抖动重试。

        仅对网络异常 / 429 / 5xx 重试; 4xx (400/401/403) 不重试。
        """
        attempts = max(1, settings.UPSTREAM_RETRY_ATTEMPTS)
        base = max(0.0, settings.UPSTREAM_RETRY_BACKOFF_BASE)
        jitter = max(0.0, settings.UPSTREAM_RETRY_JITTER)
        max_backoff = max(0.0, settings.UPSTREAM_RETRY_MAX_BACKOFF)

        assert self.client is not None, "provider 未初始化"
        retries = 0
        for n in range(attempts):
            if n > 0:
                retries += 1
                backoff = min(base * (2 ** (n - 1)), max_backoff) + random.uniform(0, jitter)
                # 3.D.1 验收: 重试计数入日志, 便于观测瞬时故障
                logger.warning(f"上游重试第 {n + 1}/{attempts} 次, 退避 {backoff:.2f}s")
                await asyncio.sleep(backoff)
            try:
                resp = await self.client.post(self.BASE_URL, headers=headers, json=payload)
            except _TRANSPORT_ERRORS:
                if trace is not None:
                    trace["retries"] = retries
                if n >= attempts - 1:
                    raise
                continue
            if resp.status_code in _RETRYABLE_STATUS and n < attempts - 1:
                continue
            if trace is not None:
                trace["retries"] = retries
            return resp
        raise httpx.TransportError("upstream unreachable")  # pragma: no cover - 防御性

    async def translate_batch(
        self, texts: list[str], source_lang: str, target_lang: str
    ) -> list[dict[str, Any]]:
        sem = asyncio.Semaphore(max(1, settings.BATCH_MAX_CONCURRENCY))
        budget = max(1, settings.BATCH_DEADLINE_SECONDS)
        deadline = asyncio.get_event_loop().time() + budget

        async def _one(t: str) -> dict[str, Any]:
            async with sem:
                try:
                    out = await self._translate(t, source_lang, target_lang)
                    return {"text": t, "translated": out, "ok": True, "error": None}
                except Exception as exc:
                    logger.warning("批量翻译单条失败 (已计入指标)")
                    return {
                        "text": t,
                        "translated": "",
                        "ok": False,
                        "error": self._brief_error(exc),
                    }

        tasks = [asyncio.ensure_future(_one(t)) for t in texts]
        results: list[dict[str, Any]] = []
        loop = asyncio.get_event_loop()
        for i, task in enumerate(tasks):
            remaining = deadline - loop.time()
            if remaining <= 0:
                if task.done():
                    results.append(task.result())
                else:
                    task.cancel()
                    results.append(
                        {"text": texts[i], "translated": "", "ok": False, "error": "timeout"}
                    )
                continue
            try:
                results.append(await asyncio.wait_for(asyncio.shield(task), timeout=remaining))
            except asyncio.TimeoutError:
                task.cancel()
                results.append(
                    {"text": texts[i], "translated": "", "ok": False, "error": "timeout"}
                )
        return results

    @staticmethod
    def _brief_error(exc: Exception) -> str:
        """把单条失败压缩为简短可读错误 (不回传敏感细节)。"""
        if isinstance(exc, httpx.HTTPStatusError):
            return f"upstream_{exc.response.status_code}"
        if isinstance(exc, _TRANSPORT_ERRORS):
            return "upstream_network"
        detail = getattr(exc, "detail", None)
        if isinstance(detail, str):
            return detail[:80]
        return type(exc).__name__

    def _new_trace(self, request_id: str) -> dict[str, Any]:
        """阶段 1.2: 初始化链路摘要记录 (只存元数据, 不含原文与明文 Key)。"""
        return {
            "request_id": request_id,
            "cache_hit": None,
            "used_key": None,
            "upstream_status": None,
            "retries": 0,
            "circuit_open": bool(self.circuit_breaker and not self.circuit_breaker.allow()),
            "result": None,
            "error": None,
            "created_at": time.time(),
        }

    def _store_trace(
        self,
        trace: dict[str, Any],
        started: float,
        result: str,
        error: str | None = None,
    ) -> None:
        """阶段 1.2: 补全耗时/结果并写入环形缓冲。"""
        trace["result"] = result
        if error is not None:
            trace["error"] = error
        trace["duration_ms"] = int((time.perf_counter() - started) * 1000)
        self.trace_store.put(trace["request_id"], trace)

    def _sync_key_pool_metrics(self) -> None:
        """阶段 2.1: 各 Key 可用/冷却状态同步到 /metrics (只暴露摘要)。"""
        if self.key_pool is None:
            return
        for item in self.key_pool.status():
            for state in ("ok", "cooldown"):
                metrics.key_pool_status.labels(key=item["key_hash"], state=state).set(
                    1 if item["state"] == state else 0
                )

    # --- 校验与参数提取 (在进入流之前失败, 保证 HTTP 状态码语义正确) ---
    def _validate_and_extract(self, request_data: dict[str, Any]) -> tuple[str, str, str]:
        messages = request_data.get("messages")
        if not isinstance(messages, list) or not messages:
            raise HTTPException(status_code=400, detail="请求体缺少 messages 字段或格式不正确。")
        last = messages[-1]
        if not isinstance(last, dict) or last.get("role") != "user":
            raise HTTPException(
                status_code=400, detail="messages 最后一条必须为 role=user 的用户消息。"
            )

        # content 支持 str 和 OpenAI 多段格式 (List[{"type":"text","text":"..."}])
        text_to_translate = self._extract_text(last.get("content"))
        if not text_to_translate:
            raise HTTPException(status_code=400, detail="用户消息内容不能为空。")

        # P1.6: 输入长度上限, 防止打爆上游
        if len(text_to_translate) > settings.MAX_TEXT_LENGTH:
            raise HTTPException(
                status_code=413,
                detail=f"文本长度超限: {len(text_to_translate)} > {settings.MAX_TEXT_LENGTH}",
            )

        # source_lang: 默认 auto, 显式指定则透传
        source_lang = request_data.get("source_lang") or "auto"
        if source_lang != "auto" and not is_supported(source_lang):
            raise HTTPException(
                status_code=400, detail=f"不支持的语言代码: source_lang={source_lang}"
            )

        # target_lang: 显式指定优先, 否则按文本自动检测
        target_lang = request_data.get("target_lang")
        if target_lang:
            if not is_supported(target_lang):
                raise HTTPException(
                    status_code=400, detail=f"不支持的语言代码: target_lang={target_lang}"
                )
        else:
            target_lang = auto_detect_target(text_to_translate)

        return text_to_translate, source_lang, target_lang

    @staticmethod
    def _extract_text(content: str | list[Any] | None) -> str:
        """从 OpenAI content 字段提取纯文本 (兼容字符串与多段数组)。"""
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for seg in content:
                if isinstance(seg, str):
                    parts.append(seg)
                elif isinstance(seg, dict) and seg.get("type") == "text":
                    parts.append(str(seg.get("text", "")))
            return "".join(parts).strip()
        return ""

    # --- M16: 轻量语言检测 (基于字符集推断, 非 Google 官方检测) ---
    @staticmethod
    def detect_language(text: str) -> dict[str, Any]:
        """基于脚本/字符集的推断: 返回命中的脚本族 + 自动路由目标语言。

        明确标注 source=script_heuristic, 避免被误认为官方语言检测。
        """
        if not text:
            return {
                "object": "language_detection",
                "scripts": [],
                "target_lang": "zh-CN",
                "source": "script_heuristic",
                "note": "基于字符集的轻量推断, 非 Google 官方语言检测",
            }
        scripts: list[str] = []
        checks = (
            ("cjk_han", "一", "鿿"),
            ("hiragana_katakana", "぀", "ヿ"),
            ("hangul", "가", "힯"),
            ("arabic", "؀", "ۿ"),
            ("cyrillic", "Ѐ", "ӿ"),
        )
        for name, lo, hi in checks:
            if any(lo <= c <= hi for c in text):
                scripts.append(name)
        return {
            "object": "language_detection",
            "scripts": scripts,
            "target_lang": auto_detect_target(text),
            "source": "script_heuristic",
            "note": "基于字符集的轻量推断, 非 Google 官方语言检测",
        }

    def _prepare_headers(self, google_api_key: str) -> dict[str, str]:
        return {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/json+protobuf",
            "Origin": "https://stackoverflow.ai",
            "Referer": "https://stackoverflow.ai/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "x-goog-api-key": google_api_key or "",
        }

    def _prepare_payload(self, text: str, source_lang: str, target_lang: str) -> list:
        return [[[text], source_lang, target_lang], "te_lib"]

    def _clean_response(self, response_data: Any) -> str:
        """解析上游 [[translated_html]] 并清理为 Markdown。"""
        translated_html = ""
        if isinstance(response_data, list) and response_data:
            if isinstance(response_data[0], list) and response_data[0]:
                translated_html = response_data[0][0]
        elif not isinstance(response_data, list):
            preview = str(response_data)[:200]
            raise ValueError(f"上游响应格式不符合预期: {preview}")

        soup = BeautifulSoup(translated_html, "html.parser")
        clean_text = soup.get_text().replace("\u200b", "")
        return md(clean_text)

    def _log_upstream_error(self, response: httpx.Response, status_code: int) -> None:
        """P3-3: 接线 _parse_upstream_error, 把上游错误摘要写入日志 (截断 120, 不刷堆栈)。"""
        try:
            summary = self._parse_upstream_error(response, status_code)[:120]
        except Exception:
            summary = ""
        if summary:
            logger.warning(f"上游返回 {status_code}: {summary}")
        else:
            logger.warning(f"上游返回 {status_code}")

    def _parse_upstream_error(self, response: httpx.Response, status_code: int) -> str:
        """把上游错误响应转为可读字符串 (仅用于日志, 不回客户端)。"""
        try:
            data = response.json()
        except ValueError:
            # 上游返回非 JSON, 回退原始文本
            return response.text[:200]
        # 上游错误格式: [code, "message"] 或 [3, "msg", [["type", ...]]]
        if isinstance(data, list) and len(data) >= 2:
            return str(data[1])
        return str(data)

    async def get_models(self) -> JSONResponse:
        model_data = {
            "object": "list",
            "data": [
                {"id": name, "object": "model", "created": int(time.time()), "owned_by": "lzA6"}
                for name in settings.KNOWN_MODELS
            ],
        }
        return JSONResponse(content=model_data)

    # --- 就绪探针 (P1.5 + M4): 熔断打开即不健康; 探测不污染熔断计数 ---
    async def probe_ready(self) -> bool:
        if self.circuit_breaker and not self.circuit_breaker.allow():
            logger.warning("就绪探测失败: 熔断器打开")
            return False
        try:
            await self._translate(settings.READY_PROBE_TEXT, "auto", "zh-CN", record_health=False)
            return True  # 上游可达即就绪
        except Exception as exc:
            # 3.G.3: 失败原因写入日志/指标, 便于排障
            logger.warning(f"就绪探测失败: {type(exc).__name__}: {str(exc)[:120]}")
            return False
