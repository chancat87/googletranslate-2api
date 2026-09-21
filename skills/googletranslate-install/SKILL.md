---
name: googletranslate-install
description: 一条命令安装并启动 googletranslate-2api（Windows 优先），校验密钥后验证 /health。
---

# 安装与启动

1. 克隆仓库并准备环境：
   ```bash
   git clone <repo> && cd googletranslate-2api
   py -3.10 -m venv .venv
   .\.venv\Scripts\python -m pip install -r requirements-dev.txt
   ```
2. 准备 `.env`：复制 `.env.example`，填入 `GOOGLE_API_KEYS`（或 `GOOGLE_API_KEY`）与 `API_MASTER_KEY`。
   - 未设置真实 key 启动会报 `GOOGLE_API_KEY / GOOGLE_API_KEYS 未配置`；占位符会被拒启。
3. 启动：`start-dev.bat`（或 `python -m uvicorn main:app --port 8088`）。
4. 验证：
   ```bash
   curl -s http://localhost:8088/health   # 期待 {"status":"ok",...,"version":"1.5.x"}
   ```
5. 失败排查：先看启动日志（弱 key 告警/占位符拒启/端口占用），再读 `googletranslate-debug`。
