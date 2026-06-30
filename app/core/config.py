from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra="ignore"
    )

    APP_NAME: str = "googletranslate-2api"
    APP_VERSION: str = "1.1.0"
    DESCRIPTION: str = "一个将 Google Translate API 转换为兼容 OpenAI 格式的代理。"

    API_MASTER_KEY: Optional[str] = None
    NGINX_PORT: int = 8088

    GOOGLE_API_KEY: Optional[str] = None

    API_REQUEST_TIMEOUT: int = 60

    DEFAULT_MODEL: str = "google-translate"
    KNOWN_MODELS: List[str] = ["google-translate"]

    # --- P1.1 流式分批: 长文本按句切分, 默认关 (切句会丢跨句上下文) ---
    STREAM_CHUNK_ENABLED: bool = False
    STREAM_CHUNK_THRESHOLD: int = 500
    STREAM_CHUNK_MAX: int = 500

    # --- P1.2 缓存: 内存 TTL-LRU ---
    CACHE_ENABLED: bool = True
    CACHE_MAXSIZE: int = 1000
    CACHE_TTL: int = 3600

    # --- P1.6 输入长度上限 ---
    MAX_TEXT_LENGTH: int = 5000

    # --- P1.5 /ready 探活 ---
    READY_PROBE_TEXT: str = "hi"

    # --- P2.2 批量翻译并发 ---
    BATCH_MAX_CONCURRENCY: int = 10
    BATCH_MAX_ITEMS: int = 50

    # --- P2.4 结构化日志 ---
    LOG_FORMAT: str = "text"

settings = Settings()
