"""确定性基准 (v2.1.0): mock 上游 + 应用 + loadtest 一键跑通。

用法: python scripts/bench_ci.py [--output bench.json]
流程: 起 mock 上游(8899) -> 起应用(8090, UPSTREAM_BASE_URL 指向 mock) -> loadtest cache 模式 -> 停服。
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOCK_PORT = 8899
APP_PORT = 8090


def wait_health(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="mock 上游确定性基准")
    ap.add_argument("--output", default=str(ROOT / "bench.json"))
    args = ap.parse_args()

    mock_env = dict(os.environ)
    app_env = dict(os.environ)
    app_env.update(
        {
            "GOOGLE_API_KEY": "dummy-key-for-mock",
            "API_MASTER_KEY": "1",
            "LOG_LEVEL": "WARNING",
            "LOG_FORMAT": "json",
            "PYTHONUTF8": "1",
            "UPSTREAM_BASE_URL": f"http://127.0.0.1:{MOCK_PORT}",
            "CACHE_BACKEND": "memory",
        }
    )

    mock = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "mock_upstream:app",
            "--app-dir",
            str(ROOT / "scripts"),
            "--port",
            str(MOCK_PORT),
            "--log-level",
            "warning",
        ],
        env=mock_env,
    )
    app = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--port",
            str(APP_PORT),
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT),
        env=app_env,
    )
    try:
        if not wait_health(f"http://127.0.0.1:{MOCK_PORT}/health"):
            print("mock 上游未就绪")
            return 1
        if not wait_health(f"http://127.0.0.1:{APP_PORT}/health"):
            print("应用未就绪")
            return 1
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "loadtest.py"),
            "--url",
            f"http://127.0.0.1:{APP_PORT}/v1/chat/completions",
            "--mode",
            "cache",
            "--levels",
            "1,5,10,20",
            "--per",
            "10",
            "--warm",
            "20",
            "--output",
            args.output,
        ]
        rc = subprocess.call(cmd, cwd=str(ROOT))
        # loadtest 预热失败会提前 return 且不写 output, 此时判定失败
        if not os.path.exists(args.output):
            print("bench 未产出结果 (预热失败或服务异常)")
            return 1
        return rc
    finally:
        for proc in (app, mock):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
