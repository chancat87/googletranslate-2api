import hmac
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import settings
from app.core.languages import is_supported
from app.core.metrics import metrics
from app.core.rate_limit import RateLimiter
from app.providers.googletranslate_provider import GoogleTranslateProvider
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field


# --- 配置 Loguru (P2.4: 支持 JSON 结构化日志, 由 LOG_FORMAT 切换) ---
def _log_sink(message):
    sys.stdout.write(message)


def _configure_logging():
    logger.remove()
    if settings.LOG_FORMAT.lower() == "json":
        logger.add(_log_sink, level="INFO", serialize=True)
    else:
        logger.add(
            _log_sink,
            level="INFO",
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            colorize=True,
        )


_configure_logging()

# --- 全局 Provider 实例 ---
provider = GoogleTranslateProvider()

# --- M6 限流器 (默认关; 进程内令牌桶, 多副本需网关层兜底) ---
rate_limiter = RateLimiter(
    settings.RATE_LIMIT_CAPACITY, settings.RATE_LIMIT_PER_SECOND, settings.RATE_LIMIT_MAX_KEYS
)
RATE_LIMIT_SKIP_PATHS = {
    "/",
    "/health",
    "/ready",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
}


_WEAK_MASTER_KEY_MARKERS = ("default-key", "changeme", "please-change")


def _hash_key_component(s: str) -> str:
    """把 token/IP 摘要为定长 key, 避免超长原始串进入限流桶字典 (P2-2/P2-3)。"""
    import hashlib

    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]


def _check_weak_api_key() -> None:
    """3.B.2 启动安全检查: 认证关闭告警 / 公开示例默认 key 拒绝启动 / 短 key 告警。"""
    master = settings.API_MASTER_KEY
    if not master or str(master).strip() == "1":
        logger.warning(
            "API_MASTER_KEY 未设置或为 '1', 认证已关闭 (仅限本地调试, 生产必须设置强随机 key)"
        )
        return
    if any(m in str(master).lower() for m in _WEAK_MASTER_KEY_MARKERS):
        if not settings.ALLOW_WEAK_API_KEY:
            raise RuntimeError(
                "API_MASTER_KEY 命中公开示例/弱 key 标记, 已拒绝启动; "
                "请设置强随机 key (>=16 字符), 或显式设置 ALLOW_WEAK_API_KEY=true 强制放行"
            )
        logger.warning(
            "API_MASTER_KEY 命中公开示例/弱 key 标记, 已显式放行 (ALLOW_WEAK_API_KEY=true), 生产不建议"
        )
        return
    if len(str(master)) < 16:
        logger.warning(
            f"API_MASTER_KEY 长度偏短 ({len(str(master))}), 生产环境请设置 >=16 字符的强随机 key"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_weak_api_key()
    logger.info(f"应用启动中... {settings.APP_NAME} v{settings.APP_VERSION}")
    try:
        await provider.initialize()
        logger.info(f"服务将在 http://localhost:{settings.NGINX_PORT} 上可用")
    except Exception as e:
        logger.critical(f"启动失败: {e}")
        raise
    yield
    await provider.close()
    logger.info("应用关闭。")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.DESCRIPTION,
    lifespan=lifespan,
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """P2.4: 为每个请求注入 trace id, 贯穿日志与响应头。"""
    request_id = request.headers.get("X-Request-Id") or f"req-{uuid.uuid4().hex[:16]}"
    with logger.contextualize(request_id=request_id):
        logger.info(f"{request.method} {request.url.path}")
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """M6: 按 IP + 认证 key 双维度限流 (默认关)。

    超限返回 429 + Retry-After。跳过系统/文档/探针路径。
    """
    if not settings.RATE_LIMIT_ENABLED or request.url.path in RATE_LIMIT_SKIP_PATHS:
        return await call_next(request)

    token = _extract_bearer_token(request.headers.get("Authorization"))

    if token:
        key = f"key:{_hash_key_component(token)}"
        key_type = "key"
    else:
        client_ip = request.client.host if request.client else "unknown"
        if settings.TRUST_PROXY_HEADER:
            # P2-3: 可信反代后取 X-Forwarded-For 首个外部跳 (默认关, 防伪造)
            ff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            client_ip = ff if ff else client_ip
        key = f"ip:{client_ip}"
        key_type = "ip"

    if not rate_limiter.allow(key):
        metrics.rate_limited.labels(key_type=key_type).inc()
        logger.warning(f"rate limited ({key_type}) path={request.url.path}")
        return JSONResponse(
            status_code=429,
            content={"error": {"message": "请求过于频繁, 请稍后再试", "type": "rate_limit_error"}},
            headers={"Retry-After": "1"},
        )
    return await call_next(request)


# --- 请求/响应 Schema (供 /docs 自动生成对外文档) ---
class ChatMessage(BaseModel):
    role: str = Field(..., description="消息角色, 固定 user")
    content: str | list[Any] = Field(..., description="待翻译文本内容")


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = Field(default=None, description="模型名, 留空使用默认")
    messages: list[ChatMessage] = Field(
        ..., description="对话消息, 取最后一条 user 消息为待翻译文本"
    )
    source_lang: str | None = Field(default="auto", description="源语言代码, auto 为自动检测")
    target_lang: str | None = Field(
        default=None,
        description="目标语言代码。留空则自动判断 (中文->英, 其他->中文)",
    )
    stream: bool | None = Field(default=True, description="是否流式返回, 当前固定流式")


class BatchTranslateRequest(BaseModel):
    """P2.2 批量翻译请求。

    示例:
        curl -X POST http://localhost:8088/v1/translate/batch \\
          -H "Authorization: Bearer $API_MASTER_KEY" \\
          -H "Content-Type: application/json" \\
          -d '{"texts":["hello","world"],"target_lang":"zh-CN"}'
    """

    texts: list[str] = Field(..., description="待翻译文本列表, 上限 BATCH_MAX_ITEMS")
    source_lang: str | None = Field(default="auto", description="源语言代码")
    target_lang: str | None = Field(default="zh-CN", description="目标语言代码")


class BatchTranslateResult(BaseModel):
    text: str
    translated: str
    ok: bool
    error: str | None = Field(
        default=None, description="单条失败原因 (M5: 可为 timeout/upstream_xxx)"
    )


class BatchTranslateResponse(BaseModel):
    object: str = "list"
    data: list[BatchTranslateResult]
    count: int


class DetectRequest(BaseModel):
    """M16: 轻量语言检测请求。"""

    text: str = Field(..., description="待检测文本")


class ErrorResponse(BaseModel):
    error: dict = Field(..., description="错误信息, 含 message 与 type")


# --- 安全依赖 (支持逗号分隔多 key + 常量时间比较) ---
def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def verify_api_key(authorization: str | None = Header(None)):
    """主密钥为 1 或空时跳过认证; 否则校验 Bearer Token (多 key, 常量时间比较)。"""
    master = settings.API_MASTER_KEY
    if not master or master == "1":
        return
    token = _extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="需要 Bearer Token 认证。")
    if not token.isascii():
        raise HTTPException(status_code=401, detail="需要合法的 Bearer Token 认证。")
    keys = [k.strip() for k in master.split(",") if k.strip()]
    if not any(hmac.compare_digest(token, k) for k in keys):
        raise HTTPException(status_code=403, detail="无效的 API Key。")


