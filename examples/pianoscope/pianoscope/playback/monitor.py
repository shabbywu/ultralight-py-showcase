"""Independent live piano output, owned entirely by one worker thread."""

from __future__ import annotations

import queue
import threading

import numpy as np
import sounddevice as sd

from pianoscope.playback.synth import Synth
from pianoscope.practice.midi import MidiEvent
from pianoscope.types import Record


class MidiMonitor:
    """Render live input without consuming practice events or advancing its clock."""

    block = 256

    def __init__(self) -> None:
        """Create a dormant monitor; opening audio is explicit."""
        self.volume = 0.65
        self.error: str | None = None
        self.ready = False
        self.underruns = 0
        self._events: queue.Queue[MidiEvent] = queue.Queue(maxsize=4096)
        self._stop = threading.Event()
        self._reset = threading.Event()
        self._thread: threading.Thread | None = None

    def submit(self, event: MidiEvent) -> None:
        """Fan out captured input without blocking the MIDI callback."""
        if not self.ready:
            return
        try:
            self._events.put_nowait(event)
        except queue.Full:
            self.silence()

    def silence(self) -> None:
        """Request all-sound-off and discard pending input on the worker."""
        self._reset.set()

    def status(self) -> Record:
        """Return serializable output diagnostics."""
        return dict(
            enabled=self.ready,
            volume=self.volume,
            error=self.error,
            underruns=self.underruns,
        )

    def start(self) -> Record:
        """Open a low-latency output and SoundFont off the application thread."""
        self.close()
        self.error = None
        self._reset.clear()
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                break
        self._stop.clear()
        started = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(started,), name="pianoscope-live-piano", daemon=True
        )
        self._thread.start()
        if not started.wait(10):
            self._stop.set()
            self.error = "实时钢琴初始化超时"
        return self.status()

    def _run(self, started: threading.Event) -> None:
        """Own both native synthesis and paced blocking PortAudio writes."""
        try:
            with (
                Synth(48000) as synth,
                sd.OutputStream(
                    samplerate=48000,
                    channels=2,
                    dtype="float32",
                    blocksize=self.block,
                    latency="low",
                ) as stream,
            ):
                self.ready = not self._stop.is_set()
                started.set()
                while not self._stop.is_set():
                    if self._reset.is_set():
                        self._reset.clear()
                        while True:
                            try:
                                self._events.get_nowait()
                            except queue.Empty:
                                break
                        for channel in range(16):
                            synth.cc(channel, 64, 0)
                            synth.cc(channel, 120, 0)
                            synth.cc(channel, 123, 0)
                    for _ in range(4096):
                        try:
                            event = self._events.get_nowait()
                        except queue.Empty:
                            break
                        if event.kind == "note_on":
                            synth.note_on(event.channel, event.pitch, event.velocity)
                        elif event.kind == "note_off":
                            synth.note_off(event.channel, event.pitch)
                        elif event.kind == "control_change":
                            synth.cc(event.channel, event.control, event.value)
                    pcm = synth.samples(self.block)
                    pcm *= self.volume
                    np.clip(pcm, -1, 1, out=pcm)
                    if stream.write(pcm):
                        self.underruns += 1
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.ready = False
            started.set()

    def close(self) -> None:
        """Stop and join the output worker before releasing application state."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self.ready = False
        self.silence()
