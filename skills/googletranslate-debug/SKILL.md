---
name: googletranslate-debug
description: 排查翻译失败 / 慢 / 限流 / 多 Key 切换 / 熔断，用 X-Trace-Summary、/v1/traces、/metrics 定位。
---

# 调试

- **先看链路摘要**：非流式响应头 `X-Trace-Summary: cache=... upstream=... 123ms key=<hash> retries=...`；流式拿 `X-Trace-Id` 后 `GET /v1/traces/{id}`。
- **502 上游错误**：`upstream=403/400` -> key 失效，检查轮换；`upstream=429` -> 配额，看重试/冷却；`upstream=5xx` -> 上游抖动，重试已兜底。
- **429**：`RATE_LIMIT_ENABLED` 开启时按 IP+key 限流，响应含 `Retry-After`；上游 429 会走多 Key 切换 + 退避。
- **熔断 503**：`/ready` 503，观察连续失败；失败恢复后自动闭合。
- **多 Key**：`GOOGLE_API_KEYS="k1,k2"` 自动切换；`/metrics` 的 `translate_key_switches_total` / `translate_upstream_errors_by_key_hash_total{code}` 定位坏 key（只暴露哈希）。
- **慢**：压测参考 `docs/loadtest-2026-09-22.md`；调 `HTTPX_MAX_CONNECTIONS` / 多 worker / 多 key；生产取消彩色日志(`LOG_FORMAT=json`)。
- **完全不通**：`/health` 是否 200、启动日志是否有弱 key 告警/占位符拒启。
