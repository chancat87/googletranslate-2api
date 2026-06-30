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
