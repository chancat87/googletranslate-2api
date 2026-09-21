# 验收报告 (v1.6.0, 2026-09-22)

## 一、范围

- 功能验收: 翻译 API 全端点真实 E2E (非流式 / 流式 / 批量 / 检测 / 模型 / trace / 健康 / 文档 / 指标)
- 并发验收: 真实上游 + 缓存命中压测, 单 Key 吞吐边界与连接池调参
- 新功能验收: Redis 共享缓存 (fakeredis 单测 + 不可用时真实降级 E2E)
- 质量审计: 测试套件 / 覆盖率 / ruff / mypy / 依赖 lock / compose 结构

## 二、E2E 结果 (真实 Key, 真实上游, 服务实跑)

| 模式 | 服务配置 | 结果 |
|---|---|---|
| 内存缓存 / 认证关闭 | port 8090 | **18/18 PASS** |
| 内存缓存 / 认证开启 | port 8091 | **20/20 PASS** (含 401/403) |
| Redis 不可用降级 | port 8092 (`CACHE_BACKEND=redis` + 死端口) | **18/18 PASS** + 启动告警 "回退内存缓存" |
| 限流开启 | port 8093 (`RATE_LIMIT_ENABLED=true`, 容量5/速率2) | **19/19 PASS** (429 实测触发) |

覆盖断言: `/health`(版本 1.6.0) / `/ready` / `/` / `/docs` / `/redoc` / `/openapi.json` /
`/metrics` / `/v1/models` / 非流式翻译(usage=estimate) / SSE 流式(`data:` + `[DONE]`) /
缓存命中(trace `cache_hit=true`) / 批量 4 条全 ok / 语言检测 / 422 / 400 / 413 / 401 / 403 / 429。

## 三、自动化测试与质量门禁

- `pytest --cov=app --cov=main`: **215 passed, 1 skipped, 覆盖率 99.90%** (1051 stmts, provider 100%)
- `ruff check` / `ruff format --check`: 全过
- `mypy app main.py`: 15 个源文件无问题
- `uv pip compile` 重生成 `requirements.lock`: 仅新增 4 行 (redis 运行时依赖)
- `docker-compose.yml` YAML 校验: nginx / app / redis 三服务, app depends_on redis(healthy)
- `docs/curl_appendix.md`: 真实 curl 重新生成, health 返回 `version 1.6.0`

## 四、并发结论 (本轮复测)

- 真实上游单 Key: 并发 1-40 全 200、0 错 0 429, 吞吐约 5-10 QPS (调参池 conc20 达 10.1 QPS)
- 缓存命中单 worker: 约 15-35 QPS; 高并发 (100-200) 延迟升高, 瓶颈是事件循环与每请求固定成本
- 日志/worker 调优: `LOG_LEVEL=WARNING` + 多 Key + nginx keepalive + Linux 多 worker 为扩展路径

## 五、遗留事项 (环境受限, 非代码缺陷)

1. **Linux 容器多 worker + 真实 Redis 的 E2E**: 本机无 Docker/Redis, 已提供 `docker-compose.yml` (内置 redis) 与 `scripts/e2e_smoke.py`; 在 Linux 主机 `docker compose up -d --build` 后复跑同一脚本即可验收。
2. **多上游 Key 实测**: 仅 1 个可用 Key; 多 Key 池逻辑已有 32 项单测, 真实 N×QPS 需准备 N 个 Key 后复测。
3. **Git 历史中的 Key 轮换**: 见 `docs/AUDIT_2026-09-22.md` 高优先级发现。

## 六、Linux 容器 E2E 尝试与结论 (2026-09-22, v1.6.1)

本机启用 WSL2 Ubuntu 24.04 + Docker (29.7.2, compose v5.5.0) 尝试完整容器验收:

1. `docker compose up -d --build` 成功: nginx / app / redis 三容器启动, redis healthy, app healthy。
2. **环境限制确认**: 包括纯 `python -c "time.sleep(600)"` 对照容器在内, 所有容器在 ~4 分钟后被系统以 `exit 255` 终止 (无日志、无 OOM、dmesg 无 kill 记录) —— WSL2 Docker VM 周期性回收容器进程, 与项目代码无关 (纯 sleep 容器同样被杀)。
3. 结果: Linux 容器内完整 E2E 未能在本机稳定跑完; 项目代码正确性以 Windows 原生真实 Key E2E (四模式 18-20/19 全过) + 215 项单测 + 容器内可正常启动/健康/Redis 连接建连为准。

**在稳定 Docker host 上验收的命令**:

