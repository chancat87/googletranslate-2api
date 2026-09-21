# Changelog

本项目所有显著变更均记录于此。遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [1.4.3] - 2026-09-21

### 文档与验收 (3.F)
- README 新增「真实调用输出附录」：非流式/流式/批量/422/401/403/429 七条路径的 curl 实测输出（有效 key，非编造）
- API_DOCS 新增「错误信封统一（含 422）」小节（含 429 Retry-After 语义、upstream_auth_error 说明）
- README 补充批量「部分失败」示例（条目级 ok/error，整体 200）
- 新增 OpenAPI 一致性测试：/docs 覆盖所有公开路由

### 验证
- 全量回归 169 passed / 1 skipped，覆盖率 100%（767 stmts）；ruff / mypy / format 0
- curl 实测：非流式"你好世界"、流式 SSE+[DONE]、批量 苹果/香蕉、422/401/403 统一信封、429 Retry-After 实际秒数
## [1.4.2] - 2026-09-21

### 文档与验收
- 文档同步到 v1.4.x：README 增补 v1.4.x 更新记录；CLAUDE/API_DOCS 补充 3.B/3.C/3.D 特性与 Retry-After 语义
- 真实服务器级 E2E 审计（有效 key + 限流开启）：/ready 200、非流式/流式/批量真实翻译、include_usage、**429 Retry-After=实际秒数(998)** 全部验证通过
- 远端 GitHub Actions CI v1.4.1 main/tag 双 success

### 验证
- 全量回归 168 passed / 1 skipped，覆盖率 100%（767 stmts）；ruff / mypy / format 0
## [1.4.1] - 2026-09-21

### 增强 (3.D / 3.E 验收补齐)
- **3.D.5 连接池显式限制**：`initialize()` 使用 `httpx.Limits`（max_connections = max(10, BATCH_MAX_CONCURRENCY+5)，max_keepalive = max(5, BATCH_MAX_CONCURRENCY)），与批量并发匹配
- **3.D.1 重试日志**：`_post_with_retry` 重试时输出带次数的 WARNING（"上游重试第 n/attempts 次，退避 x s"），满足 3.D 验收"日志含重试计数"
- 批量 deadline 耗时断言收紧（整体耗时受 budget 约束，实测 ~1s）

### 验证
- 新增连接池/重试日志测试；全量回归 **168 passed / 1 skipped，覆盖率 100%**（767 stmts）
- ruff / mypy / format 0；真实上游翻译 E2E PASSED
## [1.4.0] - 2026-09-21

### 增强 (P3 项闭环)
- **P3-8 Retry-After 精确化**：`TokenBucket.retry_after()` / `RateLimiter.retry_after(key)` 按桶回填时间计算等待秒数，429 响应头返回实际值（不再固定 "1"）
- **P3-1 弱 key 熵检查**：主密钥字符多样性 <6 时启动告警（即使长度达标）
- **P3-5 流式 SSE detail 白名单**：非白名单 detail 统一为 "请求处理失败"，防未来误带上游/用户文本进 SSE
- **3.F OpenAPI 补漏**：`/v1/translate/batch` 响应声明补齐 413/422

### 验证
- 新增/更新测试：Retry-After 精确值与 inf 分支、熵告警、SSE 白名单透传/兜底、OpenAPI 413/422
- 全量回归 **167 passed / 1 skipped，覆盖率 100%**（765 stmts）；ruff / mypy / format 0
## [1.3.3] - 2026-09-21

### 增强 (3.C 缓存与性能)
- 首尾空白归一化 (3.C.3)：`_translate` / `_stream_translate` 计算缓存 key 前仅 `strip()` 首尾空白，
  `" hello "` 与 `"hello"` 共享缓存命中（批量条目同样受益），不再因空白差异重复打上游。
- 命中指标可观测：`cache_hit_total` / `cache_miss_total`（`/metrics`），命中场景计数已验证。
- 修正 `APP_VERSION` 漂移至 v1.3.3。

### 验证
- 新增 4 个缓存归一化测试（translate / stream / batch 共享缓存 + 命中指标 +1）
- 全量回归 161 passed / 1 skipped，覆盖率 100%（738 stmts）；ruff / mypy / format 0

## [1.3.2] - 2026-09-21

### 工程
- API_DOCS.md / docs/上游接口直连文档.md：ruff-format 规范化文档内 python 代码块
- pre-commit 真实可用（ruff + ruff-format 全绿）；远端 GitHub Actions CI 全 run success

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
