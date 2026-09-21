"""文档本地链接死链检查 (v2.0.0)。

扫描仓库内 Markdown 链接, 校验相对路径目标是否存在。
跳过: http(s)/mailto/data/codex 外部链接、锚点 (#...)、D:\\ 绝对路径。
用法: python scripts/check_docs_links.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_SKIP_PREFIXES = ("http://", "https://", "mailto:", "data:", "codex://", "D:\\", "d:\\", "#")


def iter_markdown_files(root: Path):
    candidates = [
        root / "README.md",
        root / "API_DOCS.md",
        root / "CHANGELOG.md",
        root / "SECURITY.md",
    ]
    candidates += sorted((root / "docs").glob("*.md"))
    plan = root / "计划文档"
    if plan.is_dir():
        candidates += sorted(plan.glob("*.md"))
    return [p for p in candidates if p.is_file()]


def check_file(path: Path, missing: list[str]) -> int:
    count = 0
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        missing.append(f"{path}: 无法读取")
        return 1
    for m in _LINK_RE.finditer(text):
        target = m.group(1).strip()
        if not target or target.startswith(_SKIP_PREFIXES):
            continue
        fragment_target = target.split("#", 1)[0]
        if not fragment_target:
            continue
        resolved = (path.parent / fragment_target).resolve()
        if not resolved.exists():
            missing.append(f"{path.relative_to(ROOT)} -> {target}")
            count += 1
    return count


def main() -> int:
    missing: list[str] = []
    total = 0
    for p in iter_markdown_files(ROOT):
        total += check_file(p, missing)
    if missing:
        print("发现死链:")
        for item in missing:
            print(f"  - {item}")
    else:
        print(f"全部 {len(iter_markdown_files(ROOT))} 个 Markdown 文档无死链")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
