from types import SimpleNamespace

import numpy as np

from pianoscope.audio import Audio


class Stream:
    def __init__(self):
        self.time = 0.0
        self.active = True

    def abort(self):
        self.active = False

    def close(self):
        pass


def test_dac_clock_not_submitted_cursor_and_post_gain():
    a = Audio()
    a.stream = Stream()
    a.ready = True
    a.pcm = np.ones((10000, 2), np.float32) * 0.25
    a.duration = 10000 / 48000
    a.playing = True
    out = np.empty((512, 2), np.float32)
    a._callback(
        out,
        512,
        SimpleNamespace(outputBufferDacTime=1.0),
        SimpleNamespace(output_underflow=False),
    )
    # The buffer is submitted, but still a second away from reaching the DAC.
    assert a.cursor == 512 and a.clock()[0] == 0
    a.stream.time = 1.0 + 128 / 48000
    assert abs(a.clock()[0] - 128 / 48000) < 1e-12
    window = a.heard_window()
    assert np.max(window) > 0.01 and np.count_nonzero(window) <= 128 * 2
    a.close()


def test_ten_loops_inside_single_stream_no_tail_leak():
    a = Audio()
    a.stream = Stream()
    a.ready = True
    a.pcm = np.ones((48000, 2), np.float32) * 0.25
    a.duration = 1
    a.loop = {"enabled": True, "a_s": 0.01, "b_s": 0.51}
    a.cursor = 480
    a.position = 0.01
    a.playing = True
    out = np.empty((512, 2), np.float32)
    wraps = 0
    last = 0.01
    for i in range(600):
        dac = i * 512 / 48000
        a._callback(
            out,
            512,
            SimpleNamespace(outputBufferDacTime=dac),
            SimpleNamespace(output_underflow=False),
        )
        a.stream.time = dac + 256 / 48000
        pos, tail, ended = a.clock()
        assert 0.01 <= pos < 0.51 and not tail and not ended
        wraps += pos < last
        last = pos
    assert wraps >= 10
    a.close()


def test_end_waits_until_last_frame_reaches_dac():
    a = Audio()
    a.stream = Stream()
    a.ready = True
    a.pcm = np.zeros((100, 2), np.float32)
    a.duration = 100 / 48000
    a.playing = True
    out = np.empty((512, 2), np.float32)
    a._callback(
        out,
        512,
        SimpleNamespace(outputBufferDacTime=2),
        SimpleNamespace(output_underflow=False),
    )
    a.stream.time = 1.9
    assert not a.clock()[2]
    a.stream.time = 2 + 101 / 48000
    assert a.clock()[2]
    a.close()


def test_loop_fades_are_continuous_across_callback_boundaries():
    a = Audio()
    a.stream = Stream()
    a.ready = True
    a.pcm = np.ones((48000, 2), np.float32) * 0.25
    a.duration = 1
    a.volume = 1
    a.loop = {"enabled": True, "a_s": 0.0, "b_s": 0.5}
    a.playing = True
    out = np.empty((512, 2), np.float32)
    blocks = []
    for i in range(120):
        a._callback(
            out,
            512,
            SimpleNamespace(outputBufferDacTime=i * 512 / 48000),
            SimpleNamespace(output_underflow=False),
        )
        blocks.append(out[:, 0].copy())
    signal = np.concatenate(blocks)
    # A clipped fade at the first tiny post-wrap fragment causes a >0.1 jump.
    # A continuous 5ms envelope changes a DC fixture by at most 1/240 per sample.
    assert np.max(np.abs(np.diff(signal[1024:]))) < 0.003
    a.close()
