"""文档死链检查测试 (v2.0.0)。"""

import subprocess
import sys
from pathlib import Path


def test_docs_have_no_broken_links():
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_docs_links.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
