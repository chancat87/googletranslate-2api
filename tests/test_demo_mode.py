"""v2.10.0: DEMO_MODE 无 Key 可启动, 返回 demo 翻译, 不内置第三方 Key。"""

import pytest
from app.core import config as cfg
from app.providers.googletranslate_provider import GoogleTranslateProvider


def _enable_demo(monkeypatch):
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", None)
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS_FILE", None)
    monkeypatch.setattr(cfg.settings, "DEMO_MODE", True)


@pytest.mark.asyncio
async def test_demo_mode_initializes_without_key(monkeypatch):
    _enable_demo(monkeypatch)
    provider = GoogleTranslateProvider()
    await provider.initialize()
    assert provider.key_pool is not None
    assert len(provider.key_pool) == 1
    await provider.close()


@pytest.mark.asyncio
async def test_demo_mode_translate_returns_demo(monkeypatch):
    _enable_demo(monkeypatch)
    provider = GoogleTranslateProvider()
    await provider.initialize()
    out = await provider._translate("hello", "en", "zh-CN")
    assert out.startswith("demo:")
    await provider.close()


@pytest.mark.asyncio
async def test_demo_mode_probe_key_ok(monkeypatch):
    _enable_demo(monkeypatch)
    provider = GoogleTranslateProvider()
    await provider.initialize()
    result = await provider.probe_key("demo-key")
    assert result == {"http_status": 200, "ok": True}
    await provider.close()
