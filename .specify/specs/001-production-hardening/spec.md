# Feature Specification: 生产加固与终局审计 (production-hardening)

**Feature Branch**: `001-production-hardening`

**Created**: 2026-09-22

**Status**: Accepted

**Input**: 完整上下文需求重审 + Spec Kit 规范化 + 终局闭环审计

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 调用方一次接入成功 (Priority: P1)

外部调用方拿到 Base URL 与 Key 后，按文档一次调用即可完成认证与非流式/流式翻译，错误时有明确、一致的状态码与错误信息。

**Why this priority**: 这是产品核心价值，任何伪实现或文档不一致都会直接破坏接入体验。

**Independent Test**: 用示例 curl/httpx 调用 `/v1/chat/completions`（含 stream 与非 stream）、`/v1/translate/batch`、`/v1/models`，断言 200 与结构。

**Acceptance Scenarios**:

1. **Given** 正确的 Bearer Key，**When** 提交非流式翻译，**Then** 返回 OpenAI 兼容结构（`choices[0].message.content`、`usage`）
2. **Given** 正确的 Bearer Key，**When** 提交流式翻译，**Then** 返回 SSE `data:` chunk 并以 `data: [DONE]` 结束
3. **Given** 缺失/错误 Key，**When** 调用任意受保护端点，**Then** 返回 401 且错误信息稳定

---

### User Story 2 - Web UI 管理员可用 (Priority: P1)

浏览器打开根路径即可进入 UI；翻译工作台、总览、Key 池（含批量导入/验证）、用量、最近请求均与后端真实打通。

**Why this priority**: 运营与自检依赖 UI 真实反馈，按钮后必须有结果与错误提示。

**Independent Test**: 浏览器 E2E（`npm run web:ui:e2e`）+ 各管理端点 curl 实测。

**Acceptance Scenarios**:

1. **Given** 浏览器访问 `/`，**When** 加载，**Then** 返回 `text/html` 的 UI 且无外部依赖
2. **Given** 管理员输入 Key，**When** 添加/批量导入/验证，**Then** 状态真实反映（成功/失败列表）

---

### User Story 3 - 部署方零中断升级 (Priority: P1)

运维在单机 Docker 上执行 `deploy/upgrade.sh <image>` 或 Watchtower 自动更新时，服务对外始终可用，支持一键回滚。

**Why this priority**: 已在生产运行，中断即事故。

**Independent Test**: 升级/回滚期间并发打 `/health`，断言 100% 200；`docker compose ps` 全 healthy。

**Acceptance Scenarios**:

1. **Given** 双副本蓝绿栈运行，**When** 滚动升级到新镜像，**Then** 健康检查 60/60 200
2. **Given** 新版本异常，**When** 指定旧镜像回滚，**Then** 健康检查 60/60 200 且版本切回

---

### User Story 4 - 新开发者按文档跑通 (Priority: P2)

新环境按 README/启动脚本（`start-dev.bat` / `start.ps1`）即可运行；无 Key 时自动 DEMO 模式可用。

**Why this priority**: 降低上手门槛，避免“靠猜”的隐性前提。

**Independent Test**: 文档命令逐条复核 + 全量回归 + 文档死链检查。

**Acceptance Scenarios**:

1. **Given** 无 `.env`，**When** 运行启动脚本，**Then** 自动创建 `.env` 并进入 DEMO 模式启动
2. **Given** `.env` 含真实 Key，**When** 启动脚本，**Then** 生产模式启动并自动打开 Web UI

---

### Edge Cases

- 空文本 / 超长文本 / 不支持语言 / 非法 JSON / 缺失必填字段 → 400/422/413 明确错误
- 上游超时 / 429 / 5xx → 重试 + 熔断 + 单飞，返回可读错误而非裸连接异常
- 无 Key 用户 → DEMO 模式降级且 UI 明示当前为演示
- 升级中断 / 镜像拉取失败 / readiness 不过 → `upgrade.sh` 超时失败并提示，旧副本继续服务
- 多 Key 池中单 Key 失效 → 自动切换，不泄露明文

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `/v1/chat/completions` 非流式与流式翻译，OpenAI 兼容
- **FR-002**: `/v1/translate/batch` 批量翻译；`/v1/models` 模型列表
- **FR-003**: Bearer 认证，`API_MASTER_KEY` 缺失/过弱时告警但仍可启动（DEMO 除外）
- **FR-004**: `/v1/admin/*` Key 池增删、批量导入、probe 自检、用量、trace
- **FR-005**: WebSocket `/v1/ws/translate` 分片翻译网关
- **FR-006**: 缓存/限流/熔断/单飞/用量存储；Redis 可切换与降级
- **FR-007**: 无 Key DEMO_MODE 启动与 UI 明示
- **FR-008**: CI/CD 全链路与蓝绿零中断升级/回滚

### Key Entities

- **KeyPool**: 多 Key 状态、冷却、负载
- **TraceStore / UsageStore**: 最近请求与按 Key 用量
- **Cache**: 翻译缓存（memory/redis），trace 与乐观并发
- **Deployment**: 双副本蓝绿 + gateway + redis

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 一次调用即可跑通非流式/流式/批量/模型，错误码稳定
- **SC-002**: 覆盖率 ≥ 97%（实测 98.94%），全部测试绿
- **SC-003**: 压测 0 错 0 429，QPS 随并发提升
- **SC-004**: 升级/回滚期间健康检查 100% 200
- **SC-005**: 文档（README/API/部署/排障/审计）与真实行为一致

## Assumptions

- 仅保留 Google 上游，不接第三方扩展内置 Key（已审计，见 `docs/IMMERSIVE_TRANSLATE_AUDIT.md`）
- 生产服务器单机 1 核 1.7G，`APP_CPUS=1`/`APP_WORKERS=1`，双副本可承载当前流量
- 真实 Google Key 仅在服务器 `.env`，不在仓库/镜像/文档展示
