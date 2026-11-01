"""Live MIDI routing and real SoundFont rendering without physical devices."""

import threading
import time
from types import SimpleNamespace

import numpy as np

from pianoscope.playback.monitor import MidiMonitor
from pianoscope.practice.midi import MidiInput


def test_monitor_routing_preserves_scoring_and_pedal_channels():
    midi = MidiInput()
    received = []
    midi.listener = received.append
    midi._callback(SimpleNamespace(type="note_on", note=60, velocity=90, channel=2))
    midi._callback(
        SimpleNamespace(type="control_change", control=64, value=127, channel=2)
    )
    midi._callback(SimpleNamespace(type="note_on", note=60, velocity=0, channel=2))
    scored = midi.drain()
    assert [e.kind for e in scored] == ["note_on", "note_off"]
    assert received[0] is scored[0]
    assert received[1].control == 64
    assert received[1].value == 127
    assert all(e.channel == 2 for e in received)


def test_live_worker_renders_and_panics_without_consuming_practice(monkeypatch):
    monitor = MidiMonitor()
    sounded = threading.Event()
    silent = threading.Event()
    check_silence = threading.Event()

    class Output:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, pcm):
            if np.max(np.abs(pcm)) > 0.001:
                sounded.set()
            if check_silence.is_set() and np.max(np.abs(pcm)) < 0.00001:
                silent.set()
            time.sleep(len(pcm) / 48000)
            return False

    monkeypatch.setattr("pianoscope.playback.monitor.sd.OutputStream", Output)
    midi = MidiInput()
    midi.listener = monitor.submit
    midi.on_reset = monitor.silence
    try:
        assert monitor.start()["enabled"]
        midi._callback(
            SimpleNamespace(type="note_on", note=60, velocity=100, channel=0)
        )
        assert sounded.wait(3)
        assert midi.drain()[0].pitch == 60
        midi.close()
        check_silence.set()
        assert silent.wait(3)
    finally:
        monitor.close()
    assert not monitor.ready
    assert not monitor._thread


def test_monitor_initialization_failure_is_reported(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("no output")

    monkeypatch.setattr("pianoscope.playback.monitor.sd.OutputStream", fail)
    monitor = MidiMonitor()
    try:
        assert monitor.start()["error"] == "no output"
        assert not monitor.ready
    finally:
        monitor.close()
