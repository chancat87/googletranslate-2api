# googletranslate-2api 测试套件

## 运行

```bash
pip install -r requirements.txt pytest pytest-asyncio
pytest -v
```

## 测试分层

- `tests/test_languages.py` — 纯单元, 语言码校验与自动路由, 无外部依赖
- `tests/test_provider.py` — provider 逻辑 (mock httpx 上游), 校验/解析/多段 content
- `tests/test_sse_utils.py` — SSE/响应构造器单元
- `tests/test_api.py` — FastAPI 集成 (ASGI transport), 状态码/认证/流式与非流式
- `tests/test_integration_real.py` — 真实上游集成 (需 GOOGLE_API_KEY, 默认 skip)

集成测试 mock 上游, 不触达真实 Google, 可离线/CI 运行。
