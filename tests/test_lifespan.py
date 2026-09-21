"""lifespan 成功/失败路径 (main.py:58-67) — 用 TestClient 触发。"""

import main as app_main
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _key_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-placeholder")


def test_lifespan_starts_and_stops():
    with TestClient(app_main.app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_lifespan_failure_raises(monkeypatch):
    async def _boom():
        raise ValueError("GOOGLE_API_KEY 未配置")

    monkeypatch.setattr(app_main.provider, "initialize", _boom)
    with pytest.raises(ValueError), TestClient(app_main.app):
        pass
