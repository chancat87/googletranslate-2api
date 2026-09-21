# googletranslate-2api 使用教程 (v2.0.0)

> 面向小白与进阶用户。完整参数见 `API_DOCS.md`，规划台账见 `计划文档/`。

## 一、30 秒看懂它是什么

这是一个「翻译网关」：把 Google 翻译包成 OpenAI `v1/chat/completions` 格式。
任何支持 OpenAI API 的客户端，把 `base_url` 指向本服务，就能用翻译代替聊天。

## 二、快速开始（新手路径）

### 1. 准备环境

- Python 3.10+（Windows 可用 `py -3.10 --version` 确认）
- 一个可用的 Google 翻译网页版 API Key（从浏览器 DevTools 的 `translateHtml` 请求头 `x-goog-api-key` 获取）

### 2. 启动

Windows：

```powershell
start.ps1        # 或双击 start-dev.bat
```

脚本会自动：创建 `.venv` → 安装依赖 → 校验 `.env` → 启动服务。
启动后访问：

- Web UI: `http://127.0.0.1:8088/app`
- API: `http://127.0.0.1:8088`
- 文档: `http://127.0.0.1:8088/docs`
- 管理面板: `http://127.0.0.1:8088/admin`

Docker：

```bash
cp .env.example .env   # 填 GOOGLE_API_KEY
docker compose up -d --build
```

### 3. 第一次翻译

```bash
curl -X POST http://127.0.0.1:8088/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello world"}],"target_lang":"zh-CN","stream":false}'
```

流式：

```bash
curl -N -X POST http://127.0.0.1:8088/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Good morning"}],"target_lang":"zh-CN","stream":true}'
```

## 三、进阶用法

### 批量翻译

```bash
curl -X POST http://127.0.0.1:8088/v1/translate/batch \
  -H "Content-Type: application/json" \
  -d '{"texts":["apple","banana"],"target_lang":"zh-CN"}'
```

### 语言检测

```bash
curl -X POST http://127.0.0.1:8088/v1/translate/detect \
  -H "Content-Type: application/json" \
  -d '{"text":"hello world"}'
```

### 多上游 Key 池

`.env` 配 `GOOGLE_API_KEYS="k1,k2,k3"`，403/429/网络错误自动切换，失败 Key 冷却 60s。

### 共享缓存

```dotenv
CACHE_BACKEND=redis
REDIS_URL=redis://127.0.0.1:6379/0
```

Redis 不可用时自动回退内存缓存，服务不中断。

### 分布式限流

```dotenv
RATE_LIMIT_ENABLED=true
RATE_LIMIT_BACKEND=redis   # 多副本一致
```

### SSE 心跳

```dotenv
SSE_HEARTBEAT_INTERVAL=30   # 空闲 30s 发一次 ping, 防止网关掐断慢连接
```

### 告警

`prometheus/alerts.yml` 提供 5 条告警规则（403/错误率/Key 切换/限流/失败占比），配合 Prometheus + Alertmanager 使用。

## 四、管理面板

浏览器打开 `http://127.0.0.1:8088/admin`，填入 `API_MASTER_KEY` 后：

- 总览：版本、运行时长、缓存、Key 池、指标、链路记录数
- Keys：查看/新增/移除上游 Key（只显示哈希摘要）
- 用量：按 Key 统计成功/失败/错误码
- 最近请求：最近 30 条链路摘要（缓存/上游/耗时/结果）
- 自检：一键调用健康检查 + 真实翻译

## 五、故障排查 FAQ

| 现象 | 原因/处理 |
|---|---|
| 启动报「GOOGLE_API_KEY 未配置」 | `.env` 缺少 Key 或仍是占位符 |
| 翻译返回 502 `upstream_auth_error` | 上游 Key 无效/失效，换 Key 或走 `POST /v1/admin/keys` 热增 |
| 一直 429 | 应用限流或上游配额；先看 `/v1/admin/overview` 的限流计数 |
| 流式被网关掐断 | 开 `SSE_HEARTBEAT_INTERVAL` |
| 多 worker 下 `/v1/traces` 查不到 | trace 默认进程内；开 `TRACE_BACKEND=redis` |
| 想测并发 | `python scripts/loadtest.py --mode cache` / `--mode upstream` |
| 想自动验收 | `python scripts/e2e_smoke.py --url http://127.0.0.1:8088` |

## 六、相关文档

- [API 文档](../API_DOCS.md)
- [压测报告](loadtest-2026-09-22.md)
- [验收报告](ACCEPTANCE_2026-09-22.md)
- [审计报告](AUDIT_2026-09-22.md)
- [密钥轮换](rotate-key.md)
