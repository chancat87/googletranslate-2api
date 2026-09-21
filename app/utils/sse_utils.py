import json
import time
from typing import Any

DONE_CHUNK = b"data: [DONE]\n\n"


def create_sse_data(data: dict[str, Any]) -> bytes:
    """将字典数据格式化为 SSE 事件字符串。"""
    return f"data: {json.dumps(data)}\n\n".encode()


def create_chat_completion_chunk(
    request_id: str,
    model: str,
    content: str,
    finish_reason: str | None = None,
) -> dict[str, Any]:
    """创建一个与 OpenAI 兼容的聊天补全流式块。"""
    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": finish_reason,
            }
        ],
    }


def create_chat_completion_usage_chunk(
    request_id: str,
    model: str,
    prompt_text: str,
    completion_text: str,
) -> dict[str, Any]:
    """OpenAI `stream_options.include_usage` 要求流末尾附带 usage 块 (M8)。

    语义: choices 为空数组, 携带 usage 字段; 供 OpenAI SDK 汇总计费。
    """
    usage = create_usage(prompt_text, completion_text)
    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [],
        "usage": usage,
    }


def estimate_tokens(text: str) -> int:
    """粗估 token 数: 英文 ~4 字符/token, 兜底避免 0。"""
    if not text:
        return 0
    return max(1, len(text) // 4)


def create_usage(prompt_text: str, completion_text: str) -> dict[str, Any]:
    """构造 usage 对象 (估算值, estimate=True 标记)。"""
    prompt_tokens = estimate_tokens(prompt_text)
    completion_tokens = estimate_tokens(completion_text)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimate": True,
    }


def create_chat_completion(
    request_id: str,
    model: str,
    content: str,
    prompt_text: str = "",
) -> dict[str, Any]:
    """创建与 OpenAI 兼容的非流式聊天补全响应。

    usage 为粗估值 (无分词器), 以 estimate 标记。
    """
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": create_usage(prompt_text, content),
    }
