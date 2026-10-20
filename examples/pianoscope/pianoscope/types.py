"""跨包使用的记录、路径和取消协议；异构记录的字段由各业务函数校验。"""

from __future__ import annotations

from collections.abc import Callable
from os import PathLike
from typing import Any, TypeAlias

Record: TypeAlias = dict[str, Any]
PathInput: TypeAlias = str | PathLike[str]
Cancelled: TypeAlias = Callable[[], bool]
Progress: TypeAlias = Callable[[float], None]
PhaseProgress: TypeAlias = Callable[[str], None]
HandAssignments: TypeAlias = dict[str, str]
