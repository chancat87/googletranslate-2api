# CI/CD Pipeline 设计 (v2.11.0)

## 1. 总览

googletranslate-2api 使用 **GitHub Actions** 作为 CI/CD 平台，目标环境为
**Kubernetes (kustomize)**，镜像推送至 **GHCR (ghcr.io)**。核心原则：

- 分支隔离：`feature/*` 只跑 CI；`develop` 合入后自动部署 staging；`main` 合入后经人工审批部署 production
- 左移质量：lint / 格式 / 类型 / 文档链接 / 单元+集成测试 / 浏览器 E2E / K8s schema 全部在合并前完成
- 安全三道闸：Gitleaks（密钥泄漏）+ Trivy（文件系统漏洞）+ SBOM，另有 pip-audit 做 Python 依赖漏洞扫描
- 可回滚：镜像按版本与 commit SHA 打标签，Deployment 使用滚动发布 + `rollout undo` 一键回滚
- 失败可见：CI / Deploy 任一失败自动向 Slack Webhook 推送上下文（仓库、分支、提交、Run URL）

```text
                        +-----------------------------------------------+
                        |               GitHub Actions                  |
                        +-----------------------------------------------+

  feature/*  --push-->  CI (build  quality  test  e2e  security)  --绿-->  PR 合并
                              |
                              v
  develop  --merge-->  CI  --绿-->  Deploy: staging (自动)  -->  ghcr.io/...:staging-<sha>
                              |
                              v
  main  --merge-->  CI  --绿-->  Deploy: production --人工审批(Environment)-->  ghcr.io/...:vX.Y.Z
                              |                                                  |
                              v                                                  v
                    hotfix/*  -->  main (快速通道)                    rollout undo 一键回滚

  Stage Build       : pip/npm 依赖安装 + Docker build 冒烟
  Stage Qualite     : ruff lint / ruff format / mypy / docs 死链
  Stage Tests       : pytest(单元+集成) 覆盖率阈值 97% + Playwright 浏览器 E2E + kubeconform
  Stage Securite    : Gitleaks / Trivy / SBOM / pip-audit
  Stage Deploiement : staging 自动, production 人工审批, rollback 手动任务
  Notifications     : Slack Webhook (CI 失败 / Deploy 失败)
```

## 2. 分支策略

| 分支 | 触发 | CI | 部署 | 说明 |
|---|---|---|---|---|
| `feature/*` | push / PR | 全量 CI | 无 | 开发分支，必须通过 CI 才能合并 |
| `develop` | push / merge | 全量 CI | staging 自动部署 | 集成环境，合入即发布到 staging |
| `main` | push / merge / tag | 全量 CI | production（人工审批） | 主干，禁止直接提交，只接受 PR |
| `hotfix/*` | push / PR | 全量 CI | 按需 | 从 main 拉出，修复后直接合 main，再 cherry-pick 到 develop |

## 3. 各阶段实现

### 3.1 Build

- 文件：[`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
- Python 依赖：`pip install -r requirements-dev.txt pytest-cov ruff mypy prometheus_client`
- 依赖缓存：`actions/setup-python` 的 `cache: pip` + `cache-dependency-path`（requirements.txt / requirements-dev.txt）
- 镜像冒烟：`docker build -t googletranslate-2api .`（验证 Dockerfile 与单测同跑）
- K8s 清单校验：kubeconform `-strict` 校验 `deploy/k8s`

### 3.2 Qualite

- `ruff check`（lint）、`ruff format --check`（格式）、`mypy app main.py`（类型）、`scripts/check_docs_links.py`（文档死链）
- 任一不通过即 Job 失败，阻止合并（分支保护规则中设为 required check）

### 3.3 Tests

- 单元 + 集成：`pytest --cov=app --cov=main --cov-report=term-missing --cov-report=xml`
- 覆盖率阈值：`pytest.ini` 中 `--cov-fail-under=97`（当前实测 98.94%）
- 浏览器 E2E：`npm install && npx playwright install --with-deps chromium && npm run web:ui:e2e`
- 辅助服务：单测使用 `fakeredis` 模拟 Redis；真实 Redis 可选用 `REDIS_URL` 集成测试

### 3.4 Securite

- Gitleaks：扫描提交历史中的密钥泄漏（失败不阻塞，但留下证据，见 `docs/AUDIT_2026-09-22.md`）
- Trivy：文件系统扫描 HIGH/CRITICAL，`ignore-unfixed: true`
- SBOM：`anchore/sbom-action` 生成 SPDX 清单
- pip-audit：扫描 `requirements.txt` / `requirements-dev.txt` 已知漏洞（默认留证不阻塞）

### 3.5 Deploiement

文件：[`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)、
[`scripts/ci/kubectl_deploy.sh`](../scripts/ci/kubectl_deploy.sh)、
[`scripts/ci/kubectl_rollback.sh`](../scripts/ci/kubectl_rollback.sh)

