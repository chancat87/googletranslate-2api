# Kubernetes 部署 (v2.3.0)

提供原生 K8s 清单，用于多副本滚动发布。`kustomization.yaml` 不包含
`secret.example.yaml`，避免把占位 Secret 直接应用。

## 前置条件

1. 构建并推送应用镜像，然后把 `deployment.yaml` 中的
   `image: lza6/googletranslate-2api:v2.3.0` 换成实际镜像地址和版本。
2. 准备好强随机 `API_MASTER_KEY` 与真实 `GOOGLE_API_KEY`。
3. 集群已安装 nginx Ingress Controller（或改用对应 IngressClass）。

## 部署

```bash
kubectl create secret generic googletranslate-2api-secret \
  --from-literal=GOOGLE_API_KEY=<real-key> \
  --from-literal=API_MASTER_KEY=<strong-random-key>

kubectl apply -k deploy/k8s
kubectl rollout status deployment/googletranslate-2api
```

## 行为

- `maxUnavailable: 0` + `maxSurge: 1`：滚动发布不缩容到零。
- `readinessProbe` 使用 `/ready`，新副本未就绪前不会被 Service 拉入流量。
- `terminationGracePeriodSeconds: 35`，镜像内 uvicorn 使用
  `--timeout-graceful-shutdown 30` 排空存量连接。
- HPA 按 CPU 70% 从 2 扩到 6，默认带 300s 缩容稳定窗口。
- Redis 作为共享缓存/分布式限流/trace 的示例后端；生产可替换为托管 Redis 并改
  `configmap.yaml` 的 `REDIS_URL`。
