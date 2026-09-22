"""代理池 (v2.13.0): 住宅文件 + 免费抓取双源, 智能轮换出口 IP。

设计要点:
- 双源: residential(文件, 优先) + free(抓取, 兜底), 每请求换出口降低上游按 IP 风控
- 分配: 优先使用从未用过的 IP; 全用过一轮后按 health_score(EWMA) 降序 + 冷却最早结束
- 冷却: 递增冷却 (PROXY_USE_COOLDOWN_MAP), 429/失败触发冷却并下调健康分
- 健康: EWMA 成功率, 失败降分、成功升分, 不硬剔除, 给恢复机会
- 观测: snapshot 只暴露 host:port, 不泄漏 user:pass 凭据
- 抓取: free_proxy_fetcher_loop 周期抓取公共免费代理列表, 并发校验后注入, 过期剔除
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

DAILY_WINDOW = 24 * 3600
DEFAULT_FREE_URLS = (
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000"
    "&country=all&ssl=all&anonymity=all,"
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt,"
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
)


def _parse_cooldown_map(raw: str) -> dict[int, int]:
    out: dict[int, int] = {}
    for i, part in enumerate(raw.split(","), start=1):
        part = part.strip()
        if part.isdigit():
            out[i] = int(part)
    return out or {1: 0, 2: 10, 3: 30, 4: 90, 5: 300}


_COOLDOWN_MAP = _parse_cooldown_map(settings.PROXY_USE_COOLDOWN_MAP)


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
        "day_key",
        "health_score",
        "last_success_ts",
        "last_used_at",
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
        self.day_key = int(time.time() / DAILY_WINDOW)
        self.cooldown_until = 0.0
        self.consecutive_fails = 0
        self.health_score = 1.0
        self.last_success_ts = 0.0
        self.validated = False

    def available(self, now: float) -> bool:
        if now < self.cooldown_until:
            return False
        day = int(now / DAILY_WINDOW)
        if day != self.day_key:
            self.day_key = day
            self.use_count = 0
            self.consecutive_fails = 0
        max_use = settings.PROXY_MAX_USE_PER_DAY
        return not (max_use > 0 and self.use_count >= max_use)

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
        """取一个可用出口; 无可用时返回 None (上层走直连)。"""
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
                unused = [e for e in candidates if e.use_count == 0]
                if unused:
                    pick = max(unused, key=lambda e: e.health_score)
                else:
                    pick = max(candidates, key=lambda e: (e.health_score, -e.cooldown_until))
            else:
                pick = min(self.entries, key=lambda e: e.cooldown_until)
            pick.last_used_at = now
            pick.use_count += 1
            next_level = min(pick.use_count, max(_COOLDOWN_MAP))
            pick.cooldown_until = now + _COOLDOWN_MAP[next_level]
            metrics.proxy_uses.labels(source=pick.source).inc()
            return pick.url

    async def mark_failure(self, url: str, rate_limited: bool = True) -> None:
        async with self._lock:
            for e in self.entries:
                if e.url == url:
                    e.consecutive_fails += 1
                    e.health_score = 0.7 * e.health_score
                    next_level = min(e.use_count + 1, max(_COOLDOWN_MAP))
                    delay = _COOLDOWN_MAP[next_level] if rate_limited else 30
                    e.cooldown_until = time.time() + delay
                    metrics.proxy_results.labels(source=e.source, result="fail").inc()
                    return

    async def mark_success(self, url: str) -> None:
        async with self._lock:
            for e in self.entries:
                if e.url == url:
                    e.consecutive_fails = 0
                    e.health_score = 0.7 * e.health_score + 0.3
                    e.last_success_ts = time.time()
                    metrics.proxy_results.labels(source=e.source, result="ok").inc()
                    return

    async def mark_validated(self, url: str, ok: bool) -> None:
        """校验结果回填: 通过则 validated=True 且健康分上调, 失败也标记已校验(不再兜底优先)。"""
        async with self._lock:
            for e in self.entries:
                if e.url == url:
                    e.validated = True
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


async def validate_proxy(url: str) -> bool:  # pragma: no cover - 网络校验, 由生产 E2E 覆盖
    """用短超时请求校验代理出口可用性 (不会消耗翻译配额)。"""
    target = settings.PROXY_VALIDATE_URL
    timeout = max(1.0, settings.PROXY_VALIDATE_TIMEOUT)
    try:
        async with httpx.AsyncClient(proxy=url, timeout=timeout) as client:
            resp = await client.get(target)
            return resp.status_code in (200, 204)
    except Exception:
        return False


async def _validate_and_mark(pool: ProxyPool, url: str) -> None:  # pragma: no cover - 网络校验
    ok = await validate_proxy(url)
    await pool.mark_validated(url, ok)


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
