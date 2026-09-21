# ====================================================================
# Dockerfile for googletranslate-2api (v1.0 - Chimera Synthesis)
# ====================================================================

FROM python:3.10-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1
ENV PYTHONIOENCODING=utf-8
WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock

# 复制应用代码
COPY . .

# 健康检查（复制代码后定义，与 docker-compose 保持一致）
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)"

# 创建并切换到非 root 用户
RUN useradd --create-home appuser && \
    chown -R appuser:appuser /app
USER appuser

# 暴露端口并启动
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]