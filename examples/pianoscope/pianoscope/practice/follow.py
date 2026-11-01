"""Deterministic key-gated score clock; pedals never participate in matching."""

from __future__ import annotations

from pianoscope.practice.midi import MidiEvent
from pianoscope.score.plan import PlaybackPlan
from pianoscope.types import Record


class FollowSession:
    """Advance only through held targets or real elapsed rest time."""

    def __init__(
        self, notes: list[Record], a: float, b: float, rate: float, loop: bool = False
    ) -> None:
        """Clip immutable targets and initialize an unstarted score clock."""
        self.notes = [
            dict(n, start=max(a, n["start"]), end=min(b, n["end"]))
            for n in notes
            if n["start"] < b and n["end"] > a
        ]
        if not self.notes:
            raise ValueError("跟弹片段内没有目标音符")
        self.a, self.b, self.rate, self.loop = a, b, rate, loop
        self.boundaries = sorted(
            {a, b, *(n[k] for n in self.notes for k in ("start", "end"))}
        )
        self.position = a
        self.state = "playing"
        self.last_ns: int | None = None
        self.keys: set[tuple[int, int]] = set()
        self.accepted: set[str] = set()
        self.completed: set[str] = set()
        self.round_index = 1
        self.completed_rounds = 0
        self.wrong_count = self.interruptions = 0
        self.waiting_s = 0.0

    def active(self) -> list[Record]:
        """Return targets requiring physical holds at this score position."""
        return [n for n in self.notes if n["start"] <= self.position < n["end"]]

    def moving(self) -> bool:
        """A rest runs freely; notes require both fresh attacks and held keys."""
        held = {pitch for _, pitch in self.keys}
        return self.state == "playing" and all(
            n["id"] in self.accepted and n["pitch"] in held for n in self.active()
        )

    def advance(self, now_ns: int) -> None:
        """Consume elapsed time without crossing any unmatched target boundary."""
        if self.last_ns is None:
            self.last_ns = now_ns
            return
        elapsed = max(0, now_ns - self.last_ns) / 1e9
        self.last_ns = max(now_ns, self.last_ns)
        if self.state != "playing":
            return
        remaining = elapsed * self.rate
        while remaining > 1e-10 and self.state == "playing":
            if not self.moving():
                self.waiting_s += remaining / self.rate
                break
            boundary = next(v for v in self.boundaries if v > self.position + 1e-10)
            step = min(remaining, boundary - self.position)
            self.position += step
            remaining -= step
            if abs(self.position - boundary) < 1e-9:
                self.position = boundary
                self.completed.update(
                    n["id"] for n in self.notes if n["end"] <= boundary
                )
                if boundary == self.b:
                    self.completed_rounds += 1
                    if self.loop:
                        self.round_index += 1
                        self.position = self.a
                        self.accepted.clear()
                        self.completed.clear()
                    else:
                        self.state = "finished"

    def event(self, event: MidiEvent) -> None:
        """Apply physical attacks/releases after advancing to their capture time."""
        self.advance(event.timestamp_ns)
        if self.state != "playing" or event.kind not in ("note_on", "note_off"):
            return
        key = (event.channel, event.pitch)
        if event.kind == "note_off":
            was_moving = self.moving()
            self.keys.discard(key)
            if was_moving and not self.moving():
                self.interruptions += 1
            return
        if key in self.keys:
            return
        self.keys.add(key)
        targets = [n for n in self.active() if n["pitch"] == event.pitch]
        if not targets:
            self.wrong_count += 1
        self.accepted.update(n["id"] for n in targets)

    def pause(self, now_ns: int) -> None:
        """Freeze both holds and rests; resuming requires fresh physical input."""
        self.advance(now_ns)
        if self.state == "playing":
            self.state = "paused"
        self.keys.clear()
        self.accepted.clear()

    def resume(self, now_ns: int) -> None:
        """Resume from the frozen score position without crediting paused time."""
        self.last_ns = now_ns
        self.state = "playing"

    def snapshot(self) -> Record:
        """Expose bounded targets, motion limit and non-rhythmic statistics."""
        active = self.active() if self.state != "finished" else []
        moving = self.moving()
        boundary = next(
            (v for v in self.boundaries if v > self.position + 1e-10), self.b
        )
        return dict(
            state=self.state,
            stage="rest" if not active else "holding" if moving else "waiting",
            position_s=self.position,
            moving=moving,
            boundary_s=boundary,
            target_pitches=sorted({n["pitch"] for n in active}),
            target_ids=[n["id"] for n in active],
            held_pitches=sorted({pitch for _, pitch in self.keys}),
            remaining_s=(boundary - self.position) / self.rate,
            round_index=self.round_index,
            completed_rounds=self.completed_rounds,
            completed_count=len(self.completed),
            expected_count=len(self.notes),
            wrong_count=self.wrong_count,
            interruptions=self.interruptions,
            waiting_s=self.waiting_s,
        )


def follow_notes(plan: PlaybackPlan, selected: list[str]) -> list[Record]:
    """Compile expanded ties and written holds, independent of pedal release tails."""
    elements = {e.id: e for e in plan.document.elements}
    result = []
    allowed = set(selected)
    for note in plan.instances:
        if note["id"] not in allowed:
            continue
        end = note["key_off_s"]
        first = elements[note["element_ids"][0]]
        if first.staccato and len(note["element_ids"]) == 1:
            end = float(plan.seconds(note["onset_qn"] + first.duration))
        result.append(
            dict(id=note["id"], pitch=note["pitch"], start=note["onset_s"], end=end)
        )
    return result
