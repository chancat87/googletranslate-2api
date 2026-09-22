# 热更新 / 零中断升级 (v2.12.0)

## 1. 现状结论

googletranslate-2api 已经具备“不中断服务更新”的基础能力：

- Dockerfile：`STOPSIGNAL SIGTERM` + uvicorn `--timeout-graceful-shutdown 30`，停容器时排空存量连接
- 健康检查：容器 `HEALTHCHECK /health`，K8s 使用 `/ready` 就绪探针
- K8s 部署：`maxUnavailable: 0` + `maxSurge: 1`，滚动发布不缩容到零，见 `deploy/k8s/`
- 单机 compose 旧版：只有一个 `app` 副本，`docker compose up -d` 重建时会短暂中断

因此本次新增**单机零中断部署方案**：nginx 蓝绿网关 + 双 app 副本 + 可选 Watchtower 自动更新，行为对齐参考项目 new-api 的 Docker Compose + Watchtower 方案，并解决其单副本重建的短暂中断问题。

## 2. 架构

```text
                        ┌──────────────┐
   客户端 ──8088──►     │ nginx gateway │  (proxy_next_upstream 自动重试)
                        └──────┬───────┘
                  ┌────────────┴─────────────┐
                  ▼                          ▼
           ┌──────────────┐          ┌──────────────┐
           │  app-blue    │          │  app-green   │
           │  v2.12.0     │          │  v2.11.1     │
           └──────────────┘          └──────────────┘
                  └──────────┬─────────────┘
                             ▼
                     ┌──────────────┐
                     │    redis     │
                     └──────────────┘

升级时一次只重建一个 app 副本；重建期间该副本短暂不可用，nginx 自动重试到另一个副本，客户端无感。
```

## 3. 快速开始 (单机生产)

```bash
# 1) 准备 .env (与根目录 docker-compose 共用同一份)
cp .env.example .env

# 2) 启动生产栈 (nginx + 双 app + redis)
APP_IMAGE=ghcr.io/lza6/googletranslate-2api:latest \
  docker compose -f deploy/compose/docker-compose.prod.yml up -d

# 3) 验证
docker compose -f deploy/compose/docker-compose.prod.yml ps
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/ready
```

## 4. 升级 / 回滚

```bash
# 升级到指定版本 (逐个滚动重建, 服务不中断)
./deploy/upgrade.sh ghcr.io/lza6/googletranslate-2api:v2.12.0

# 升级到 latest
./deploy/upgrade.sh

# 回滚: 同一入口指定旧镜像
./deploy/upgrade.sh ghcr.io/lza6/googletranslate-2api:v2.11.1
```

脚本流程：拉取/构建新镜像 → 重建 `app-blue` → 等待 `/ready` → 重建 `app-green` → 等待 `/ready` → 输出状态。

## 5. 自动更新 (Watchtower)

```bash
docker compose -f deploy/compose/docker-compose.watchtower.yml up -d
```

- 只更新带 `com.centurylinklabs.watchtower.enable=true` 标签的 app 副本
- 默认每天轮询一次；可改 `WATCHTOWER_POLL_INTERVAL`（秒）
- 自动清理旧镜像（`WATCHTOWER_CLEANUP=true`）
- 双副本逐个重建，nginx 蓝绿网关兜底，服务不中断

## 6. 为什么不直接 `docker compose up -d`

单副本 compose 直接重建会先停旧容器再起新容器，几秒内返回 502。双副本 + nginx
`proxy_next_upstream` 后，任一时刻至少一个副本在服务，客户端无感知。K8s 用户继续走
`deploy/k8s` 的滚动发布即可，两者互不冲突。

## 7. 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `upgrade.sh` 等待就绪超时 | 新镜像未构建/`.env` 缺 Key | 查看 `docker compose logs <svc>`；确认 `.env` 与 `DEMO_MODE` |
| 升级后 `503` | 两个副本同时未就绪 | 等健康检查通过；检查 redis 是否 healthy |
| Watchtower 不更新 | 标签未命中 | 确认 app 服务有 `com.centurylinklabs.watchtower.enable=true` |
| nginx 启动失败 | 上游主机名未解析 | 确保先 `up -d` 起 app-blue/app-green 再起 gateway |
| 回滚失败 | 旧镜像 tag 不存在 | 用 `docker images` 确认本地/远端旧 tag |
