# 生产部署验收与审计 (2026-09-22)

## 1. 环境

| 项 | 值 |
|---|---|
| 服务器 | `8.218.136.189`（Debian 12 bookworm，1 vCPU，1.7Gi 内存，49G 磁盘） |
| 域名 | `https://gapi.isrna.cn`（nginx 反代 `127.0.0.1:8088`，UFW 仅放行 80/443） |
| 项目路径 | `/opt/googletranslate-2api`（git tag `v2.13.6`） |
| 运行方式 | Docker Compose 蓝绿生产栈：`gateway`(nginx:8088) + `app-blue`/`app-green` + `redis` |
| 应用镜像 | `ghcr.io/lza6/googletranslate-2api:v2.13.6` |

## 2. 验收清单

| 类别 | 项 | 结果 |
|---|---|---|
| 质量 | 全量回归 | 334+ passed / 1 skipped，覆盖率 98.94% |
| 质量 | ruff / format / mypy / 文档死链 | 全过 |
| CI | main / tag push（test 含浏览器 E2E、Docker、kubeconform） | success |
| 安全 | Gitleaks / Trivy / SBOM / pip-audit | success（历史泄漏 Key 非阻塞留证） |
| Deploy | GHCR 构建推送 `v2.13.6` | success |
| 公网 | `GET /health` | 200，`version: 2.13.6` |
| 公网 | `GET /ready` | 200 |
| 公网 | `GET /v1/models` | 200，`google-translate` |
| 公网 | `POST /v1/chat/completions`（非流式） | 200，译文核验通过 |
| 公网 | `POST /v1/chat/completions`（SSE 流式） | 200，`chunk` + `[DONE]` |
| 公网 | 根路径（`Accept: text/html`） | 200，`text/html` Web UI |
| 压测 | `conc 1/5/10`（真实上游，经网关） | 全 200，0 错 0 429，QPS `6.3/21.8/18.3` |
| 零中断 | 重启 `app-blue` 期间健康检查 | 30/30 全 200 |
| 零中断 | 热升级 `v2.12.0 → v2.12.1` 期间健康检查 | 60/60 全 200 |
| 回滚 | 热回滚 `v2.12.1 → v2.12.0` 期间健康检查 | 60/60 全 200 |
| 压测 | 真实上游直连优先（v2.13.6）conc 50/100/200 | 全 200，0 错 0 429，QPS 18.6/9.9/17.0 |
| 压测 | 缓存命中模式 conc 500 | 全 200，0 错 0 429，QPS 峰值约 57 |
| 代理池 | 生产快照 | 3435 个代理，延迟/健康/冷却可观测 |

## 3. 审计结论

- 仓库工作区干净：除用户未跟踪目录外无未提交改动；`v2.13.6` 已提交、推送、发版
- 密钥安全：`.env` 不入库（`.gitignore` / `.dockerignore` 均排除）；Google Key 全程不明文展示
- 认证安全：`API_MASTER_KEY` 强制校验；`/ready` 就绪探测；未授权请求统一 401
- 运行时安全：镜像非 root 用户、`securityContext.runAsNonRoot`、禁止提权、优雅停机 30s + `stop_grace_period 35s`
- 可观测：`/health`、`/ready`、`/metrics`、`/v1/admin/traces`、日志可查
- 改进建议：并发不足时用 `GOOGLE_API_KEYS` / Web UI 批量导入多 Key；更大吞吐移入 K8s + HPA；需要自动更新时启用 Watchtower

## 4. 运维手册

```bash
# 状态 / 日志
cd /opt/googletranslate-2api
docker compose -f deploy/compose/docker-compose.prod.yml ps
docker compose -f deploy/compose/docker-compose.prod.yml logs -f --tail=100 gateway app-blue app-green

# 升级（零中断） / 回滚（零中断）
bash deploy/upgrade.sh ghcr.io/lza6/googletranslate-2api:v2.13.6
bash deploy/upgrade.sh ghcr.io/lza6/googletranslate-2api:v2.13.5

# 重启/停止/拉起
docker compose -f deploy/compose/docker-compose.prod.yml restart app-blue
docker compose -f deploy/compose/docker-compose.prod.yml down
docker compose -f deploy/compose/docker-compose.prod.yml up -d
```
