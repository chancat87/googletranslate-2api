# Implementation Plan: 生产加固与终局审计

## Technology Stack

- Backend: Python 3.10 + FastAPI + uvicorn（多 worker 由容器控制，单 worker 每副本）
- Frontend: 原生单文件 Web UI（`app/web/app.html`，无外部依赖）
- Deployment: Docker Compose（蓝绿）+ GHCR + 可选 K8s；CI/CD GitHub Actions
- Data/Cache: Redis 7（共享缓存/限流/用量），不可用自动回退内存
- Observability: loguru + request_id、Prometheus `/metrics`、trace/usage API、`/health` `/ready`

## Architecture

```text
Client -> https://gapi.isrna.cn (nginx 443) -> gateway:8088 (nginx)
        -> upstream app-blue:8000 / app-green:8000 (proxy_next_upstream)
        -> provider (GoogleTranslateProvider)
        -> key pool + cache(redis/memory) + circuit breaker + singleflight + rate limit
        -> translate-pa.googleapis.com
```

## Component Design

### API 层 (`main.py`)
- OpenAI 兼容 `chat/completions`（stream/SSE + `[DONE]`）、`translate/batch`、`models`
- Web UI 路由 `/`（浏览器 `text/html` 时）、`/app`、`/admin`、favicon
- 管理端点 `/v1/admin/*`（key/keys/bulk/probe/usage/traces）
- 统一鉴权、请求 ID、日志、限流中间件

### Provider 层 (`app/providers/googletranslate_provider.py`)
- 多 Key 池、429/403/网络错误冷却切换、重试+退避+jitter
- 缓存（memory/redis）、单飞（同文并发只放行一次上游）、熔断
- DEMO_MODE 无 Key 降级（`demo:` 前缀）

### 部署层 (`deploy/compose/*` + `deploy/upgrade.sh`)
- 双 app 副本 + nginx gateway + redis；`/ready` 就绪；优雅停机 30s；`stop_grace_period 35s`
- `upgrade.sh` 逐副本 `--force-recreate` 并等待就绪；指定旧镜像即回滚
- Watchtower 可选自动更新（标签限定 app 副本）

## Error Handling

- 4xx（400/401/403/404/413/422）不重试，返回稳定错误 JSON
- 429/5xx/网络错误：重试 + 冷却 + 熔断，返回可读错误
- 未捕获异常：统一异常处理器返回 500 JSON + 日志带 request_id

## Security

- 认证 Bearer；Key 永不明文入库/镜像/日志；`.dockerignore` 排除 `.env`
- 镜像非 root、禁止提权；K8s `securityContext`；Secrets 走 K8s Secret/服务器 `.env`
- CI Secrets 不落仓库

## Performance

- Redis 共享缓存提升命中；单飞合并同文并发；HTTPX 连接池；nginx keepalive + gzip
- 单机 1 核：`APP_WORKERS=1`/`APP_CPUS=1`；双副本分摊
- 压测目标：0 错 0 429，QPS 随并发提升（实测 conc1/5/10 = 6.3/21.8/18.3）

## Testing Strategy

- 单元/集成：pytest + coverage 97%；契约/错误路径/E2E 脚本
- 浏览器 E2E：Playwright（`npm run web:ui:e2e`）
- 部署配置测试：`tests/test_deploy_compose.py` + kubeconform
- 生产验收：公网 `/health` `/ready` 翻译/SSE/管理端点 + 压测 + 升级/回滚健康循环

## Risk Mitigation

- 镜像拉取失败：`upgrade.sh` 先 pull 再本地 build 兜底
- readiness 不过：脚本超时失败，nginx 仍路由到健康副本
- Key 失效：KeyPool 自动切换；probe 自检人工兜底
- 内存压力：双副本各 `mem_limit 800m`、redis 64mb LRU
