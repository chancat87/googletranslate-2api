import sys
import uuid
from contextlib import asynccontextmanager
from typing import Optional, List, Union, Any

from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field, ConfigDict

from app.core.config import settings
from app.core.languages import is_supported
from app.providers.googletranslate_provider import GoogleTranslateProvider

# --- 配置 Loguru (P2.4: 支持 JSON 结构化日志, 由 LOG_FORMAT 切换) ---
logger.remove()


def _log_sink(message):
    sys.stdout.write(message)


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


# --- 全局 Provider 实例 ---
provider = GoogleTranslateProvider()


@asynccontextmanager
async def lifespan(app: FastAPI):
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


# --- 请求/响应 Schema (供 /docs 自动生成对外文档) ---
class ChatMessage(BaseModel):
    role: str = Field(..., description="消息角色, 固定 user")
    content: Union[str, List[Any]] = Field(..., description="待翻译文本内容")


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: Optional[str] = Field(default=None, description="模型名, 留空使用默认")
    messages: List[ChatMessage] = Field(..., description="对话消息, 取最后一条 user 消息为待翻译文本")
    source_lang: Optional[str] = Field(default="auto", description="源语言代码, auto 为自动检测")
    target_lang: Optional[str] = Field(
        default=None,
        description="目标语言代码。留空则自动判断 (中文->英, 其他->中文)"
    )
    stream: Optional[bool] = Field(default=True, description="是否流式返回, 当前固定流式")


class BatchTranslateRequest(BaseModel):
    """P2.2 批量翻译请求。

    示例:
        curl -X POST http://localhost:8088/v1/translate/batch \\
          -H "Authorization: Bearer $API_MASTER_KEY" \\
          -H "Content-Type: application/json" \\
          -d '{"texts":["hello","world"],"target_lang":"zh-CN"}'
    """
    texts: List[str] = Field(..., description="待翻译文本列表, 上限 BATCH_MAX_ITEMS")
    source_lang: Optional[str] = Field(default="auto", description="源语言代码")
    target_lang: Optional[str] = Field(default="zh-CN", description="目标语言代码")


class BatchTranslateResult(BaseModel):
    text: str
    translated: str
    ok: bool


class BatchTranslateResponse(BaseModel):
    object: str = "list"
    data: List[BatchTranslateResult]
    count: int


class ErrorResponse(BaseModel):
    error: dict = Field(..., description="错误信息, 含 message 与 type")


# --- 安全依赖 ---
async def verify_api_key(authorization: Optional[str] = Header(None)):
    """主密钥为 1 或空时跳过认证; 否则校验 Bearer Token。"""
    if settings.API_MASTER_KEY and settings.API_MASTER_KEY != "1":
        if not authorization or "bearer" not in authorization.lower():
            raise HTTPException(status_code=401, detail="需要 Bearer Token 认证。")
        token = authorization.split(" ")[-1]
        if token != settings.API_MASTER_KEY:
            raise HTTPException(status_code=403, detail="无效的 API Key。")


# --- 全局 JSON 错误响应 (统一状态码语义) ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"message": exc.detail, "type": "invalid_request_error"}},
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
    """P1.5 就绪探针: 探测上游翻译服务可用性。成功 200; 上游不可达 503。"""
    if await provider.probe_ready():
        return {"status": "ready", "service": settings.APP_NAME}
    return JSONResponse(
        status_code=503,
        content={"error": {"message": "上游翻译服务不可用", "type": "upstream_unavailable"}},
    )


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
        "**错误码**:\n"
        "- 400: 参数无效 / 文本为空 / 语言码不支持\n"
        "- 413: 单条文本超长 (MAX_TEXT_LENGTH)\n"
        "- 401/403: 认证失败\n\n"
        "**响应**: 每条返回 `{text, translated, ok}`, 单条失败不影响其他。"
    ),
    responses={
        400: {"model": ErrorResponse, "description": "参数无效"},
        401: {"model": ErrorResponse, "description": "缺少认证"},
        403: {"model": ErrorResponse, "description": "认证失败"},
    },
)
async def translate_batch(payload: BatchTranslateRequest):
    """批量翻译: 限并发复用 _translate, 单条失败不中断。

    - 上限 BATCH_MAX_ITEMS, 超出 400。
    - 空文本 / 超长 / 语言码不支持 400 或 413。
    """
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
    if source_lang != "auto" and not is_supported(source_lang):
        raise HTTPException(status_code=400, detail=f"不支持的语言代码: source_lang={source_lang}")
    if not is_supported(payload.target_lang):
        raise HTTPException(status_code=400, detail=f"不支持的语言代码: target_lang={payload.target_lang}")

    results = await provider.translate_batch(payload.texts, source_lang, payload.target_lang)
    return BatchTranslateResponse(
        data=[BatchTranslateResult(**r) for r in results],
        count=len(results),
    )


@app.post(
    "/v1/chat/completions",
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse, "description": "请求参数无效"},
        401: {"model": ErrorResponse, "description": "缺少认证"},
        403: {"model": ErrorResponse, "description": "认证失败"},
        413: {"model": ErrorResponse, "description": "文本长度超限"},
        500: {"model": ErrorResponse, "description": "服务器内部错误"},
        502: {"model": ErrorResponse, "description": "上游翻译服务错误"},
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
                "  -H \"Authorization: Bearer $API_MASTER_KEY\" \\\n"
                "  -H \"Content-Type: application/json\" \\\n"
                "  -d '{\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}],\"stream\":true}'\n"
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
    - **P1.1**: STREAM_CHUNK_ENABLED 开启后, 长文本按句分批流式。
    - OpenAI 标准字段 (temperature/top_p/max_tokens 等) 接受但忽略。
    """
    return await provider.chat_completion(payload.model_dump(exclude_none=False))
