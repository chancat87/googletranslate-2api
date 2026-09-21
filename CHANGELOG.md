# Changelog

本项目所有显著变更均记录于此。遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [2.5.0] - 2026-09-22

### 新增 (现代化 Web UI)

- `GET /app` 新前端入口（`/admin` 兼容共用）：翻译工作台（流式/非流式）+ 总览健康 + Key 池 + 用量 + 最近请求 + 设置
- 无构建静态单文件：CSS/JS 内联、零外部依赖、深浅主题、桌面侧栏 / 移动底部导航、`prefers-reduced-motion` 支持
- 响应式：320px 起适配，`100dvh` + safe-area，移动触控目标 ≥44px，表格横向滚动
- 安全渲染：所有用户/API 数据经 HTML 转义后输出，Token 只存 localStorage

### 验证

- Web UI 路由验收 3 项：`/app` 与 `/admin` 均返回 HTML、无外部资产依赖、响应式/主题标记存在
- JS 语法经 Node `--check` 通过；进程级 mock E2E API 20/20 + UI 入口 PASS
- 全量回归 **285 passed / 1 skipped，覆盖率 98.89%**；ruff / format / mypy / 文档死链全过

## [2.4.0] - 2026-09-22

### 新增 (K8s Schema 校验收口)

- **kubeconform v0.8.0 接入 CI**：每次 push 用 `-strict -ignore-missing-schemas` 校验 `deploy/k8s`
- **修复 Deployment securityContext**：`allowPrivilegeEscalation: false` 移到容器级（Pod 级 Schema 不允许该字段），kubeconform 全量校验 `8 valid / 0 invalid`
- 清单结构回归测试补强：Pod/容器 securityContext 位置、CI 步骤存在性断言

### 验证

- kubeconform v0.8.0 本地实测：`9 resources found in 8 files - Valid: 8, Invalid: 0, Errors: 0, Skipped: 1`
- 全量回归 **282 passed / 1 skipped，覆盖率 98.88%**；ruff / format / mypy / 文档死链全过
- 进程级 mock E2E 20/20（见验收文档）

## [2.3.0] - 2026-09-22

### 新增 (K8s 部署清单 + 优雅停机)

- **`deploy/k8s/` 原生清单**：Deployment / Service / HPA / Ingress / ConfigMap / Secret 示例 / Redis（Deployment+Service），Kustomize 一键 `kubectl apply -k`
- **滚动发布安全**：`maxUnavailable: 0` + `maxSurge: 1`，`/health` 存活探针 + `/ready` 就绪探针，未就绪不入流量
- **优雅停机**：Dockerfile 增加 `STOPSIGNAL SIGTERM` 与 uvicorn `--timeout-graceful-shutdown 30`（`APP_SHUTDOWN_GRACE` 可配），compose 与 K8s 均设 35s 终止宽限
- **无状态化说明**：内存态（缓存/熔断/限流/trace）随 Pod 消亡无副作用；多副本共享缓存/限流/trace 走 Redis（清单已内置）

### 验证

- 新增 12 项 K8s 清单验收：文件齐全、YAML 可解析、Deployment 滚动策略/探针/优雅终止、Service/HPA/Ingress/Redis/ConfigMap 结构
- 全量回归 **281 passed / 1 skipped，覆盖率 98.88%**；ruff / format / mypy / 文档死链全过
- 进程级 mock E2E 与基准见验收文档；真实 Google 上游仍被历史 Key 失效阻塞，待新 Key

## [2.2.0] - 2026-09-22

### 新增 (缓存 stampede 防护)

- **进程内 singleflight**：`GoogleTranslateProvider` 按缓存 key 持有有界 `asyncio.Lock`（LRU 驱逐上限 2048），并发同文本只放行一个上游请求，其余等待缓存写回
- **Redis 跨进程门闩**：`RedisCacheBackend.acquire_lock/release_lock` 用 SETNX + token 删除，多 worker/多副本下同一文本同样只打一次上游；Redis 异常或门闩超时自动降级直接打上游
- 上游调用提取为 `_translate_uncached`，保持既有 Key 池 / 重试 / 熔断 / 配额逻辑不变

### 验证

