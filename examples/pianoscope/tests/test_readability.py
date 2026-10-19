"""Focused notation-readability cases, without device or long performance runs."""
from fractions import Fraction as F
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET
import pytest
from test_notation import midi,assert_conserved
from pianoscope.dev_paths import MIDI_ROOT
from pianoscope.midi import parse_midi
from pianoscope.notation import build,musicxml,KEYS
from pianoscope.readable import TRIPLETS,spell
from pianoscope.score_spelling import plan_clefs,ledger_cost

OPTIONS=dict(profile=2,rhythm='auto',confirm_defaults=True)


def test_jittered_chords_and_releases_stay_conventional(tmp_path):
    source=midi(tmp_path,[(j*480+offset,j*480+480+offset+1,pitch)
        for j in range(8) for offset,pitch in ((0,60),(18,64),(49,67))])
    original=[vars(n).copy() for n in source.notes]
    doc=build(source,OPTIONS);assert_conserved(doc,source)
    for n in source.notes:
        index=doc['source_note_index'][n.id]
        assert len(index['notation_event_ids'])==1
        e=next(e for e in doc['events'] if e['id']==index['notation_event_ids'][0])
        assert e['duration']==1 and e['onset'].denominator==1
    assert not any(e['duration'] in TRIPLETS for e in doc['events'])
    assert original==[vars(n) for n in source.notes]


def test_binary_rests_never_use_triplets_to_save_symbols(tmp_path):
    assert all(d not in TRIPLETS for d in spell(F(15,4),rest=True))
    source=midi(tmp_path,[(1800,1920,60)])
    doc=build(source,OPTIONS);assert_conserved(doc,source)
    xml=ET.fromstring(musicxml(doc))
    assert not xml.findall('.//time-modification')
    assert not any(n.find('dot') is not None for n in xml.findall('.//note') if n.find('rest') is not None)


def test_ordinary_syncopated_quarter_does_not_acquire_a_tie(tmp_path):
    source=midi(tmp_path,[(240,720,60)])
    doc=build(source,OPTIONS);assert_conserved(doc,source)
    notes=[e for e in doc['events'] if e['pitch'] is not None]
    assert len(notes)==1 and notes[0]['duration']==1
    assert not notes[0]['tie_start'] and not notes[0]['tie_stop']


def test_source_triplets_and_fast_same_pitch_attacks_survive(tmp_path):
    source=midi(tmp_path,[(k*80,k*80+75,72+k) for k in range(6)]+
        [(480+k*30,480+k*30+27,84) for k in range(4)])
    doc=build(source,OPTIONS);assert_conserved(doc,source)
    first=[doc['source_note_index'][n.id]['normalization'] for n in source.notes[:6]]
    assert all(v['onset_division']==6 for v in first)
    assert any(e['duration']==F(1,6) for e in doc['events'])
    fast=[e for e in doc['events'] if e['pitch']==84]
    assert len(fast)==4 and len({e['onset'] for e in fast})==4


def test_regular_fast_attacks_are_not_merged_even_with_overlapping_lengths(tmp_path):
    source=midi(tmp_path,[(k*60,k*60+480,72+k) for k in range(4)])
    doc=build(source,OPTIONS);assert_conserved(doc,source)
    starts={n.id:next(e['onset'] for e in doc['events'] if n.id in e['source_note_ids']) for n in source.notes}
    assert sorted(starts.values())==[F(0),F(1,8),F(1,4),F(3,8)]


def test_quarter_triplets_across_two_beats_preserve_binary_accompaniment(tmp_path):
    source=midi(tmp_path,[(k*320,k*320+304,72) for k in range(3)]+[(240,480,48)])
    doc=build(source,OPTIONS);assert_conserved(doc,source)
    high=[e for e in doc['events'] if e['pitch']==72]
    assert sorted(e['onset'] for e in high)==[F(0),F(2,3),F(4,3)]
    assert all(e['duration']==F(2,3) for e in high)
    low=next(e for e in doc['events'] if e['pitch']==48)
    assert low['onset']==F(1,2) and low['duration']==F(1,2)


