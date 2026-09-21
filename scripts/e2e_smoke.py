"""真实 E2E 验收脚本 (v1.6.0): 端到端打一个运行中的服务, 校验全端点矩阵。

用法:
  python scripts/e2e_smoke.py --url http://127.0.0.1:8090 [--auth <token>]
                              [--expect-version 1.6.0] [--rate-limit]
返回码: 0 = 全部通过; 1 = 有失败项。
"""

import argparse
import sys
import uuid

import httpx

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description="googletranslate-2api E2E 验收")
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--auth", default="", help="Bearer token; 留空表示服务关闭认证")
    ap.add_argument("--expect-version", default="")
    ap.add_argument(
        "--rate-limit", action="store_true", help="校验限流 429 (需服务开启 RATE_LIMIT)"
    )
    args = ap.parse_args()

    base = args.url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if args.auth:
        headers["Authorization"] = f"Bearer {args.auth}"

    with httpx.Client(timeout=90.0, headers=headers) as c:
        print(f"== E2E smoke base={base} auth={'on' if args.auth else 'off'} ==")

        # --- 系统端点 ---
        r = c.get(f"{base}/health")
        body = r.json()
        check("GET /health", r.status_code == 200 and body.get("status") == "ok", str(body))
        if args.expect_version:
            check(
                "version matches",
                body.get("version") == args.expect_version,
                str(body.get("version")),
            )

        r = c.get(f"{base}/ready")
        check(
            "GET /ready",
            r.status_code == 200 and r.json().get("status") == "ready",
            str(r.text[:120]),
        )

        r = c.get(f"{base}/")
        check(
            "GET /", r.status_code == 200 and "googletranslate-2api" in r.text, str(r.status_code)
        )

        r = c.get(f"{base}/docs")
        check("GET /docs", r.status_code == 200)
        r = c.get(f"{base}/redoc")
        check("GET /redoc", r.status_code == 200)
        r = c.get(f"{base}/openapi.json")
        paths = r.json().get("paths", {}) if r.status_code == 200 else {}
        need = {"/v1/chat/completions", "/v1/translate/batch", "/v1/translate/detect", "/v1/models"}
        check(
            "openapi paths",
            r.status_code == 200 and need.issubset(paths),
            str(sorted(need - set(paths))),
        )

        r = c.get(f"{base}/metrics")
        check("GET /metrics", r.status_code == 200 and "translate_requests_total" in r.text)

        # --- 模型 ---
        r = c.get(f"{base}/v1/models")
        ok = r.status_code == 200 and any(
            m.get("id") == "google-translate" for m in r.json().get("data", [])
        )
        check("GET /v1/models", ok)

        # --- 非流式翻译 ---
        text1 = f"E2E hello world {uuid.uuid4().hex[:8]}"
        r = c.post(
            f"{base}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": text1}],
                "target_lang": "zh-CN",
                "stream": False,
            },
        )
        j = r.json() if r.status_code == 200 else {}
        content1 = j.get("choices", [{}])[0].get("message", {}).get("content", "")
        ok = r.status_code == 200 and bool(content1) and j.get("usage", {}).get("estimate") is True
        check("non-stream translate", ok, content1[:40] or str(r.text[:120]))

        # --- 流式翻译 (SSE) ---
        r = c.post(
            f"{base}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": text1}],
                "target_lang": "zh-CN",
                "stream": True,
            },
        )
        ok = r.status_code == 200 and "data: {" in r.text and "data: [DONE]" in r.text
        check("stream translate (SSE)", ok, str(r.text[:80]))

        # --- 缓存命中 (trace 复验) ---
        r1 = c.post(
            f"{base}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": text1}],
                "target_lang": "zh-CN",
                "stream": False,
            },
        )
        id2 = r1.json().get("id", "") if r1.status_code == 200 else ""
        trace_hit = False
        if id2:
            tr = c.get(f"{base}/v1/traces/{id2}")
            trace_hit = tr.status_code == 200 and tr.json().get("cache_hit") is True
        check("cache hit via trace", r1.status_code == 200 and trace_hit, f"id={id2}")

        # --- 批量 ---
        r = c.post(
            f"{base}/v1/translate/batch",
            json={"texts": ["apple", "banana", "car", "dog"], "target_lang": "zh-CN"},
        )
        j = r.json() if r.status_code == 200 else {}
        ok = j.get("count") == 4 and all(x.get("ok") for x in j.get("data", []))
        check("batch translate", r.status_code == 200 and ok, str(j.get("data", []))[:120])

        # --- 语言检测 ---
        r = c.post(f"{base}/v1/translate/detect", json={"text": "hello world"})
        ok = r.status_code == 200 and r.json().get("source") == "script_heuristic"
        check("detect", ok, str(r.text[:120]))

        # --- 错误矩阵 ---
        r = c.post(f"{base}/v1/chat/completions", json={"stream": False})
        ok = r.status_code == 422 or (args.rate_limit and r.status_code == 429)
        check("422 missing messages", ok, str(r.status_code))
        r = c.post(f"{base}/v1/translate/batch", json={"texts": [], "target_lang": "zh-CN"})
        ok = r.status_code == 400 or (args.rate_limit and r.status_code == 429)
        check("400 empty batch", ok, str(r.status_code))
        r = c.post(
            f"{base}/v1/translate/batch",
            json={"texts": ["a"], "source_lang": "klingon", "target_lang": "zh-CN"},
        )
        # 限流模式下令牌桶可能先耗尽, 429 同样证明中间件生效
        ok = r.status_code == 400 or (args.rate_limit and r.status_code == 429)
        check("400 bad lang", ok, str(r.status_code))
        long_text = "x" * 5001
        r = c.post(
            f"{base}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": long_text}], "stream": False},
        )
        ok = r.status_code == 413 or (args.rate_limit and r.status_code == 429)
        check("413 too long", ok, str(r.status_code))

        # --- 认证矩阵 (仅 --auth 时) ---
        if args.auth:
            with httpx.Client(
                timeout=90.0, headers={"Content-Type": "application/json"}
            ) as c_noauth:
                r = c_noauth.post(
                    f"{base}/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "x"}], "stream": False},
                )
            check("401 no auth", r.status_code == 401, str(r.status_code))
            r = c.post(
                f"{base}/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "x"}], "stream": False},
                headers={"Authorization": "Bearer wrong-key-0000000000"},
            )
            check("403 bad auth", r.status_code == 403, str(r.status_code))

        # --- 限流 (仅 --rate-limit, 需服务开启 RATE_LIMIT_ENABLED) ---
        if args.rate_limit:
            saw_429 = False
            for _ in range(12):
                r = c.post(
                    f"{base}/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": f"rl {uuid.uuid4().hex}"}],
                        "stream": False,
                    },
                )
                if r.status_code == 429:
                    saw_429 = True
                    break
            check("rate limit 429", saw_429, "no 429 observed" if not saw_429 else "429 observed")

    failed = [x for x in RESULTS if not x[1]]
    print(f"\n== RESULT: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed ==")
    if failed:
        print("FAILED:")
        for name, _, detail in failed:
            print(f"  - {name}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
