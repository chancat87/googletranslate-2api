# 代理池轮换 (v2.13.0)

## 1. 解决的问题

Google 上游会按出口 IP 限制高并发。多 Key 只能解决“Key 维度”限额，无法改变同一出口 IP
的并发压力。代理池为每个上游请求分配不同出口 IP，配合多 Key 双维度轮换，降低 429/风控。

## 2. 架构

```text
上游请求 -> ProxyPool.acquire()
         -> 优先未用过 IP -> 全部用过按 health_score 降序 + 冷却最早结束
         -> httpx.AsyncClient(proxy=url) 请求 translate-pa.googleapis.com
成功 -> mark_success(健康分上升)
429/网络失败 -> mark_failure(递增冷却 + 健康分下降) -> KeyPool 切下一 Key 重试
```

双源：

- `residential`：`PROXY_FILE` 每行一个（`host:port` / `user:pass@host:port` / 完整 URL），优先使用
- `free`：`PROXY_FREE_FETCH=true` 时后台周期抓取公共免费代理列表，解析后并发校验（`/generate_204`）再注入

## 3. 配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `PROXY_ENABLED` | false | 总开关；池为空时自动回退直连 |
| `PROXY_FILE` | `data/proxies.txt` | 住宅代理文件 |
| `PROXY_FREE_FETCH` | false | 是否后台抓取免费代理 |
| `PROXY_FREE_REFRESH_SECONDS` | 600 | 抓取/校验周期 |
| `PROXY_FREE_URLS` | 内置 3 源 | 逗号分隔列表 URL |
| `PROXY_MAX_USE_PER_DAY` | 200 | 每代理每日最大使用次数 |
| `PROXY_USE_COOLDOWN_MAP` | `0,10,30,90,300` | 递增冷却秒数 |
| `PROXY_VALIDATE_URL` | `https://www.gstatic.com/generate_204` | 健康校验目标 |
| `PROXY_CONNECT_TIMEOUT` | 8.0 | 走代理的连接超时 |
| `PROXY_REQUEST_TIMEOUT` | 10.0 | 走代理的整体请求超时（免费代理慢，设短值快速换下一个） |
| `PROXY_MAX_INFLIGHT` | 50 | 代理请求并发上限，0=不限 |

## 4. 管理与观测

```bash
curl -H "Authorization: Bearer <KEY>" https://gapi.isrna.cn/v1/admin/proxy
```

返回：总数 / 住宅 / 免费 / 可用 / 冷却 / 分页条目（URL 脱敏为 `host:port`，不泄漏凭据），
每项含 `use_count`、`health_score`、`cooling`、`fails`。

Prometheus 指标：`proxy_uses_total{source}`、`proxy_results_total{source,result}`。

## 5. 注意事项

- 免费代理可用性低，建议住宅代理文件为主源、免费为兜底
- 免费代理抓取会短暂占用少量带宽与连接，生产按需开启
- 代理失效不硬剔除，通过健康分沉底并给恢复机会；连续 3h 未用会被 `reap_free` 清理
- 走代理时每请求独立 `AsyncClient` 连接，连接超时设短值以便快速换下一代理