# --- 全局 JSON 错误响应 (统一状态码语义, 含 M7 422) ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"message": exc.detail, "type": "invalid_request_error"}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """M7: 校验失败统一为 {error:{message,type,detail}}, 不再是 FastAPI 默认 {detail:[...]}。"""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "message": "请求参数校验失败",
                "type": "invalid_request_error",
                "detail": exc.errors(),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": {"message": "内部服务器错误", "type": "internal_error"}},
    )


# --- API 路由 ---
@app.get("/", summary="根路径", tags=["系统"], include_in_schema=False)
def root():
    return {"message": f"欢迎来到 {settings.APP_NAME} v{settings.APP_VERSION}. 服务运行正常。"}


@app.get("/health", summary="存活探针 (liveness)", tags=["系统"])
def health():
    """存活探针: 进程活着即返回 ok, 不探测上游。用于 liveness check。"""
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/ready", summary="就绪探针 (readiness)", tags=["系统"])
async def ready():
    """P1.5 就绪探针: 探测上游翻译服务可用性 (熔断打开时直接不健康)。成功 200; 不可用 503。"""
    if await provider.probe_ready():
        return {"status": "ready", "service": settings.APP_NAME}
    return JSONResponse(
        status_code=503,
        content={"error": {"message": "上游翻译服务不可用", "type": "upstream_unavailable"}},
    )


@app.get("/metrics", summary="Prometheus 指标 (M12)", tags=["系统"], include_in_schema=False)
async def metrics_endpoint():
    """M12: Prometheus 文本指标。生产环境建议在网关层做访问控制。"""
    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/v1/models", dependencies=[Depends(verify_api_key)], response_model=dict, tags=["模型"])
async def list_models():
    """列出可用模型。"""
    return await provider.get_models()


