# Implementation Tasks: 生产加固与终局审计

## Phase 1: 事实重建

- [x] T001 [US1] 重建需求追踪矩阵：显式/隐式/验收/非功能需求映射到文件与证据 `workflow_status.md`
- [x] T002 [US4] 扫描仓库真实状态：git status、版本、CI、文档、部署配置 `workflow_status.md`

## Phase 2: 反向审计

- [x] T003 [US1] 对自己最强反驳：伪闭环/浅实现/文档不一致/新环境盲点逐条落点 `docs/PRODUCTION_AUDIT_2026-09-22.md`
- [x] T004 [P] [US1] 全量回归 + ruff + mypy + 文档死链（312 passed / 1 skipped，98.94%）
- [x] T005 [P] [US2] 浏览器/UI 与 API 契约实测（公网 `/health` `/ready` `/v1/models` 翻译/SSE/Web UI）

## Phase 3: 生产验收

- [x] T006 [US3] 单机蓝绿部署：双副本 + gateway + redis 全部 healthy
- [x] T007 [US3] 压测：conc 1/5/10 全 200，0 错 0 429，QPS 6.3/21.8/18.3
- [x] T008 [US3] 零中断：重启单副本 30/30 200；热升级/回滚各 60/60 200

## Phase 4: 规范与收尾

- [x] T009 [US4] Spec Kit：`.specify` 初始化 + 宪法 + 001 规范/计划/任务
- [x] T010 [US4] 生成 `workflow_status.md` 任务链路与证据
- [x] T011 [US1] 生成 HTML 变更报告（上下文/直觉/改动/底部测验）`docs/CHANGE_REPORT_2026-09-22.html`
- [x] T012 [US4] 文档同步：README / CHANGELOG / 审计文档与真实状态一致

## Phase 5: 发布

- [x] T013 [US3] 提交推送仓库并创建发行版
- [x] T014 [US1] CI / Deploy 全绿确认
