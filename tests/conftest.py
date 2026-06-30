"""pytest 公共配置与夹具。"""
import os
import sys
from pathlib import Path

import pytest

# 将项目根目录加入 sys.path, 便于 import main / app
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _ensure_google_key(monkeypatch):
    """多数测试 mock 上游, 不需要真实密钥; 注入占位符避免 initialize 报错。"""
    monkeypatch.setenv("GOOGLE_API_KEY", os.environ.get("GOOGLE_API_KEY", "test-key-placeholder"))
