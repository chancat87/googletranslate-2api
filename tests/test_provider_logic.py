"""Provider 逻辑测试 — mock httpx 上游, 离线可运行。"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.providers.googletranslate_provider import GoogleTranslateProvider


def _make_provider():
    p = GoogleTranslateProvider()
    p.client = MagicMock()
    return p


# ---------- _extract_text ----------

class TestExtractText:
    def test_string(self):
        assert GoogleTranslateProvider._extract_text("hello") == "hello"

    def test_none(self):
        assert GoogleTranslateProvider._extract_text(None) == ""

    def test_list_of_strings(self):
        assert GoogleTranslateProvider._extract_text(["a", "b"]) == "ab"

    def test_list_of_text_segments(self):
        content = [{"type": "text", "text": "foo"}, {"type": "image_url"}, {"type": "text", "text": "bar"}]
        assert GoogleTranslateProvider._extract_text(content) == "foobar"

    def test_list_ignores_non_text(self):
        assert GoogleTranslateProvider._extract_text([{"type": "image", "url": "x"}]) == ""

    def test_whitespace_stripped(self):
        assert GoogleTranslateProvider._extract_text("  hi  ") == "hi"


# ---------- _validate_and_extract ----------

class TestValidateAndExtract:
    def test_happy_path(self):
        p = _make_provider()
        text, src, tgt = p._validate_and_extract({
            "messages": [{"role": "user", "content": "你好"}]
        })
        assert text == "你好"
        assert src == "auto"
        assert tgt == "en"  # 中文自动转英文

    def test_missing_messages(self):
        p = _make_provider()
        with pytest.raises(HTTPException) as e:
            p._validate_and_extract({})
        assert e.value.status_code == 400

    def test_empty_messages(self):
        p = _make_provider()
        with pytest.raises(HTTPException) as e:
            p._validate_and_extract({"messages": []})
        assert e.value.status_code == 400

    def test_last_not_user(self):
        p = _make_provider()
        with pytest.raises(HTTPException) as e:
            p._validate_and_extract({"messages": [{"role": "system", "content": "x"}]})
        assert e.value.status_code == 400

    def test_empty_content(self):
        p = _make_provider()
        with pytest.raises(HTTPException) as e:
            p._validate_and_extract({"messages": [{"role": "user", "content": ""}]})
        assert e.value.status_code == 400

    def test_bad_source_lang(self):
        p = _make_provider()
        with pytest.raises(HTTPException) as e:
            p._validate_and_extract({
                "messages": [{"role": "user", "content": "hi"}],
                "source_lang": "klingon",
            })
        assert e.value.status_code == 400

    def test_bad_target_lang(self):
        p = _make_provider()
        with pytest.raises(HTTPException) as e:
            p._validate_and_extract({
                "messages": [{"role": "user", "content": "hi"}],
                "target_lang": "xxxx",
            })
        assert e.value.status_code == 400

    def test_explicit_langs(self):
        p = _make_provider()
        text, src, tgt = p._validate_and_extract({
            "messages": [{"role": "user", "content": "bonjour"}],
            "source_lang": "fr",
            "target_lang": "de",
        })
        assert src == "fr" and tgt == "de"


# ---------- _clean_response / _parse_upstream_error ----------

class TestCleanResponse:
    def test_normal_nested(self):
        p = _make_provider()
        # 上游格式: [["<b>你好</b>"]]
        out = p._clean_response([["<b>你好</b>"]])
        assert "你好" in out

    def test_empty_list(self):
        p = _make_provider()
        assert p._clean_response([]) == ""

    def test_bad_format(self):
        p = _make_provider()
        with pytest.raises(ValueError):
            p._clean_response({"unexpected": True})


class TestParseUpstreamError:
    def test_list_format(self):
        p = _make_provider()
        resp = MagicMock()
        resp.json.return_value = [3, "Request contains an invalid argument."]
        assert "invalid argument" in p._parse_upstream_error(resp, 400)

    def test_fallback_text(self):
        p = _make_provider()
        resp = MagicMock()
        resp.json.side_effect = ValueError("not json")
        resp.text = "raw error body"
        assert "raw error body" in p._parse_upstream_error(resp, 500)
