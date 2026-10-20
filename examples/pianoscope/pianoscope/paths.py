"""Stable resource locations and the workspace for local application jobs."""

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
RESOURCES = PACKAGE_ROOT / "resources"


def work_root():
    return (
        Path(os.environ.get("PIANOSCOPE_TMP_DIR", WORKSPACE_ROOT / ".tmp/pianoscope"))
        .expanduser()
        .resolve()
    )