def test_automatic_key_is_an_explicit_suggestion_not_a_source_edit(tmp_path):
    source=midi(tmp_path,[(0,1920,59),(0,1920,63),(0,1920,66),(1920,2400,61),(2400,2880,68)])
    before=json.dumps(source.key_map)
    doc=build(source,dict(OPTIONS,key='auto'))
    assert doc['key_analysis']['requires_confirmation']
    assert json.dumps(source.key_map)==before
    root=ET.fromstring(musicxml(doc))
    assert int(root.findtext('.//fifths'))==KEYS[doc['key_analysis']['key']]
    manual=build(source,dict(OPTIONS,key='G#m'))
    assert manual['key_analysis'] is None and ET.fromstring(musicxml(manual)).findtext('.//mode')=='minor'


def test_clefs_follow_ranges_without_switching_on_every_note():
    assert ledger_cost(64,'G',0)==0 and ledger_cost(60,'G',0)==1
    assert ledger_cost(84,'G',0)==4
    measures=[dict(id=f'm{i}',start=F(4*i),length=F(4)) for i in range(16)]
    events=[dict(measure_id=m['id'],staff=1,pitch=43 if i<8 else 88,onset=m['start'],duration=F(4),tie_stop=False) for i,m in enumerate(measures)]
    plan_clefs(measures,events,'auto')
    states=[m['clefs']['1']['sign'] for m in measures]
    assert states[:8]==['F']*8 and states[8:]==['G']*8
    assert sum(a!=b for a,b in zip(states,states[1:]))==1


def test_ottava_xml_keeps_true_pitches_and_closes_marks(tmp_path):
    source=midi(tmp_path,[(i*480,i*480+480,96) for i in range(16)])
    doc=build(source,dict(OPTIONS,clef_mode='auto_octaves'));assert_conserved(doc,source)
    assert all(m['clefs']['1']['octave']==1 for m in doc['measures'])
    root=ET.fromstring(musicxml(doc));shifts=root.findall('.//octave-shift')
    assert [s.attrib['type'] for s in shifts]==['down','stop']
    assert all(n.findtext('pitch/octave')=='7' for n in root.findall('.//note') if n.find('pitch') is not None)
    from music21 import converter
    reread=converter.parseData(musicxml(doc),format='musicxml')
    assert {int(p.midi) for n in reread.flatten().notes for p in n.pitches}=={96}


def test_split_track_download_measure_36_and_all_sources_preserved():
    path=MIDI_ROOT/'Interstellar-Main-Theme-Left-Right-Hand.mid'
    if not path.exists():pytest.skip('Local user MIDI not distributed')
    source=parse_midi(path);fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
    original=[vars(n).copy() for n in source.notes]
    doc=build(source,dict(OPTIONS,staff_mode='tracks',staff_tracks={'t0c0':1,'t1c1':2},key='auto'))
    assert_conserved(doc,source)
    assert len(doc['source_note_index'])==1566 and len(doc['events'])<4500
    bar=[e for e in doc['events'] if e['measure_id']=='m36']
    assert all(e['duration'] not in TRIPLETS for e in bar)
    assert all(e['duration'].denominator in (1,2,4,8,16) for e in doc['events'])
    assert doc['key_analysis']['key']=='B' and doc['key_analysis']['relative_key']=='G#m'
    assert doc['measures'][0]['clefs']['1']['sign']=='F'
    assert original==[vars(n) for n in source.notes] and hashlib.sha256(path.read_bytes()).hexdigest()==fingerprint
    # Every chain covers its inferred duration, while sounding spans stay source based.
    events={e['id']:e for e in doc['events']}
    for index in doc['source_note_index'].values():
        assert sum(events[eid]['duration'] for eid in index['notation_event_ids'])==F(*index['normalization']['inferred_duration'])
