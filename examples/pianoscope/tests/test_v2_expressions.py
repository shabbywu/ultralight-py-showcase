"""Hand-derived ornament events checked with an independent SMF reader."""

from fractions import Fraction as Q
from io import BytesIO
from pathlib import Path

import mido
import pytest
from test_v2_profile import note, xml

from pianoscope.midi_compile import compile_midi
from pianoscope.playback_plan import compile_plan
from pianoscope.score_model import parse_score
from pianoscope.score_source import ScoreInputError, source_from_bytes

FIXTURE = Path(__file__).parent / "fixtures/v2/expressions.musicxml"


def plan(raw):
    return compile_plan(parse_score(source_from_bytes(raw)))


def test_cross_staff_arpeggio_and_alternating_chord_tremolo():
    raw = FIXTURE.read_bytes()
    p = plan(raw)
    assert p.document.source.original_bytes == raw
    assert p.duration_qn == 8
    assert sorted(
        (n["pitch"], n["onset_qn"], n["key_off_qn"]) for n in p.instances[:3]
    ) == [(48, 0, 4), (60, Q(1, 16), 4), (64, Q(1, 8), 4)]
    strokes = [(n["pitch"], n["onset_qn"], n["key_off_qn"]) for n in p.instances[3:]]
    expected = [
        (pitch, 4 + Q(j, 4), 4 + Q(j + 1, 4))
        for j in range(16)
        for pitch in ([60, 64] if j % 2 == 0 else [67])
    ]
    assert strokes == expected
    midi = mido.MidiFile(file=BytesIO(compile_midi(p)))
    tick = 0
    actual = []
    for event in midi.tracks[1]:
        tick += event.time
        if event.type == "note_on" and event.velocity:
            actual.append((event.note, Q(tick, midi.ticks_per_beat)))
    assert actual == [(48, Q(0)), (60, Q(1, 16)), (64, Q(1, 8))] + [
        (a, b) for a, b, c in expected
    ]
    assert all(s["end_qn"] > s["start_qn"] for s in p.display_spans)
    assert all(
        any(
            s["instance_id"] == n["id"] and s["element_id"] == n["element_ids"][0]
            for s in p.display_spans
        )
        for n in p.instances
    )
    assert any(
        d["code"] == "DISPLAY_ONLY" and "breath-mark" in d["message"]
        for d in p.diagnostics
    )


def test_downward_separate_groups_and_short_arpeggio_cap():
    raw = FIXTURE.read_bytes().replace(
        b'<arpeggiate number="1"/>', b'<arpeggiate number="1" direction="down"/>'
    )
    p = plan(raw)
    assert sorted((n["onset_qn"], n["pitch"]) for n in p.instances[:3]) == [
        (0, 64),
        (Q(1, 16), 60),
        (Q(1, 8), 48),
    ]
    raw = raw.replace(
        b'<arpeggiate number="1" direction="down"/>', b'<arpeggiate number="2"/>', 1
    )
    p = plan(raw)
    assert (
        next(n for n in p.instances if n["element_ids"] == ["arp-c"])["onset_qn"] == 0
    )
    raw = (
        FIXTURE.read_bytes()
        .replace(b"<duration>48</duration>", b"<duration>1</duration>")
        .replace(b"<type>whole</type>", b"<type>64th</type>")
    )
    # Short source notes remain positive; no arpeggio extends their releases.
    p = plan(raw[: raw.index(b'<measure id="trem"')] + b"</part></score-partwise>")
    assert all(0 <= n["onset_qn"] < n["key_off_qn"] == Q(1, 12) for n in p.instances)


def test_single_tremolo_repeats_and_integrates_mid_measure_tempo():
    trem = "<notations><ornaments><tremolo>2</tremolo></ornaments></notations>"
    text = xml(
        note("single", duration=48, type="whole", extra=trem)
        + '<sound tempo="60"><offset>-24</offset></sound><barline><repeat direction="backward"/></barline>'
    )
    p = plan(text.encode())
    assert len(p.instances) == 32 and p.duration_qn == 8
    assert [n["onset_qn"] for n in p.instances] == [Q(i, 4) for i in range(32)]
    assert p.instances[7]["key_off_s"] - p.instances[7]["onset_s"] == 0.125
    assert p.instances[8]["key_off_s"] - p.instances[8]["onset_s"] == 0.25
    assert p.instances[16]["onset_s"] == 3


@pytest.mark.parametrize(
    "before,after",
    [
        (b'type="stop"', b'type="start"'),
        (b'type="start">2', b'type="unmeasured">0'),
        (b'type="stop">2', b'type="stop">3'),
    ],
)
def test_ambiguous_or_free_tremolo_stays_located_rejection(before, after):
    with pytest.raises(ScoreInputError) as exc:
        plan(FIXTURE.read_bytes().replace(before, after))
    assert exc.value.issues[0]["source_locator"].startswith("/score-partwise")


def test_explicit_sound_values_and_sequential_tempo_have_diagnostics():
    text = xml(note("n", duration=48, type="whole")).replace(
        '<sound tempo="120"/>',
        '<direction><direction-type><metronome><beat-unit>quarter</beat-unit></metronome></direction-type><direction-type><dynamics><other-dynamics>x</other-dynamics><ff/></dynamics></direction-type><sound tempo="70" dynamics="90"/></direction><sound tempo="94"/>',
    )
    p = plan(text.encode())
    assert p.tempos[0]["bpm"] == 94 and p.instances[0]["velocity"] == 81
    assert {"METRONOME_SOUND_TEMPO", "DYNAMICS_SOUND_VALUE", "TEMPO_SOURCE_ORDER"} <= {
        d["code"] for d in p.diagnostics
    }
    with pytest.raises(ScoreInputError, match="metronome"):
        plan(text.replace(' tempo="70"', "").encode())
