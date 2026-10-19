"""Hand-authored expectations for the MusicXML path, independent SMF readback."""
from fractions import Fraction as Q
from io import BytesIO
from pathlib import Path
import hashlib
import zipfile
import mido
import pytest
from pianoscope.score_source import read_source, source_from_bytes, ScoreInputError
from pianoscope.score_model import parse_score
from pianoscope.playback_plan import compile_plan
from pianoscope.midi_compile import compile_midi

FIXTURES = Path(__file__).parent / 'fixtures/v2'


def phrase(text=None, settings=None):
    source = read_source(FIXTURES / 'temporal.musicxml') if text is None else source_from_bytes(text.encode())
    return compile_plan(parse_score(source, settings), settings)


def test_hand_written_path_and_tempo_integrals():
    plan = phrase()
    assert [(o['measure_uid'], o['visit_index']) for o in plan.occurrences] == [
        ('pickup', 1), ('A', 1), ('B', 1), ('A', 2), ('C', 1), ('D', 1)]
    assert [o['start_s'] for o in plan.occurrences] == pytest.approx([0, .5, 3.5, 7.5, 10.5, 13.5])
    assert plan.duration_qn == 21
    assert plan.seconds(21) == Q(97, 6)
    assert len(plan.instances) == 20
    tied = [n for n in plan.instances if n['element_ids'][0] == 'a-long']
    assert [n['element_ids'] for n in tied] == [['a-long', 'b-tie'], ['a-long', 'c-tie-cross']]
    assert [(n['onset_s'], n['key_off_s']) for n in tied] == pytest.approx([(.5, 7.5), (7.5, 73/6)])
    # A pedal press at key-off cannot sustain the pickup; jump reset releases tails.
    assert plan.instances[0]['sustain_end_s'] == .5
    assert next(n for n in plan.instances if n['id'] == 'i4')['sustain_end_s'] == 7.5


def test_smf_independent_reader_matches_manual_note_events():
    plan = phrase()
    raw = compile_midi(plan)
    midi = mido.MidiFile(file=BytesIO(raw))
    assert midi.type == 1 and midi.ticks_per_beat == 24
    seconds, pending, played = 0., {}, []
    for message in midi:
        seconds += message.time
        if message.type == 'note_on' and message.velocity:
            key = (message.channel, message.note)
            assert key not in pending
            pending[key] = seconds
        elif message.type == 'note_off':
            played.append((message.note, pending.pop((message.channel, message.note)), seconds))
    expected = [(67, 0, .5), (72, .5, 7.5), (76, .5, 1.5), (72, .5, 1.5),
                (48, .5, 3.5), (43, 3.5, 5.5), (43, 5.5, 7.5),
                (72, 7.5, 73/6), (76, 7.5, 8.5), (72, 7.5, 8.5), (48, 7.5, 10.5),
                (53, 10.5, 13.5), (74, 73/6, 13.5), (84, 13.5, 13.5+2/9),
                (48, 13.5, 97/6), (86, 13.5+2/9, 13.5+4/9),
                (88, 13.5+4/9, 85/6), (91, 85/6, 91/6), (88, 91/6, 15.5), (84, 15.5, 97/6)]
    assert not pending and len(played) == len(expected)
    # SMF microsecond tempos are integer; the explicit measured error is tiny.
    for actual, wanted in zip(sorted(played), sorted(expected)):
        assert actual == pytest.approx(wanted, abs=plan.midi_precision['seconds_error_bound'] + 1e-12)
    # Seven quarter notes at 90 BPM: 666667 versus 2000000/3 us/qn.
    assert plan.midi_precision['seconds_error_bound'] == pytest.approx(7 / 3 / 1_000_000)
    assert any(msg.type == 'control_change' and msg.control == 64 and msg.value == 127 for tr in midi.tracks for msg in tr)
    assert len(plan.midi_event_map) >= 40


def test_tie_segment_seek_and_occurrence_policy():
    plan = phrase()
    assert plan.seek_target('b-tie')['start_s'] == 3.5
    assert plan.seek_target('c-tie-cross')['start_s'] == 10.5
    assert plan.seek_target('a-long', seconds=4)['start_s'] == 7.5
    assert plan.seek_target('a-long', seconds=8)['start_s'] == 7.5
    assert plan.seek_target('a-long', occurrence_id='o2')['start_s'] == .5
    assert plan.seek_target('a-rest', occurrence_id='o4')['start_s'] == 8.5
    assert plan.seek_target('A', occurrence_id='o4')['start_s'] == 7.5
    with pytest.raises(ScoreInputError):
        plan.seek_target('a-long', occurrence_id='o6')


