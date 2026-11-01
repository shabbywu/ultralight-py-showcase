"""Deterministic physical-key and real-time-rest follow rules."""

import pytest

from pianoscope.practice.follow import FollowSession
from pianoscope.practice.midi import MidiEvent


def event(session, seconds, pitch=60, kind="note_on", channel=0):
    session.event(MidiEvent(kind, pitch, 90, channel, round(seconds * 1e9)))


def test_holds_rests_and_repeated_attacks():
    session = FollowSession(
        [
            dict(id="a", pitch=60, start=0, end=1),
            dict(id="b", pitch=60, start=2, end=3),
        ],
        0,
        4,
        1,
    )
    session.advance(0)
    session.advance(2_000_000_000)
    assert session.position == 0
    event(session, 2, 61)
    assert session.wrong_count == 1
    event(session, 2, 60)
    event(session, 2.4, kind="note_off")
    assert session.position == pytest.approx(0.4)
    session.advance(3_000_000_000)
    assert session.position == pytest.approx(0.4)
    event(session, 3)
    session.advance(3_600_000_000)
    assert session.position == 1
    assert session.snapshot()["stage"] == "rest"
    session.advance(4_100_000_000)
    assert session.position == pytest.approx(1.5)
    session.advance(5_000_000_000)
    assert session.position == 2  # still-held previous key cannot unlock repeated note
    event(session, 5, kind="note_off")
    event(session, 5)
    session.advance(6_000_000_000)
    assert session.position == 3
    session.advance(6_500_000_000)
    assert session.position == pytest.approx(3.5)
    session.advance(7_000_000_000)
    assert session.state == "finished"


def test_chords_unequal_lengths_channels_and_pedal_not_required():
    session = FollowSession(
        [
            dict(id="a", pitch=60, start=0, end=1),
            dict(id="b", pitch=64, start=0, end=2),
        ],
        0,
        2,
        1,
    )
    session.advance(0)
    event(session, 0)
    session.advance(1_000_000_000)
    assert session.position == 0
    event(session, 1, 64, channel=2)
    session.advance(2_000_000_000)
    assert session.position == 1
    event(session, 2, kind="note_off")
    session.advance(3_000_000_000)
    assert session.state == "finished"


def test_slow_rest_pause_and_loop_require_fresh_attack():
    session = FollowSession([dict(id="a", pitch=60, start=1, end=2)], 0, 2, 0.5, True)
    session.advance(0)
    session.advance(1_000_000_000)
    assert session.position == 0.5
    session.pause(1_000_000_000)
    session.advance(9_000_000_000)
    assert session.position == 0.5
    session.resume(9_000_000_000)
    session.advance(10_000_000_000)
    assert session.position == 1
    event(session, 10)
    session.advance(12_000_000_000)
    assert session.position == 0
    assert session.completed_rounds == 1
    session.advance(15_000_000_000)
    assert session.position == 1


def test_pedal_does_not_replace_physical_hold():
    session = FollowSession([dict(id="a", pitch=60, start=0, end=1)], 0, 1, 1)
    session.advance(0)
    event(session, 0)
    session.event(MidiEvent("control_change", 0, 0, 0, 100_000_000, 64, 127))
    event(session, 0.2, kind="note_off")
    session.advance(2_000_000_000)
    assert session.position == pytest.approx(0.2)
    assert session.interruptions == 1


def test_long_tick_stops_at_unmatched_overlapping_voice():
    session = FollowSession(
        [
            dict(id="long", pitch=60, start=0, end=3),
            dict(id="short", pitch=64, start=1, end=2),
        ],
        0,
        4,
        1,
    )
    session.advance(0)
    event(session, 0)
    session.advance(10_000_000_000)
    assert session.position == 1
    event(session, 10, 64)
    event(session, 11, 64, "note_off")
    assert session.position == 2
    session.advance(12_000_000_000)
    assert session.position == 3
    session.advance(13_000_000_000)
    assert session.state == "finished"


def test_fragment_clips_tied_hold_and_waits_trailing_rest():
    session = FollowSession([dict(id="tie", pitch=60, start=0, end=3)], 1, 4, 1)
    session.advance(0)
    event(session, 0)
    session.advance(2_000_000_000)
    assert session.position == 3
    assert session.snapshot()["stage"] == "rest"
    session.advance(2_500_000_000)
    assert session.state == "playing"
    session.advance(3_000_000_000)
    assert session.state == "finished"
