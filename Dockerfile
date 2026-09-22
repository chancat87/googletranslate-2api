# Dockerfile for googletranslate-2api (v2.12.4)
# 多阶段构建：builder 只负责装依赖，最终镜像只保留运行所需，缩小体积并减少层数。

# Phase 1: builder (仅安装依赖, 不进入最终镜像)
FROM python:3.10-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# 依赖文件变化频率低, 放在最前以命中构建缓存
COPY requirements.txt requirements.lock ./

# 依赖以 --prefix 安装到 /install, 最终阶段仅拷贝 /install 合并进 /usr/local
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.lock

# Phase 2: 最终运行镜像
FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONHASHSEED=random

WORKDIR /app

# 把 builder 装好的依赖合并进 /usr/local (site-packages + bin/uvicorn)
COPY --from=builder /install /usr/local

# 创建非 root 用户
RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

# 复制应用代码 (由 .dockerignore 排除 .env/.venv/tests/docs 等, 以 appuser 属主)
COPY --chown=appuser:appuser . .

# 健康检查 (与 compose healthcheck 保持一致)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)"

USER appuser

EXPOSE 8000

ENV APP_WORKERS=1 \
    APP_SHUTDOWN_GRACE=30

STOPSIGNAL SIGTERM
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${APP_WORKERS:-1} --timeout-graceful-shutdown ${APP_SHUTDOWN_GRACE:-30}"]
