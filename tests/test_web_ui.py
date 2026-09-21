"""Web UI 前端路由验收 (v2.5.0): /app 与 /admin 均可访问且无外部依赖。"""

import main as main_mod
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    app = main_mod.app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_app_and_admin_serve_modern_ui(client):
    for path in ("/app", "/admin"):
        r = await client.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "管理面板" in r.text
        assert "翻译" in r.text
        assert "data-theme" in r.text


@pytest.mark.asyncio
async def test_ui_has_no_external_asset_dependency(client):
    r = await client.get("/app")
    assert "http://" not in r.text and "https://" not in r.text
    assert "script src=" not in r.text and "link rel=" not in r.text


@pytest.mark.asyncio
async def test_ui_contains_responsive_and_theme_support(client):
    r = await client.get("/app")
    assert "@media (max-width: 640px)" in r.text
    assert "prefers-reduced-motion" in r.text
    assert "localStorage" in r.text
