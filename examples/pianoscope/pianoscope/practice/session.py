"""MIDI-to-score matching and practice-session lifecycle."""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

from pianoscope.practice.midi import MidiEvent, MidiInput
from pianoscope.practice.storage import PracticeStore
from pianoscope.types import Record


class PracticeManager:
    """Match a bounded MIDI session against one immutable playback snapshot."""

    MATCH_WINDOW_S = 0.150
    HIT_WINDOW_S = 0.050

    def __init__(self, database: Path) -> None:
        """Create a session manager backed by the given SQLite database."""
        self.midi = MidiInput()
        self.store = PracticeStore(database)
        self.session_id: str | None = None
        self.state = "idle"
        self.expected: list[dict[str, Any]] = []
        self.matched: set[str] = set()
        self.results: list[dict[str, Any]] = []
        self.last_position = 0.0
        self.last_update_ns = time.monotonic_ns()
        self.metadata: dict[str, Any] = {}
        self.active_inputs: dict[int, tuple[int, int]] = {}

    def midi_inputs(self) -> Record:
        """Return available MIDI devices and the selected device."""
        result = self.midi.list_inputs()
        result.update(self.midi.status())
        return result

    def select_midi_input(self, name: str | None) -> Record:
        """Open a device by name or close the current device."""
        return self.midi.select(name)

    def start(self, plan: Any, config: Record, transport: Record) -> Record:
        """Start matching input against the current playback snapshot."""
        if self.state in ("armed", "playing"):
            raise ValueError("已有练习会话正在进行")
        loop = transport["loop"]
        a_s = loop["a_s"] if loop["enabled"] else 0.0
        b_s = loop["b_s"] if loop["enabled"] else plan.duration_s
        allowed = set(config.get("allowed_note_ids") or [])
        self.expected = [
            dict(
                instance_id=n["id"],
                pitch=n["pitch"],
                onset_s=n["onset_s"],
                key_off_s=n["key_off_s"],
                occurrence_id=(n.get("occurrence_ids") or [None])[0],
            )
            for n in plan.instances
            if a_s <= n["onset_s"] < b_s and (not allowed or n["id"] in allowed)
        ]
        self.expected.sort(
            key=lambda item: (item["onset_s"], item["pitch"], item["instance_id"])
        )
        source = plan.document.source
        self.metadata = dict(
            source_fingerprint=source.sha256,
            source_revision=plan.document.revision,
            playback_revision=plan.revision,
            rate=config["rate"],
            hand_mode=config["hand_mode"],
            staff_ids=config.get("staff_ids") or [],
            voice_ids=config.get("voice_ids") or [],
            loop_a_s=a_s,
            loop_b_s=b_s,
            expected_count=len(self.expected),
        )
        self.session_id = self.store.create(self.metadata)
        self.matched.clear()
        self.results.clear()
        self.active_inputs.clear()
        self.last_position = transport["position_s"]
        self.last_update_ns = time.monotonic_ns()
        self.state = "playing"
        return self.snapshot(transport)

    def _event_position(
        self, event: MidiEvent, transport: Record, now_ns: int
    ) -> float:
        if transport["phase"] != "playing":
            return transport["position_s"]
        elapsed = max(0.0, (now_ns - event.timestamp_ns) / 1_000_000_000)
        return max(0.0, transport["position_s"] - elapsed * transport["rate"])

    def _result_for_event(self, event: MidiEvent, position: float) -> dict[str, Any]:
        candidates = [
            item
            for item in self.expected
            if item["instance_id"] not in self.matched
            and item["pitch"] == event.pitch
            and abs(item["onset_s"] - position) <= self.MATCH_WINDOW_S
        ]
        if not candidates:
            return dict(
                result="extra",
                actual_pitch=event.pitch,
                actual_s=position,
                velocity=event.velocity,
            )
        target = min(candidates, key=lambda item: abs(item["onset_s"] - position))
        delta = position - target["onset_s"]
        self.matched.add(target["instance_id"])
        if abs(delta) <= self.HIT_WINDOW_S:
            result = "hit"
        elif delta < 0:
            result = "early"
        else:
            result = "late"
        return dict(
            result=result,
            expected_instance_id=target["instance_id"],
            occurrence_id=target["occurrence_id"],
            expected_pitch=target["pitch"],
            actual_pitch=event.pitch,
            expected_s=target["onset_s"],
            actual_s=position,
            delta_ms=delta * 1000,
            velocity=event.velocity,
        )

    def _mark_misses(self, position: float) -> None:
        for target in self.expected:
            if target["instance_id"] in self.matched:
                continue
            if target["onset_s"] + self.MATCH_WINDOW_S < position:
                self.matched.add(target["instance_id"])
                self.results.append(
                    dict(
                        result="miss",
                        expected_instance_id=target["instance_id"],
                        occurrence_id=target["occurrence_id"],
                        expected_pitch=target["pitch"],
                        expected_s=target["onset_s"],
                    )
                )

    def update(self, transport: Record) -> Record:
        """Consume input events and advance misses for the current position."""
        if self.state != "playing":
            return self.snapshot(transport)
        position = transport["position_s"]
        if position + 0.01 < self.last_position:
            self.matched.clear()
        now_ns = time.monotonic_ns()
        self._mark_misses(position)
        for event in self.midi.drain():
            event_position = self._event_position(event, transport, now_ns)
            if event.kind == "note_on":
                result = self._result_for_event(event, event_position)
                self.results.append(result)
                self.active_inputs[event.pitch] = (event.timestamp_ns, event.velocity)
            else:
                started = self.active_inputs.pop(event.pitch, None)
                if started and self.results:
                    duration_ms = (event.timestamp_ns - started[0]) / 1_000_000
                    for item in reversed(self.results):
                        if (
                            item.get("actual_pitch") == event.pitch
                            and "actual_duration_ms" not in item
                        ):
                            item["actual_duration_ms"] = duration_ms
                            break
        self.last_position = position
        self.last_update_ns = now_ns
        return self.snapshot(transport)

    def finish(self, transport: Record) -> Record:
        """Finalize, persist, and summarize the current session."""
        if self.state == "idle":
            return self.snapshot(transport)
        self.update(transport)
        self._mark_misses(
            self.metadata.get("loop_b_s", transport["position_s"]) + self.MATCH_WINDOW_S
        )
        deltas = [
            abs(item["delta_ms"])
            for item in self.results
            if item.get("delta_ms") is not None
        ]
        summary = dict(
            hit_count=sum(item["result"] == "hit" for item in self.results),
            miss_count=sum(item["result"] == "miss" for item in self.results),
            extra_count=sum(item["result"] == "extra" for item in self.results),
            mean_abs_delta_ms=statistics.fmean(deltas) if deltas else None,
            status="finished",
        )
        if self.session_id:
            self.store.finish(self.session_id, summary, self.results)
        self.state = "finished"
        return dict(self.snapshot(transport), summary=summary)

    def snapshot(self, transport: Record) -> Record:
        """Return the live practice counters for the UI."""
        return dict(
            state=self.state,
            session_id=self.session_id,
            expected_count=len(self.expected),
            matched_count=sum(
                item in self.matched
                for item in (n["instance_id"] for n in self.expected)
            ),
            miss_count=sum(item["result"] == "miss" for item in self.results),
            extra_count=sum(item["result"] == "extra" for item in self.results),
            latest_event=self.results[-1] if self.results else None,
            elapsed_s=max(
                0.0, transport["position_s"] - self.metadata.get("loop_a_s", 0.0)
            ),
        )

    def results_page(self, session_id: str, offset: int, limit: int) -> Record:
        """Read one page of persisted per-note results."""
        return self.store.results(session_id, offset, limit)

    def close(self) -> None:
        """Close the MIDI input service."""
        self.midi.close()
