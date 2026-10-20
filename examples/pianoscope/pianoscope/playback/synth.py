"""Small explicit FluidSynth C ABI adapter. Never opens a MIDI/audio driver."""

import ctypes as C
import ctypes.util
import os

import numpy as np

from pianoscope.paths import RESOURCES

SOUNDFONT = RESOURCES / "soundfonts/TimGM6mb.sf2"


class Synth:
    def __init__(self, sample_rate=48000):
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

        def bind(name, result, *args):
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
    def version(self):
        return self.version_fn().decode()

    def note_on(self, ch, pitch, velocity):
        self.on(self.synth, ch, pitch, velocity)

    def note_off(self, ch, pitch):
        self.off(self.synth, ch, pitch)

    def cc(self, ch, control, value):
        self.control(self.synth, ch, control, value)

    def samples(self, frames):
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

    def close(self):
        if self.synth:
            self.delete_synth(self.synth)
            self.synth = None
        if self.settings:
            self.delete_settings(self.settings)
            self.settings = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
