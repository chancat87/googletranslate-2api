"""SSE / 响应构造器单元。"""
import time

from app.utils.sse_utils import (
    create_sse_data,
    create_chat_completion_chunk,
    create_chat_completion,
    DONE_CHUNK,
)


class TestCreateSSEData:
    def test_format(self):
        out = create_sse_data({"a": 1})
        assert out.endswith(b"\n\n")
        assert out.startswith(b"data: ")
        assert b'"a": 1' in out

    def test_done_chunk(self):
        assert DONE_CHUNK == b"data: [DONE]\n\n"


class TestChatCompletionChunk:
    def test_delta_content_shape(self):
        c = create_chat_completion_chunk("id-1", "google-translate", "你好", None)
        assert c["object"] == "chat.completion.chunk"
        assert c["model"] == "google-translate"
        assert c["choices"][0]["delta"]["content"] == "你好"
        assert c["choices"][0]["finish_reason"] is None

    def test_finish_reason(self):
        c = create_chat_completion_chunk("id-1", "m", "", "stop")
        assert c["choices"][0]["finish_reason"] == "stop"
        assert c["choices"][0]["delta"]["content"] == ""


class TestChatCompletionNonStream:
    def test_shape(self):
        c = create_chat_completion("id-1", "google-translate", "Hello")
        assert c["object"] == "chat.completion"
        msg = c["choices"][0]["message"]
        assert msg["role"] == "assistant"
        assert msg["content"] == "Hello"
        assert c["choices"][0]["finish_reason"] == "stop"

    def test_usage_is_estimated(self):
        # usage 为粗估值 (无分词器), estimate=True 标记, 非写死 -1
        c = create_chat_completion("id-1", "m", "Hello world text", prompt_text="some prompt")
        u = c["usage"]
        assert u["estimate"] is True
        assert u["completion_tokens"] >= 1
        assert u["prompt_tokens"] >= 1
        assert u["total_tokens"] == u["prompt_tokens"] + u["completion_tokens"]

    def test_usage_empty_input_is_zero(self):
        c = create_chat_completion("id-1", "m", "")
        u = c["usage"]
        assert u["prompt_tokens"] == 0
        assert u["completion_tokens"] == 0
        assert u["total_tokens"] == 0

    def test_created_is_int(self):
        c = create_chat_completion("id-1", "m", "x")
        assert isinstance(c["created"], int)
        assert c["created"] <= int(time.time())
