# googletranslate-2api 对外 API 文档

> 版本: 1.0.0
> 将 Google Translate 适配为 OpenAI Chat Completions 兼容接口, 支持全语言互转、流式与非流式响应。

---

## 基础信息

| 项目 | 值 |
|------|----|
| Base URL | `http://<host>:8088` |
| 交互式文档 | `http://<host>:8088/docs` (Swagger UI) |
| ReDoc 文档 | `http://<host>:8088/redoc` |
| 协议 | HTTP / HTTPS |
| 请求体格式 | `application/json` |
| 流式响应格式 | `text/event-stream` (SSE) |

## 认证

若服务端 `API_MASTER_KEY` 配置为 `1` 或留空, **跳过认证**。
否则所有 `/v1/*` 接口需在请求头携带 Bearer Token:

```
Authorization: Bearer <API_MASTER_KEY>
```

---

## 接口列表

### 1. 翻译接口 — `POST /v1/chat/completions`

核心接口。取 `messages` 最后一条 `user` 消息作为待翻译文本, 返回翻译结果。

#### 请求参数 (JSON Body)

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `messages` | array | 是 | — | 消息数组, 取**最后一条** `role=user` 的 `content` 为待翻译文本 |
| `model` | string | 否 | `google-translate` | 模型名, 当前仅 `google-translate` |
| `source_lang` | string | 否 | `auto` | 源语言代码, `auto` 自动检测 |
| `target_lang` | string | 否 | 自动判断 | 目标语言代码。留空时: 中文/日/韩/阿/俄输入 → 英文, 其他 → 中文 |
| `stream` | boolean | 否 | `true` | `true` 流式 (SSE), `false` 非流式 (JSON) |

`messages[].content` 可为字符串或 OpenAI 多段数组 (取文本拼接)。

#### 响应

**流式 (`stream=true`, 默认)** — `Content-Type: text/event-stream`

按 OpenAI `chat.completion.chunk` 格式逐块推送:

```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":...,"model":"google-translate","choices":[{"index":0,"delta":{"content":"翻译结果"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk",...,"choices":[{"index":0,"delta":{"content":""},"finish_reason":"stop"}]}

data: [DONE]
```

**非流式 (`stream=false`)** — `Content-Type: application/json`

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "google-translate",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "翻译结果"},
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": -1, "completion_tokens": -1, "total_tokens": -1}
}
```

> `usage` 各字段为 `-1`, 因为翻译接口不消耗 token。

#### 请求示例

**cURL — 流式中→英:**
```bash
curl -N http://localhost:8088/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"你好世界"}]}'
```

**cURL — 非流式英→日:**
```bash
curl http://localhost:8088/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"good morning"}],"target_lang":"ja","stream":false}'
```

**Python (OpenAI SDK):**
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8088/v1", api_key="unused")

# 流式
stream = client.chat.completions.create(
    model="google-translate",
    messages=[{"role": "user", "content": "你好世界"}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)

# 非流式
resp = client.chat.completions.create(
    model="google-translate",
    messages=[{"role": "user", "content": "good morning"}],
    stream=False,
)
print(resp.choices[0].message.content)
```

> 注: OpenAI SDK 无 `target_lang` 字段, 需通过 `extra_body` 传递:
> `client.chat.completions.create(..., extra_body={"target_lang": "ja"})`

---

### 2. 模型列表 — `GET /v1/models`

```json
{
  "object": "list",
  "data": [{"id": "google-translate", "object": "model", "created": 1700000000, "owned_by": "lzA6"}]
}
```

### 3. 健康检查 — `GET /health`

```json
{"status": "ok", "service": "googletranslate-2api", "version": "1.0.0"}
```

### 4. 根路径 — `GET /`

### 5. 链路摘要查询 — `GET /v1/traces/{request_id}` (v1.5.0, 需认证)

只读查询最近一次请求的链路摘要（进程内环形缓冲，上限 `TRACE_STORE_MAXLEN`）：

- 非流式：响应头 `X-Trace-Summary`（`cache=… upstream=… 123ms key=<hash8> retries=…`）
- 流式：响应头 `X-Trace-Id` → `GET /v1/traces/{request_id}` 查询

