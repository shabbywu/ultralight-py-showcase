"""Additional hand-authored profile cases, not MIDI-derived notation."""

from fractions import Fraction as Q
from io import BytesIO

import mido
import pytest

from pianoscope.score.midi import compile_midi
from pianoscope.score.model import parse_score
from pianoscope.score.plan import compile_plan
from pianoscope.score.source import ScoreInputError, source_from_bytes


def note(
    ident,
    step="C",
    octave=4,
    duration=12,
    voice="1",
    staff=1,
    extra="",
    alter=0,
    type="quarter",
):
    return f'<note id="{ident}"><pitch><step>{step}</step><alter>{alter}</alter><octave>{octave}</octave></pitch><duration>{duration}</duration><voice>{voice}</voice><type>{type}</type>{extra}<staff>{staff}</staff></note>'


def xml(content, divisions=12, clef="G", time=(4, 4)):
    return f"""<score-partwise version="4.0"><part-list><score-part id="P"><part-name>Piano</part-name></score-part></part-list><part id="P"><measure id="M" number="one"><attributes><divisions>{divisions}</divisions><key><fifths>0</fifths></key><time><beats>{time[0]}</beats><beat-type>{time[1]}</beat-type></time><staves>2</staves><clef number="1"><sign>{clef}</sign><line>3</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes><sound tempo="120"/>{content}</measure></part></score-partwise>"""


def plan(text, settings=None):
    source = source_from_bytes(text.encode())
    return compile_plan(parse_score(source, settings), settings)


def test_divisions_change_and_non_numeric_voice_identifiers():
    text = xml(
        note("a", voice="melody")
        + "<attributes><divisions>24</divisions></attributes>"
        + note("b", "E", duration=24, voice="melody")
        + note("c", "G", duration=48, voice="melody", type="half")
        + "<backup><duration>96</duration></backup>"
        + note("bass", octave=3, duration=96, staff=2, voice="bass", type="whole")
    )
    p = plan(text)
    assert [
        (n["onset_qn"], n["key_off_qn"])
        for n in p.instances
        if n["voice_id"] == "melody"
    ] == [(0, 1), (1, 2), (2, 4)]
    assert {e.voice_id for e in p.document.elements} == {"melody", "bass"}
    assert len(mido.MidiFile(file=BytesIO(compile_midi(p))).tracks) == 2


def test_forward_sparse_voices_and_slur_rearticulation():
    text = xml(
        note("a")
        + "<forward><duration>24</duration></forward>"
        + note("b")
        + "<backup><duration>48</duration></backup><forward><duration>12</duration></forward>"
        + note("other", "E", duration=24, voice="3", type="half")
        + "<forward><duration>12</duration></forward><backup><duration>48</duration></backup>"
        + note("bass", octave=3, duration=48, staff=2, voice="2", type="whole")
    )
    p = plan(text)
    assert next(e for e in p.document.elements if e.id == "other").onset == 1
    assert next(e for e in p.document.elements if e.id == "b").onset == 3
    slur = xml("".join(note("s" + str(i)) for i in range(4)))
    slur = slur.replace('<note id="s0">', '<note id="s0">').replace(
        "</staff></note>",
        '</staff><notations><slur type="start" number="1"/></notations></note>',
        1,
    )
    import xml.etree.ElementTree as E

    tree = E.fromstring(slur)
    E.SubElement(
        E.SubElement(tree.find("part/measure/note[@id='s3']"), "notations"),
        "slur",
        type="stop",
        number="1",
    )
    slur = E.tostring(tree, encoding="unicode")
    p = plan(slur)
    assert len(p.instances) == 4 and len({n["id"] for n in p.instances}) == 4


@pytest.mark.parametrize(
    "actual,normal,kind,divisions",
    [
        (3, 2, "half", 3),
        (5, 4, "quarter", 5),
        (6, 4, "quarter", 6),
        (7, 4, "quarter", 7),
    ],
)
def test_exact_supported_tuplet_durations(actual, normal, kind, divisions):
    duration = 4
    tm = f"<time-modification><actual-notes>{actual}</actual-notes><normal-notes>{normal}</normal-notes></time-modification>"
    text = xml(
        "".join(
            note("n" + str(i), duration=duration, type=kind, extra=tm)
            for i in range(actual)
        ),
        divisions=divisions,
    )
    p = plan(text)
    assert p.duration_qn == 4
    assert [n["onset_qn"] for n in p.instances] == [
        Q(i * 4, actual) for i in range(actual)
    ]
    assert p.duration_s == 2
    compile_midi(p)


def test_c_clef_key_spelling_and_octave_display_do_not_shift_pitch_twice():
    text = xml(
        note("bsharp", "B", 3, alter=1)
        + note("fdoubleflat", "F", 5, alter=-2)
        + note("gdouble", "G", 4, alter=2)
        + note("c", "C", 4),
        clef="C",
    )
    text = text.replace(
        "<key><fifths>0</fifths></key>",
        "<key><fifths>7</fifths><mode>major</mode></key>",
    )
    text = text.replace(
        '<note id="bsharp">',
        '<direction><direction-type><octave-shift type="up" size="8"/></direction-type><staff>1</staff></direction><note id="bsharp">',
    )
    p = plan(text)
    assert [n["pitch"] for n in p.instances] == [60, 75, 69, 60]
    assert p.document.elements[0].written_pitch == ("B", 1, 3)


