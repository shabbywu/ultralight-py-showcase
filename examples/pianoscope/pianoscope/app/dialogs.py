"""原生打开、保存与窗口关闭通知，前端只接收不透明文件令牌。"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


def choose_path(
    auto_cancel: bool = False,
    folder: bool = False,
    extensions: list[str] | None = None,
    label: str = "MIDI",
) -> Path | None:
    """打开原生文件或目录选择器，返回所选路径；取消返回 None。

    auto_cancel 仅供原生验收；extensions 不含点号。选择器不可用时抛出 RuntimeError。
    """
    if sys.platform == "darwin":
        from AppKit import NSModalPanelRunLoopMode, NSModalResponseOK, NSOpenPanel
        from Foundation import NSRunLoop, NSTimer

        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(not folder)
        panel.setCanChooseDirectories_(folder)
        panel.setAllowsMultipleSelection_(False)
        panel.setTitle_("选择 " + label + " 文件夹" if folder else "打开" + label)
        panel.setAllowedFileTypes_(None if folder else (extensions or ["mid", "midi"]))
        timer = None
        if auto_cancel:
            timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                0.25, False, lambda _: panel.cancel_(None)
            )
        if timer:
            NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSModalPanelRunLoopMode)
        result = panel.runModal()
        if timer:
            timer.invalidate()
        return Path(str(panel.URL().path())) if result == NSModalResponseOK else None
    try:
        import tkinter as tk
        from tkinter.filedialog import askdirectory, askopenfilename

        root = tk.Tk()
        root.withdraw()
        try:
            value = (
                askdirectory(title="选择 " + label + " 文件夹")
                if folder
                else askopenfilename(
                    filetypes=[
                        (
                            label,
                            " ".join(
                                "*." + ext for ext in (extensions or ["mid", "midi"])
                            ),
                        )
                    ]
                )
            )
            return Path(value) if value else None
        finally:
            root.destroy()
    except Exception as exc:
        raise RuntimeError(
            "文件选择器不可用，请使用路径输入或 --file 打开文件。"
        ) from exc


def before_window_close(title: str, callback: Callable[[], None]) -> Callable[[], None]:
    """在匹配标题的 macOS 窗口释放前执行 callback，返回注销观察者的函数。

    其他平台返回空操作；调用方应在应用退出时注销观察者。
    """
    if sys.platform != "darwin":
        return lambda: None
    from Foundation import NSNotificationCenter

    center = NSNotificationCenter.defaultCenter()

    def closing(notification: Any) -> None:
        """接收 PyObjC 原生通知，仅关闭标题匹配的窗口所关联的会话。"""
        window = notification.object()
        if str(window.title()) == title:
            callback()

    token = center.addObserverForName_object_queue_usingBlock_(
        "NSWindowWillCloseNotification", None, None, closing
    )
    return lambda: center.removeObserver_(token)


def choose_score_path(
    title: str, format: str, auto_cancel: bool = False
) -> Path | None:
    """选择导出路径并由原生窗口确认覆盖；取消返回 None。

    format 为受支持的文件扩展名；无效格式抛出 ValueError。此函数不写入文件。
    """
    if format not in ("pdf", "musicxml", "xml", "mxl", "mid"):
        raise ValueError("无效导出格式")
    filename = "".join(c for c in title if c not in "/\\:\0")[:80] or "练习谱"
    if sys.platform == "darwin":
        from AppKit import NSModalPanelRunLoopMode, NSModalResponseOK, NSSavePanel
        from Foundation import NSRunLoop, NSTimer

        panel = NSSavePanel.savePanel()
        panel.setAllowedFileTypes_([format])
        panel.setNameFieldStringValue_(filename + "." + format)
        panel.setCanCreateDirectories_(True)
        timer = None
        if auto_cancel:
            timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                0.25, False, lambda _: panel.cancel_(None)
            )
            NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSModalPanelRunLoopMode)
        try:
            result = panel.runModal()
            return (
                Path(str(panel.URL().path())) if result == NSModalResponseOK else None
            )
        finally:
            if timer:
                timer.invalidate()
    import tkinter as tk
    from tkinter.filedialog import asksaveasfilename

    root = tk.Tk()
    root.withdraw()
    try:
        value = asksaveasfilename(
            initialfile=filename + "." + format,
            defaultextension="." + format,
            filetypes=[(format.upper(), "*." + format)],
        )
        return Path(value) if value else None
    finally:
        root.destroy()
