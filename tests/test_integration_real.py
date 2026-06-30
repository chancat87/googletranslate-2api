"""真实上游集成测试 — 需要有效的 GOOGLE_API_KEY, 默认 skip。

CI / 离线环境无密钥时自动跳过, 不影响其它测试。
设置 RUN_REAL_INTEGRATION=1 且 .env 有真实 key 时才运行。
"""
import os
import json

import pytest
from httpx import ASGITransport, AsyncClient

import main as app_main

REAL_KEY = os.environ.get("GOOGLE_API_KEY", "")
RUN_REAL = os.environ.get("RUN_REAL_INTEGRATION") == "1"
SHOULD_RUN = bool(REAL_KEY and RUN_REAL and REAL_KEY != "test-key-placeholder")

pytestmark = pytest.mark.skipif(
    not SHOULD_RUN,
    reason="需要 RUN_REAL_INTEGRATION=1 且有效 GOOGLE_API_KEY 才运行真实上游集成测试",
)


@pytest.mark.asyncio
async def test_real_en_to_zh():
    await app_main.provider.initialize()
    try:
        transport = ASGITransport(app=app_main.app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=30) as c:
            r = await c.post("/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "Hello world"}],
                "stream": False,
                "target_lang": "zh-CN",
            })
            assert r.status_code == 200
            content = r.json()["choices"][0]["message"]["content"]
            assert any("一" <= ch <= "鿿" for ch in content), f"expected CJK, got: {content!r}"
    finally:
        await app_main.provider.close()
