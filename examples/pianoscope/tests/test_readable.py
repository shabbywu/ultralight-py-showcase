from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path
from pianoscope.dev_paths import MIDI_ROOT
import json
import xml.etree.ElementTree as ET
import numpy as np
import pytest
from test_notation import midi,assert_conserved
from pianoscope.notation import build,musicxml,serialize,NotationError
from pianoscope.readable import normalize,onset_grids,release,split,TRIPLETS
from pianoscope.midi import parse_midi
from pianoscope.hands import preview,assigned
from pianoscope.render import render

OPTIONS=dict(profile=2,rhythm='auto',confirm_defaults=True)


def test_readable_release_models_and_exact_note_stay_exact(tmp_path):
    s=midi(tmp_path,[(0,455,60),(480,959,62),(960,1435,64),(1440,1920,65)])
    doc=build(s,OPTIONS);assert_conserved(doc,s)
    normalized=doc['source_note_index']
    for n in s.notes:
        events=[e for e in doc['events'] if n.id in e['source_note_ids']]
        assert sum(e['duration'] for e in events)==1
    assert normalized[s.notes[0].id]['normalization']['gate']==[19,20]
    assert normalized[s.notes[1].id]['normalization']['early_release_ticks']==1
    assert release(480,480)[1]['gate']==[1,1]
    assert release(480,480)[1]['early_release_ticks']==0


def test_zero_and_tiny_notes_retained_without_inventing_sounding_time(tmp_path):
    s=midi(tmp_path,[(0,0,60),(0,0,60),(390,417,64)])
    # The fixture writer sorts note-offs first at the same tick; explicitly set
    # the source's zero release, independently of event pairing conventions.
    s.notes[0].key_off_tick=0;s.notes[0].key_off_s=0
    s.notes[1].key_off_tick=0;s.notes[1].key_off_s=0
    doc=build(s,OPTIONS);assert_conserved(doc,s)
    for n in s.notes[:2]:
        source=doc['source_note_index'][n.id]
        assert source['normalization']['kind']=='short_fill'
        es=[e for e in doc['events'] if n.id in e['source_note_ids']]
        assert sum(e['duration'] for e in es)==F(1,16)
        assert all(p['start_s']==p['end_s']==0 for e in es for p in e['source_display_spans'])
    assert doc['voices'][1]>=2
    assert any(e['duration']==F(1,16) for e in doc['events'])


def test_four_voices_unique_xml_ids_and_fifth_rejected(tmp_path):
    s=midi(tmp_path,[(0,480,72),(0,960,74),(0,1440,76),(0,1920,77),(0,480,48)])
    doc=build(s,OPTIONS);assert_conserved(doc,s)
    assert doc['voices']=={1:4,2:1}
    root=ET.fromstring(musicxml(doc));ids={}
    for n in root.findall('.//note'):
        staff=int(n.findtext('staff'));ids.setdefault(staff,set()).add(int(n.findtext('voice')))
    assert ids[1]=={1,2,3,4} and ids[2]=={5}
    crowded=midi(tmp_path,[(0,480*(i+1),72) for i in range(5)])
    with pytest.raises(NotationError,match='四个声部'):build(crowded,OPTIONS)


def test_tuplet_sixteenth_and_64th_spelling_and_xml_beams(tmp_path):
    s=midi(tmp_path,[(0,75,72),(80,155,74),(160,235,76),(240,315,77),(320,395,79),(400,475,81),
                     (480+390,480+417,72),(480+420,480+447,74),(480+450,480+477,76)])
    doc=build(s,OPTIONS);assert_conserved(doc,s)
    root=ET.fromstring(musicxml(doc))
    assert root.findall('.//time-modification')
    assert any(n.findtext('type')=='16th' and n.find('time-modification') is not None for n in root.findall('.//note'))
    assert any(n.findtext('type')=='64th' for n in root.findall('.//note'))
    assert root.findall('.//beam[@number="4"]')
    for measure in root.findall('.//measure'):
        starts=len(measure.findall('.//tuplet[@type="start"]'));stops=len(measure.findall('.//tuplet[@type="stop"]'))
        assert starts==stops
    assert sum(d for a,d in split(F(2,3),F(1)))==F(1,3)


def test_readable_preserves_pcm_and_source_tempo_tie_boundaries(tmp_path):
    import mido
    s=midi(tmp_path,[(0,2735,60)],[(1440,0,mido.MetaMessage('set_tempo',tempo=1000000))])
    cfg=dict(rate=1,tracks=s.tracks,hand_mode='both');before=render(s,cfg,24000)
    snapshot=json.dumps([vars(n) for n in s.notes]);doc=build(s,OPTIONS);assert_conserved(doc,s)
    assert snapshot==json.dumps([vars(n) for n in s.notes])
    assert np.array_equal(before,render(s,cfg,24000))
    chain=[e for e in doc['events'] if s.notes[0].id in e['source_note_ids']]
    # Source qn4 is 1.5 + 1.0 seconds under the actual tempo map.
    second=next(e for e in chain if e['onset']==4)
    assert second['source_display_spans'][0]['start_s']==2.5