- 新增 8 项 singleflight + Redis 门闩测试：同文 20 并发仅 1 次上游、不同 key 隔离、跨进程共享 Redis 仅 1 次上游、门闩异常/超时降级、释放失败不抛错、有界锁驱逐
- 全量回归 **269 passed / 1 skipped，覆盖率 98.88%**；ruff / format / mypy 全过
- 真实 E2E 与 mock 基准见验收文档

## [2.1.1] - 2026-09-22

### 修复

- **CI Redis mock 测试顺序敏感修复**：`test_make_redis_cache_success_with_fake_module` 原先替换 `sys.modules["redis.asyncio"]`，在 CI 中该模块已被其他测试提前 import 后失效，导致真实连接 `127.0.0.1:6379` 被拒；改为 `make_redis_cache(client_factory=...)` 显式注入 fakeredis 客户端

### 验证

- GitHub Actions run `35652812969`：`test` / `security-scan` 全绿，`bench`（workflow_dispatch 条件）跳过
- CI `test`：**259 passed / 1 skipped，覆盖率 98.76%**；ruff / format / mypy / 文档死链 / Docker build smoke 全过
- 本地 Windows 全量回归：**259 passed / 1 skipped，覆盖率 98.76%**；ruff / mypy 全过

## [2.1.0] - 2026-09-22

### 新增 (用量计费 + WebSocket + 供应链安全 + 基准自动化)

- **按 Key 用量持久化与配额** (`USAGE_STORE_ENABLED=true` + `USAGE_DAY_QUOTA`)：SQLite 聚合（只存哈希），配额用尽自动切 Key/429，管理面板用量接口读取
- **WebSocket 翻译网关** `/v1/ws/translate`：chunk/done/error 消息，支持 `?token=` 认证
- **供应链安全 CI**：gitleaks（历史已知泄漏不阻塞留证）+ SBOM(SPDX) + trivy fs 扫描
- **基准自动化**：`scripts/mock_upstream.py`（确定性 mock 上游）+ `scripts/bench_ci.py`（一键起服跑 loadtest），`UPSTREAM_BASE_URL` 可覆盖

### 验证

- 全量回归见验收报告；ruff / mypy / format 0
- UsageStore 单测（聚合/配额）+ provider 配额切 Key/429 + WebSocket 4 用例 + mock 上游形状
- `scripts/bench_ci.py` 本地实测跑通

## [2.0.0] - 2026-09-22

### 新增 (管理 API + 管理面板 + 小白体验)

- **管理 API**（受 `API_MASTER_KEY` 保护）：`/v1/admin/overview`、`/v1/admin/usage`、`/v1/admin/keys`（GET/POST/DELETE，只存哈希）、`/v1/admin/traces`
- **Key 池运行时运维**：`KeyPool.add_key / remove_key_by_hash`，热增/热删上游 Key 无需重启
- **管理面板** `GET /admin`：原生单文件 Web UI（总览/Keys/用量/最近请求/一键自检，加载态与错误反馈齐全）
- **启动脚本体验**：`start.ps1` / `start-dev.bat` 启动后打印 API 文档与管理面板地址
- **中文教程** `docs/TUTORIAL.md` + **文档死链检查** `scripts/check_docs_links.py`（已入 CI 与测试）

### 验证

- 全量回归 **244 passed / 1 skipped**；ruff / mypy / format 0
- 管理 API 单测覆盖：认证 401/403、总览/用量、Key 增删查、最近请求、UI HTML
- 真实 Key E2E 见 `docs/ACCEPTANCE_2026-09-22.md`（本轮追加 v2.0.0 管理矩阵）

## [1.7.0] - 2026-09-22

### 新增 (可观测与运维基础)

- **Redis 分布式限流** (`RATE_LIMIT_BACKEND=redis`)：WATCH/MULTI/EXEC 原子令牌桶，多副本限流一致；Redis 故障自动回退内存并告警
- **SSE 心跳** (`SSE_HEARTBEAT_INTERVAL`，默认 0=关)：空闲发 `data: {"type":"ping"}`，泵任务队列实现，不打断内层流
- **链路摘要集中化** (`TRACE_BACKEND=redis`)：多 worker 下 `/v1/traces/{id}` 可查（SET + ZSET 时间序），故障回退内存
- **Prometheus 告警规则** (`prometheus/alerts.yml`)：403/错误率/Key 切换/限流/失败占比 5 条规则

