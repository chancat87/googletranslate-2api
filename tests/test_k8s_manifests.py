"""K8s 部署清单验收 (v2.3.0): 结构、滚动更新、探针、优雅终止与访问面。"""

from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parent.parent / "deploy" / "k8s"
ROOT = DEPLOY.parent.parent


def _load(name: str):
    with open(DEPLOY / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_all(name: str):
    with open(DEPLOY / name, encoding="utf-8") as f:
        return [doc for doc in yaml.safe_load_all(f) if doc]


def test_required_manifest_files_exist():
    expected = {
        "configmap.yaml",
        "deployment.yaml",
        "hpa.yaml",
        "ingress.yaml",
        "kustomization.yaml",
        "redis.yaml",
        "secret.example.yaml",
        "service.yaml",
        "README.md",
    }
    missing = expected - {p.name for p in DEPLOY.iterdir()}
    assert not missing


def test_deployment_rolling_update_grace_and_probes():
    doc = _load("deployment.yaml")
    assert doc["kind"] == "Deployment"
    spec = doc["spec"]
    assert spec["replicas"] == 2
    strategy = spec["strategy"]["rollingUpdate"]
    assert strategy["maxUnavailable"] == "0"
    assert strategy["maxSurge"] == 1
    assert spec["template"]["spec"]["terminationGracePeriodSeconds"] >= 30
    pod_spec = spec["template"]["spec"]
    assert pod_spec["securityContext"]["runAsNonRoot"] is True
    container = spec["template"]["spec"]["containers"][0]
    assert container["image"].endswith(":v2.4.0")
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["livenessProbe"]["httpGet"]["path"] == "/health"
    assert container["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert container["ports"][0]["containerPort"] == 8000


def test_service_hpa_ingress_redis_and_config():
    service = _load("service.yaml")
    assert service["kind"] == "Service"
    assert service["spec"]["ports"][0]["port"] == 80

    hpa = _load("hpa.yaml")
    assert hpa["kind"] == "HorizontalPodAutoscaler"
    assert hpa["spec"]["maxReplicas"] >= 4
    assert hpa["spec"]["metrics"][0]["resource"]["name"] == "cpu"

    ingress = _load("ingress.yaml")
    assert ingress["kind"] == "Ingress"
    assert ingress["spec"]["rules"][0]["http"]["paths"][0]["pathType"] == "Prefix"

    redis = _load_all("redis.yaml")
    kinds = [doc["kind"] for doc in redis]
    assert kinds == ["Deployment", "Service"]

    config = _load("configmap.yaml")
    assert config["data"]["CACHE_BACKEND"] == "redis"
    assert config["data"]["REDIS_URL"].startswith("redis://")


def test_kustomization_links_all_resources():
    doc = _load("kustomization.yaml")
    resources = set(doc["resources"])
    assert {
        "configmap.yaml",
        "deployment.yaml",
        "service.yaml",
        "hpa.yaml",
        "ingress.yaml",
        "redis.yaml",
    } <= resources


def test_dockerfile_graceful_shutdown():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "STOPSIGNAL SIGTERM" in dockerfile
    assert "--timeout-graceful-shutdown ${APP_SHUTDOWN_GRACE:-30}" in dockerfile


def test_compose_stop_grace_period():
    with open(ROOT / "docker-compose.yml", encoding="utf-8") as f:
        compose = yaml.safe_load(f)
    assert compose["services"]["app"]["stop_grace_period"] == "35s"


def test_ci_has_kubeconform_schema_validation():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Kubeconform schema validate" in text
    assert "kubeconform-linux-amd64.tar.gz" in text
    assert "-strict -ignore-missing-schemas -summary deploy/k8s" in text


@pytest.mark.parametrize(
    "name",
    ["configmap.yaml", "deployment.yaml", "hpa.yaml", "ingress.yaml", "redis.yaml", "service.yaml"],
)
def test_yaml_files_parse(name):
    docs = _load_all(name) if name == "redis.yaml" else [_load(name)]
    assert docs
    for doc in docs:
        assert isinstance(doc, dict)
        assert doc["apiVersion"]
        assert doc["kind"]