def test_implicit_forward_repeat_and_explicit_counts():
    source = xml(
        note("a", duration=48, type="whole")
        + '<barline location="right"><repeat direction="backward" times="3"/></barline>'
    )
    p = plan(source)
    assert [o["measure_uid"] for o in p.occurrences] == ["M", "M", "M"]
    assert len(p.instances) == 3 and p.duration_s == 6
    nested = source.replace(
        '<sound tempo="120"/>',
        '<barline location="left"><repeat direction="forward"/></barline><barline location="left"><repeat direction="forward"/></barline><sound tempo="120"/>',
    )
    with pytest.raises(ScoreInputError, match="前反复"):
        plan(nested)
    two = source.replace(
        "</measure>",
        '</measure><measure id="M2" number="two"><barline location="left"><repeat direction="forward"/></barline>'
        + note("b", duration=48, type="whole")
        + '<barline location="right"><repeat direction="backward"/></barline></measure>',
        1,
    )
    two = two.replace(
        '<sound tempo="120"/>',
        '<barline location="left"><repeat direction="forward"/></barline><sound tempo="120"/>',
        1,
    )
    # The first repeat already closes, so this remains two sequential regions.
    assert len(plan(two).occurrences) == 5


def test_two_parts_require_confirmation_and_align_by_structure():
    def part(pid, pitch):
        return (
            f'<part id="{pid}"><measure id="m-{pid}" number="same"><attributes><divisions>12</divisions><time><beats>4</beats><beat-type>4</beat-type></time><staves>1</staves><clef><sign>G</sign><line>2</line></clef></attributes><sound tempo="120"/>'
            + note(pid, pitch, duration=48, type="whole")
            + "</measure></part>"
        )

    text = (
        '<score-partwise version="4.0"><part-list><score-part id="R"><part-name>Upper</part-name></score-part><score-part id="L"><part-name>Lower</part-name></score-part></part-list>'
        + part("R", "C")
        + part("L", "E")
        + "</score-partwise>"
    )
    source = source_from_bytes(text.encode())
    assert "piano_group_confirmed" in parse_score(source).needs_confirmation
    p = plan(text, {"piano_group_confirmed": True})
    assert len(p.instances) == 2 and {n["part_id"] for n in p.instances} == {"R", "L"}
    assert len({e.measure_uid for e in p.document.elements}) == 1
    bad = text.replace('<sound tempo="120"/>', '<sound tempo="90"/>', 1)
    with pytest.raises(ScoreInputError, match="冲突"):
        plan(bad, {"piano_group_confirmed": True})


def test_maximum_exact_ppqn_does_not_require_a_24_multiple():
    text = xml(
        "".join(note("p" + str(i), duration=32767) for i in range(4)), divisions=32767
    )
    text = text.replace(
        '<sound tempo="120"/>',
        '<sound tempo="120"/><sound tempo="60"><offset>1</offset></sound>',
    )
    p = plan(text)
    midi = mido.MidiFile(file=BytesIO(compile_midi(p)))
    assert midi.ticks_per_beat == 32767


def test_real_source_note_count_boundary():
    first = note("n0", duration=48, type="whole")
    rest = "".join(
        note("n" + str(i), duration=48, type="whole").replace(
            "<pitch>", "<chord/><pitch>", 1
        )
        for i in range(1, 5001)
    )
    source = source_from_bytes(xml(first + rest).encode())
    with pytest.raises(ScoreInputError, match="5,000"):
        parse_score(source)
    assert (
        len(
            parse_score(
                source_from_bytes(xml(first + rest[: rest.rfind("<note ")]).encode())
            ).elements
        )
        == 5000
    )


def test_written_measure_and_expanded_occurrence_boundaries():
    first = xml(note("n0", duration=48, type="whole")).replace(
        "</measure>",
        '<barline location="left"><repeat direction="forward"/></barline></measure>',
    )
    tail = "".join(
        '<measure id="m'
        + str(i)
        + '" number="same">'
        + note("n" + str(i), duration=48, type="whole")
        + "</measure>"
        for i in range(1, 256)
    )
    text = first.replace("</part>", tail + "</part>").replace(
        '<sound tempo="120"/>', '<sound tempo="600"/>'
    )
    text = text.replace(
        "</measure></part>",
        '<barline location="right"><repeat direction="backward" times="4"/></barline></measure></part>',
    )
    p = plan(text)
    assert len(p.occurrences) == 1024
    with pytest.raises(ScoreInputError, match="1,024"):
        plan(text.replace('times="4"', 'times="5"'))
    with pytest.raises(ScoreInputError, match="256"):
        parse_score(
            source_from_bytes(
                text.replace(
                    "</part>",
                    '<measure number="overflow">'
                    + note("extra", duration=48, type="whole")
                    + "</measure></part>",
                ).encode()
            )
        )


def test_duration_and_expanded_instance_limits_are_rejected():
    with pytest.raises(ScoreInputError, match="600"):
        plan(
            xml(note("n", duration=48, type="whole")).replace(
                'tempo="120"', 'tempo="0.1"'
            )
        )
    chord = note("c0", duration=48, type="whole") + "".join(
        note("c" + str(i), duration=48, type="whole").replace(
            "<pitch>", "<chord/><pitch>", 1
        )
        for i in range(1, 1251)
    )
    text = xml(
        chord
        + '<barline location="right"><repeat direction="backward" times="16"/></barline>'
    )
    with pytest.raises(ScoreInputError, match="20,000"):
        plan(text)
