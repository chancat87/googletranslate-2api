#!/usr/bin/env bash
# kubectl_rollback.sh - 回滚 googletranslate-2api Deployment
# 用法: kubectl_rollback.sh <namespace> [revision]
# 省略 revision 时回滚到上一个可用版本
set -euo pipefail

NS="${1:?namespace 必填}"
REV="${2:-}"

if [ -n "${KUBECONFIG_B64:-}" ]; then
  mkdir -p "$HOME/.kube"
  echo "$KUBECONFIG_B64" | base64 -d > "$HOME/.kube/config"
  chmod 600 "$HOME/.kube/config"
fi

command -v kubectl >/dev/null 2>&1 || { echo "kubectl 未安装" >&2; exit 2; }

if [ -n "$REV" ]; then
  echo "==> 回滚 $NS 到 revision $REV"
  kubectl rollout undo deployment/googletranslate-2api -n "$NS" --to-revision="$REV"
else
  echo "==> 回滚 $NS 到上一个版本"
  kubectl rollout undo deployment/googletranslate-2api -n "$NS"
fi

kubectl rollout status deployment/googletranslate-2api -n "$NS" --timeout=240s
echo "==> 回滚完成: $NS"