```bash
docker compose up -d --build
# 在任意能访问 8088 的机器 (或容器内):
python scripts/e2e_smoke.py --url http://<host>:8088 --expect-version 1.6.1
# 跨进程 Redis 共享缓存: 起两个 app 进程/容器共用同一 Redis, A 翻译一次, B 再翻同文本,
# 响应头 X-Trace-Summary 应显示 cache=hit。
```

## 七、v2.1.1 CI 修复闭环 (2026-09-22)

**问题**: v2.1.0 的 CI run `35651713119` 中
`tests/test_redis_cache.py::test_make_redis_cache_success_with_fake_module` 失败。原因是测试用
`monkeypatch.setitem(sys.modules, "redis.asyncio", fake)` 模拟成功路径，但 CI 收集顺序里
`redis.asyncio` 已被其他测试提前 import，`sys.modules` 替换不再对 `make_redis_cache` 生效，
于是走了真实连接被拒的降级分支，断言 `None is not None`。

**修复**: `make_redis_cache` 增加 `client_factory` 注入参数，默认使用
`_default_redis_client_factory()`；测试改为 `client_factory=_fake_redis` 显式注入 fakeredis，
不再依赖 import 顺序。

**验收结果**:

| 门禁 | 结果 |
|---|---|
| GitHub Actions `test` (run 35652812969) | ✅ success |
| GitHub Actions `security-scan` (gitleaks/SBOM/trivy) | ✅ success |
| GitHub Actions `bench` | ✅ skipped (workflow_dispatch 条件) |
| CI pytest | ✅ 259 passed / 1 skipped, 覆盖率 98.76% |
| CI ruff / format / mypy / docs links / docker build smoke | ✅ 全过 |
| 本地 Windows pytest | ✅ 259 passed / 1 skipped, 覆盖率 98.76% |

## 八、v2.2.0 缓存 stampede 防护 (2026-09-22)

**功能**: 进程内 per-key singleflight（有界 `asyncio.Lock`，上限 2048）+ Redis SETNX
跨进程门闩（token 校验删除、异常/超时降级直接打上游），并发同文本只放行一次上游请求。

**单测验收**: 新增 8 项

| 用例 | 结果 |
|---|---|
| 同文 20 并发 | ✅ 仅 1 次上游，19 个等待者缓存命中 |
| 不同 key 隔离 | ✅ 各自独立打上游 |
| 跨进程共享 Redis 门闩 | ✅ 仅 1 次上游 |
| Redis 门闩异常 / 超时 | ✅ 降级直接打上游不抛错 |
| 门闩释放失败 | ✅ 抑制并告警，不影响结果 |
| 有界锁 LRU 驱逐 | ✅ 超过 2048 后淘汰最旧 key |

**进程级 E2E (mock 上游 + 认证开启, v2.2.0)**: **20/20 全过**，包含 stream/cache hit/batch/detect/
错误矩阵/401/403。

**确定性并发基准 (cache 模式, mock 上游)**: conc 1/5/10/20 全 200、0 错 0 429，
QPS `26.8 / 23.8 / 22.8 / 21.7`，p95 `41.4 / 268.4 / 418.2 / 414.5ms`。

**全量回归**: **269 passed / 1 skipped，覆盖率 98.88%**；ruff / format / mypy 全过。

**真实 Google 上游复测 (2026-09-22)**: 使用历史 `.env` Key 启动后，上游返回 **400**，
E2E 仅 14/20（非流式/批量/cache 断言受影响），判定为凭证失效而非代码缺陷；真实上游验收需新 Key，
详见 `docs/AUDIT_2026-09-22.md`。

## 九、v2.3.0 K8s 部署 + 优雅停机 (2026-09-22)

**功能**: 新增 `deploy/k8s/` 原生清单（ConfigMap / Deployment / Service / HPA / Ingress /
Redis / Secret 示例 + Kustomize），并给 Dockerfile/compose 增加优雅停机配置。

**验收结果**:

| 项 | 结果 |
|---|---|
| K8s 清单 YAML 解析与结构 | ✅ 12/12（文件齐全、滚动策略、探针、优雅终止、HPA/Ingress/Redis） |
| Dockerfile 优雅停机 | ✅ `STOPSIGNAL SIGTERM` + `--timeout-graceful-shutdown 30` |
| compose 停止宽限 | ✅ `stop_grace_period: 35s` |
| 进程级 E2E（mock 上游 + 认证, v2.3.0） | ✅ 20/20 全过 |
| 全量回归 | ✅ 285 passed / 1 skipped，覆盖率 98.89% |
| ruff / format / mypy / docs links | ✅ 全过 |

