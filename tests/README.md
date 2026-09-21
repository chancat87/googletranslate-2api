# googletranslate-2api 测试套件

## 运行

```bash
pip install -r requirements-dev.txt pytest-cov
pytest -v
pytest --cov=app --cov=main --cov-report=term-missing   # 覆盖率 (fail_under=97 在 pyproject.toml)
```

## 密封性 (重要)

测试**无需 .env、无需预置 GOOGLE_API_KEY**：`conftest.py` 顶层会在任何 app 模块
import 之前注入占位 key（`app/core/config.py` 的 `Settings()` 在导入期读取环境变量并定格单例，
因此必须在 import 之前预置）。全新环境直接 `pytest` 即可全绿。

## 测试分层

- `test_languages.py` — 语言码校验与自动路由（纯单元）
- `test_provider_logic.py` — provider 逻辑（mock httpx）：校验/解析/多段 content/错误解析
- `test_provider.py` — SSE / 响应构造器
- `test_cache_retry_circuit.py` — M2 缓存 key / M3 重试 / M4 熔断 / M5 批量 deadline / M6 令牌桶
- `test_api.py` — FastAPI 集成（ASGI + patch httpx）：状态码/认证/流式/非流式
- `test_p1_p2.py` — P1.x/P2.x 功能：长度上限/缓存/就绪探针/批量/request_id/切句流式
- `test_security_ux.py` — 限流中间件/422 统一信封/语言检测/多 key 认证/metrics 端点
- `test_stream_compat.py` — include_usage/模型别名/取消传播/段落切分
- `test_coverage_edges.py` — 覆盖率补齐（异常分支/禁用态）
- `test_lifespan.py` — lifespan 成功/失败路径（TestClient）
- `test_integration_real.py` — 真实上游（默认 skip，需有效 GOOGLE_API_KEY + `RUN_REAL_INTEGRATION=1`）

## 当前基线

- 141 passed, 1 skipped（skipped 为真实集成，属设计）
- 覆盖率 100%（app + main，688 stmts / 0 miss）
- ruff check 0 / ruff format 0 / mypy 0