- staging：push `develop` 自动构建并推送 `ghcr.io/<owner>/googletranslate-2api:staging-<sha>`，kubectl 滚动发布到 `staging` 命名空间
- production：push `main` 后进入 `production` Environment，等待人工审批（在仓库 Settings - Environments - production 配置 required reviewers），使用 `vX.Y.Z`（从 `pyproject.toml` 读取）与 `main-<sha>` 双标签
- 回滚：`workflow_dispatch` 手动任务，`kubectl rollout undo` 到指定 revision 或上一版本
- 未配置集群密钥时（`KUBE_CONFIG_*` 为空）自动跳过实际部署，只构建推送镜像，保证新仓库不会因缺密钥而红

## 4. 环境变量与 Secrets

| Secret / Variable | 用途 | 必填 |
|---|---|---|
| `KUBE_CONFIG_STAGING` | base64 编码的 staging kubeconfig | 部署 staging 时 |
| `KUBE_CONFIG_PRODUCTION` | base64 编码的 production kubeconfig | 部署 production 时 |
| `SLACK_WEBHOOK` | Slack 失败通知 Webhook | 通知时 |
| `GITHUB_TOKEN` | 自动注入，用于登录 GHCR（需 packages: write） | 自动 |
| `API_MASTER_KEY` / `GOOGLE_API_KEY` | 应用运行密钥，放在 K8s Secret `googletranslate-2api-secret` | 生产必填 |

## 5. 回滚策略

1. 滚动发布已配置 `maxUnavailable: 0` + `maxSurge: 1`，新副本未就绪不接流量
2. 发布异常通常由 CI 的 `kubectl rollout status` 超时拦截，不会放量
3. 紧急回滚：手动运行 Deploy 工作流（workflow_dispatch 选择 rollback 场景）或执行：

```bash
kubectl rollout undo deployment/googletranslate-2api -n production
kubectl rollout status deployment/googletranslate-2api -n production --timeout=240s
```

4. 指定版本回滚：在 workflow_dispatch 里填 `revision`（`kubectl rollout history deployment/...` 可查）

## 6. 性能优化

- **并行 Job**：`test`、`security-scan`、`bench` 并行运行
- **依赖缓存**：pip 缓存 + 隐式 node_modules（npm install 幂等）
- **并发控制**：`concurrency.cancel-in-progress: true`，同一分支的旧运行自动取消，节省 runner 分钟
- **矩阵**：当前锁定 Python 3.10（与 Dockerfile 一致）；如需扩展，将 `test` Job 改为 matrix（3.10/3.11/3.12），K8s schema 与容器构建保持单份
- **工件**：coverage.xml 作为 artifact 上传，便于后续 Codecov / 覆盖率看板

## 7. 故障排查指南

| 症状 | 常见原因 | 处理 |
|---|---|---|
| pip install 慢/超时 | 缓存未命中或网络抖动 | 检查 pip 缓存 key；重跑 Job |
| Ruff 失败 | 格式/规范不合规 | 运行 `ruff format` 后提交 |
| Mypy 失败 | 类型标注缺失 | 运行 `mypy app main.py` 修复标注 |
| pytest 覆盖率低于 97% | 新代码缺测试 | 补单测；临时调阈值需评审 |
| Playwright E2E 超时 | 未安装浏览器 / 端口占用 | 确认 `playwright install --with-deps chromium`；本地不占用 8091/8899 |
| kubeconform 失败 | K8s 清单不合法 | `kubectl kustomize deploy/k8s` 本地验证后修复 |
| Gitleaks 报泄漏 | 历史 commit 含密钥 | 非阻塞，但需轮换密钥并清理历史 |
| deploy 被跳过 | KUBE_CONFIG_* 未配置 | 在仓库 Settings - Secrets 配置 base64 kubeconfig |
| production 等待审批 | Environment 保护规则 | 配置 required reviewers；审批通过后继续 |
| rollout 卡住 | 镜像拉取失败 / 就绪探针不过 | `kubectl describe pod -n <ns>` 查看事件；确认 Secret/ConfigMap 就绪 |

## 8. 启用清单

1. 仓库 Settings - Actions - General：允许工作流并开启 required status checks
2. 创建 staging / production Environment，production 配置 required reviewers
3. 配置 Secrets：KUBE_CONFIG_STAGING、KUBE_CONFIG_PRODUCTION、SLACK_WEBHOOK
4. 集群预置 Secret：`kubectl create secret generic googletranslate-2api-secret --from-literal=GOOGLE_API_KEY=... --from-literal=API_MASTER_KEY=...`
5. 推送后观察 Actions 页面：CI 绿 - Deploy 绿
