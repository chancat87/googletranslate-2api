"""v2.1.0 mock 上游形状测试。"""

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "mock_upstream.py"


def _load_mock():
    spec = importlib.util.spec_from_file_location("mock_upstream", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_mock_upstream_translate_shape():
    mod = _load_mock()
    with TestClient(mod.app) as client:
        r = client.post("/v1/translateHtml", json=[[["hello"], "en", "zh-CN"], "te_lib"])
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert isinstance(body[0][0], str)
        assert body[0][0].startswith("mock:hello:")
        r2 = client.get("/health")
        assert r2.status_code == 200
        assert r2.json()["service"] == "mock-upstream"