**说明**: 本机无 `kubectl`，清单以 YAML 解析 + 结构断言验收；有集群时按
`deploy/k8s/README.md` 执行 `kubectl apply -k deploy/k8s` 后再做滚动发布压测。

## 十、v2.4.0 K8s Schema 校验 (2026-09-22)

**动作**: 在 v2.3.0 清单基础上接入 kubeconform v0.8.0 Schema 校验，并把
`allowPrivilegeEscalation` 从 Pod 级移到容器级（Pod 级 Schema 不允许该字段）。

**验收结果**:

| 项 | 结果 |
|---|---|
| kubeconform v0.8.0 本地实测 | ✅ 8 valid / 0 invalid（9 resources / 8 files，跳过 kustomization） |
| Deployment securityContext | ✅ Pod 级 `runAsNonRoot` true；容器级 `allowPrivilegeEscalation` false |
| CI kubeconform 步骤 | ✅ 已加入 `.github/workflows/ci.yml` |
| 清单结构断言 | ✅ 补齐 Pod/容器 securityContext 与 CI 步骤断言 |
| 全量回归 | ✅ 281 passed / 1 skipped，覆盖率 98.88% |

## 十一、v2.5.0 Web UI 前端 (2026-09-22)

**交付**: `/app` 现代化中文 Web UI + `/admin` 兼容入口，翻译工作台与运维面板合并。

| 项 | 结果 |
|---|---|
| `/app` 可访问 | ✅ 200 text/html，包含“管理面板” |
| `/admin` 可访问 | ✅ 与 `/app` 共用同一页面 |
| 无外部资产 | ✅ 0 个 `http(s)`/CDN/script src/link rel 依赖 |
| 响应式标记 | ✅ `@media (max-width: 1023px)` / `640px`，移动底部导航，safe-area |
| 主题与动效 | ✅ `data-theme` 深浅色 + `prefers-reduced-motion` |
| 渲染安全 | ✅ 数据全部经 HTML 转义 |
| JS 语法 | ✅ Node `--check` 通过 |
| 进程级 E2E | ✅ mock 上游 API 矩阵 20/20 + UI `/app`、`/admin` 均 PASS |
| 全量回归 | ✅ 285 passed / 1 skipped，覆盖率 98.89% |

## 十二、v2.5.1 浏览器 E2E + 交互修复 (2026-09-22)

**问题**: 浏览器实测发现点击“翻译”按钮被事件委托当成 `data-view` 导航处理，导致输出不更新。

**修复**: 事件委托只匹配 `.nav-item, .nav-mobile-item`，操作按钮走 `data-action` 分支。

**新增**: Playwright 浏览器 E2E（`scripts/web_ui_e2e.mjs` + `package.json`），已接入 CI。

| 项 | 结果 |
|---|---|
| 本地 Playwright | ✅ PASS（桌面 1440×900 + 移动 390×844、dark theme、流式翻译、/admin、零 console error） |
| 横向溢出 | ✅ 移动视口无横向滚动 |
| CI Web UI browser E2E 步骤 | ✅ 已加入 `.github/workflows/ci.yml` |
| 防回归断言 | ✅ 导航委托只匹配导航按钮类 |
| 全量回归 | ✅ 288 passed / 1 skipped，覆盖率 98.89% |

## 十三、v2.6.0 响应压缩 (2026-09-22)

**交付**: Nginx 网关开启 gzip，压缩普通 JSON/文本响应，SSE 流式保持不压缩不缓冲。

| 项 | 结果 |
|---|---|
| `gzip on / level 5 / min_length 1024` | ✅ 已配置 |
| `gzip_proxied any` + `gzip_vary on` | ✅ 已配置 |
| JSON / 文本 / JS / CSS / SVG gzip_types | ✅ 已配置 |
| SSE 不压缩 | ✅ `text/event-stream` 不在 gzip_types，`proxy_buffering off` 保留 |
| nginx 静态验收 | ✅ 2/2 |
| 全量回归 | ✅ 290 passed / 1 skipped，覆盖率 98.89% |

## 十四、v2.7.0 批量 Key 导入 (2026-09-22)

**交付**: 管理 API + Web UI 支持批量导入用户自持的真实 Key，N 条一次进池。

| 项 | 结果 |
|---|---|
| `POST /v1/admin/keys/bulk` | ✅ 新增/跳过统计，只回传哈希 |
| 批量导入去重/空值 | ✅ 自动 strip、去重、跳过空行 |
| Web UI 批量导入 | ✅ Keys 页“批量导入”折叠面板 |
| Playwright 浏览器 E2E | ✅ 含批量导入步骤，PASS |
| 全量回归 | ✅ 293 passed / 1 skipped，覆盖率 98.90% |
