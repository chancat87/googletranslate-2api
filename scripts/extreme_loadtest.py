"""Extreme concurrency load tester for googletranslate-2api.

Unlike scripts/loadtest.py this raises httpx connection limits so a single
process can hold 1000+ concurrent requests instead of being capped by the
httpx default connection pool.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid

import httpx


async def run_burst(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    concurrency: int,
    total: int,
    text_provider,
) -> dict:
    sem = asyncio.Semaphore(concurrency)
    lat: list[float] = []
    ok = err = r429 = done = 0
    status: dict[str, int] = {}
    tasks: list[asyncio.Task] = []
    stop = asyncio.Event()

    async def one(i: int) -> None:
        nonlocal ok, err, r429, done
        async with sem:
            payload = json.dumps(
                {"messages": [{"role": "user", "content": text_provider(i)}], "stream": False}
            )
            t0 = time.perf_counter()
            try:
                r = await client.post(url, content=payload, headers=headers)
                dt = (time.perf_counter() - t0) * 1000
                code = str(r.status_code)
            except httpx.HTTPError:
                dt = (time.perf_counter() - t0) * 1000
                lat.append(dt)
                err += 1
                done += 1
                status["exception"] = status.get("exception", 0) + 1
                return
            lat.append(dt)
            status[code] = status.get(code, 0) + 1
            if code == "200":
                ok += 1
            elif code == "429":
                r429 += 1
                err += 1
            else:
                err += 1
            done += 1
            if done >= 20 and r429 / done > 0.5 and not stop.is_set():
                stop.set()
                current = asyncio.current_task()
                for task in tasks:
                    if task is not current:
                        task.cancel()

    t0 = time.perf_counter()
    tasks = [asyncio.create_task(one(i)) for i in range(total)]
    await asyncio.gather(*tasks, return_exceptions=True)
    wall = time.perf_counter() - t0

    ls = sorted(lat)

    def pct(p: float) -> float:
        if not ls:
            return 0.0
        return ls[min(len(ls) - 1, int(len(ls) * p))]

    return {
        "concurrency": concurrency,
        "total": total,
        "ok": ok,
        "err": err,
        "r429": r429,
        "qps": round(total / wall, 1) if wall > 0 else 0.0,
        "wall_s": round(wall, 3),
        "p50_ms": round(pct(0.5), 1),
        "p95_ms": round(pct(0.95), 1),
        "p99_ms": round(pct(0.99), 1),
        "mean_ms": round(statistics.mean(lat), 1) if lat else 0.0,
        "status": status,
        "stopped_early": stop.is_set(),
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description="Extreme concurrency load tester")
    ap.add_argument("--url", required=True)
    ap.add_argument("--auth", default="")
    ap.add_argument("--mode", choices=["cache", "upstream"], default="cache")
    ap.add_argument("--concurrency", type=int, default=1000)
    ap.add_argument("--total", type=int, default=1000)
    ap.add_argument("--warm", type=int, default=20)
    ap.add_argument("--warm-repeat", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--max-connections", type=int, default=1500)
    ap.add_argument("--max-keepalive", type=int, default=500)
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    headers = {"Content-Type": "application/json"}
    if args.auth:
        headers["Authorization"] = f"Bearer {args.auth}"

    limits = httpx.Limits(
        max_connections=args.max_connections,
        max_keepalive_connections=args.max_keepalive,
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(args.timeout), limits=limits) as client:
        print(
            f"== extreme mode={args.mode} conc={args.concurrency} total={args.total} "
            f"max_conn={args.max_connections} =="
        )

        if args.mode == "cache":
            texts = [f"Hello world cached #{i} {uuid.uuid4().hex[:8]}" for i in range(args.warm)]
            print(f"warming {args.warm} texts x{args.warm_repeat} ...")
            for i, text in enumerate(texts):
                for rep in range(args.warm_repeat):
                    payload = json.dumps(
                        {"messages": [{"role": "user", "content": text}], "stream": False}
                    )
                    r = await client.post(args.url, content=payload, headers=headers)
                    if r.status_code != 200:
                        print(
                            f"warmup failed #{i} rep {rep + 1}: HTTP {r.status_code} -> abort"
                        )
                        return
            print("warmup done")

            def text_provider(i: int) -> str:
                return texts[i % len(texts)]
        else:
            def text_provider(i: int) -> str:
                return f"Upstream unique extreme #{i} {uuid.uuid4().hex} {time.time()}"

        row = await run_burst(client, args.url, headers, args.concurrency, args.total, text_provider)
        print(
            f"  conc={row['concurrency']} ok={row['ok']} err={row['err']} 429={row['r429']} "
            f"qps={row['qps']} wall={row['wall_s']}s p50={row['p50_ms']}ms "
            f"p95={row['p95_ms']}ms p99={row['p99_ms']}ms status={row['status']} "
            f"stopped_early={row['stopped_early']}"
        )

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({"mode": args.mode, "rows": [row]}, f, ensure_ascii=False, indent=2)
            print(f"saved {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
