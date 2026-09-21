# Immersive Translate 上游接入审计 (v2.9.1)

## 结论

**不接入“沉浸式翻译匿名免费上游”。** 用户提供的网络包/扩展源码显示，翻译请求实际打到
`translate-pa.googleapis.com/v1/translateHtml`，与我们项目已使用的 Google 上游相同；
区别只是请求头里带了一个**扩展内置的 Google API Key**。这既不是 Immersive Translate
的公开免费 API，也不是“匿名无限高并发”的独立服务。批量、高频使用这个内置 Key 属于
对第三方凭证的未授权使用，违反 Google 使用条款，且随时会被 Google 吊销/限流，反而破坏稳定性。

## 证据

- `network-log.har`：
  - `POST https://translate-pa.googleapis.com/v1/translateHtml`
  - 请求头包含 `x-goog-api-key`（扩展内置）
  - `Origin: chrome-extension://bpoadfkcbjbfhfodiogcnhhhpibjhbnh`
  - `POST https://lang-detect.immersivetranslate.com/api/predict/batch`
  - 该请求携带扩展 Cookie：`imt-lang`、`_ga`、`immersive_translate_token` 等
- `background.js`（Immersive Translate 1.33.1）：
  - 同时内置 OpenAI/Anthropic/DeepL/Baidu 等官方服务配置
  - 包含账号 PKCE 登录、Token 换取等认证流程
  - 未发现可供第三方服务无限免费调用的公开 API 契约

## 为什么不接入

1. **不是匿名**：Key 固定在扩展包里，Google 侧能追踪来源和配额。
2. **不稳定**：扩展更新/Google 风控即可吊销该 Key，接入后随时断。
3. **不可无限高并发**：该 Key 同样受 Google 配额约束；高频请求只会更快触发 429/封禁。
4. **合规风险**：批量自动化使用第三方扩展内置凭证，属于未授权使用，不纳入本项目。

## 合规接入路径（如果以后要做）

- 用户自己持有 Immersive Translate 官方账号/订阅/API Key，并提供给本项目；
- 或使用其官方开发者 API（如有公开文档）并遵守配额；
- 或继续使用本项目已实现的 Google KeyPool：
  `GOOGLE_API_KEYS`、`GOOGLE_API_KEYS_FILE`、`/v1/admin/keys/bulk`、`/v1/admin/keys/probe`。

## 处理

- 本轮不新增该上游，不把抓包得到的 Key 写入代码/配置。
- 用户提供的 `沉浸式翻译的翻译/` 目录保持未提交，仅作为审计输入。
