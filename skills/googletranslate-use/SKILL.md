---
name: googletranslate-use
description: 用 curl / OpenAI SDK / Cherry Studio 调用翻译 API（流式/非流式/批量/语言检测），含认证与错误码。
---

# 使用

- **认证**：`Authorization: Bearer $API_MASTER_KEY`（多 key 取其一；`1`/空=关闭认证仅限本地）。
- **非流式**：
  ```bash
  curl -s -X POST http://localhost:8088/v1/chat/completions -H 'Content-Type: application/json' \
    -H 'Authorization: Bearer $KEY' \
    -d '{"messages":[{"role":"user","content":"Hello world"}],"target_lang":"zh-CN","stream":false}'
  ```
- **流式**：同上但 `"stream":true`，接收 SSE `chat.completion.chunk` 至 `[DONE]`。
- **批量**：`POST /v1/translate/batch`，`{"texts":[...],"target_lang":"zh-CN"}`，条目级 `ok/error`，整体 200。
- **语言检测**：`POST /v1/translate/detect`（`source=script_heuristic`，推断非官方）。
- **模型别名**：`model=gpt-3.5-turbo` 会被 `MODEL_ALIASES` 映射到默认模型。
- **错误码**：400 参数 / 401 缺认证 / 403 key 无效 / 413 超长 / 422 校验 / 429 限流(带 Retry-After) / 502 上游 / 503 熔断。
