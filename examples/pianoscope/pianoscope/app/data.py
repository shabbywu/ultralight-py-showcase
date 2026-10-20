"""在主线程把共享界面输入固化为不依赖 JS 文档的作业数据。"""

from collections.abc import Mapping, Sequence
from typing import Any

from pianoscope.types import Record


def snapshot(value: Any, depth: int = 0) -> Any:
    """递归复制基础记录与序列，禁止把共享视图带入异步作业或工作线程。"""
    if depth > 64:
        raise ValueError("设置嵌套过深或包含循环引用")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(k): snapshot(v, depth + 1) for k, v in value.items()}
    if isinstance(value, Sequence):
        return [snapshot(v, depth + 1) for v in value]
    raise ValueError("设置必须为基础数据")


def snapshot_record(value: Mapping[str, Any]) -> Record:
    """复制命令参数及全部嵌套容器，结果可安全跨 await 和线程保存。"""
    return snapshot(value)
