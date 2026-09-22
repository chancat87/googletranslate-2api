"""单机零中断部署配置验收 (v2.12.0): 双 app 副本 + nginx 蓝绿网关 + Watchtower。"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


def test_prod_compose_has_dual_app_replicas_and_gateway():
    compose = _load_yaml("deploy/compose/docker-compose.prod.yml")
    services = compose["services"]
    assert {"gateway", "app-blue", "app-green", "redis"} <= set(services)
    assert services["gateway"]["depends_on"]["app-blue"]["condition"] == "service_started"
    assert services["gateway"]["depends_on"]["app-green"]["condition"] == "service_started"
    for svc in ("app-blue", "app-green"):
        assert services[svc]["stop_grace_period"] == "35s"
        assert services[svc]["healthcheck"]
        assert services[svc]["labels"]["com.centurylinklabs.watchtower.enable"] == "true"


def test_bluegreen_nginx_retries_other_upstream():
    conf = (ROOT / "deploy/compose/nginx-bluegreen.conf").read_text(encoding="utf-8")
    assert "server app-blue:8000;" in conf
    assert "server app-green:8000;" in conf
    assert "proxy_next_upstream error timeout http_502 http_503 http_504;" in conf
    assert "proxy_next_upstream_tries 2;" in conf


def test_watchtower_compose_uses_label_scope():
    compose = _load_yaml("deploy/compose/docker-compose.watchtower.yml")
    env = " ".join(compose["services"]["watchtower"]["environment"])
    assert "WATCHTOWER_LABEL_ENABLE=true" in env
    assert "WATCHTOWER_CLEANUP=true" in env


def test_upgrade_script_rolls_both_replicas():
    script = (ROOT / "deploy/upgrade.sh").read_text(encoding="utf-8")
    assert "app-blue" in script and "app-green" in script
    assert "--force-recreate" in script
    assert "wait_ready" in script


def test_prod_compose_hardening(options=()):
    """v2.12.4: 只读根文件系统/init/no-new-privileges/tmpfs/数据卷/日志轮转。"""
    compose = _load_yaml("deploy/compose/docker-compose.prod.yml")
    for svc in ("app-blue", "app-green"):
        s = compose["services"][svc]
        assert s["read_only"] is True
        assert s["init"] is True
        assert s["security_opt"] == ["no-new-privileges:true"]
        assert any("/tmp" in t for t in s["tmpfs"])
        assert "app-data:/app/data" in s["volumes"]
        assert s["logging"]["options"]["max-size"] == "10m"
    redis = compose["services"]["redis"]
    assert redis["mem_limit"] == "128m"
    assert redis["cpus"] == "0.5"
    assert "app-data" in compose.get("volumes", {})
    gateway = compose["services"]["gateway"]
    assert gateway["read_only"] is True
    assert gateway["init"] is True
    assert gateway["security_opt"] == ["no-new-privileges:true"]
    assert "/var/cache/nginx" in gateway["tmpfs"]
    assert gateway["mem_limit"] == "64m"
    assert gateway["logging"]["options"]["max-size"] == "10m"


def test_dockerfile_multi_stage_and_hardening():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "AS builder" in dockerfile
    assert "pip install --no-cache-dir --prefix=/install -r requirements.lock" in dockerfile
    assert "COPY --from=builder /install /usr/local" in dockerfile
    assert "COPY --chown=appuser:appuser . ." in dockerfile
    assert "USER appuser" in dockerfile
    assert "STOPSIGNAL SIGTERM" in dockerfile
    assert "HEALTHCHECK" in dockerfile


def test_dockerignore_excludes_secrets_and_tooling():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for pattern in (".env", "data/", ".venv/", "tests/", ".specify/", "node_modules/"):
        assert pattern in ignore
