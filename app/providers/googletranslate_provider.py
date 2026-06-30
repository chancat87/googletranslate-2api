import asyncio
import httpx
import re
import time
import uuid
from typing import Dict, Any, AsyncGenerator, Optional, Tuple, Union, List

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from loguru import logger
from markdownify import markdownify as md
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.languages import is_supported, auto_detect_target
from app.core.cache import make_cache, cache_key, cache_get, cache_put
from app.providers.base_provider import BaseProvider
from app.utils.sse_utils import (
    create_sse_data,
    create_chat_completion_chunk,
    create_chat_completion,
    DONE_CHUNK,
)


# 句子切分: 保留标点, 按中英文句末符号切 (P1.1)
_SENT_SPLIT_RE = re.compile(r"(?<=[。!?\.!?])\s*")


class GoogleTranslateProvider(BaseProvider):
    """将 Google Translate 翻译接口适配为 OpenAI Chat Completions 流式响应。

    全语言互转: source_lang / target_lang 显式指定即透传上游; 不指定则自动检测。
    """

    BASE_URL = "https://translate-pa.googleapis.com/v1/translateHtml"

    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self.cache = make_cache()

    async def initialize(self):
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY 未在 .env 文件中配置。")
        self.client = httpx.AsyncClient(timeout=settings.API_REQUEST_TIMEOUT)
        # 每次初始化重建缓存, 避免跨测试/重启的脏数据
        self.cache = make_cache()

    async def close(self):
        if self.client:
            await self.client.aclose()

    # --- 主流程: 校验 -> 翻译 -> 按 stream 决定流式 / 非流式响应 ---
    async def chat_completion(self, request_data: Dict[str, Any]):
        text_to_translate, source_lang, target_lang = self._validate_and_extract(request_data)
        model_name = request_data.get("model") or settings.DEFAULT_MODEL
        stream = request_data.get("stream", True)

        if stream:
            return self._stream_response(text_to_translate, source_lang, target_lang, model_name)
        return await self._non_stream_response(text_to_translate, source_lang, target_lang, model_name)

    # --- 非流式: 单次完整 JSON (OpenAI chat.completion 格式) ---
    async def _non_stream_response(
        self, text: str, source_lang: str, target_lang: str, model_name: str
    ) -> JSONResponse:
        request_id = f"chatcmpl-{uuid.uuid4()}"
        try:
            markdown_text = await self._translate(text, source_lang, target_lang)
            completion = create_chat_completion(request_id, model_name, markdown_text, text)
            return JSONResponse(content=completion)
        except httpx.HTTPStatusError:
            logger.error(f"上游返回非 200 (src={source_lang} tgt={target_lang})")
            return JSONResponse(
                status_code=502,
                content={"error": {"message": "翻译服务暂时不可用", "type": "upstream_error"}},
            )
        except Exception:
            logger.exception("处理翻译请求时发生错误")
            return JSONResponse(
                status_code=500,
                content={"error": {"message": "内部服务器错误", "type": "internal_error"}},
            )

    # --- 流式: SSE (OpenAI chat.completion.chunk 格式) ---
    def _stream_response(
        self, text: str, source_lang: str, target_lang: str, model_name: str
    ) -> StreamingResponse:
        async def stream_generator() -> AsyncGenerator[bytes, None]:
            request_id = f"chatcmpl-{uuid.uuid4()}"
            try:
                chunks_to_send = await self._stream_translate(text, source_lang, target_lang)
                for piece in chunks_to_send:
                    chunk = create_chat_completion_chunk(request_id, model_name, piece)
                    yield create_sse_data(chunk)
                final_chunk = create_chat_completion_chunk(request_id, model_name, "", "stop")
                yield create_sse_data(final_chunk)
                yield DONE_CHUNK
            except httpx.HTTPStatusError:
                logger.error(f"上游返回非 200 (src={source_lang} tgt={target_lang})")
                error_chunk = create_chat_completion_chunk(
                    request_id, model_name, "翻译服务暂时不可用", "stop"
                )
                yield create_sse_data(error_chunk)
                yield DONE_CHUNK
            except Exception:
                logger.exception("处理翻译请求时发生错误")
                error_chunk = create_chat_completion_chunk(
                    request_id, model_name, "内部服务器错误", "stop"
                )
                yield create_sse_data(error_chunk)
                yield DONE_CHUNK

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    # --- 翻译分发: 缓存命中直接返回; 长文本可选分批 (P1.1 + P1.2) ---
    async def _stream_translate(
        self, text: str, source_lang: str, target_lang: str
    ) -> List[str]:
        key = cache_key(text, source_lang, target_lang)
        cached = cache_get(self.cache, key)
        if cached is not None:
            logger.debug("cache hit")
            return [cached]

        # 默认整段翻译; 长文本且开启切句时分批
        if settings.STREAM_CHUNK_ENABLED and len(text) > settings.STREAM_CHUNK_THRESHOLD:
            return await self._translate_batched(text, source_lang, target_lang)
        whole = await self._translate(text, source_lang, target_lang)
        return [whole] if whole else []

    async def _translate_batched(
        self, text: str, source_lang: str, target_lang: str
    ) -> List[str]:
        """按句切分, 逐批翻译; 失败的批次以空串占位, 不中断整体。

        切句会丢失跨句上下文, 默认关闭 (STREAM_CHUNK_ENABLED=False)。
        """
        sentences = [s for s in _SENT_SPLIT_RE.split(text) if s.strip()]
        results: List[str] = []
        for sent in sentences:
            try:
                out = await self._translate(sent, source_lang, target_lang)
                results.append(out or "")
            except Exception:
                logger.warning("批次翻译失败, 跳过该句")
                results.append("")
        return results

    # --- 调用上游并清理结果 (共享给流式 / 非流式) ---
    async def _translate(self, text: str, source_lang: str, target_lang: str) -> str:
        key = cache_key(text, source_lang, target_lang)
        cached = cache_get(self.cache, key)
        if cached is not None:
            logger.debug("cache hit")
            return cached

        headers = self._prepare_headers()
        payload = self._prepare_payload(text, source_lang, target_lang)
        logger.info(f"向上游发送翻译请求: src={source_lang} tgt={target_lang}")
        response = await self.client.post(self.BASE_URL, headers=headers, json=payload)
        if response.status_code != 200:
            raise httpx.HTTPStatusError(
                f"上游状态码 {response.status_code}", request=response.request, response=response
            )
        markdown_text = self._clean_response(response.json())
        if not markdown_text:
            logger.warning("上游返回空翻译结果")
        else:
            cache_put(self.cache, key, markdown_text)
        return markdown_text

    # --- 批量翻译 (P2.2): 限并发, 复用 _translate ---
    async def translate_batch(
        self, texts: List[str], source_lang: str, target_lang: str
    ) -> List[Dict[str, Any]]:
        sem = asyncio.Semaphore(max(1, settings.BATCH_MAX_CONCURRENCY))

        async def _one(t: str) -> Dict[str, Any]:
            async with sem:
                try:
                    out = await self._translate(t, source_lang, target_lang)
                    return {"text": t, "translated": out, "ok": True}
                except Exception:
                    logger.exception("批量翻译单条失败")
                    return {"text": t, "translated": "", "ok": False}

        return await asyncio.gather(*[_one(t) for t in texts])

    # --- 校验与参数提取 (在进入流之前失败, 保证 HTTP 状态码语义正确) ---
    def _validate_and_extract(self, request_data: Dict[str, Any]) -> Tuple[str, str, str]:
        messages = request_data.get("messages")
        if not isinstance(messages, list) or not messages:
            raise HTTPException(status_code=400, detail="请求体缺少 messages 字段或格式不正确。")
        last = messages[-1]
        if not isinstance(last, dict) or last.get("role") != "user":
            raise HTTPException(status_code=400, detail="messages 最后一条必须为 role=user 的用户消息。")

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
            raise HTTPException(status_code=400, detail=f"不支持的语言代码: source_lang={source_lang}")

        # target_lang: 显式指定优先, 否则按文本自动检测
        target_lang = request_data.get("target_lang")
        if target_lang:
            if not is_supported(target_lang):
                raise HTTPException(status_code=400, detail=f"不支持的语言代码: target_lang={target_lang}")
        else:
            target_lang = auto_detect_target(text_to_translate)

        return text_to_translate, source_lang, target_lang

    @staticmethod
    def _extract_text(content: Union[str, List[Any], None]) -> str:
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

    def _prepare_headers(self) -> Dict[str, str]:
        return {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/json+protobuf",
            "Origin": "https://stackoverflow.ai",
            "Referer": "https://stackoverflow.ai/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "x-goog-api-key": settings.GOOGLE_API_KEY,
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
            raise ValueError(f"上游响应格式不符合预期: {response_data}")

        soup = BeautifulSoup(translated_html, "html.parser")
        clean_text = soup.get_text().replace("\u200b", "")
        return md(clean_text)

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
            ]
        }
        return JSONResponse(content=model_data)

    # --- 就绪探针 (P1.5): 发一个最小翻译探上游可用性 ---
    async def probe_ready(self) -> bool:
        try:
            await self._translate(settings.READY_PROBE_TEXT, "auto", "zh-CN")
            return True  # 上游可达即就绪
        except Exception:
            return False
