"""Prometheus 指标 (M12)。

进程内指标: 请求量/结果、上游错误、缓存命中/未命中、翻译耗时、限流计数。
仅在 METRICS_ENABLED=True 时初始化; /metrics 端点由 main.py 暴露。
"""

from typing import Any

from app.core.config import settings

try:
    from prometheus_client import Counter, Histogram, generate_latest

    _HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover - 无依赖时退化为空实现
    _HAS_PROMETHEUS = False


class _NullMetric:
    def labels(self, *args, **kwargs):
        return self

    def inc(self, *args, **kwargs):
        return None

    def observe(self, *args, **kwargs):
        return None


class Metrics:
    """指标门面: 无 prometheus_client 时全部空操作, 不阻断功能。"""

    def __init__(self) -> None:
        self.translate_requests: Any
        self.upstream_errors: Any
        self.cache_hits: Any
        self.cache_misses: Any
        self.translate_duration: Any
        self.rate_limited: Any
        if not (settings.METRICS_ENABLED and _HAS_PROMETHEUS):
            self.enabled = False
            self.translate_requests = _NullMetric()
            self.upstream_errors = _NullMetric()
            self.cache_hits = _NullMetric()
            self.cache_misses = _NullMetric()
            self.translate_duration = _NullMetric()
            self.rate_limited = _NullMetric()
            return
        self.enabled = True
        self.translate_requests = Counter(
            "translate_requests_total", "翻译请求数", ["stream", "result"]
        )
        self.upstream_errors = Counter("translate_upstream_errors_total", "上游错误数", ["code"])
        self.cache_hits = Counter("cache_hit_total", "缓存命中数")
        self.cache_misses = Counter("cache_miss_total", "缓存未命中数")
        self.translate_duration = Histogram("translate_duration_seconds", "翻译耗时 (秒)")
        self.rate_limited = Counter("rate_limited_total", "被限流请求数", ["key_type"])

    def render(self) -> bytes:
        if not self.enabled:
            return b"# metrics disabled\n"
        return generate_latest()


metrics = Metrics()
