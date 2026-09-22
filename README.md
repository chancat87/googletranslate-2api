# 🌍 googletranslate-2api 🚀

![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)
![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)
![Docker](https://img.shields.io/badge/docker-ready-brightgreen.svg)
![GitHub Repo](https://img.shields.io/badge/GitHub-lzA6/googletranslate--2api-green?logo=github)

**一行代码，为你的应用注入强大的免费谷歌翻译能力，完全兼容 OpenAI API 格式！**

> "语言不应成为思想的牢笼，而翻译则是打破边界的钥匙。本项目致力于让知识在全球范围内自由流动。"

---

## ✨ 项目概览

`googletranslate-2api` 是一个轻量级、高性能的代理服务，其核心功能是**将谷歌翻译服务封装成与 OpenAI `v1/chat/completions` 格式完全兼容的 API 接口**。

这意味着任何支持 OpenAI API 的应用程序、客户端或代码库都可以**无缝、零成本**地接入谷歌翻译服务。无需修改现有代码，只需将 API 的 `base_url` 指向本服务即可。

这就像为传统设备安装了一个智能转换器，瞬间解锁现代化功能！🎛️✨

---

## 🎯 核心优势

*   **💰 完全免费**：基于谷歌翻译网页版 API，提供高质量的翻译服务，无需支付商业 API 费用
*   **🔌 无缝兼容**：完美模拟 OpenAI 的 `chat/completions` 接口，**同时支持流式（SSE）与非流式（JSON）响应**
*   **🌍 全语言互转**：显式 `source_lang` / `target_lang` 支持 100+ 语言任意方向互转，含智能自动检测
*   **⚡ 一键部署**：通过 Docker Compose 快速部署，简单高效
*   **🧠 智能语言识别**：自动检测输入语言并智能选择翻译方向（中/日/韩/阿/俄 ↔ 英，其他 → 中文），也支持手动指定
*   **🏗️ 稳定架构**：基于 FastAPI 和 Nginx 构建，具备优秀的性能和并发处理能力
*   **🔁 多 Key 自动切换 (v1.5.0)**：`GOOGLE_API_KEYS` 多上游 Key 池，403/429/网络错误自动降级，单 Key 失效不再全挂
*   **🔍 链路摘要 (v1.5.0)**：`X-Trace-Summary` / `/v1/traces/{request_id}` 把缓存命中、上游耗时、所用 Key、重试/熔断状态一目了然，小白也能排障
*   **🖥️ Web UI (v2.5.0)**：浏览器打开根路径 `/` 即进入中文界面（翻译工作台 + 总览 / Key 池 / 用量 / 最近请求），`/app`、`/admin` 兼容共用同一套页面
*   **📖 中文教程 (v2.0.0)**：见 `docs/TUTORIAL.md`，新手到进阶一站式
*   **📊 用量与配额 (v2.1.0)**：按上游 Key 哈希 SQLite 持久化用量，`USAGE_DAY_QUOTA` 配额用尽自动切 Key/429
*   **🔌 WebSocket 翻译 (v2.1.0)**：`/v1/ws/translate` chunk 流式推送
*   **🧪 基准自动化 (v2.1.0)**：`scripts/mock_upstream.py` + `scripts/bench_ci.py` 确定性压测，供应链安全扫描入 CI
*   **🧯 缓存防击穿 (v2.2.0)**：进程内 per-key singleflight + Redis SETNX 跨进程门闩，并发同文本只打一次上游
*   **☸️ K8s 部署 (v2.4.0)**：`deploy/k8s` 滚动发布 `maxUnavailable=0`、`/ready` 就绪探针、HPA、Ingress、内置 Redis，Dockerfile 优雅停机 30s；CI 用 kubeconform Schema 校验
*   **🚀 响应压缩 (v2.6.0)**：Nginx gzip 压缩 JSON/文本/JS/CSS，SSE 流式不压缩不缓冲
*   **📥 批量 Key 导入 (v2.7.0)**：`POST /v1/admin/keys/bulk` + Web UI 批量粘贴，N 条真实 Key 一次进池
*   **🗂️ 文件批量加载 (v2.8.0)**：`GOOGLE_API_KEYS_FILE` 启动时自动读入每行一个 Key
*   **🩺 Key 自检 (v2.9.0)**：`POST /v1/admin/keys/probe` + Web UI 一键验证批量 Key 有效性
*   **🧪 无 Key Demo 模式 (v2.10.0)**：`DEMO_MODE=true` 无需真实 Key 即可启动试用，返回 `demo:` 结果
*   **🚀 完整 CI/CD (v2.11.0)**：GitHub Actions 质量门禁 + staging/production 部署 + 一键回滚 + Slack 通知，见 [`docs/CI_CD_PIPELINE.md`](docs/CI_CD_PIPELINE.md)
*   **🛡️ 规范化错误处理**：统一状态码与错误响应格式，含健康检查端点
*   **🔓 完全开源**：代码透明，易于理解和扩展

---

## 🏗️ 系统架构

```mermaid
graph TB
    subgraph "客户端应用"
        A[OpenAI 兼容客户端<br>ChatGPT/第三方应用] --> B{API 请求}
    end
    
    subgraph "googletranslate-2api 服务"
        B --> C[🌐 Nginx 反向代理<br/>端口: 8088]
        C --> D[⚡ FastAPI 应用]
        D --> E[🔧 请求处理器]
        E --> F[🤖 GoogleTranslate Provider]
        F --> G[🔄 响应格式化器]
        G --> H[📤 SSE 流式输出]
    end
    
    subgraph "外部服务"
        F --> I[🔗 谷歌翻译 API<br/>translate.googleapis.com]
    end
    
    subgraph "数据流"
        A -.->|OpenAI 格式请求| C
        H -.->|OpenAI 格式响应| A
        F -.->|HTTP 请求| I
        I -.->|翻译结果| F
    end

    style A fill:#ff6b6b,color:#fff
    style C fill:#4ecdc4,color:#fff
    style D fill:#45b7d1,color:#fff
    style F fill:#96ceb4,color:#fff
    style I fill:#feca57,color:#fff
```

---

## 🎬 快速开始

### 环境要求
- 🐳 Docker & Docker Compose
- 🔑 有效的谷歌翻译 API Key

### 三步部署指南

> 启动后访问：Web UI `http://127.0.0.1:8088/`（自动打开）· 管理面板 `http://127.0.0.1:8088/admin` · API 文档 `http://127.0.0.1:8088/docs`（教程见 `docs/TUTORIAL.md`）。

1. **克隆项目**
   ```bash
   git clone https://github.com/lzA6/googletranslate-2api.git
   cd googletranslate-2api
   ```

2. **配置环境变量**
   ```bash
   cp .env.example .env
   ```
   
   编辑 `.env` 文件，配置以下参数：
   ```env
   # 服务访问密钥（建议修改）
   API_MASTER_KEY=sk-googletranslate-2api-default-key-please-change-me
   
   # 服务端口
   NGINX_PORT=8088
   
   # 谷歌翻译 API Key（必需）
   GOOGLE_API_KEY=你的谷歌API密钥
   
   # 可选：从文件批量加载多个 Key（每行一个）
   # GOOGLE_API_KEYS_FILE=/path/to/keys.txt
   ```

3. **获取谷歌 API Key**
   
   <details>
   <summary>📝 点击查看详细获取步骤</summary>
   
   1. 在 Chrome/Edge 浏览器中打开任意使用谷歌翻译的网站
   2. 按 `F12` 打开开发者工具，切换到 **Network** 标签页
   3. 在页面中进行翻译操作
   4. 找到名为 `translateHtml` 的请求
   5. 在请求头中复制 `x-goog-api-key` 的值
   
   ![获取API Key示意图](https://user-images.githubusercontent.com/10633963/235218940-90a83573-4191-45f5-a742-86333e361b39.png)
   </details>

4. **启动服务**
   ```bash
   docker-compose up -d
   ```

🎉 **恭喜！** 服务已在 `http://localhost:8088` 启动运行！

> 生产多副本 / Kubernetes 部署见 `deploy/k8s/README.md`：滚动更新不缩容到零，新副本未就绪不进流量。

---

## 🔧 配置说明

### 环境变量配置

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|---------|------|
| `API_MASTER_KEY` | ✅ | `sk-googletranslate-2api...` | API 访问密钥 |
| `NGINX_PORT` | ❌ | `8088` | 服务监听端口 |
| `GOOGLE_API_KEY` | ✅ | - | 谷歌翻译 API 密钥 |

---

## 🚀 使用指南

### API 端点
```
POST http://localhost:8088/v1/chat/completions
```

### 认证方式
```http
Authorization: Bearer YOUR_API_MASTER_KEY
```

### 基础使用示例

```bash
curl -X POST "http://localhost:8088/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-googletranslate-2api-default-key-please-change-me" \
  -d '{
    "model": "google-translate",
    "messages": [
      {
        "role": "user",
        "content": "Hello, world! This is a test translation."
      }
    ],
    "stream": true
  }'
```

### 流式响应示例
```json
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1677652288,"model":"google-translate","choices":[{"index":0,"delta":{"content":"你好，世界！这是一个测试翻译。"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1677652288,"model":"google-translate","choices":[{"index":0,"delta":{"content":""},"finish_reason":"stop"}]}

data: [DONE]
```

### 语言控制

**智能模式（默认）**：
- 输入英文 → 翻译为中文
- 输入中文 → 翻译为英文

**手动指定语言**：
```json
{
  "model": "google-translate",
  "messages": [
    {
      "role": "user", 
      "content": "文本内容"
    }
  ],
  "source_lang": "auto",
  "target_lang": "ja"
}
```

### 非流式响应

设置 `"stream": false` 即可获取普通 JSON 响应（默认 `stream: true` 为 SSE 流）：

```bash
curl -X POST "http://localhost:8088/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_KEY" \
  -d '{
    "model": "google-translate",
    "messages": [{"role": "user", "content": "good morning"}],
    "target_lang": "ja",
    "stream": false
  }'
```

返回 OpenAI `chat.completion` 格式：
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "model": "google-translate",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "おはよう"}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": -1, "completion_tokens": -1, "total_tokens": -1}
}
```

### 状态码与错误处理

| 状态码 | 含义 |
|--------|------|
| `200` | 成功（流式 SSE 或非流式 JSON） |
| `400` | 请求参数无效（缺 messages / 内容空 / 语言码不支持） |
| `401` | 未携带认证 |
| `403` | 认证失败 |
| `422` | 请求体不符合 schema（Pydantic 校验失败） |
| `500` | 服务器内部错误 |
| `502` | 上游翻译服务错误（仅非流式） |

统一错误响应格式：
```json
{"error": {"message": "具体描述", "type": "invalid_request_error"}}
```

完整对外 API 文档见 [`API_DOCS.md`](API_DOCS.md)，运行后也可访问 `http://localhost:8088/docs`（Swagger UI）。

### 健康检查

```bash
curl http://localhost:8088/health
# {"status":"ok","service":"googletranslate-2api","version":"1.0.0"}
```

### ⚠️ 安全须知

- `API_MASTER_KEY=1` 或留空 = **关闭认证**，仅建议本地调试使用。生产环境**必须**设置为强随机密钥。
- `.env` 文件已被 `.gitignore` 忽略，**切勿提交真实密钥**。`.env.example` 仅作模板，不含真实凭证。
- 若曾误将真实 `GOOGLE_API_KEY` 提交到仓库，请**立即在谷歌侧轮换该密钥**。

### 测试

```bash
pip install -r requirements-dev.txt
pytest                    # 单元 + 集成 (mock 上游, 离线可跑)
# 真实上游集成 (需有效 GOOGLE_API_KEY):
GOOGLE_API_KEY=你的key RUN_REAL_INTEGRATION=1 pytest tests/test_integration_real.py
```

---

## 🏗️ 技术架构深度解析

### 系统架构图

```mermaid
flowchart TB
    subgraph ClientLayer [客户端层]
        A[📱 用户应用<br/>OpenAI Client]
        B[🖥️ Web 前端<br/>测试界面]
    end
    
    subgraph GatewayLayer [网关层]
        C[🌐 Nginx<br/>负载均衡 & SSL]
    end
    
    subgraph AppLayer [应用层]
        D[⚡ FastAPI Server]
        
        subgraph ServiceLayer [服务层]
            E[🔍 请求解析器]
            F[🎯 路由控制器]
        end
        
        subgraph ProviderLayer [提供者层]
            G[🤖 GoogleTranslate<br/>Provider]
            H[🔧 BaseProvider<br/>抽象基类]
        end
        
        subgraph UtilLayer [工具层]
            I[📦 SSE 格式化器]
            J[🛡️ 认证中间件]
        end
    end
    
    subgraph ExternalLayer [外部服务]
        K[🌍 Google Translate API]
    end
    
    A --> C
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> K
    G --> I
    H -.->|继承| G
    
    style A fill:#74b9ff,color:#fff
    style C fill:#0984e3,color:#fff
    style D fill:#00b894,color:#fff
    style G fill:#fdcb6e,color:#fff
    style K fill:#e17055,color:#fff
```

### 核心组件说明

| 组件 | 技术栈 | 职责 | 关键特性 |
|------|--------|------|----------|
| **🌐 Nginx** | Nginx 1.18+ | 反向代理、负载均衡 | `proxy_buffering off` 支持流式响应 |
| **⚡ FastAPI** | FastAPI + Uvicorn | Web API 框架 | 异步处理、自动文档生成 |
| **🤖 Provider** | httpx + BeautifulSoup4 | 翻译服务适配器 | 请求转换、响应解析 |
| **📦 SSE Utils** | 自定义工具类 | 响应格式化 | OpenAI 格式兼容 |

### 请求处理流程

```mermaid
sequenceDiagram
    participant C as Client
    participant N as Nginx
    participant F as FastAPI
    participant P as Provider
    participant G as Google API
    
    C->>N: POST /v1/chat/completions
    N->>F: 转发请求
    F->>F: 认证验证
    F->>P: 调用翻译服务
    P->>P: 构建谷歌API请求
    P->>G: 发送翻译请求
    G->>P: 返回翻译结果
    P->>P: 解析HTML响应
    P->>F: 返回纯文本
    F->>F: 格式化为SSE
    F->>N: 流式响应
    N->>C: 实时数据流
```

---

## 🔬 技术实现细节

### 核心代码结构
```
googletranslate-2api/
├── 🐳 Dockerfile                 # 容器化配置
├── 🎯 docker-compose.yml         # 服务编排
├── ⚡ main.py                    # FastAPI 应用入口
├── 🔧 nginx.conf                 # Nginx 配置
├── 📋 requirements.txt           # 运行依赖
├── 📋 requirements-dev.txt       # 开发/测试依赖
├── 🧪 pytest.ini                 # 测试配置
├── 📖 API_DOCS.md                # 对外 API 文档
├── 📁 tests/                     # 测试套件 (单元 + 集成 + mock + 真实)
└── 📁 app/                       # 应用代码
    ├── 🔧 core/
    │   ├── config.py             # 配置管理
    │   └── languages.py          # 语言码表与自动路由
    ├── 🤖 providers/
    │   ├── base_provider.py      # 提供者抽象基类
    │   └── googletranslate_provider.py  # 谷歌翻译实现
    └── 🛠️ utils/
        └── sse_utils.py          # SSE / 响应格式工具
```

### 关键技术实现

1. **请求转换机制**
   ```python
   # 将文本与语言方向转换为谷歌 translateHtml 的 protobuf-json 格式
   def _prepare_payload(self, text: str, source_lang: str, target_lang: str) -> list:
       return [[[text], source_lang, target_lang], "te_lib"]
   ```

2. **响应解析处理**
   ```python
   # 上游返回 [[translated_html]], 提取并清理
   translated_html = response.json()[0][0]
   soup = BeautifulSoup(translated_html, "html.parser")
   clean_text = soup.get_text()  # 再转 Markdown
   ```

3. **流式 / 非流式响应**
   - `stream=true`：生成 OpenAI `chat.completion.chunk` SSE 流, 以 `data: [DONE]` 结束
   - `stream=false`：返回 `chat.completion` JSON, 含 `message.content`

   ```python
   # 非流式响应构造
   create_chat_completion(request_id, model, markdown_text)
   ```

---

## 📊 性能与扩展性

### 性能优化策略

| 优化点 | 实现方式 | 效果 |
|--------|----------|------|
| **异步处理** | FastAPI + httpx.AsyncClient | 高并发支持 |
| **连接复用** | HTTP Keep-Alive | 减少连接开销 |
| **流式传输** | Nginx proxy_buffering off | 实时响应 |

### 扩展能力

1. **多翻译提供商支持**
   - 实现 `BaseProvider` 抽象类
   - 支持 DeepL、百度翻译等提供商
   - 动态切换翻译引擎

2. **缓存层集成**
   ```python
   # Redis 缓存示例
   async def get_translation(self, text: str, target_lang: str):
       cache_key = f"translation:{hash(text)}:{target_lang}"
       cached = await redis.get(cache_key)
       if cached:
           return cached
       # ... 翻译逻辑
   ```

### 实测调优指引 (v1.6.0, 见 docs/loadtest-2026-09-22.md)

真实压测基线: 单 worker 缓存命中承载约 15-35 QPS; 真实上游单 Key 约 5-10 QPS (conc≤40 全 200, 温和压测 0 个 429)。要更高并发, 按收益排序:

1. **多上游 Key** — `GOOGLE_API_KEYS="k1,k2,..."`。真实翻译吞吐唯一线性扩展手段, N 个 Key ≈ N×10 QPS。
2. **Docker/Linux + nginx 分摊** — `APP_WORKERS≈CPU 核数` (Dockerfile 已支持 `${APP_WORKERS}`, compose 默认 2 + `cpus: 2.0`), nginx 已启用 `keepalive 32`。Linux 无 Windows 的 accept 分配不均问题, 缓存命中承载随 worker 线性涨。
3. **调大上游连接池** — `HTTPX_MAX_CONNECTIONS=40`、`HTTPX_MAX_KEEPALIVE_CONNECTIONS=20` (conc 20 实测 10.1 QPS, 默认池约 5-9 QPS)。
4. **降低日志开销** — `LOG_FORMAT=json` + `LOG_LEVEL=WARNING` (本版新增; 终端外自动关闭 ANSI 彩色)。
5. **Redis 共享缓存 (v1.6.0 已实现)** — `CACHE_BACKEND=redis` + `REDIS_URL`, 多 worker/多副本共用翻译缓存, 提高命中率、减少打上游; Redis 不可用时自动回退内存缓存。compose 部署默认已带 Redis 服务。

> Windows 本地 `uvicorn --workers N` 实测不提升吞吐 (共享监听 socket 连接分配不均), 多 worker 请走 Linux 容器 + nginx/负载均衡。

---

## 🚧 开发路线图

### ✅ 已完成功能
- [x] 核心翻译代理功能
- [x] OpenAI API 格式兼容（流式 SSE + 非流式 JSON）
- [x] 全语言互转（显式 source_lang / target_lang，100+ 语言）
- [x] 智能语言自动检测（中/日/韩/阿/俄 ↔ 英，其他 → 中文）
- [x] OpenAI 多段 content 数组兼容
- [x] 健康检查端点 `/health`
- [x] 规范化状态码与统一错误响应
- [x] Docker 容器化部署
- [x] Pytest 测试套件（单元 + 集成 + mock）
- [x] 多上游 Key 池 + 403/429/网络自动切换 + 冷却 (v1.5.0)
- [x] 链路摘要 X-Trace-Summary / /v1/traces/{request_id} (v1.5.0)
- [x] Key 维度用量指标 /metrics (v1.5.0)
- [x] 连接池参数可配 + 真实并发压测基线 (v1.5.1, 见 docs/loadtest-2026-09-22.md)
- [x] SECURITY.md / docs/rotate-key.md / curl 附录自动刷新 (v1.5.2)
- [x] Skills 四件套 (v1.5.2, 见 skills/)
- [x] LOG_LEVEL 可配 + 终端外关闭 ANSI 彩色 + nginx keepalive + APP_WORKERS 可配 (v1.5.3)
- [x] Redis 共享缓存 + 优雅降级 + compose 内置 Redis + E2E 验收脚本 (v1.6.0)
- [x] Redis 分布式限流 + SSE 心跳 + trace 集中化 + Prometheus 告警规则 (v1.7.0)

### 🚀 近期规划 (v1.1)
- [ ] 真正的实时流式翻译（按句增量推送）
- [ ] 多翻译提供商支持（DeepL、百度）
- [ ] Redis 缓存集成
- [ ] 请求频率限制

### 🎯 长期愿景
- [ ] Web 管理界面
- [ ] 多租户支持
- [ ] 翻译质量评估
- [ ] 插件生态系统

---

## 🔍 故障排除

### 常见问题

**❌ 认证失败**
```bash
# 错误信息
{"error":"Invalid API key"}

# 解决方案
检查 .env 文件中的 API_MASTER_KEY 配置
```

**❌ 谷歌 API 错误**
```bash
# 错误信息  
{"error":"Google API error: 403"}

# 解决方案
验证 GOOGLE_API_KEY 有效性，重新获取密钥
```

**❌ 服务无法访问**
```bash
# 检查服务状态
docker-compose ps
docker-compose logs app

# 重启服务
docker-compose restart
```

---

## 🤝 贡献指南

我们欢迎各种形式的贡献！🎉

1. **报告问题**：在 GitHub Issues 中提交 bug 报告或功能请求
2. **代码贡献**：提交 Pull Request 改进代码
3. **文档改进**：帮助完善文档和示例
4. **测试反馈**：测试新功能并提供反馈

### 开发环境搭建
```bash
# 克隆项目
git clone https://github.com/lzA6/googletranslate-2api.git

# 安装依赖
pip install -r requirements.txt

# 启动开发服务
uvicorn main:app --reload --port 8088
```

---

## 🌟 致谢

感谢所有为这个项目做出贡献的开发者们！特别感谢：

- **谷歌翻译**：提供高质量的翻译服务
- **FastAPI 团队**：优秀的 Web 框架
- **Docker 社区**：容器化技术支持
- **所有用户和贡献者**：你们的反馈让项目变得更好

---

## 📞 支持与联系

- 🐛 **问题报告**：[GitHub Issues](https://github.com/lzA6/googletranslate-2api/issues)
- 📚 **文档**：[项目 Wiki](https://github.com/lzA6/googletranslate-2api/wiki)  
- 💬 **讨论**：[GitHub Discussions](https://github.com/lzA6/googletranslate-2api/discussions)

---

**让翻译变得简单，让世界没有语言障碍！** 🌍✨

---


---

## 📦 v1.2.0 更新记录（2026-09-21）

> 本轮为完整优化落地（详见 `计划文档/下一步改进指南.md` 与 `计划文档/项目规格.md`）。

### 新增端点
- `POST /v1/translate/detect` — 轻量语言检测（基于字符集的脚本推断，`source=script_heuristic`，**非 Google 官方检测**）
- `GET /metrics` — Prometheus 指标（`translate_requests_total` / `cache_hit_total` / `cache_miss_total` / `translate_upstream_errors_total` / `rate_limited_total` 等）

### 新增 / 增强能力
- **上游重试**：网络异常 / 429 / 5xx 自动重试（指数退避 + 抖动），4xx 不重试
- **熔断器**：滑动窗口，上游持续故障时快速失败（503），`/ready` 联动
- **批量整体 deadline**：`BATCH_DEADLINE_SECONDS`，超时条目标记 `error=timeout`，条目新增 `error` 字段（向后兼容）
- **限流**：IP + 认证 key 双维度令牌桶，429 + `Retry-After`（**默认关闭**，`RATE_LIMIT_ENABLED=true` 开启）
- **422 统一错误信封**：所有错误统一 `{error: {message, type, detail}}`
- **`stream_options.include_usage`**：流式请求可获末尾 `usage` 块（OpenAI SDK 兼容）
- **模型别名 `MODEL_ALIASES`**：客户端硬编码模型名（如 `gpt-3.5-turbo`）可映射到 `google-translate`
- **流式取消/关闭释放**：客户端断开即中止，不浪费上游
- **缓存 key 稳定化**：改用 sha256 摘要，跨进程/重启后依然可命中
- **段落优先切分**：长文本渐进流按段落切分（默认关，单段落回退按句）

### 配置新增（详见 `.env.example` 或 `app/core/config.py`）
`UPSTREAM_RETRY_*`、`CIRCUIT_BREAKER_ENABLED/FAILURE_THRESHOLD/WINDOW_SECONDS/OPEN_SECONDS`、`BATCH_DEADLINE_SECONDS`、`RATE_LIMIT_ENABLED/CAPACITY/PER_SECOND`、`METRICS_ENABLED`、`MODEL_ALIASES`。

### 错误码补充
| 状态码 | 含义 |
|--------|------|
| `422` | 请求体校验失败（统一信封） |
| `429` | 触发限流（默认关） |
| `503` | 熔断打开 / 上游不可用 |

### 工程质量
- 测试 **141 passed / 1 skipped**（真实集成默认 skip；测试已密封，无需 `.env`）
- 覆盖率 **100%**（`app` + `main.py`），`pyproject.toml` 门禁 `fail_under=97`
- `ruff check` 0 错误、`ruff format` 0 差异、`mypy` 0 错误
- 新增 `pyproject.toml`（ruff / mypy / coverage 配置）、`.github/workflows/ci.yml`、`.pre-commit-config.yaml`、`start-dev.bat` / `start.ps1` / `stop.ps1`、`CHANGELOG.md`
- Docker：HEALTHCHECK、`PYTHONUTF8`、资源限制（compose `mem_limit/cpus`）、`.dockerignore`、nginx 读/发送超时与 `client_max_body_size`

### 快速启动（Windows）
```bat
start-dev.bat     :: 自动创建 .venv + 装依赖 + 校验 .env + 启动 uvicorn :8088
start.ps1         :: 同上（PowerShell 版）
stop.ps1          :: 停止监听 8088 的服务
```

### ⚠️ 安全提醒（重要）
历史 git 提交（`f229883` / `a35417e` / `834501e`）中曾包含真实 `GOOGLE_API_KEY`，该 key 当前已被 Google 吊销（返回 `API_KEY_INVALID`）。**请及时在谷歌侧轮换 key**；若需彻底清除历史，可评估 `git filter-repo`（破坏性操作，务必备份并明确确认，严禁 `--force` 覆盖）。

---

## v1.4.x 更新记录 (2026-09-21)

### 安全 (3.B 加固)
- `API_MASTER_KEY` 命中公开示例/弱 key 标记默认**拒绝启动**（`ALLOW_WEAK_API_KEY=true` 才显式放行）
- 主密钥字符多样性 <6 时启动 WARNING（熵检查）；多 key + `hmac.compare_digest` 常量时间比较
- 限流桶有界（`RATE_LIMIT_MAX_KEYS` + LRU 淘汰）；`TRUST_PROXY_HEADER=true` 时按 `X-Forwarded-For` 首跳限流
- 上游 403 → `upstream_auth_error` 独立语义；流式 SSE detail 白名单（非白名单输出通用文案）

### 缓存 (3.C)
- 缓存 key 使用 sha256 摘要（跨进程稳定）；**首尾空白归一化**：`" hello "` 与 `"hello"` 共享缓存命中
- 命中/未命中指标：`cache_hit_total` / `cache_miss_total`（`/metrics`）

### 可靠性与限流 (3.D / P3-8)
- 显式 `httpx.Limits` 连接池（与 `BATCH_MAX_CONCURRENCY` 匹配）
- 上游重试日志含次数与退避；批量整体 deadline（超时条目 `error=timeout`）
- **429 的 `Retry-After` 为按令牌桶回填计算的实际秒数**（不再固定 1）

### 质量基线
- 测试 **168 passed / 1 skipped**，覆盖率 **100%**（767 stmts）
- ruff check / format 0，mypy 0；pre-commit 全绿；远端 GitHub Actions CI 全 success
- 发行版：v1.4.1（Latest）→ v1.2.0 共 8 个

---

## 真实调用输出附录

> 由 `scripts/refresh_curl_appendix.ps1` 生成（点击查看 [docs/curl_appendix.md](docs/curl_appendix.md)）；历史快照：

## 历史附录快照（2026-09-21 实测, 有效 GOOGLE_API_KEY）

> 以下为对本地真实服务（`uvicorn main:app`）用 curl 实跑的原始响应摘录，Authorization 已掩码；与当前代码一致，非编造。

### 1) 非流式翻译（英→中）
```bash
curl -s -X POST http://localhost:8088/v1/chat/completions   -H "Content-Type: application/json"   -H "Authorization: Bearer <YOUR_KEY>"   -d '{"messages":[{"role":"user","content":"Hello world"}],"target_lang":"zh-CN","stream":false}'
```
```json
{"id":"chatcmpl-...","object":"chat.completion","model":"google-translate",
 "choices":[{"index":0,"message":{"role":"assistant","content":"你好世界"},"finish_reason":"stop"}],
 "usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3,"estimate":true}}
```

### 2) 流式翻译（SSE, 截断）
```bash
curl -s -N -X POST http://localhost:8088/v1/chat/completions   -H "Content-Type: application/json"   -H "Authorization: Bearer <YOUR_KEY>"   -d '{"messages":[{"role":"user","content":"Good morning"}],"target_lang":"zh-CN","stream":true}'
```
```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"早上好"},"finish_reason":null}]}
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop"}]}
data: [DONE]
```

### 3) 批量翻译（含部分失败语义）
```bash
curl -s -X POST http://localhost:8088/v1/translate/batch   -H "Content-Type: application/json" -H "Authorization: Bearer <YOUR_KEY>"   -d '{"texts":["apple","banana"],"target_lang":"zh-CN"}'
```
```json
{"object":"list","data":[
  {"text":"apple","translated":"苹果","ok":true,"error":null},
  {"text":"banana","translated":"香蕉","ok":true,"error":null}],"count":2}
```
> 整体始终 200；单条失败时该条目 `"ok":false,"error":"upstream_400"`（或 `"timeout"`），不影响其他条目。

### 4) 422（缺 messages, 统一信封）
```json
{"error":{"message":"请求参数校验失败","type":"invalid_request_error",
  "detail":[{"type":"missing","loc":["body","messages"],"msg":"Field required","input":{"model":"x"}}]}}
```

### 5) 401（无 token）
```json
{"error":{"message":"需要 Bearer Token 认证。","type":"invalid_request_error"}}
```

### 6) 403（错 token）
```json
{"error":{"message":"无效的 API Key。","type":"invalid_request_error"}}
```

### 7) 429（限流开启后, 返回 Retry-After 实际秒数）
```http
HTTP/1.1 429 Too Many Requests
Retry-After: 998
```
```json
{"error":{"message":"请求过于频繁, 请稍后再试","type":"rate_limit_error"}}
```
