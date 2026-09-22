#!/usr/bin/env bash
# kubectl_deploy.sh - 用 kubectl/kustomize 部署 googletranslate-2api
# 用法: kubectl_deploy.sh <namespace> <image>
# 依赖: KUBECONFIG_B64 环境变量(base64 编码的 kubeconfig), 未设置则使用默认 kubeconfig
set -euo pipefail

NS="${1:?namespace 必填}"
IMG="${2:?image 必填}"

if [ -n "${KUBECONFIG_B64:-}" ]; then
  mkdir -p "$HOME/.kube"
  echo "$KUBECONFIG_B64" | base64 -d > "$HOME/.kube/config"
  chmod 600 "$HOME/.kube/config"
fi

command -v kubectl >/dev/null 2>&1 || { echo "kubectl 未安装" >&2; exit 2; }

echo "==> namespace: $NS  image: $IMG"
kubectl get namespace "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS"
kubectl apply -k deploy/k8s -n "$NS"
kubectl set image deployment/googletranslate-2api app="$IMG" -n "$NS"
kubectl rollout status deployment/googletranslate-2api -n "$NS" --timeout=240s
kubectl get pods -n "$NS" -l app.kubernetes.io/name=googletranslate-2api
echo "==> deploy 完成: $NS"