### 验证

- 全量回归 **224 passed / 1 skipped**；ruff / mypy 0
- 真实 Key E2E：内存模式 18/18；Redis 限流+trace 死端口降级模式 19/19（429 实测 + 降级告警实测）
- SSE 心跳实测：流式响应中出现 12 个 ping 且正常结束 `[DONE]`
- fakeredis 单测覆盖 Redis 令牌桶/隔离/降级、Redis trace 往返/淘汰/最近列表

## [1.6.1] - 2026-09-22

### 变更

- **CI 质量门禁覆盖 `scripts/`**: ruff check / format 现在包含 `scripts/`（e2e_smoke / loadtest）
- **E2E 缓存命中断言改为 `X-Trace-Summary` 响应头**: 多 worker/多副本下 trace 表按进程隔离, 头断言在单/多 worker 均可靠

### 验证

- 全量回归 **215 passed / 1 skipped，覆盖率 99.90%**；ruff / mypy 全过
- Windows 原生真实 Key E2E 四模式全过：内存 18/18、认证 20/20、Redis 降级 18/18、限流 19/19
- Linux 容器 E2E 尝试：本机 WSL2 Docker 周期性回收容器（纯 `sleep` 容器 ~4 分钟即 `exit 255`），判定为环境限制；稳定 Docker host 复跑命令见 `docs/ACCEPTANCE_2026-09-22.md`

## [1.6.0] - 2026-09-22

### 新增 (Redis 共享缓存 + E2E 验收)

- **`CACHE_BACKEND=redis`**：多 worker / 多副本共用一份翻译缓存（统一前缀 + TTL），提升缓存命中率、减少打上游
- **Redis 优雅降级**：连接失败/不可用时自动回退进程内内存缓存，服务不中断（启动告警日志）
- **`docker-compose.yml` 内置 Redis 服务**：compose 部署默认启用共享缓存
- **`scripts/e2e_smoke.py`**：真实 E2E 验收脚本（端点/流式/批量/检测/trace/缓存命中/错误矩阵/限流）
- **`requirements.lock` 重编译**：新增 `redis`（运行时）与 `fakeredis`（测试）依赖

### 验证

- 全量回归 **215 passed / 1 skipped，覆盖率 99.71%**（1049 stmts, provider 100%）
- ruff / mypy / format 全过
- 真实 Key E2E：非流式/流式/批量/检测/models/traces/健康检查/文档全部 200
- Redis 后端单测（fakeredis）：读写/TTL/前缀/降级/关闭清理 8 项通过

## [1.5.3] - 2026-09-22

### 新增 (高并发调优)

- **`LOG_LEVEL` 可配**（`DEBUG`/`INFO`/`WARNING`/`ERROR`）：生产可关每请求 INFO 日志，降低写入与存储开销
- **终端外自动关闭 ANSI 彩色日志**：重定向/容器内不再输出颜色转义码
- **nginx `keepalive 32` + `worker_connections 4096`**：复用后端连接，减少高并发下 TCP 建连开销
- **Docker `APP_WORKERS` 可配**（Dockerfile 默认 1，compose 默认 2 + `cpus: 2.0`）：多核部署可调 worker 数
- **`scripts/loadtest.py --warm-repeat N`**：多 worker 压测时让每个 worker 都缓存同一批文本

### 验证

- 高并发调优实验见 `docs/loadtest-2026-09-22.md` 第七节（单 worker 缓存命中 15-35 QPS，真实上游单 Key 5-10 QPS，Windows 多 worker 受 accept 分配限制不提升）
- 全量回归 **207 passed / 1 skipped**；ruff / mypy 通过

## [1.5.2] - 2026-09-22

### 新增 (阶段 0 文档 + 阶段 2.2 SKILL 体系)

- **`SECURITY.md`**：安全模型（认证/输入边界/上游密钥/限流/失败兜底/已知边界）
- **`docs/rotate-key.md`**：谷歌侧轮换 + git filter-repo 历史清理指引（不可逆操作需你确认后执行）
- **`scripts/refresh_curl_appendix.ps1`**：一键刷新真实 curl 输出附录（`docs/curl_appendix.md`），防文档漂移
- **`skills/` 四件套**：install / use / debug / extend（anthropics SKILL.md 规范），沉淀使用者技能、预留多模态/新 SKILL 打包规范

