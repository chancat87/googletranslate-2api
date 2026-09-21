"""进程内令牌桶限流 (M6)。

按请求维度 (客户端 IP / 认证 key) 维护独立令牌桶。默认关闭 (RATE_LIMIT_ENABLED)。
注意: 进程内实现, 多 worker / 多副本不共享 —— 水平扩展需 Redis 或网关层
(nginx limit_req) 兜底, 详见 下一步改进指南 §3.B。

P2-2: 桶字典有界 (max_keys), 超出时淘汰最久未访问的桶, 防止攻击者用随机 key 撑爆内存;
使用 OrderedDict 便于 LRU 淘汰 (每次访问 move_to_end)。
"""

import threading
import time
from collections import OrderedDict


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

    def retry_after(self) -> float:
        """还需等待多少秒才能获得 1 个令牌 (供 429 Retry-After 头, P3-8)。

        只做时间回填与读取, 不消费令牌; per_second<=0 时返回正无穷。
        """
        now = time.monotonic()
        elapsed = now - self._updated
        self._updated = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.per_second)
        if self._tokens >= 1.0:
            return 0.0
        if self.per_second <= 0:
            return float("inf")
        return (1.0 - self._tokens) / self.per_second


class RateLimiter:
    """按 key 隔离的多桶限流器 (有界, LRU 淘汰)。"""

    def __init__(self, capacity: int, per_second: float, max_keys: int = 10000) -> None:
        self._capacity = capacity
        self._per_second = per_second
        self._max_keys = max(1, max_keys)
        self._buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._max_keys:
                    # 淘汰最久未访问的桶 (有序字典首个)
                    self._buckets.popitem(last=False)
                bucket = TokenBucket(self._capacity, self._per_second)
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)
            return bucket.consume()

    def retry_after(self, key: str) -> float:
        """该 key 距可放行还需等待的秒数 (P3-8); 未知 key 返回 0。"""
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return 0.0
            self._buckets.move_to_end(key)
            return bucket.retry_after()