@app.post(
    "/v1/translate/batch",
    dependencies=[Depends(verify_api_key)],
    response_model=BatchTranslateResponse,
    tags=["翻译"],
    summary="批量翻译 (P2.2)",
    description=(
        "并发翻译多条文本, 内部限并发 (BATCH_MAX_CONCURRENCY), 复用单条翻译与缓存。\n\n"
        "**M5**: 整体预算 BATCH_DEADLINE_SECONDS, 超时条目标记 `error=timeout`。\n\n"
        "**错误码**:\n"
        "- 400: 参数无效 / 文本为空 / 语言码不支持\n"
        "- 413: 单条文本超长 (MAX_TEXT_LENGTH)\n"
        "- 401/403: 认证失败\n\n"
        "**响应**: 每条返回 `{text, translated, ok, error}`, 单条失败不影响其他。"
    ),
    responses={
        400: {"model": ErrorResponse, "description": "参数无效"},
        401: {"model": ErrorResponse, "description": "缺少认证"},
        403: {"model": ErrorResponse, "description": "认证失败"},
    },
)
async def translate_batch(payload: BatchTranslateRequest):
    """批量翻译: 限并发复用 _translate, 单条失败不中断, 整体 deadline 兜底。"""
    if not payload.texts:
        raise HTTPException(status_code=400, detail="texts 不能为空。")
    if len(payload.texts) > settings.BATCH_MAX_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"批量条数超限: {len(payload.texts)} > {settings.BATCH_MAX_ITEMS}",
        )
    for idx, t in enumerate(payload.texts):
        if not isinstance(t, str) or not t.strip():
            raise HTTPException(status_code=400, detail=f"texts[{idx}] 为空或非字符串。")
        if len(t) > settings.MAX_TEXT_LENGTH:
            raise HTTPException(
                status_code=413,
                detail=f"texts[{idx}] 长度超限: {len(t)} > {settings.MAX_TEXT_LENGTH}",
            )
    source_lang = payload.source_lang or "auto"
    target_lang = payload.target_lang or "zh-CN"
    if source_lang != "auto" and not is_supported(source_lang):
        raise HTTPException(status_code=400, detail=f"不支持的语言代码: source_lang={source_lang}")
    if not is_supported(target_lang):
        raise HTTPException(status_code=400, detail=f"不支持的语言代码: target_lang={target_lang}")

    results = await provider.translate_batch(payload.texts, source_lang, target_lang)
    return BatchTranslateResponse(
        data=[BatchTranslateResult(**r) for r in results],
        count=len(results),
    )


@app.post(
    "/v1/translate/detect",
    dependencies=[Depends(verify_api_key)],
    tags=["翻译"],
    summary="语言检测 (M16, 轻量推断)",
    description=(
        "基于字符集/脚本的轻量推断: 返回命中的脚本族与自动路由目标语言。\n"
        "**注意**: 非 Google 官方语言检测, source=script_heuristic。"
    ),
    responses={
        400: {"model": ErrorResponse, "description": "参数无效"},
        401: {"model": ErrorResponse, "description": "缺少认证"},
        403: {"model": ErrorResponse, "description": "认证失败"},
    },
)
async def translate_detect(payload: DetectRequest):
    """M16: 轻量语言检测 (推断)。"""
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="text 不能为空。")
    return provider.detect_language(payload.text)


@app.post(
    "/v1/chat/completions",
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse, "description": "请求参数无效"},
        401: {"model": ErrorResponse, "description": "缺少认证"},
        403: {"model": ErrorResponse, "description": "认证失败"},
        413: {"model": ErrorResponse, "description": "文本长度超限"},
        422: {"model": ErrorResponse, "description": "请求体校验失败"},
        500: {"model": ErrorResponse, "description": "服务器内部错误"},
        502: {"model": ErrorResponse, "description": "上游翻译服务错误"},
        503: {"model": ErrorResponse, "description": "熔断/上游不可用"},
        200: {
            "content": {
                "text/event-stream": {"schema": {"type": "string"}},
                "application/json": {"schema": {"type": "object"}},
            },
            "description": (
                "stream=true 返回 SSE (chat.completion.chunk); stream=false 返回 JSON (chat.completion)。\n\n"
                "用法示例:\n"
                "```\n"
                "curl -X POST http://localhost:8088/v1/chat/completions \\\n"
                '  -H "Authorization: Bearer $API_MASTER_KEY" \\\n'
                '  -H "Content-Type: application/json" \\\n'
                '  -d \'{"messages":[{"role":"user","content":"Hello"}],"stream":true}\'\n'
                "```"
            ),
        },
    },
    tags=["翻译"],
)
async def chat_completions(payload: ChatCompletionRequest):
    """翻译接口, 兼容 OpenAI Chat Completions。

    - 取 messages 最后一条 user 消息为待翻译文本。
    - source_lang/target_lang 显式指定即支持全语言互转。
    - target_lang 留空时: 输入含中文/日/韩/阿/俄 -> 英文, 否则 -> 中文。
    - stream=true 返回 SSE 流 (默认); stream=false 返回普通 JSON。
    - **P1.6**: 文本长度上限 MAX_TEXT_LENGTH, 超出 413。
    - **P1.2**: 命中缓存时直接返回, 不打上游。
    - **M8**: stream_options.include_usage=true 时流末尾追加 usage 块。
    - **M9**: model 支持 MODEL_ALIASES 别名映射。
    - **M4**: 熔断打开时快速 503。
    - OpenAI 标准字段 (temperature/top_p/max_tokens 等) 接受但忽略。
    """
    return await provider.chat_completion(payload.model_dump(exclude_none=False))
