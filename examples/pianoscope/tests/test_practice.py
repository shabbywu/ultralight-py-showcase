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


def test_early_stop_does_not_penalize_future_targets(tmp_path):
    manager = PracticeManager(tmp_path / "early.sqlite3")
    manager.midi = FakeMidi()
    manager.start(plan(), dict(rate=1, hand_mode="both"), transport(0))
    result = manager.finish(transport(0.1))
    assert result["summary"]["miss_count"] == 0
    assert result["summary"]["evaluated_count"] == 0
    assert result["summary"]["status"] == "stopped"
    assert manager.results_page(result["session_id"], 0, 20)["total"] == 0


def test_loop_rounds_persist_under_one_session_and_filter(tmp_path):
    manager = PracticeManager(tmp_path / "loop.sqlite3")
    manager.midi = FakeMidi()

    def loop(position, index):
        value = transport(position)
        value.update(loop_round=index, loop=dict(enabled=True, a_s=0, b_s=4))
        return value

    manager.start(plan(), dict(rate=1, hand_mode="both"), loop(0, 0))
    session = manager.session_id
    manager.update(loop(0.2, 2))  # UI may miss multiple boundaries.
    result = manager.finish(loop(0.2, 2))
    assert manager.session_id == session
    assert result["summary"]["completed_rounds"] == 2
    assert result["summary"]["miss_count"] == 4
    page = manager.store.results(session, 0, 20, {"round_index": 2, "result": "miss"})
    assert page["total"] == 2
    assert {r["round_index"] for r in page["items"]} == {2}
    assert manager.store.history()["total"] == 1


def test_slow_rate_uses_real_milliseconds(tmp_path):
    manager = PracticeManager(tmp_path / "slow.sqlite3")
    manager.midi = FakeMidi()
    manager.start(plan(), dict(rate=0.5, hand_mode="both"), transport(0))
    manager.midi.events.append(MidiEvent("note_on", 60, 100, 0, time.monotonic_ns()))
    value = transport(0.54)
    value["rate"] = 0.5
    result = manager.update(value)
    assert result["latest_event"]["result"] == "late"
    assert 75 < result["latest_event"]["delta_ms"] < 85


def test_event_is_matched_before_delayed_poll_marks_miss(tmp_path, monkeypatch):
    manager = PracticeManager(tmp_path / "delayed.sqlite3")
    manager.midi = FakeMidi()
    manager.start(plan(), dict(rate=1, hand_mode="both"), transport(0))
    now = time.monotonic_ns()
    monkeypatch.setattr("pianoscope.practice.session.time.monotonic_ns", lambda: now)
    manager.midi.events.append(MidiEvent("note_on", 60, 100, 0, now - 300_000_000))
    result = manager.update(transport(0.8))
    assert result["hit_count"] == 1
    assert result["miss_count"] == 0


def test_explicit_empty_target_is_rejected(tmp_path):
    import pytest

    manager = PracticeManager(tmp_path / "empty.sqlite3")
    with pytest.raises(ValueError, match="没有目标"):
        manager.start(
            plan(), dict(rate=1, hand_mode="both", allowed_note_ids=[]), transport(0)
        )
    assert manager.store.history()["total"] == 0


def test_finished_session_is_idempotent_and_survives_restart(tmp_path):
    database = tmp_path / "history.sqlite3"
    manager = PracticeManager(database)
    manager.midi = FakeMidi()
    manager.start(
        plan(),
        dict(rate=1, hand_mode="both", title="测试曲目", device="MIDI"),
        transport(0),
    )
    value = transport(4)
    value["phase"] = "ended"
    manager.update(value)
    manager.finish(value)
    restored = PracticeManager(database)
    history = restored.store.history()["items"]
    assert len(history) == 1
    assert history[0]["title"] == "测试曲目"
    assert history[0]["device"] == "MIDI"
    assert history[0]["completed_rounds"] == 1
    assert history[0]["miss_count"] == 2
    assert restored.store.results(history[0]["id"])["total"] == 2


def test_late_note_across_loop_boundary_belongs_to_previous_round(tmp_path):
    manager = PracticeManager(tmp_path / "boundary.sqlite3")
    manager.midi = FakeMidi()
    score = plan()
    score.instances[0]["onset_s"] = 3.95
    score.instances = score.instances[:1]
    start = transport(0)
    start.update(loop_round=0, loop=dict(enabled=True, a_s=0, b_s=4))
    manager.start(score, dict(rate=1, hand_mode="both"), start)
    current = transport(0.02)
    current.update(loop_round=1, loop=start["loop"])
    manager.update(current)
    assert manager.completed_rounds == 0
    manager.midi.events.append(MidiEvent("note_on", 60, 100, 0, time.monotonic_ns()))
    current["position_s"] = 0.04
    result = manager.update(current)
    assert result["latest_event"]["result"] == "late"
    assert result["latest_event"]["round_index"] == 1
    current["position_s"] = 0.2
    manager.update(current)
    assert manager.completed_rounds == 1
    assert manager.store.results(manager.session_id)["items"][0]["result"] == "late"


def test_nonloop_practice_range_excludes_outside_notes(tmp_path):
    manager = PracticeManager(tmp_path / "range.sqlite3")
    manager.midi = FakeMidi()
    manager.start(
        plan(),
        dict(
            rate=1,
            hand_mode="both",
            practice_options=dict(range_enabled=True, range_a_s=0.75, range_b_s=1.5),
        ),
        transport(0.75),
    )
    assert [n["instance_id"] for n in manager.expected] == ["n2"]
    end = transport(1.5)
    end["phase"] = "ended"
    result = manager.finish(end)
    assert result["summary"]["miss_count"] == 1
