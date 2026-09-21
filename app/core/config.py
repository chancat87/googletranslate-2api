"""集中配置 (pydantic-settings)。

注意: 本模块在导入时即创建 `settings` 单例并读取 .env / 环境变量, 之后不再刷新。
因此测试必须在 import 本模块之前预置必要的环境变量 (见 tests/conftest.py 顶层)。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "googletranslate-2api"
    APP_VERSION: str = "2.0.0"
    DESCRIPTION: str = "一个将 Google Translate API 转换为兼容 OpenAI 格式的代理。"

    API_MASTER_KEY: str | None = None
    NGINX_PORT: int = 8088
    # P1-1: 命中公开示例主密钥时默认拒绝启动; true 则显式放行 (仍会告警)
    ALLOW_WEAK_API_KEY: bool = False

    GOOGLE_API_KEY: str | None = None
    # 阶段 1.1: 多上游 Key 池 (逗号分隔); 未设置时回退 GOOGLE_API_KEY (向后兼容)
    GOOGLE_API_KEYS: str | None = None
    # Key 失败冷却 (秒): 403/429/transport 触发后进入冷却, 到期前不再优先选它
    KEY_FAILOVER_COOLDOWN_SECONDS: int = 60
    # 阶段 1.2: 链路摘要环形缓冲上限
    TRACE_STORE_MAXLEN: int = 512
    # v1.7.0: 链路摘要后端 memory | redis (多 worker 集中可查; redis 故障回退内存)
    TRACE_BACKEND: str = "memory"
    TRACE_PREFIX: str = "g2api:trace:"
    TRACE_TTL: int = 3600

    API_REQUEST_TIMEOUT: int = 60
    # v2.1.0: 上游基址可覆盖 (压测/本地 mock; 默认 Google translate-pa)
    UPSTREAM_BASE_URL: str = "https://translate-pa.googleapis.com"

    DEFAULT_MODEL: str = "google-translate"
    KNOWN_MODELS: list[str] = ["google-translate"]
    # 模型别名: 客户端硬编码的模型名 -> 本项目实际模型 (P2-3 / M9)
    MODEL_ALIASES: dict[str, str] = {}

    # --- P1.1 流式分批: 长文本按段切分, 默认关 (切段会丢跨段上下文) ---
    STREAM_CHUNK_ENABLED: bool = False
    STREAM_CHUNK_THRESHOLD: int = 500
    STREAM_CHUNK_MAX: int = 500
    # v1.7.0: SSE 心跳间隔秒数, 0=关闭 (防止慢连接被网关/中间件掐断)
    SSE_HEARTBEAT_INTERVAL: float = 0.0

    # --- P1.2 缓存: 内存 TTL-LRU / Redis 共享缓存 (v1.6.0) ---
    CACHE_ENABLED: bool = True
    CACHE_MAXSIZE: int = 1000
    CACHE_TTL: int = 3600
    # 共享缓存后端: memory | redis (多 worker/多副本共用一份翻译缓存)
    CACHE_BACKEND: str = "memory"
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    CACHE_PREFIX: str = "g2api:"

    # --- P1.6 输入长度上限 ---
    MAX_TEXT_LENGTH: int = 5000

    # --- P1.5 /ready 探活 ---
    READY_PROBE_TEXT: str = "hi"

    # --- P2.2 批量翻译并发 ---
    # --- v1.5.1: HTTPX 连接池 (0 = 自动 = max(10, BATCH_MAX_CONCURRENCY+5) / max(5, BATCH_MAX_CONCURRENCY)) ---
    HTTPX_MAX_CONNECTIONS: int = 0
    HTTPX_MAX_KEEPALIVE_CONNECTIONS: int = 0

    BATCH_MAX_CONCURRENCY: int = 10
    BATCH_MAX_ITEMS: int = 50
    # 批量整体预算 (秒): 超时后未完成条目标记 error=timeout (M5)
    BATCH_DEADLINE_SECONDS: int = 120

    # --- P2.4 结构化日志 ---
    LOG_FORMAT: str = "text"
    # 高并发调优: 生产可设 WARNING/ERROR 减少每请求日志开销 (v1.5.3)
    LOG_LEVEL: str = "INFO"

    # --- M3 上游重试: 指数退避 + 抖动 (仅对网络异常/429/5xx) ---
    UPSTREAM_RETRY_ATTEMPTS: int = 3
    UPSTREAM_RETRY_BACKOFF_BASE: float = 0.5
    UPSTREAM_RETRY_MAX_BACKOFF: float = 3.0
    UPSTREAM_RETRY_JITTER: float = 0.3

    # --- M4 熔断: 滑动窗口 ---
    CIRCUIT_BREAKER_ENABLED: bool = True
    CIRCUIT_FAILURE_THRESHOLD: int = 10
    CIRCUIT_WINDOW_SECONDS: int = 60
    CIRCUIT_OPEN_SECONDS: int = 30

    # --- M6 限流 (默认关, 按 IP + 认证 key 双维度) ---
    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_CAPACITY: int = 30
    RATE_LIMIT_PER_SECOND: float = 10.0
    RATE_LIMIT_MAX_KEYS: int = 10000  # 限流桶上限, 防无界内存增长 (P2-2)
    # v1.7.0: 限流后端 memory | redis (多副本一致; redis 故障回退内存)
    RATE_LIMIT_BACKEND: str = "memory"
    RATE_LIMIT_REDIS_URL: str = ""
    RATE_LIMIT_PREFIX: str = "g2api:rl:"
    RATE_LIMIT_TTL: int = 3600
    # 可信反代后取 X-Forwarded-For 首跳做 IP 维度 (P2-3); 默认关, 防伪造
    TRUST_PROXY_HEADER: bool = False

    # --- M12 指标 ---
    METRICS_ENABLED: bool = True


settings = Settings()
