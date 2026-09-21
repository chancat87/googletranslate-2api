"""v2.1.0 WebSocket 翻译端点测试。"""

from unittest.mock import AsyncMock

import main as main_mod
from fastapi.testclient import TestClient


def test_ws_translate_returns_chunks_and_done(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "1")
    main_mod.provider._stream_translate = AsyncMock(return_value=["你好", "世界"])
    with TestClient(main_mod.app) as client, client.websocket_connect("/v1/ws/translate") as ws:
        ws.send_json({"text": "hello world", "target_lang": "zh-CN"})
        messages = []
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] == "done":
                break
    chunks = [m["content"] for m in messages if m["type"] == "chunk"]
    assert chunks == ["你好", "世界"]
    assert messages[-1]["type"] == "done"


def test_ws_translate_auth_required(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "master-key-1234567890")
    with TestClient(main_mod.app) as client, client.websocket_connect("/v1/ws/translate") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "认证" in msg["message"]


def test_ws_translate_auth_ok_with_token(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "master-key-1234567890")
    main_mod.provider._stream_translate = AsyncMock(return_value=["ok"])
    with (
        TestClient(main_mod.app) as client,
        client.websocket_connect("/v1/ws/translate?token=master-key-1234567890") as ws,
    ):
        ws.send_json({"text": "hi"})
        messages = []
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] == "done":
                break
    assert messages[0]["type"] == "chunk"
    assert messages[0]["content"] == "ok"


def test_ws_translate_empty_text_error(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "1")
    with TestClient(main_mod.app) as client, client.websocket_connect("/v1/ws/translate") as ws:
        ws.send_json({"text": "   "})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "不能为空" in msg["message"]


def test_ws_translate_too_long_error(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "1")
    monkeypatch.setattr(main_mod.settings, "MAX_TEXT_LENGTH", 5)
    with TestClient(main_mod.app) as client, client.websocket_connect("/v1/ws/translate") as ws:
        ws.send_json({"text": "very long text here"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "超长" in msg["message"]


def test_ws_translate_bad_langs_error(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "1")
    with TestClient(main_mod.app) as client, client.websocket_connect("/v1/ws/translate") as ws:
        ws.send_json({"text": "hi", "source_lang": "klingon"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "源语言" in msg["message"]

    with TestClient(main_mod.app) as client, client.websocket_connect("/v1/ws/translate") as ws:
        ws.send_json({"text": "hi", "target_lang": "klingon"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "目标语言" in msg["message"]


def test_ws_translate_invalid_frame_error(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "1")
    with TestClient(main_mod.app) as client, client.websocket_connect("/v1/ws/translate") as ws:
        ws.send_text("{not-json")
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "请求体无效" in msg["message"]


def test_ws_translate_upstream_error(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "1")

    async def _boom(*a, **k):
        raise HTTPException(status_code=503, detail="翻译服务暂时不可用")

    main_mod.provider._stream_translate = _boom
    with TestClient(main_mod.app) as client, client.websocket_connect("/v1/ws/translate") as ws:
        ws.send_json({"text": "hi"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "暂时不可用" in msg["message"]


def test_ws_translate_generic_error(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "API_MASTER_KEY", "1")

    async def _boom(*a, **k):
        raise RuntimeError("boom")

    main_mod.provider._stream_translate = _boom
    with TestClient(main_mod.app) as client, client.websocket_connect("/v1/ws/translate") as ws:
        ws.send_json({"text": "hi"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "翻译失败" in msg["message"]
