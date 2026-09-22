"""代理池 (v2.13.6): 住宅文件 + 免费抓取双源, 低延迟粘滞 + 失败重试冷却。

设计要点:
- 出口策略: 先本机服务器直连(无代理); 直连失败/429 再按延迟从低到高逐个换代理
- 分配: 已校验/住宅优先, 选延迟最低的健康代理粘滞复用; 失败进 PROXY_RETEST_SECONDS 冷却
- 冷却: 失败(网络/429/5xx)后冷却 1s, 到点重新测延迟/可用, 可用即回池
- 健康: EWMA 成功率; 失败降分, 成功升分并记录延迟
- 无每日限额: 代理按 可用性 / 延迟 / 健康 调度
- 观测: snapshot 只暴露 host:port + latency_ms / validated / health
- 抓取: free_proxy_fetcher_loop 周期抓取公共免费代理列表, 分批校验后注入, 过期剔除
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from urllib.parse import urlsplit

import httpx
from loguru import logger

from app.core.config import settings
from app.core.metrics import metrics

DEFAULT_FREE_URLS = (
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000"
    "&country=all&ssl=all&anonymity=all,"
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt,"
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
)


def normalize_proxy_url(line: str) -> str | None:
    """把 `host:port` / `user:pass@host:port` / `http://...` 规整为完整 URL。"""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" not in line:
        line = "http://" + line
    try:
        u = urlsplit(line)
        if not u.hostname or not u.port:
            return None
    except ValueError:
        return None
    return line


def safe_url(url: str) -> str:
    """脱敏: 只暴露 host:port, 不泄漏 user:pass。"""
    try:
        u = urlsplit(url)
        host = u.hostname or url
        return f"{host}:{u.port}" if u.port else host
    except (ValueError, TypeError):
        return url[:24]


class ProxyEntry:
    __slots__ = (
        "added_at",
        "consecutive_fails",
        "cooldown_until",
        "health_score",
        "last_success_ts",
        "last_used_at",
        "latency_ms",
        "source",
        "url",
        "use_count",
        "validated",
    )

    def __init__(self, url: str, source: str = "residential") -> None:
        self.url = url
        self.source = source
        self.added_at = time.time()
        self.last_used_at = 0.0
        self.use_count = 0
        self.cooldown_until = 0.0
        self.consecutive_fails = 0
        self.health_score = 1.0
        self.last_success_ts = 0.0
        self.validated = False
        self.latency_ms = 0.0

    def available(self, now: float) -> bool:
        return now >= self.cooldown_until

    def snapshot(self) -> dict:
        now = time.time()
        return {
            "url": safe_url(self.url),
            "source": self.source,
            "use_count": self.use_count,
            "cooling": now < self.cooldown_until,
            "cooldown_seconds": max(0, int(self.cooldown_until - now)),
            "fails": self.consecutive_fails,
            "health_score": round(self.health_score, 3),
            "validated": self.validated,
            "latency_ms": round(self.latency_ms, 1) if self.latency_ms else None,
        }


class ProxyPool:
    def __init__(self) -> None:
        self.entries: list[ProxyEntry] = []
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.entries)

    def load_file(self, path: str) -> int:
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError as exc:
            logger.warning(f"代理文件不可读 {path}: {exc}")
            return 0
        return self.add_many([normalize_proxy_url(x) for x in lines], source="residential")

    def add_many(self, urls: Sequence[str | None], source: str) -> int:
        seen = {e.url for e in self.entries}
        added = 0
        for u in urls:
            if not u or u in seen:
                continue
            entry = ProxyEntry(u, source=source)
            entry.validated = source == "residential"
            self.entries.append(entry)
            seen.add(u)
            added += 1
        if added:
            logger.info(f"代理池注入 {added} 个 {source}(总数 {len(self.entries)})")
        return added

    def reap_free(self) -> int:
        now = time.time()
        keep = []
        for e in self.entries:
            if e.source == "free" and now - e.added_at > 10800 and now - e.last_used_at > 1800:
                continue
            keep.append(e)
        removed = len(self.entries) - len(keep)
        self.entries = keep
        if removed:
            logger.info(f"剔除过期免费代理 {removed} 个")
        return removed

    async def acquire(self, prefer_source: str | None = None) -> str | None:
        """取一个可用出口: 已校验/住宅优先, 延迟最低的健康代理粘滞复用。

        成功不触发冷却, 因此低延迟代理会一直被复用; 失败由 mark_failure 冷却 1s 后回池。
        """
        if not self.entries:
            return None
        async with self._lock:
            now = time.time()
            candidates = [e for e in self.entries if e.available(now)]
            if settings.PROXY_PREFER_VALIDATED:
                validated = [e for e in candidates if e.validated or e.source == "residential"]
                if validated:
                    candidates = validated
            if prefer_source:
                pref = [e for e in candidates if e.source == prefer_source]
                if pref:
                    candidates = pref
            if candidates:
                healthy = [e for e in candidates if e.health_score >= 0.5]
                if healthy:
                    candidates = healthy
                # 延迟已知的优先, 按延迟升序; 未知延迟按健康分降序兜底
                known = [e for e in candidates if e.latency_ms > 0]
                if known:
                    pick = min(known, key=lambda e: (e.latency_ms, -e.health_score))
                else:
                    pick = max(candidates, key=lambda e: (e.health_score, -e.cooldown_until))
            else:
                pick = min(self.entries, key=lambda e: e.cooldown_until)
            pick.last_used_at = now
            pick.use_count += 1
            metrics.proxy_uses.labels(source=pick.source).inc()
            return pick.url

    async def mark_failure(self, url: str, rate_limited: bool = True) -> None:
        async with self._lock:
            for e in self.entries:
                if e.url == url:
                    e.consecutive_fails += 1
                    e.health_score = 0.7 * e.health_score
                    # 1s 后重新测延迟/可用性, 能用了就回池
                    e.cooldown_until = time.time() + max(0.0, settings.PROXY_RETEST_SECONDS)
                    metrics.proxy_results.labels(source=e.source, result="fail").inc()
                    return

    async def mark_success(self, url: str, latency_ms: float | None = None) -> None:
        async with self._lock:
            for e in self.entries:
                if e.url == url:
                    e.consecutive_fails = 0
                    e.health_score = 0.7 * e.health_score + 0.3
                    e.last_success_ts = time.time()
                    if latency_ms is not None and latency_ms > 0:
                        e.latency_ms = (
                            0.7 * e.latency_ms + 0.3 * latency_ms if e.latency_ms else latency_ms
                        )
                    metrics.proxy_results.labels(source=e.source, result="ok").inc()
                    return

    async def mark_validated(self, url: str, ok: bool, latency_ms: float | None = None) -> None:
        """校验结果回填: 通过则 validated=True 且健康分上调, 失败也标记已校验(不再兜底优先)。"""
        async with self._lock:
            for e in self.entries:
                if e.url == url:
                    e.validated = True
                    if latency_ms is not None and latency_ms > 0:
                        e.latency_ms = latency_ms
                    if ok:
                        e.consecutive_fails = 0
                        e.health_score = 0.7 * e.health_score + 0.3
                        e.last_success_ts = time.time()
                        metrics.proxy_results.labels(source=e.source, result="ok").inc()
                    else:
                        e.consecutive_fails += 1
                        e.health_score = 0.7 * e.health_score
                        metrics.proxy_results.labels(source=e.source, result="fail").inc()
                    return

    def snapshot(self, page: int = 1, page_size: int = 20) -> dict:
        now = time.time()
        total = len(self.entries)
        start = max(0, (page - 1) * page_size)
        items = [e.snapshot() for e in self.entries[start : start + page_size]]
        return {
            "enabled": self.enabled,
            "total": total,
            "residential": sum(1 for e in self.entries if e.source == "residential"),
            "free": sum(1 for e in self.entries if e.source == "free"),
            "available": sum(1 for e in self.entries if e.available(now)),
            "cooldown": sum(1 for e in self.entries if now < e.cooldown_until),
            "page": page,
            "page_size": page_size,
            "items": items,
        }


def parse_free_lines(text: str) -> list[str]:
    return [n for n in (normalize_proxy_url(x) for x in text.splitlines()) if n]


async def validate_proxy(url: str) -> float | None:  # pragma: no cover - 网络校验
    """短超时校验代理出口可用性, 返回延迟毫秒; 失败返回 None。"""
    target = settings.PROXY_VALIDATE_URL
    timeout = max(1.0, settings.PROXY_VALIDATE_TIMEOUT)
    try:
        started = time.monotonic()
        async with httpx.AsyncClient(proxy=url, timeout=timeout) as client:
            resp = await client.get(target)
            if resp.status_code in (200, 204):
                return (time.monotonic() - started) * 1000
            return None
    except Exception:
        return None


async def _validate_and_mark(pool: ProxyPool, url: str) -> None:  # pragma: no cover - 网络校验
    latency = await validate_proxy(url)
    await pool.mark_validated(url, latency is not None, latency_ms=latency)


async def free_proxy_fetcher_loop(
    pool: ProxyPool,
) -> None:  # pragma: no cover - 后台网络抓取, 由生产 E2E 覆盖
    """后台周期抓取免费代理: 解析 -> 注入 -> 并发校验 -> 过期剔除。"""
    urls = [
        u.strip() for u in (settings.PROXY_FREE_URLS or DEFAULT_FREE_URLS).split(",") if u.strip()
    ]
    refresh = max(60, settings.PROXY_FREE_REFRESH_SECONDS)
    logger.info(f"免费代理抓取器启动: {len(urls)} 源, 每 {refresh}s")
    while True:
        fresh: list[str] = []
        async with httpx.AsyncClient(timeout=15) as client:
            for src in urls:
                try:
                    resp = await client.get(src)
                    if resp.status_code == 200:
                        fresh.extend(parse_free_lines(resp.text))
                except Exception:
                    continue
        added = pool.add_many(fresh, source="free")
        if added:
            sample = fresh[: max(1, settings.PROXY_VALIDATE_SAMPLE)]
            concurrency = max(1, settings.PROXY_VALIDATE_CONCURRENCY)
            for i in range(0, len(sample), concurrency):
                chunk = sample[i : i + concurrency]
                await asyncio.gather(*(_validate_and_mark(pool, u) for u in chunk))
                await asyncio.sleep(max(0.0, settings.PROXY_VALIDATE_PACE))
        pool.reap_free()
        await asyncio.sleep(refresh)
