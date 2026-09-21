# Changelog

本项目所有显著变更均记录于此。遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [1.3.1] - 2026-09-21

### 安全加固（3.B 审查修复, code-review 子代理审计后落地）
- **P1-1**：`.env.example` 主密钥示例值清空；命中公开示例/弱 key 标记默认**拒绝启动**（`ALLOW_WEAK_API_KEY=true` 才显式放行）
- **P2-1**：非 ASCII Bearer token 返回 401（不再触发 `hmac.compare_digest` TypeError → 500 + 日志轰炸）
- **P2-2**：限流桶有界（`RATE_LIMIT_MAX_KEYS`，OrderedDict LRU 淘汰），防随机 key 内存 DoS
- **P2-3**：`TRUST_PROXY_HEADER`（默认关，防伪造）开启后按 `X-Forwarded-For` 首跳做 IP 维度限流
- **P2-4**：上游 403 返回独立语义 `upstream_auth_error`（非流式）+ SSE 明确文案，可区分永久凭证错误
- **P3-2/3/4/6/7/9**：非分支状态补告警日志；`_clean_response` 异常消息截断（上游原始响应不再进日志）；批量失败日志不再记录用户原文；nginx 注释补 `limit_req_status 429`；限流中间件复用 `_extract_bearer_token`；`initialize()` 校验 GOOGLE_API_KEY 示例占位符

### 工程
- 新增 `requirements.lock`（`uv pip compile` 生成，锁定全部运行依赖版本）
- `Dockerfile` 改用锁文件安装依赖（镜像构建可复现）
- `stop.ps1` 修复：Windows 下 uvicorn --reload 需整树终止（reloader 父 + spawn worker 子），否则端口被继承 socket 占住
- 真实脚本 E2E 验证 `start.ps1` / `stop.ps1`（起服务→翻译→停止→端口释放→无残留）

### 验证
- 全量回归 **157 passed / 1 skipped，覆盖率 100%**（736 stmts）
- ruff check / format 0，mypy 0
- 真实上游集成回归通过（有效 key 下 PASSED）
## [1.3.0] - 2026-09-21

### 新增 (3.B 安全加固)
- **启动弱 key 告警**：`API_MASTER_KEY` 未设置/为 `'1'`/长度<16/为示例默认值时，启动日志打 `warning`
- **上游 403/429 告警**：升级 key 失效（403）与频率限制（429）时输出专用告警日志 + 指标计数
- **Nginx 限流兜底示例**：`limit_req_zone` 定义（默认不限制请求），多副本部署可取消注释启用

### 强化
- 错误响应保洁断言固化：500 内部错误与 SSE 错误 chunk 均不泄露异常详情

### 验证
- 新增 8 个安全验收测试（弱 key 告警 / 403-429 告警与指标 / 响应保洁）
- 全量回归 149 passed / 1 skipped，覆盖率 100%，ruff / mypy 0 错误
## [1.2.1] - 2026-09-21

### 修正
- `.env.example` 补全 v1.2.0 全部新增配置项（重试/熔断/批量 deadline/限流/指标/模型别名/流式分段/缓存等）
- `GOOGLE_API_KEY` 取值提示：去掉引号，避免把引号当 key 的一部分

### 验证
- 真实上游翻译 E2E 通过（英→中 / 中→英 / 流式 / 批量，使用有效 GOOGLE_API_KEY）

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
