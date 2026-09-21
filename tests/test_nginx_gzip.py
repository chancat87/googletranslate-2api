"""Nginx 响应压缩验收 (v2.6.0): JSON/文本 gzip, SSE 不压缩。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _nginx_conf() -> str:
    return (ROOT / "nginx.conf").read_text(encoding="utf-8")


def test_nginx_enables_gzip_for_json_and_text():
    conf = _nginx_conf()
    assert "gzip on;" in conf
    assert "gzip_comp_level 5;" in conf
    assert "gzip_min_length 1024;" in conf
    assert "gzip_proxied any;" in conf
    assert "gzip_vary on;" in conf
    assert "gzip_types" in conf
    assert "application/json" in conf
    assert "text/plain" in conf


def test_nginx_does_not_gzip_sse():
    conf = _nginx_conf()
    gzip_types = next(line for line in conf.splitlines() if line.strip().startswith("gzip_types"))
    assert "text/event-stream" not in gzip_types
