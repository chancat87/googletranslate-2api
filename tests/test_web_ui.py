"""Web UI 前端路由验收 (v2.5.0): /app 与 /admin 均可访问且无外部依赖。"""

import json
from pathlib import Path

import main as main_mod
import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parent.parent


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


def test_ci_has_web_ui_browser_e2e():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Web UI browser E2E" in ci
    assert "npm run web:ui:e2e" in ci


def test_package_json_defines_web_ui_script():
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert pkg["scripts"]["web:ui:e2e"] == "node scripts/web_ui_e2e.mjs"


def test_ui_nav_delegation_does_not_shadow_action_buttons():
    html = (ROOT / "app" / "web" / "app.html").read_text(encoding="utf-8")
    assert 'closest(".nav-item, .nav-mobile-item")' in html


def test_ui_has_bulk_key_import():
    html = (ROOT / "app" / "web" / "app.html").read_text(encoding="utf-8")
    assert "批量导入" in html
    assert 'data-action="bulkkeys"' in html
