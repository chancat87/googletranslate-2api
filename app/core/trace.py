"""请求链路摘要 (阶段 1.2 / 结果计划指南 §6-1.2)。

设计来源: 参考库 skills 生态「让用户边用边学」——把一次请求的完整链路
(缓存命中 / 上游状态 / 耗时 ms / 使用的 Key 哈希 / 重试次数 / 熔断状态)
用人类可读形式呈现, 小白可直接看懂一次翻译为什么慢/为什么失败。

- 非流式: 响应头 X-Trace-Summary (单行摘要) + 环形缓冲可查。
- 流式: 响应头 X-Trace-Id, 客户端可凭该 ID 查 /v1/traces/{request_id}。
- 隐私: 只存元数据, 不含请求原文与明文 Key。
"""

import threading
from collections import OrderedDict


class TraceStore:
    """进程内环形缓冲: 上限 TRACE_STORE_MAXLEN, 满则淘汰最旧。"""

    def __init__(self, maxlen: int = 512) -> None:
        self.maxlen = maxlen
        self._data: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, request_id: str, record: dict) -> None:
        with self._lock:
            self._data[request_id] = record
            self._data.move_to_end(request_id)
            while len(self._data) > self.maxlen:
                self._data.popitem(last=False)

    def get(self, request_id: str) -> dict | None:
        with self._lock:
            rec = self._data.get(request_id)
            return dict(rec) if rec else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


def format_trace_summary(trace: dict) -> str:
    """压缩为单行人类可读摘要 (供 X-Trace-Summary 响应头)。"""
    parts = ["cache=hit" if trace.get("cache_hit") else "cache=miss"]
    status = trace.get("upstream_status")
    if status:
        parts.append(f"upstream={status}")
    duration = trace.get("duration_ms")
    if duration is not None:
        parts.append(f"{duration}ms")
    used_key = trace.get("used_key")
    if used_key:
        parts.append(f"key={used_key}")
    retries = trace.get("retries") or 0
    if retries:
        parts.append(f"retries={retries}")
    if trace.get("circuit_open"):
        parts.append("circuit=open")
    return " ".join(parts)
