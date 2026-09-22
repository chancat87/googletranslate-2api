"""pytest 公共配置与夹具。

密封性说明 (M0):
`app/core/config.py` 在模块导入时即执行 `settings = Settings()`, pydantic-settings
会立即读取 .env 与环境变量并"定格"该单例; 而 `main.py` 的 lifespan 又会强校验
GOOGLE_API_KEY。因此必须在**任何 app 模块被 import 之前**于本文件顶层预置占位
key, 否则全新环境 (无 .env) 下所有依赖 lifespan/initialize 的测试都会报
`ValueError: GOOGLE_API_KEY 未在 .env 文件中配置`。
"""

import os
import sys
from pathlib import Path

import pytest

# --- M0: 导入期预置 (必须在 import main / app 之前执行) ---
os.environ.setdefault("GOOGLE_API_KEY", "test-key-placeholder")
os.environ.setdefault("API_MASTER_KEY", "1")

# 将项目根目录加入 sys.path, 便于 import main / app
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _ensure_google_key(monkeypatch):
    """双保险: 每个测试再次注入占位 key (对新创建的 Settings 实例生效)。"""
    monkeypatch.setenv("GOOGLE_API_KEY", os.environ.get("GOOGLE_API_KEY", "test-key-placeholder"))
    monkeypatch.setenv("API_MASTER_KEY", os.environ.get("API_MASTER_KEY", "1"))
