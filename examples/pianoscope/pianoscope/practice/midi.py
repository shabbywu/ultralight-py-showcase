"""Threaded MIDI input with a safe, serializable application-facing state."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MidiEvent:
    """A normalized MIDI note event captured from a device thread."""

    kind: str
    pitch: int
    velocity: int
    channel: int
    timestamp_ns: int


class MidiInput:
    """Own one optional mido input port without touching the UI thread."""

    def __init__(self, max_events: int = 4096) -> None:
        """Create a bounded event queue for one optional input port."""
        self._events: queue.Queue[MidiEvent] = queue.Queue(maxsize=max_events)
        self._lock = threading.Lock()
        self._port: Any = None
        self._name: str | None = None
        self._error: str | None = None
        self.dropped = 0

    @staticmethod
    def _mido() -> Any:
        import mido

        return mido

    def list_inputs(self) -> dict[str, Any]:
        """Return input ports and a backend error without raising to the UI."""
        try:
            names = list(self._mido().get_input_names())
        except Exception as exc:
            return dict(available=False, backend="mido", inputs=[], error=str(exc))
        return dict(
            available=True,
            backend="mido",
            inputs=[dict(name=name) for name in names],
            selected=self._name,
            error=self._error,
        )

    def _callback(self, message: Any) -> None:
        kind = str(getattr(message, "type", ""))
        if kind not in ("note_on", "note_off"):
            return
        velocity = int(getattr(message, "velocity", 0))
        if kind == "note_on" and velocity == 0:
            kind = "note_off"
        event = MidiEvent(
            kind=kind,
            pitch=max(0, min(127, int(getattr(message, "note", 0)))),
            velocity=max(0, min(127, velocity)),
            channel=max(0, min(15, int(getattr(message, "channel", 0)))),
            timestamp_ns=time.monotonic_ns(),
        )
        try:
            self._events.put_nowait(event)
        except queue.Full:
            self.dropped += 1

    def select(self, name: str | None) -> dict[str, Any]:
        """Open a named input, or close the current input when name is None."""
        self.close()
        self._error = None
        if not name:
            return self.status()
        try:
            port = self._mido().open_input(name, callback=self._callback)
        except Exception as exc:
            self._error = str(exc)
            return self.status()
        with self._lock:
            self._port = port
            self._name = name
        return self.status()

    def drain(self, limit: int = 256) -> list[MidiEvent]:
        """Remove at most limit pending events in capture order."""
        events = []
        for _ in range(max(0, limit)):
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def status(self) -> dict[str, Any]:
        """Return current port state and backend diagnostics."""
        with self._lock:
            opened = self._port is not None
            name = self._name
        return dict(
            available=self.list_inputs().get("available", False),
            selected=name,
            opened=opened,
            error=self._error,
            dropped=self.dropped,
        )

    def close(self) -> None:
        """Close the port and release its backend callback."""
        with self._lock:
            port, self._port, self._name = self._port, None, None
        if port is not None:
            try:
                port.close()
            except Exception:
                pass
