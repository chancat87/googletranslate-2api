# Feature Specification: 代理池轮换 (proxy-pool)

**Feature Branch**: `002-proxy-pool`

**Created**: 2026-09-22

**Status**: Accepted

**Input**: 上游按出口 IP 高并发风控 → 需每请求轮换出口 IP 缓解

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 运维按需开代理池 (Priority: P1)

运维配置 `PROXY_ENABLED=true` 后，上游请求每请求使用不同出口 IP；代理故障自动冷却/降级，无代理时回退直连。

**Independent Test**: 单测 + 生产 `/v1/admin/proxy` 快照（总数/可用/健康分）+ Prometheus 指标。

**Acceptance Scenarios**:

1. **Given** 代理池启用且有可用代理，**When** 翻译请求，**Then** 每请求换出口且成功/失败回写健康分
2. **Given** 代理全部失效，**When** 翻译请求，**Then** 降级直连或返回可读错误，不无限挂起

---

### User Story 2 - 运维观测轮换成效 (Priority: P2)

通过 `GET /v1/admin/proxy` 查看池总量/住宅/免费/冷却/健康分与分页条目（脱敏 host:port）。

**Independent Test**: 端点单测 + 生产快照。

**Acceptance Scenarios**:

1. **Given** 代理池有数据，**When** 调用端点，**Then** 返回脱敏 URL 与统计信息

---

### User Story 3 - 高并发轮换实测 (Priority: P1)

线上并发压测验证轮换是否能缓解 IP 风控；用 `PROXY_REQUEST_TIMEOUT` / `PROXY_MAX_INFLIGHT` 保证失败有界。

**Independent Test**: 生产分层压测（conc 1/10/50/100/200）并记录 QPS/错误/429。

**Acceptance Scenarios**:

1. **Given** 免费代理池 3500+ 个，**When** 压测，**Then** 观察轮换生效与真实 QPS（当前实测约 0.1-0.2，未达 200/s，如实披露）

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 住宅文件 + 免费抓取双源注入
- **FR-002**: 智能分配（未使用优先 + 健康分 EWMA + 递增冷却 + 每日限额）
- **FR-003**: 每请求走独立代理连接；失败快速轮换（PROXY_MAX_ATTEMPTS）
- **FR-004**: 请求超时有界（PROXY_REQUEST_TIMEOUT）与并发上限（PROXY_MAX_INFLIGHT）
- **FR-005**: `/v1/admin/proxy` 快照 + Prometheus 指标

## Success Criteria *(mandatory)*

- **SC-001**: 代理池可用、轮换可观测、失败有界
- **SC-002**: 全量回归保留 334+，覆盖率 ≥97%
- **SC-003**: 生产升级零中断（60/60 200）
- **SC-004**: 诚实披露高并发边界（免费代理无法到 200/s）

## Out of Scope

- 住宅/付费代理清单由用户提供后调参复测
- 多 Key 与代理双维度并发压测在提供清单后执行
