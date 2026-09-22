#!/usr/bin/env bash
# upgrade.sh - 单机零中断滚动升级/回滚 (nginx 蓝绿网关 + 双 app 副本)
#
# 用法:
#   升级到指定镜像: ./deploy/upgrade.sh ghcr.io/lza6/googletranslate-2api:v2.12.0
#   升级到 latest:  ./deploy/upgrade.sh
#   回滚到旧镜像:   ./deploy/upgrade.sh ghcr.io/lza6/googletranslate-2api:v2.11.1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/deploy/compose/docker-compose.prod.yml"
NEW_IMAGE="${1:-ghcr.io/lza6/googletranslate-2api:latest}"
READY_URL="http://127.0.0.1:8000/ready"
WAIT_SECONDS=120

if ! command -v docker >/dev/null 2>&1; then
  echo "docker 未安装" >&2
  exit 2
fi

wait_ready() {
  local svc="$1"
  local deadline=$(( $(date +%s) + WAIT_SECONDS ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if docker compose -f "$COMPOSE_FILE" exec -T "$svc" python -c \
        "import urllib.request;urllib.request.urlopen('$READY_URL',timeout=2)" >/dev/null 2>&1; then
      echo "==> $svc 就绪"
      return 0
    fi
    echo "==> 等待 $svc 就绪..."
    sleep 3
  done
  echo "==> ERROR: $svc 未在 ${WAIT_SECONDS}s 内就绪" >&2
  return 1
}

echo "==> 目标镜像: $NEW_IMAGE"
echo "==> 拉取镜像 (失败则本地构建) ..."
docker pull "$NEW_IMAGE" >/dev/null 2>&1 || docker compose -f "$COMPOSE_FILE" build app-blue app-green

for svc in app-blue app-green; do
  echo "==> 滚动重建 $svc"
  APP_IMAGE="$NEW_IMAGE" docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate "$svc"
  wait_ready "$svc"
done

echo "==> 当前运行状态:"
docker compose -f "$COMPOSE_FILE" ps
echo "==> 升级完成: $NEW_IMAGE"
