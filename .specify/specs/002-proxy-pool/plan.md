# Implementation Plan: 代理池轮换

## Technology Stack

- Python asyncio + httpx（每请求独立代理连接）
- pydantic-settings 配置 `PROXY_*`
- Prometheus 指标 + 管理端点观测

## Architecture

```text
上游请求 -> ProxyPool.acquire()
         -> 未使用优先 / 健康分 EWMA / 递增冷却 / 每日限额
         -> httpx.AsyncClient(proxy=url, timeout=PROXY_REQUEST_TIMEOUT)
成功 -> mark_success
失败(429/网络/5xx) -> mark_failure + 换代理(PROXY_MAX_ATTEMPTS) / 切 Key
```

## Component Design

### `app/core/proxy_pool.py`
- `ProxyEntry`：健康分、冷却、每日限额、快照脱敏
- `ProxyPool`：双源注入、reap、acquire、mark_success/failure、snapshot
- `free_proxy_fetcher_loop`：后台抓取 + 并发校验 + 过期剔除（生产 E2E 覆盖）

### Provider 接线
- 初始化/关闭代理池与抓取任务
- `_post_with_retry(..., proxy=...)`：独立客户端，代理请求整体超时 10s
- 请求循环按 Key 多代理快速轮换；`_proxy_sem` 控制并发上限

## Security

- 快照不泄漏 user:pass；`.env`/`data/proxies.txt` 不入镜像
- 代理仅作为出口轮换，不改变认证与 Key 池安全边界

## Performance

- 免费代理失败有界：10s 整体超时 + 连接 8s + 最多 N 次换代理
- 并发上限 50 保护上游；生产实测免费代理 QPS 仍 0.1-0.2，需住宅/付费代理

## Risk Mitigation

- 免费代理源失效 → 内置 3 源 + 过期剔除 + 直连回退
- 1 核机器代理校验拖慢就绪 → upgrade.sh 有 120s 超时并留证（生产实测可恢复）
