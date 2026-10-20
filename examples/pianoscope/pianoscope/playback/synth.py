"""显式绑定 FluidSynth C ABI，仅生成样本，不打开 MIDI 或音频驱动。"""

from __future__ import annotations

import ctypes as C
import ctypes.util
import os
from typing import Any

import numpy as np

from pianoscope.paths import RESOURCES
from pianoscope.playback.types import PCM

SOUNDFONT = RESOURCES / "soundfonts/TimGM6mb.sf2"


class Synth:
    """独占 FluidSynth 实例与本地 SoundFont 的离线声音生成器。"""

    def __init__(self, sample_rate: int = 48000) -> None:
        """建立指定采样率的 FluidSynth 实例并加载随包 SoundFont，不开启设备驱动。

        本机库、合成器或音源不可用时抛出 RuntimeError；虚拟通道用于隔离同音重叠。
        """
        candidates = [
            os.environ.get("PIANOSCOPE_FLUIDSYNTH"),
            ctypes.util.find_library("fluidsynth"),
            "/opt/homebrew/lib/libfluidsynth.dylib",
            "/usr/local/lib/libfluidsynth.dylib",
        ]
        self.lib = None
        for name in filter(None, candidates):
            try:
                self.lib = C.CDLL(name)
                break
            except OSError:
                pass
        if self.lib is None:
            raise RuntimeError("未找到 FluidSynth，请安装系统音频库后重试。")

        def bind(name: str, result: Any, *args: Any) -> Any:
            """按明确的返回与参数 C ABI 类型绑定原生函数；类型对象由 ctypes 提供。"""
            f = getattr(self.lib, name)
            f.restype = result
            f.argtypes = args
            return f

        ptr, integer, string = C.c_void_p, C.c_int, C.c_char_p
        self.new_settings = bind("new_fluid_settings", ptr)
        self.delete_settings = bind("delete_fluid_settings", None, ptr)
        self.setnum = bind("fluid_settings_setnum", integer, ptr, string, C.c_double)
        self.setint = bind("fluid_settings_setint", integer, ptr, string, integer)
        self.new_synth = bind("new_fluid_synth", ptr, ptr)
        self.delete_synth = bind("delete_fluid_synth", None, ptr)
        self.sfload = bind("fluid_synth_sfload", integer, ptr, string, integer)
        self.program = bind(
            "fluid_synth_program_select",
            integer,
            ptr,
            integer,
            integer,
            integer,
            integer,
        )
        self.channel_type = bind(
            "fluid_synth_set_channel_type", integer, ptr, integer, integer
        )
        self.on = bind("fluid_synth_noteon", integer, ptr, integer, integer, integer)
        self.off = bind("fluid_synth_noteoff", integer, ptr, integer, integer)
        self.control = bind("fluid_synth_cc", integer, ptr, integer, integer, integer)
        self.write = bind(
            "fluid_synth_write_float",
            integer,
            ptr,
            integer,
            ptr,
            integer,
            integer,
            ptr,
            integer,
            integer,
        )
        self.version_fn = bind("fluid_version_str", string)
        self.settings = self.new_settings()
        self.synth = None
        self.setnum(self.settings, b"synth.sample-rate", float(sample_rate))
        self.setnum(self.settings, b"synth.gain", 0.5)
        self.setint(self.settings, b"synth.midi-channels", 256)
        self.setint(self.settings, b"synth.reverb.active", 0)
        self.setint(self.settings, b"synth.chorus.active", 0)
        self.setint(self.settings, b"synth.threadsafe-api", 0)
        self.synth = self.new_synth(self.settings)
        if not self.synth:
            self.close()
            raise RuntimeError("FluidSynth 初始化失败")
        sfid = self.sfload(self.synth, os.fsencode(SOUNDFONT), 0)
        if sfid < 0:
            self.close()
            raise RuntimeError("无法加载随包钢琴音源")
        # Each concurrent same-pitch voice has an independent virtual channel.
        for ch in range(256):
            self.channel_type(self.synth, ch, 0)
            self.program(self.synth, ch, sfid, 0, 0)

    @property
    def version(self) -> str:
        """返回当前加载的 FluidSynth 原生库版本字符串。"""
        return self.version_fn().decode()

    def note_on(self, ch: int, pitch: int, velocity: int) -> None:
        """向独立虚拟通道发送 MIDI 音高和力度，范围由编译及渲染层校验。"""
        self.on(self.synth, ch, pitch, velocity)

    def note_off(self, ch: int, pitch: int) -> None:
        """关闭指定虚拟通道上的按键，保留 SoundFont 自身的释放尾音。"""
        self.off(self.synth, ch, pitch)

    def cc(self, ch: int, control: int, value: int) -> None:
        """把已校验的 MIDI 控制器值发送到指定合成通道。"""
        self.control(self.synth, ch, control, value)

    def samples(self, frames: int) -> PCM:
        """生成指定帧数的双声道 float32 样本；原生生成失败时抛出 RuntimeError。"""
        pcm = np.empty((frames, 2), dtype=np.float32)
        if (
            frames
            and self.write(
                self.synth, frames, pcm.ctypes.data, 0, 2, pcm.ctypes.data, 1, 2
            )
            != 0
        ):
            raise RuntimeError("钢琴声音生成失败")
        return pcm

    def close(self) -> None:
        """幂等释放原生合成器和设置句柄，不访问音频设备。"""
        if self.synth:
            self.delete_synth(self.synth)
            self.synth = None
        if self.settings:
            self.delete_settings(self.settings)
            self.settings = None

    def __enter__(self) -> Synth:
        """返回当前合成器，供上下文管理器独占使用。"""
        return self

    def __exit__(self, *args: object) -> None:
        """退出上下文时释放原生句柄，不吞掉上下文中的异常。"""
        self.close()
