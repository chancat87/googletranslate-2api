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
