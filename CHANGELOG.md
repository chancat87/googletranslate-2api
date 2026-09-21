# Changelog

本项目所有显著变更均记录于此。遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [1.2.0] - 2026-09-21

### 新增
- `POST /v1/translate/detect`：轻量语言检测（基于字符集脚本推断，非 Google 官方检测）
- `GET /metrics`：Prometheus 指标端点（请求量/缓存/上游错误/限流计数）
- 上游重试：`UPSTREAM_RETRY_*`，指数退避 + 抖动（仅网络异常 / 429 / 5xx）
- 熔断器：`CIRCUIT_BREAKER_*`，滑动窗口，联动 `/ready`
- 批量整体 deadline：`BATCH_DEADLINE_SECONDS`，超时条目标记 `error=timeout`
- 限流中间件：`RATE_LIMIT_*`（默认关），429 + `Retry-After`
- `stream_options.include_usage`：流式末尾 `usage` 块
- 模型别名：`MODEL_ALIASES`
- 启动/停止脚本：`start-dev.bat` / `start.ps1` / `stop.ps1`
- Docker/nginx：HEALTHCHECK、`PYTHONUTF8`、资源限制、`.dockerignore`、超时与请求体限制
- CI：`.github/workflows/ci.yml`（pytest+coverage+ruff+mypy+docker build）、`.pre-commit-config.yaml`
- 工程配置：`pyproject.toml`（ruff / mypy / coverage `fail_under=97`）

### 变更
- 缓存 key 改用 sha256 摘要（跨进程稳定）
- 422 校验错误统一为 `{error:{message,type,detail}}` 信封
- 批量响应条目新增可选 `error` 字段（向后兼容）
- 长文本分段流改为「段落优先、单段落回退按句」（M17）
- 测试密封化：无 `.env` 亦可全绿（conftest 顶层注入占位 key）
- 文档同步：README / CLAUDE / API_DOCS / CHANGELOG；历史审计 `workflow_status.md` 归档至 `docs/archive/`

### 质量
- 测试 141 passed / 1 skipped（真实集成默认 skip）
- 覆盖率 100%（app + main.py）
- ruff check 0 / ruff format 0 / mypy 0

### 安全
- ⚠️ 历史 git 提交含真实 `GOOGLE_API_KEY`（已失效）：需在谷歌侧轮换；历史清理需明确确认

## [1.1.0] - 2026-06/07（历史）

- 全语言互转 + 流式/非流式响应
- 内存 TTL-LRU 缓存（P1.2）、输入长度上限 413（P1.6）
- `/ready` 就绪探针（P1.5）、批量翻译（P2.2）、request_id（P2.4）
- 结构化日志 text/json（P2.4）、OpenAI 多段 content 解析
- 测试套件建立并修复伪校验问题（72+ passed，覆盖率 87%）

## [1.0.0] - 2026-06（历史）

- 初始 OpenAI 兼容代理：`/v1/chat/completions`、`/v1/models`、Bearer 认证
- Nginx 反代（SSE buffering off）、Docker Compose 部署
