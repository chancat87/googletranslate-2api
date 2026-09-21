"""多上游 Key 池 (阶段 1.1 / 结果计划指南 §6-1.1)。

设计来源: D:\\参考项目 free-router / ai-getaway / chatgpt2api 的
「多账号 Key 池 + 失败自动切换 + 冷却」思想, 按主项目规模 (单进程内存) 轻量实现,
不引第三方依赖。

行为:
- next(): 从游标起轮询返回一个「未冷却」的 Key; 全部冷却时返回最早到期的 Key (尽力而为)。
- mark_failed(): 给 Key 加冷却 (KEY_FAILOVER_COOLDOWN_SECONDS), 供 403/429/transport 切换。
- mark_success(): 清除冷却。
- status() / available_count(): 供 /ready 与 /metrics 暴露各 Key 状态。
- key_hash(): 只暴露摘要, 永不回传明文 Key。
"""

import hashlib
import threading
import time


def key_hash(key: str, length: int = 8) -> str:
    """Key 的短哈希摘要 (用于指标/日志/链路摘要, 不回传明文)。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:length]


class KeyPool:
    def __init__(self, keys: list[str], cooldown_seconds: float = 60.0, now=None):
        self._keys = [k for k in keys if k and k.strip()]
        self._cooldown_seconds = max(0.0, cooldown_seconds)
        # 默认用 monotonic 时钟 (不受系统时间跳变影响); 测试可注入可控时钟
        self._now = now or time.monotonic
        self._cooldowns: dict[str, float] = {}
        self._cursor = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def keys(self) -> list[str]:
        return list(self._keys)

    def next(self) -> str | None:
        """选下一个可用 Key; 全部冷却时返回最早到期者 (尽力而为, 不硬性失败)。"""
        if not self._keys:
            return None
        now = self._now()
        with self._lock:
            for _ in range(len(self._keys)):
                k = self._keys[self._cursor % len(self._keys)]
                self._cursor += 1
                if self._cooldowns.get(k, 0.0) <= now:
                    return k
            earliest = min(self._keys, key=lambda x: self._cooldowns.get(x, 0.0))
            self._cursor = (self._keys.index(earliest) + 1) % len(self._keys)
            return earliest

    def mark_failed(self, key: str) -> None:
        if key not in self._keys:
            return
        with self._lock:
            self._cooldowns[key] = self._now() + self._cooldown_seconds

    def mark_success(self, key: str) -> None:
        if key not in self._keys:
            return
        with self._lock:
            self._cooldowns.pop(key, None)

    def available_count(self) -> int:
        now = self._now()
        return sum(1 for k in self._keys if self._cooldowns.get(k, 0.0) <= now)

    def status(self) -> list[dict]:
        now = self._now()
        return [
            {
                "key_hash": key_hash(k),
                "state": "ok" if self._cooldowns.get(k, 0.0) <= now else "cooldown",
                "cooldown_seconds_left": max(0.0, self._cooldowns.get(k, 0.0) - now),
            }
            for k in self._keys
        ]
