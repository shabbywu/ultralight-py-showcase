"""Native file selection. Paths stay in Python behind opaque tokens."""

import sys
from pathlib import Path


def choose_path(auto_cancel=False, folder=False, extensions=None, label="MIDI"):
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


def before_window_close(title, callback):
    """macOS notification runs before AppCore releases its window/view."""
    if sys.platform != "darwin":
        return lambda: None
    from Foundation import NSNotificationCenter

    center = NSNotificationCenter.defaultCenter()

    def closing(notification):
        window = notification.object()
        if str(window.title()) == title:
            callback()

    token = center.addObserverForName_object_queue_usingBlock_(
        "NSWindowWillCloseNotification", None, None, closing
    )
    return lambda: center.removeObserver_(token)


def choose_score_path(title, format, auto_cancel=False):
    """Native save/overwrite confirmation; no paths cross the JS binding."""
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
