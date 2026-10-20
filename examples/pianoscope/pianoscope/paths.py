"""稳定定位随包资源与根目录下的本地作业空间。"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
RESOURCES = PACKAGE_ROOT / "resources"


def work_root() -> Path:
    """返回本地作业根目录，优先读取 PIANOSCOPE_TMP_DIR；不会创建目录。"""
    return (
        Path(os.environ.get("PIANOSCOPE_TMP_DIR", WORKSPACE_ROOT / ".tmp/pianoscope"))
        .expanduser()
        .resolve()
    )