def test_source_bytes_ids_and_unknown_fields_are_preserved():
    raw = (FIXTURES / 'temporal.musicxml').read_bytes().replace(b'<work>', b'<vendor-extension secret="42"/><work>', 1)
    source = source_from_bytes(raw)
    assert source.original_bytes == raw
    assert source.sha256 == hashlib.sha256(raw).hexdigest()
    assert b'vendor-extension' in source.preserved_tree
    assert 'http://www.musicxml.org/dtds/partwise.dtd' not in source.working_xml
    a = read_source(FIXTURES / 'temporal.musicxml')
    b = read_source(FIXTURES / 'temporal.musicxml')
    assert a.locations == b.locations
    assert 'a-long' in a.locations
    assert parse_score(a).parts[0]['id'] == 'P1'


def test_duplicate_source_note_ids_are_diagnosed_and_unique():
    raw = (FIXTURES / 'temporal.musicxml').read_bytes().replace(b'id="a-overlap"', b'id="a-long"')
    source = source_from_bytes(raw)
    elements = parse_score(source).elements
    assert len({e.id for e in elements}) == len(elements)
    assert sum(d['code'] == 'SOURCE_ID_REPLACED' for d in source.diagnostics) == 2


@pytest.mark.parametrize('replacement', [
    ('<score-partwise version="4.0">', '<score-partwise version="2.0">'),
    ('<pitch><step>G</step>', '<grace/><pitch><step>G</step>'),
    ('<alter>0</alter>', '<alter>0.5</alter>'),
    ('<sound tempo="60"/>', '<sound dacapo="yes" tempo="60"/>'),
    ('<beats>4</beats>', '<beats>5</beats>'),
    ('<duration>48</duration>', '<duration>49</duration>'),
])
def test_unsupported_music_is_blocked_with_location(replacement):
    raw = (FIXTURES / 'temporal.musicxml').read_text().replace(*replacement, 1)
    with pytest.raises(ScoreInputError) as caught:
        phrase(raw)
    assert caught.value.issues[0]['source_locator']


def test_missing_tempo_requires_explicit_confirmation():
    text = (FIXTURES / 'temporal.musicxml').read_text().replace(' tempo="120"', '')
    source = source_from_bytes(text.encode())
    assert 'default_tempo' in parse_score(source).needs_confirmation
    with pytest.raises(ScoreInputError, match='确认'):
        compile_plan(parse_score(source))
    plan = compile_plan(parse_score(source, {'default_tempo': 100}), {'default_tempo': 100})
    assert plan.tempos[0]['bpm'] == 100


def test_xxe_and_internal_entities_refused_but_external_doctype_ignored():
    raw = b'<!DOCTYPE score-partwise [<!ENTITY x SYSTEM "file:///etc/passwd">]><score-partwise version="4.0">&x;</score-partwise>'
    with pytest.raises(ScoreInputError, match='XML'):
        source_from_bytes(raw)
    assert read_source(FIXTURES / 'temporal.musicxml').container_type == 'xml'


def container(entries):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return stream.getvalue()


def test_mxl_rootfile_without_xml_suffix_and_byte_copy():
    data = container([('META-INF/container.xml', '<container><rootfiles><rootfile full-path="music" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles></container>'),
                      ('music', (FIXTURES / 'temporal.musicxml').read_bytes())])
    source = source_from_bytes(data, 'PIANO.MXL')
    assert source.root_entry == 'music' and source.original_bytes == data
    assert len(compile_plan(parse_score(source)).instances) == 20


@pytest.mark.parametrize('entries', [[('../outside', b'bad')], [('/abs', b'bad')],
    [('META-INF/container.xml', '<container/>')], [('a', b'x'), ('a', b'y')],
    [('META-INF/container.xml', '<container><rootfile full-path="missing"/></container>')]])
def test_bad_containers_are_refused(entries):
    with pytest.raises(ScoreInputError):
        source_from_bytes(container(entries), 'test.mxl')


def test_compilation_and_midi_are_deterministic():
    a, b = phrase(), phrase()
    assert compile_midi(a) == compile_midi(b)
    assert a.instances == b.instances and a.display_spans == b.display_spans
    assert a.revision == b.revision
