"""进程内令牌桶限流 (M6)。

按请求维度 (客户端 IP / 认证 key) 维护独立令牌桶。默认关闭 (RATE_LIMIT_ENABLED)。
注意: 进程内实现, 多 worker / 多副本不共享 —— 水平扩展需 Redis 或网关层
(nginx limit_req) 兜底, 详见 下一步改进指南 §3.B。
"""

import threading
import time
from collections import defaultdict


class TokenBucket:
    """令牌桶: 以固定速率补充令牌, 容量上限。"""

    def __init__(self, capacity: int, per_second: float) -> None:
        self.capacity = max(1, capacity)
        self.per_second = max(0.0, per_second)
        self._tokens = float(capacity)
        self._updated = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self._updated
        self._updated = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.per_second)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class RateLimiter:
    """按 key 隔离的多桶限流器。"""

    def __init__(self, capacity: int, per_second: float) -> None:
        self._capacity = capacity
        self._per_second = per_second
        self._buckets: defaultdict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(capacity, per_second)
        )
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            return self._buckets[key].consume()
