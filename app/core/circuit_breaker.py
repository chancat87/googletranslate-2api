"""进程内滑动窗口熔断器 (M4)。

状态机:
- closed   : 正常, 允许请求
- open     : 窗口内失败次数达阈值, 拒绝请求 (快速失败, 不浪费上游)
- half-open: 熔断窗口到期后自动进入, 放行试探请求; 成功则复位 closed, 失败则重新 open

线程安全 (asyncio 单事件循环下也用锁兜底, 兼容多线程 Uvicorn workers 内的信号)。
"""

import threading
import time


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 10,
        window_seconds: int = 60,
        open_seconds: int = 30,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.window_seconds = max(1, window_seconds)
        self.open_seconds = max(1, open_seconds)
        self._failures: list[float] = []
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._failures = [t for t in self._failures if t > cutoff]

    def allow(self) -> bool:
        """当前是否放行请求。"""
        with self._lock:
            now = time.monotonic()
            if self._opened_at is not None:
                # half-open: 放行试探, 不清空失败计数, 由结果决定 next 状态
                return now - self._opened_at >= self.open_seconds
            self._prune(now)
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = []
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            self._failures.append(now)
            if self._opened_at is not None:
                # half-open 试探失败 -> 立即重新熔断
                self._opened_at = now
                return
            if len(self._failures) >= self.failure_threshold:
                self._opened_at = now

    @property
    def is_open(self) -> bool:
        """熔断中 (不含 half-open 放行瞬间的前置判断, 仅用于探针/展示)。"""
        with self._lock:
            if self._opened_at is None:
                return False
            return (time.monotonic() - self._opened_at) < self.open_seconds
