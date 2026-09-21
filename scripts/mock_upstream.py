"""本地 mock 上游 (v2.1.0 基准自动化)。

模拟 translate-pa 的请求/响应形状, 不访问 Google, 用于 CI/本地确定性压测:
  python -m uvicorn scripts.mock_upstream:app --port 8899
"""

import asyncio
import json as _json
import time

from fastapi import FastAPI, Request

app = FastAPI()


@app.post("/v1/translateHtml")
async def translate_html(request: Request):
    # 兼容 provider 的 application/json+protobuf 内容类型: 按原始 body 解析
    try:
        payload = await request.json()
    except Exception:
        payload = _json.loads(await request.body())
    try:
        text = payload[0][0][0]
    except Exception:
        text = "hi"
    await asyncio.sleep(0.01)  # 模拟固定延迟, 让压测有可比性
    return [[f"mock:{text}:{time.time():.3f}"]]


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock-upstream"}