```bash
curl -H "Authorization: Bearer $API_MASTER_KEY" \
  http://localhost:8088/v1/traces/chatcmpl-xxxxxxxx
```

**隐私**：只返回元数据（缓存命中/上游状态/耗时/Key 哈希/重试/熔断），不含请求原文与明文 Key。不存在返回 404。

### 4.1 多上游 Key 池 (v1.5.0)

配置 `GOOGLE_API_KEYS="key1,key2"`（逗号分隔）：

- 403 / 429 / 网络错误自动切换到下一个 Key，全部耗尽才失败（403 → `upstream_auth_error`）
- 失败 Key 进入冷却（`KEY_FAILOVER_COOLDOWN_SECONDS`，默认 60s），到期前不再优先选用
- `/metrics` 新增 `translate_key_switches_total`、`translate_requests_by_key_hash_total{key,result}`、`translate_upstream_errors_by_key_hash_total{key,code}`、`translate_key_pool_status{key,state}`


返回服务欢迎信息。

---

## 支持的语言代码

完整列表见 [`app/core/languages.py`](app/core/languages.py)。常用:

| 代码 | 语言 | 代码 | 语言 | 代码 | 语言 |
|------|------|------|------|------|------|
| `zh-CN` | 简体中文 | `zh-TW` | 繁体中文 | `en` | 英语 |
| `ja` | 日语 | `ko` | 韩语 | `fr` | 法语 |
| `de` | 德语 | `es` | 西班牙语 | `ru` | 俄语 |
| `ar` | 阿拉伯语 | `pt` | 葡萄牙语 | `it` | 意大利语 |
| `th` | 泰语 | `vi` | 越南语 | `hi` | 印地语 |

源语言填 `auto` 自动检测, 其余码直接透传 Google。未列出的代码交给上游校验, 不支持时返回 400。

---

## 状态码

| 状态码 | 含义 | 触发场景 |
|--------|------|----------|
| `200` | 成功 | 翻译完成 (流式 SSE 或非流式 JSON) |
| `400` | 请求参数无效 | JSON 格式错误 / 缺少 messages / 用户消息为空 / 语言代码不支持 |
| `401` | 未认证 | 未携带或缺少 Authorization 头 |
| `403` | 认证失败 | Bearer Token 错误 |
| `500` | 服务器内部错误 | 服务端未捕获异常 |
| `502` | 上游翻译服务错误 | **仅非流式**: Google 接口返回非 200 |

### 错误响应格式 (统一)

```json
{
  "error": {
    "message": "具体错误描述",
    "type": "invalid_request_error"
  }
}
```

`type` 取值: `invalid_request_error` (400/401/403)、`upstream_error` (502)、`internal_error` (500)。

> **流式响应中的上游错误**: 由于 SSE 已建立连接 (HTTP 200), 上游错误会以错误 chunk 形式返回, 形如 `data: {"choices":[{"delta":{"content":"翻译失败 (4xx): ..."},"finish_reason":"stop"}]}` 后跟 `data: [DONE]`。

---

## 自动语言路由规则

当 `target_lang` 留空时, 服务端根据输入文本字符判断目标语言:

| 输入文本含 | 自动目标语言 |
|-----------|------------|
| 中文 (`一`-`鿿`) | `en` 英文 |
| 日文假名 | `en` 英文 |
| 韩文 (`가`-`힯`) | `en` 英文 |
| 阿拉伯文 | `en` 英文 |
| 西里尔文 (俄语等) | `en` 英文 |
| 其他 / 拉丁字母 | `zh-CN` 中文 |

**建议**: 需要精确控制方向时, 显式指定 `source_lang` 和 `target_lang`。

---

## 部署

### Docker

```bash
docker build -t googletranslate-2api .
docker run -p 8088:8000 -e GOOGLE_API_KEY=your_key googletranslate-2api
```

### 直接运行

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 环境变量

