# SECURITY

## 安全模型 (Security Model)

`googletranslate-2api` 是一个把 Google Translate 网页接口封装为 OpenAI 兼容 API 的本地/自托管网格网关。

- **认证层**：`API_MASTER_KEY`（支持逗号分隔多 key，常量时间比较 `hmac.compare_digest`）；缺失或为 `1` 时认证关闭（仅限本地调试）；弱 key/默认示例 key 启动时告警或拒启（`ALLOW_WEAK_API_KEY`）
- **输入边界**：`MAX_TEXT_LENGTH` 限制文本长度（413）；`messages` 结构校验（400/422）；SSE 错误 chunk 只输出白名单通用文案（P3-5），不带上游/用户原始文本
- **上游密钥**：`GOOGLE_API_KEY` / `GOOGLE_API_KEYS`（多 key 池，403/429/400/transport 自动切换）；错误响应不含上游内部头/堆栈/明文 key，指标与链路摘要只暴露 key 哈希
- **限流**：`RATE_LIMIT_ENABLED`（默认关），IP + 认证 key 双维度令牌桶，429 + `Retry-After` 精确值；多副本需网关层 `limit_req`
- **失败兜底**：指数退避重试（仅网络异常/429/5xx）、滑动窗口熔断（/ready 联动 503）、批量整体 deadline
- **认证度量**：`/metrics` 暴露请求/上游错误/缓存/限流/Key 池状态（按运维约定，网关层控制访问）

## 已知边界 (Known Boundaries)

1. 上游 `translate-pa` 为**非官方接口**，无 SLA，参数可能变化；已用重试/熔断/502 兜底
2. 进程内缓存/限流在多 worker / 多副本下不共享（水平扩展需 Redis）
3. 历史 commit 曾包含真实上游 key 的旧 .env 文本：**需在谷歌侧轮换该 key**，并（经你确认后）用 `git filter-repo` 清理（见 `docs/rotate-key.md`）
4. `/metrics` 与 `/docs` 按约定由网关层做访问控制（源码默认不内置强认证，因多数自托管部署在可信内网）

## 漏洞上报
私有仓库自托管用途：直接以 issue / 邮件提交给维护者（lza6），描述影响与复现即可。
