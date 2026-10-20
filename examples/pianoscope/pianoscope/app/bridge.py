"""显式的 MusicXML API 桥接表；文件路径始终保留在 Python 侧。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pianoscope.app.controller import Controller


class PianoAPI(Protocol):
    """原生 API 桥接所需的最小注册接口，避免导入 AppCore 作为类型依赖。"""

    def register(self, function: Callable[..., object]) -> object:
        """注册可由 JavaScript 调用的同步或异步 Python 函数。"""
        ...


def register(api: PianoAPI, controller: Controller) -> None:
    """把显式允许的控制器方法注册到 API("piano")。

    api 为 ultralight-py 原生 API 对象；只暴露令牌与结构化记录，不暴露文件路径。
    """
    for name in (
        "choose_score",
        "choose_score_folder",
        "get_score_library",
        "begin_score_load",
        "get_job",
        "cancel_job",
        "confirm_score_load",
        "get_candidate",
        "get_score_page",
        "begin_score_layout",
        "get_layout_candidate",
        "publish_score_layout",
        "publish_score_load",
        "get_document",
        "get_capabilities",
        "get_diagnostics",
        "get_notes",
        "get_overview",
        "get_source_elements",
        "get_practice_settings",
        "play",
        "pause",
        "stop",
        "seek",
        "seek_score",
        "configure",
        "set_volume",
        "set_loop",
        "get_transport",
        "get_analysis",
        "preview_hands",
        "apply_hands",
        "undo_hands",
        "retry_audio",
        "choose_export",
        "begin_export",
    ):
        api.register(getattr(controller, name))
