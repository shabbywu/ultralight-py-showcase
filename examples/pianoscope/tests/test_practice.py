import time
from types import SimpleNamespace

from pianoscope.practice.midi import MidiEvent, MidiInput
from pianoscope.practice.session import PracticeManager


class FakeMidi:
    def __init__(self):
        self.events = []

    def drain(self):
        events, self.events = self.events, []
        return events

    def close(self):
        pass


def plan():
    source = SimpleNamespace(sha256="source")
    document = SimpleNamespace(source=source, revision="source-rev")
    return SimpleNamespace(
        revision="playback-rev",
        duration_s=4.0,
        document=document,
        instances=[
            dict(id="n1", pitch=60, onset_s=0.5, key_off_s=0.8, occurrence_ids=["o1"]),
            dict(id="n2", pitch=62, onset_s=1.0, key_off_s=1.3, occurrence_ids=["o1"]),
        ],
    )


def transport(position):
    return dict(
        phase="playing",
        position_s=position,
        rate=1.0,
        loop=dict(enabled=False, a_s=0.0, b_s=4.0),
    )


def test_midi_note_on_zero_velocity_is_note_off():
    midi = MidiInput()
    midi._callback(SimpleNamespace(type="note_on", note=60, velocity=0, channel=2))
    assert midi.drain()[0].kind == "note_off"


def test_practice_matches_hits_and_persists_misses(tmp_path):
    manager = PracticeManager(tmp_path / "practice.sqlite3")
    fake = FakeMidi()
    manager.midi = fake
    manager.start(
        plan(),
        dict(rate=1.0, hand_mode="both", tracks=[], allowed_note_ids=None),
        transport(0.0),
    )
    fake.events.append(MidiEvent("note_on", 60, 100, 0, time.monotonic_ns()))
    live = manager.update(transport(0.5))
    assert live["matched_count"] == 1
    assert live["latest_event"]["result"] == "hit"

    fake.events.append(MidiEvent("note_on", 70, 90, 0, time.monotonic_ns()))
    manager.update(transport(1.3))
    summary = manager.finish(transport(2.0))
    assert summary["summary"]["hit_count"] == 1
    assert summary["summary"]["miss_count"] == 1
    assert summary["summary"]["extra_count"] == 1
    page = manager.results_page(summary["session_id"], 0, 10)
    assert page["total"] == 3
    manager.close()
