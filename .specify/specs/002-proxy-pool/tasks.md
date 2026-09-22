# Implementation Tasks: 代理池轮换

## Phase 1: 核心实现

- [x] T001 [FR-001] 双源代理池：文件 + 免费抓取注入 `app/core/proxy_pool.py`
- [x] T002 [FR-002] 智能分配：未使用优先 + 健康分 EWMA + 递增冷却 + 每日限额
- [x] T003 [FR-003] Provider 接线：每请求代理连接、失败快速换代理、Key 切池

## Phase 2: 保护与观测

- [x] T004 [FR-004] PROXY_REQUEST_TIMEOUT(10s) + PROXY_MAX_INFLIGHT(50)
- [x] T005 [FR-005] GET /v1/admin/proxy + Prometheus 指标

## Phase 3: 验证

- [x] T006 单元/集成测试（轮换/冷却/健康/脱敏/接线/超时/并发信号量）
- [x] T007 全量回归 334+ / 覆盖率 ≥97%
- [x] T008 生产升级零中断（60/60 200）与代理快照
- [x] T009 生产分层压测（conc 1/10/50/100/200），如实披露免费代理 QPS 0.1-0.2

## Phase 4: 发布

- [x] T010 提交推送并发布 v2.13.0/1/2/3
- [x] T011 文档同步：README / CHANGELOG / PROXY_POOL.md / Spec Kit 002