@pytest.mark.parametrize('filename,count,voices,zeros',[('Rush E.mid',1842,3,32),('Hans Zimmer - First Step - Interstellar.mid',1205,2,0),('Interstellar-Main-Theme-MIDI.mid',1566,4,0)])
def test_complete_downloaded_midis_deterministic_and_conserved(filename,count,voices,zeros):
    p=MIDI_ROOT/filename
    if not p.exists():pytest.skip('User MIDI not distributed')
    s=parse_midi(p);values,_=preview(s,dict(type='pitch_split',pitch=60));s=assigned(s,values,{})
    snapshot=[vars(n).copy() for n in s.notes]
    doc=build(s,OPTIONS);assert_conserved(doc,s)
    events={e['id']:e for e in doc['events']}
    for index in doc['source_note_index'].values():
        assert sum(events[eid]['duration'] for eid in index['notation_event_ids'])==F(*index['normalization']['inferred_duration'])
    assert len(doc['source_note_index'])==count and max(doc['voices'].values())<=4
    assert sum(v['normalization']['kind']=='short_fill' for v in doc['source_note_index'].values())==zeros
    assert serialize(doc)==serialize(build(s,OPTIONS))
    assert snapshot==[vars(n) for n in s.notes]


def test_profile_compatibility_pickup_tail_and_non_power_of_two_ppqn(tmp_path):
    s=midi(tmp_path,[(0,0,60)],ppqn=100)
    s.notes[0].key_off_tick=0;s.notes[0].key_off_s=0
    doc=build(s,dict(OPTIONS,pickup='1/16'));assert_conserved(doc,s)
    root=ET.fromstring(musicxml(doc));assert int(root.findtext('.//divisions'))%48==0
    with pytest.raises(NotationError):build(s,dict(OPTIONS,rhythm='triplets'))
    with pytest.raises(NotationError):build(s,dict(OPTIONS,profile=1))
    # Do not lose a normalized note beyond original end-of-track.
    s=midi(tmp_path,[(1440,1920,60)]);s.notes[0].start_tick=s.notes[0].key_off_tick=1920;s.notes[0].start_s=s.notes[0].key_off_s=2
    doc=build(s,OPTIONS);assert_conserved(doc,s)
    assert len(doc['measures'])==2


def test_dense_tempo_ramp_preserves_each_sound_offset_and_bounds_labels(tmp_path):
    import mido
    tempos=[(tick,0,mido.MetaMessage('set_tempo',tempo=500000-tick*10)) for tick in range(30,1800,30)]
    s=midi(tmp_path,[(0,1920,60)],tempos)
    doc=build(s,OPTIONS);root=ET.fromstring(musicxml(doc))
    sounds=root.findall('./part/measure/sound')
    assert len(sounds)==len(s.tempo_map)
    assert len(root.findall('.//metronome'))==1
    divisions=int(root.findtext('.//divisions'))
    for sound,source in zip(sounds,s.tempo_map):
        assert abs(float(sound.attrib['tempo'])-source['quarter_bpm'])<1e-8
        assert F(int(sound.findtext('offset')),divisions)==F(source['tick'],s.ppqn)
    assert doc['metadata_sources']['tempos']==s.tempo_map


def test_different_chord_releases_are_segmented_and_tied_not_five_voices(tmp_path):
    s=midi(tmp_path,[(0,480*(i+1),60+i) for i in range(5)])
    doc=build(s,OPTIONS);assert_conserved(doc,s)
    assert doc['voices'][1]<=4
    events={e['id']:e for e in doc['events']}
    for n in s.notes:
        index=doc['source_note_index'][n.id]
        assert sum(events[eid]['duration'] for eid in index['notation_event_ids'])==F(n.key_off_tick-n.start_tick,s.ppqn)


def test_ten_chord_tones_share_one_rhythmic_voice(tmp_path):
    s=midi(tmp_path,[(0,480,60+i) for i in range(10)])
    doc=build(s,OPTIONS);assert_conserved(doc,s)
    assert doc['voices']=={1:1,2:1}
    assert len([e for e in doc['events'] if e['pitch'] is not None])==10


def test_zero_fill_is_not_extended_or_hidden_by_release_alignment():
    from types import SimpleNamespace
    from pianoscope.readable import align_releases
    zero=SimpleNamespace(id='zero');next_note=SimpleNamespace(id='next')
    items=[(F(0),F(1,16),1,zero),(F(1,12),F(1,3),1,next_note)]
    records={'zero':dict(kind='short_fill'),'next':dict(kind='duration_aligned')}
    result=align_releases(items,records)
    assert result[0][1]==F(1,16) and records['zero']['kind']=='short_fill'


def test_review_warning_category_is_paged_and_complete(tmp_path):
    from types import SimpleNamespace
    from pianoscope.session import Controller
    s=midi(tmp_path,[(0,0,60),(480,935,64)])
    s.notes[0].key_off_tick=0;s.notes[0].key_off_s=0
    doc=build(s,OPTIONS)
    c=SimpleNamespace(notation=SimpleNamespace(_item=lambda _:dict(document=doc)))
    all=Controller.get_notation_warnings(c,'test',0,100)
    short=Controller.get_notation_warnings(c,'test',0,100,'short_fill')
    review=Controller.get_notation_warnings(c,'test',0,100,'review')
    assert all['total']>=short['total']==1 and review['total']>=1
    assert short['warnings'][0]['source_note_id']==s.notes[0].id
