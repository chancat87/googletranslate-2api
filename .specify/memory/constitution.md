# googletranslate-2api Constitution

## Core Principles

### I. Production-First (MUST)
任何功能从“已在生产运行”出发：必须可部署、可运维、可回滚、可观测；单机/容器/K8s 三种部署路径保持一致，升级不中断服务。

### II. One-Call Success (MUST)
调用方按文档“一次调用即可跑通”：认证、URL、路径、参数、返回、错误码必须与文档/OpenAPI 完全一致，禁止“假功能”与“文档和真实行为不一致”。

### III. API Compatibility (MUST)
对外保持 OpenAI `chat/completions` 兼容语义（含 SSE 流式与 `[DONE]` 结束符），非流式返回结构与官方一致；内部上游隔离在 provider 层。

### IV. Test-First (NON-NEGOTIABLE)
TDD 强制：先写可验证验收（单测/契约/浏览器 E2E/部署配置测试），再实现；红-绿-重构；覆盖率阈值 97%，不允许用“看起来像完成”替代。

### V. Security & Secret Hygiene (MUST)
真实 Key 永不入库、不进镜像、不进日志；`.env` 由 `.gitignore/.dockerignore` 排除；认证默认开启；敏感信息脱敏；泄漏按“证据留档+轮换”处理。

### VI. Zero-Downtime Delivery (MUST)
发布/回滚必须可滚动执行：nginx `proxy_next_upstream` + 双副本 + `/ready` 就绪探测 + 优雅停机；任何副本重建期间对外 200 连续可观测，并留证据。

### VII. Honest Closure (MUST)
禁止伪闭环：不能把“部分实现/占位/mock/理论可行”表述为“已完成”；做不到必须写明真实状态、边界、阻塞与剩余一步。所有闭环需带证据（代码/命令/测试/日志/页面）。

## Constraints

- Python 3.10，FastAPI + uvicorn，单进程事件循环，Dockerfile 与运行时锁在 3.10
- 部署：根 `docker-compose.yml`（单副本快速入门）与 `deploy/compose/docker-compose.prod.yml`（蓝绿零中断）双路径；K8s 用于更大规模
- Redis 可选共享缓存/限流/用量，不可用自动降级内存缓存
- 多 Key：`GOOGLE_API_KEYS` / `GOOGLE_API_KEYS_FILE` / 批量 API / Web UI，均为用户自有 Key；禁止采集第三方 Key
- 日志：loguru + 结构化，统一 `request_id`；Prometheus `/metrics`；trace 最近请求可在 `/v1/admin/traces` 读取

## Quality Gates

- `pytest --cov=app --cov=main --cov-fail-under=97`（当前实测 312 passed / 1 skipped，覆盖率 98.94%）
- `ruff check`、`ruff format --check`、`mypy app main.py`、`scripts/check_docs_links.py` 全过
- CI：test（含 Web UI 浏览器 E2E、Docker build smoke、kubeconform）与 security-scan（Gitleaks/Trivy/SBOM/pip-audit）全绿
- 生产验收：`/health`、`/ready`、`/v1/models`、非流式 + SSE 翻译实测 200；压测 0 错 0 429；升级/回滚期间健康检查 100% 200

## Governance

宪法高于一切惯例；修订需记录于 CHANGELOG 与本文档版本。变更评审按“有罪推定→找根因→给出可执行修复→证据验收”进行，默认质疑每行代码；关键可验证项未过门禁不算完成。

**Version**: 1.0.0 | **Ratified**: 2026-09-22 | **Last Amended**: 2026-09-22
