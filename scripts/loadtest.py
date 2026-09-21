"""真实并发压测器 (v1.5.1) — 纯 asyncio + httpx, 无第三方压测依赖。

两种模式:
  cache    模式: 预热一批文本入缓存, 并发打缓存命中 -> 测「本地服务承载上限」(不耗上游配额, 安全)
  upstream 模式: 每次唯一文本打真实上游 -> 测「真实上游并发/配额边界」(温和, 429 高时自动停)

用法:
  python scripts/loadtest.py --url http://127.0.0.1:8092/v1/chat/completions --mode cache
  python scripts/loadtest.py --mode upstream --levels 1,2,5,10,15,20 --per 20
输出: 控制台表格 + (可选) --output x.json
"""

import argparse
import asyncio
import json
import statistics as st
import time
import uuid

import httpx


async def run_level(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    concurrency: int,
    total: int,
    text_provider,
) -> dict:
    sem = asyncio.Semaphore(concurrency)
    lat: list[float] = []
    ok = err = r429 = 0
    per_status: dict[str, int] = {}

    async def one(i: int):
        nonlocal ok, err, r429
        async with sem:  # 真实限并发: 各级只放行 concurrency 个请求
            text = text_provider(i)
            payload = json.dumps({"messages": [{"role": "user", "content": text}], "stream": False})
            t0 = time.perf_counter()
            try:
                r = await client.post(url, content=payload, headers=headers)
                dt = (time.perf_counter() - t0) * 1000
            except httpx.HTTPError:
                dt = (time.perf_counter() - t0) * 1000
                lat.append(dt)
                err += 1
                per_status["exception"] = per_status.get("exception", 0) + 1
                return
            lat.append(dt)
            key = str(r.status_code)
            per_status[key] = per_status.get(key, 0) + 1
            if r.status_code == 200:
                ok += 1
            elif r.status_code == 429:
                r429 += 1
                err += 1
            else:
                err += 1

    t0 = time.perf_counter()

    t0 = time.perf_counter()
    await asyncio.gather(*(asyncio.ensure_future(one(i)) for i in range(total)))
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
        "mean_ms": round(st.mean(lat), 1) if lat else 0.0,
        "status": per_status,
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description="真实并发压测器 (v1.5.1)")
    ap.add_argument("--url", default="http://127.0.0.1:8092/v1/chat/completions")
    ap.add_argument("--auth", default="", help="Bearer token (留空=关闭认证)")
    ap.add_argument("--mode", choices=["cache", "upstream"], default="cache")
    ap.add_argument("--levels", default="1,2,5,10,15,20,30,40")
    ap.add_argument("--per", type=int, default=20, help="每级请求数")
    ap.add_argument("--warm", type=int, default=40, help="cache 模式预热文本条数")
    ap.add_argument(
        "--warm-repeat",
        type=int,
        default=1,
        help="每条预热文本重复请求次数 (多 worker 时>1, 让每个 worker 都缓存同一批文本)",
    )
    ap.add_argument("--pause", type=float, default=1.0, help="每级之间暂停秒数")
    ap.add_argument("--stop-429-ratio", type=float, default=0.5, help="429 占比超过此值停止")
    ap.add_argument("--output", default="", help="结果 JSON 输出路径")
    args = ap.parse_args()

    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    headers = {"Content-Type": "application/json"}
    if args.auth:
        headers["Authorization"] = f"Bearer {args.auth}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        print(f"== loadtest mode={args.mode} url={args.url} levels={levels} per={args.per} ==")
        if args.mode == "cache":
            texts = [f"Hello world cached #{i} {uuid.uuid4().hex[:8]}" for i in range(args.warm)]
            # 预热: 每条文本先真实翻译一次入缓存
            print(f"预热 {args.warm} 条文本入缓存 (每条重复 {args.warm_repeat} 次) ...")
            for i, t in enumerate(texts):
                for rep in range(args.warm_repeat):
                    payload = json.dumps(
                        {"messages": [{"role": "user", "content": t}], "stream": False}
                    )
                    r = await client.post(args.url, content=payload, headers=headers)
                    if r.status_code != 200:
                        print(
                            f"  预热失败 #{i} (重复 {rep + 1}/{args.warm_repeat}): HTTP {r.status_code} -> 中止"
                        )
                        return
            print("预热完成。")

            def text_provider(i: int) -> str:
                return texts[i % len(texts)]

            stop_ratio = 1.0  # 缓存命中不打上游, 不会 429
        else:

            def text_provider(i: int) -> str:
                return f"Upstream unique #{i} {uuid.uuid4().hex} {time.time()}"

            stop_ratio = args.stop_429_ratio

        rows: list[dict] = []
        for c in levels:
            row = await run_level(client, args.url, headers, c, args.per, text_provider)
            rows.append(row)
            ratio_429 = row["r429"] / row["total"] if row["total"] else 0
            print(
                f"  conc={row['concurrency']:<3} ok={row['ok']:<3} err={row['err']:<3} "
                f"429={row['r429']:<3} qps={row['qps']:<7} wall={row['wall_s']}s "
                f"p50={row['p50_ms']}ms p95={row['p95_ms']}ms p99={row['p99_ms']}ms "
                f"status={row['status']}"
            )
            if ratio_429 > stop_ratio:
                print(f"!! 429 占比 {ratio_429:.0%} 超过阈值, 停止升压 (上游配额边界)")
                break
            await asyncio.sleep(args.pause)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({"mode": args.mode, "rows": rows}, f, ensure_ascii=False, indent=2)
            print(f"已写入 {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