### 验证
- 真实运行 `refresh_curl_appendix.ps1` 产出 `docs/curl_appendix.md`（真实 curl 输出）
- 全量回归 **206 passed / 1 skipped，覆盖率 100%**（996 stmts）；ruff / mypy / format 0

## [1.5.1] - 2026-09-22

### 新增 (真实并发压测 + 连接池可配)

- **HTTPX 连接池参数可配**：`HTTPX_MAX_CONNECTIONS` / `HTTPX_MAX_KEEPALIVE_CONNECTIONS`（0=自动=max(10, BATCH+5) / max(5, BATCH)），替代写死值
- **真实并发压测基线**：`scripts/loadtest.py`（cache/upstream 两模式）+ `docs/loadtest-2026-09-22.md` + 原始 JSON 证据入 `docs/loadtest/`
- 实测结论：并发 1→40 全 200、0 错误、0 429；默认池真实上游 ~5.5-6 QPS，调参池(40) conc20+ ~10.3 QPS

### 验证
- 新增连接池显式覆盖测试；全量回归 **206 passed / 1 skipped，覆盖率 100%**（996 stmts）；ruff / mypy / format 0

## [1.5.0] - 2026-09-21

### 新增 (阶段 1.1/1.2/2.1 — 参考库对标落地)

- **多上游 Key 池 (`GOOGLE_API_KEYS`)**：逗号分隔多 Key，403/429/transport 自动切换到下一 Key，全部耗尽才失败（保留最后一次响应语义，403 → `upstream_auth_error`）；单 Key 配置完全向后兼容
- **Key 冷却退避 (`KEY_FAILOVER_COOLDOWN_SECONDS`)**：失败 Key 进入冷却，到期前不再优先选用；`/metrics` 暴露 `translate_key_pool_status` 各 Key 可用/冷却状态
- **实测厂商语义 (2026-09-21)**：Google translate-pa 对无效 Key 返回 **400 "API key not valid"**（非 403/401），因此 400 也纳入换 Key 集合，坏 Key 不会拖垮服务（真实 E2E：坏 Key → 400 → 自动切真 Key → 200）
- **链路摘要 (阶段 1.2)**：非流式响应头 `X-Trace-Summary`（cache/upstream/duration/key/retries/circuit），流式响应头 `X-Trace-Id` + 只读端点 `GET /v1/traces/{request_id}`（进程内环形缓冲 `TRACE_STORE_MAXLEN`，只含元数据，不含请求原文与明文 Key）
- **Key 维度用量指标 (阶段 2.1)**：`translate_requests_by_key_hash_total{key,result}`、`translate_upstream_errors_by_key_hash_total{key,code}`、`translate_key_switches_total`

### 验证
- 新增 30 个测试（KeyPool / TraceStore / failover 切换 / 全耗降级 / 指标 / 端点）；全量回归 **203 passed / 1 skipped，覆盖率 100%**（990 stmts）
- ruff / mypy / format 0；真实上游 E2E：坏 Key → 自动切换 → 真实翻译成功（见 README 附录）

## [1.4.4] - 2026-09-21


### 增强 (3.G 可观测性 + 3.I 清洁化)
- **translate_duration_seconds histogram 接线**：翻译路径（/v1/chat/completions、/v1/translate/batch）请求耗时正式上报 `/metrics`
- **探针失败原因日志 (3.G.3)**：`/ready` 失败（熔断打开 / 上游 403/429/网络）输出原因到日志，便于排障
- **P3-3 死代码接线**：`_parse_upstream_error` 正式接入 `_translate` 非 200 分支，上游错误摘要（截断 120）入日志
- **3.I.4 清洁化核查**：源码零 TODO/FIXME、零宽空格回归检查通过

### 验证
- 新增测试：histogram 样本、探针失败日志、上游错误摘要/解析异常分支
- 全量回归 **173 passed / 1 skipped，覆盖率 100%**（783 stmts）；ruff / mypy / format 0
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