| 变量 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `GOOGLE_API_KEY` | 是* | — | Google Translate API 密钥（*设置 `GOOGLE_API_KEYS` 后可省略） |
| `GOOGLE_API_KEYS` | 否 | — | 多上游 Key 池（逗号分隔），403/429/网络自动切换；缺省回退 `GOOGLE_API_KEY` |
| `KEY_FAILOVER_COOLDOWN_SECONDS` | 否 | 60 | Key 失败冷却秒数 |
| `TRACE_STORE_MAXLEN` | 否 | 512 | 链路摘要环形缓冲上限 |
| `HTTPX_MAX_CONNECTIONS` | 否 | 0(自动) | HTTPX 上游连接池上限 (0=max(10, BATCH_MAX_CONCURRENCY+5))，高并发可调大 |
| `HTTPX_MAX_KEEPALIVE_CONNECTIONS` | 否 | 0(自动) | HTTPX 连接池 keepalive 上限 (0=max(5, BATCH_MAX_CONCURRENCY)) |
| `API_MASTER_KEY` | 否 | — | 主密钥; `1` 或空表示关闭认证 |
| `NGINX_PORT` | 否 | `8088` | 对外暴露端口 |
| `API_REQUEST_TIMEOUT` | 否 | `60` | 上游请求超时 (秒) |

---

## OpenAI 兼容性说明

本接口**部分兼容** OpenAI Chat Completions:

- ✅ `POST /v1/chat/completions` 路径与基本字段
- ✅ `GET /v1/models`
- ✅ 流式 `chat.completion.chunk` 与非流式 `chat.completion` 结构
- ✅ 可直接用 OpenAI SDK / 任意支持 OpenAI 的客户端
- ⚠️ 翻译语义非对话语义: 仅取最后一条用户消息翻译, 忽略 `system`/历史消息
- ⚠️ 不支持 `temperature`、`top_p`、`max_tokens` 等采样参数 (传入即忽略)
- ⚠️ `usage` 为占位 `-1`, 不计费

翻译扩展字段 (`source_lang` / `target_lang`) 非 OpenAI 标准, 通过 `extra_body` 传递。


---

## 错误信封统一（含 422）

所有错误响应（含 400/401/403/413/422/429/500/502/503）统一为：

```json
{
  "error": {
    "message": "可读中文描述",
    "type": "invalid_request_error | rate_limit_error | upstream_error | upstream_auth_error | internal_error | upstream_unavailable"
  }
}
```

- `422`（Pydantic 校验失败）额外带 `detail` 数组（字段级明细，含请求者自身输入回显）
- `429`（限流开启时）带 `Retry-After` 头（实际等待秒数，按令牌桶回填计算）
- `502` 中 `upstream_auth_error` 表示上游 403（API Key 无效/失效，永久性凭证错误）
- 流式路径的错误以 SSE 错误 chunk 返回（HTTP 200 + `[DONE]`），文案为白名单通用文案

## v1.2.0 补充（2026-09-21）

### 新端点
- `POST /v1/translate/detect` — 轻量语言检测（脚本推断，`source=script_heuristic`）
- `GET /metrics` — Prometheus 指标（运维用，建议网关层做访问控制）

### 新错误码
- `422`：请求体校验失败（含 Pydantic 校验），统一信封 `{error:{message,type,detail}}`
- `429`：触发限流（`RATE_LIMIT_ENABLED=true` 时）+ `Retry-After`（**实际等待秒数**，按令牌桶回填计算；若在 nginx 层启用 `limit_req`，请加 `limit_req_status 429;` 保持语义一致）
- `503`：熔断打开 / 上游不可用（/ready 与 chat/completions 均可能）

### 流式兼容增强
- 请求携带 `stream_options: {"include_usage": true}` 时，流末尾追加一个 `choices: []` + `usage` 的 `chat.completion.chunk`
- `model` 支持 `MODEL_ALIASES` 映射（如 `gpt-3.5-turbo` → `google-translate`）
- 批量响应条目新增可选 `error` 字段（`timeout` / `upstream_<code>` / `upstream_network`），向后兼容

### 行为增强
- 上游重试（指数退避 + 抖动，仅网络异常/429/5xx；4xx 不重试）
- 熔断：连续失败快速失败，/ready 联动
- 批量整体 deadline：`BATCH_DEADLINE_SECONDS`，超时条目标记 `error=timeout`
