from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path
from types import SimpleNamespace
import json
import time
import xml.etree.ElementTree as ET
import mido
import pytest
from pianoscope.midi import parse_midi
from pianoscope.notation import build,musicxml,serialize,nearest,dependency,tempo_for,NotationError
from pianoscope.score_jobs import ScoreJobs


def midi(tmp_path,notes,meta=(),ppqn=480):
    path=tmp_path/'练习.mid';mid=mido.MidiFile(type=1,ticks_per_beat=ppqn)
    track=mido.MidiTrack();mid.tracks.append(track)
    events=[(0,0,mido.MetaMessage('set_tempo',tempo=500000)),(0,0,mido.MetaMessage('time_signature',numerator=4,denominator=4)),*meta]
    for start,end,pitch in notes:
        events.extend([(start,2,mido.Message('note_on',note=pitch,velocity=90)),(end,1,mido.Message('note_off',note=pitch))])
    last=0
    for tick,_,msg in sorted(events,key=lambda e:e[:2]):track.append(msg.copy(time=tick-last));last=tick
    mid.save(path);return parse_midi(path)


def assert_conserved(doc,score):
    assert set(doc['source_note_index'])=={n.id for n in score.notes}
    events={e['id']:e for e in doc['events']}
    for n in score.notes:
        chain=[events[i] for i in doc['source_note_index'][n.id]['notation_event_ids']]
        assert chain and all(e['pitch']==n.pitch and e['source_note_ids']==[n.id] for e in chain)
        assert not chain[0]['tie_stop'] and not chain[-1]['tie_start']
        assert chain[0]['source_display_spans'][0]['start_s']==n.start_s
        assert chain[-1]['source_display_spans'][0]['end_s']==n.key_off_s
    for m in doc['measures']:
        for staff in (1,2):
            voices=sorted({e['voice'] for e in doc['events'] if e['measure_id']==m['id'] and e['staff']==staff}) if doc['profile']==2 else range(1,doc['voices'][staff]+1)
            assert voices
            for voice in voices:
                assert sum(e['duration'] for e in doc['events'] if e['measure_id']==m['id'] and e['staff']==staff and e['voice']==voice and not e['chord'])==m['length']


def test_raw_provenance_and_pedal(tmp_path):
    s=midi(tmp_path,[(120,720,60)],[(0,0,mido.MetaMessage('key_signature',key='Eb')),(400,0,mido.Message('control_change',control=64,value=127)),(1000,0,mido.Message('control_change',control=64,value=0))])
    n=s.notes[0];assert (s.ppqn,n.start_tick,n.key_off_tick,s.duration_tick)==(480,120,720,1000)
    assert n.source_event and len(s.source_fingerprint)==64 and n.sustain_end_s>n.key_off_s
    assert s.key_map[0]['key']=='Eb' and s.tempo_map[0]['tick']==0
    assert [c['tick'] for c in s.controls if c['control']==64]==[400,1000]
    assert parse_midi(tmp_path/'练习.mid').notes[0].source_event==n.source_event


def test_chords_two_voices_same_pitch_and_staff_independence(tmp_path):
    s=midi(tmp_path,[(0,960,60),(0,480,64),(0,480,67),(480,1440,60)])
    s.notes=[replace(n,hand='left') for n in s.notes]
    d=build(s,{'staff_mode':'pitch','split':50,'confirm_defaults':True})
    assert_conserved(d,s)
    assert d['voices'][1]==2
    assert all(e['staff']==1 and e['hand']=='left' for e in d['events'] if e['pitch'] is not None)
    xml=ET.fromstring(musicxml(d));assert len(xml.findall('.//note/chord'))>=1


def test_exact_same_pitch_overlap_keeps_two_ids(tmp_path):
    s=midi(tmp_path,[(0,960,60),(0,960,60)])
    d=build(s,{'confirm_defaults':True});assert_conserved(d,s)
    assert len(d['source_note_index'])==2 and d['voices'][1]==2


def test_overvoice_is_a_blocking_error(tmp_path):
    s=midi(tmp_path,[(0,1440,60),(480,1920,62),(960,2400,64)])
    with pytest.raises(NotationError,match='超过两个声部') as exc:build(s,{'confirm_defaults':True})
    assert exc.value.issues[0]['measure']==1


def test_tie_boundaries_integrate_original_tempo_not_total_seconds(tmp_path):
    s=midi(tmp_path,[(0,4800,60)],[(1920,0,mido.MetaMessage('set_tempo',tempo=1000000))])
    d=build(s,{'confirm_defaults':True});assert_conserved(d,s)
    chain=[e for e in d['events'] if e['pitch'] is not None]
    assert chain[0]['source_display_spans'][0]['end_s']==2
    assert chain[1]['source_display_spans'][0]['start_s']==2
    assert s.notes[0].key_off_s==8
    assert tempo_for(s).tick_at(2)==1920
    xml=ET.fromstring(musicxml(d));assert len(xml.findall('.//tie'))==2*(len(chain)-1)


@pytest.mark.parametrize('meter',[(2,4),(3,4),(4,4),(6,8)])
def test_meters_pickup_tail_and_source_defaults(tmp_path,meter):
    s=midi(tmp_path,[(240,720,60)],[(0,0,mido.MetaMessage('time_signature',numerator=meter[0],denominator=meter[1]))])
    with pytest.raises(NotationError,match='确认'):build(s,{})
    d=build(s,{'confirm_defaults':True,'pickup':'1'});assert_conserved(d,s)
    assert d['measures'][0]['length']==1 and d['measures'][0]['pickup']
    assert ET.fromstring(musicxml(d)).find('.//measure').attrib['implicit']=='yes'
    plain=build(s,{'confirm_defaults':True});assert plain['events'][0]['pitch'] is None


def test_metadata_changes_and_mid_measure_meter_refused(tmp_path):
    s=midi(tmp_path,[(0,3000,60)],[(1920,0,mido.MetaMessage('time_signature',numerator=3,denominator=4)),(960,0,mido.MetaMessage('set_tempo',tempo=650000)),(1920,0,mido.MetaMessage('key_signature',key='F#'))])
    d=build(s,{'confirm_defaults':True});assert_conserved(d,s)
    root=ET.fromstring(musicxml(d));assert root.find('.//offset').text=='0'
    assert any(e.text=='6' for e in root.findall('.//fifths'))
    s.meter_map[-1]['tick']=1000
    with pytest.raises(NotationError,match='中途变拍'):build(s,{'confirm_defaults':True})


def test_quantization_tie_tolerance_collapse_and_repeatability(tmp_path):
    assert nearest(F(1,8),'straight')==F(1,4)
    assert nearest(F(1,3),'triplets')==F(1,3)
    s=midi(tmp_path,[(48,432,60)])
    d=build(s,{'confirm_defaults':True});assert_conserved(d,s)
    assert serialize(d)==serialize(build(s,{'confirm_defaults':True}))
    s=midi(tmp_path,[(49,432,60)])
    with pytest.raises(NotationError,match='容差'):build(s,{'confirm_defaults':True})
    s=midi(tmp_path,[(1,30,60)])
    with pytest.raises(NotationError,match='塌缩'):build(s,{'confirm_defaults':True})
    s=midi(tmp_path,[(0,0,60)])
    with pytest.raises(NotationError,match='零'):build(s,{'confirm_defaults':True})


def test_triplets_and_unrepresentable_union_residual(tmp_path):
    s=midi(tmp_path,[(0,160,60),(160,320,62),(320,480,64)])
    d=build(s,{'rhythm':'triplets','confirm_defaults':True});assert_conserved(d,s)
    assert len(ET.fromstring(musicxml(d)).findall('.//time-modification'))==3
    s=midi(tmp_path,[(120,160,60)])
    with pytest.raises(NotationError,match='无法表示'):build(s,{'rhythm':'triplets','confirm_defaults':True})


def test_dependency_ignores_audition_revision(tmp_path):
    s=midi(tmp_path,[(0,480,60)]);a=dependency(s)
    s.revision+=1;s.tracks[0]['muted']=True
    assert dependency(s)==a
    s.notes[0].hand='right';assert dependency(s)!=a


def test_pedal_provenance_does_not_change_original_pcm(tmp_path):
    import numpy as np
    from pianoscope.render import render
    s=midi(tmp_path,[(0,480,60)],[(0,0,mido.Message('control_change',control=64,value=127)),(960,0,mido.Message('control_change',control=64,value=0))])
    config=dict(rate=1,tracks=s.tracks,hand_mode='both')
    with_cc=render(s,config,24000);without=render(replace(s,controls=[c for c in s.controls if c['control']!=64]),config,24000)
    assert np.array_equal(with_cc,without)


def test_empty_scope_empty_score_and_unsupported_meter(tmp_path):
    s=midi(tmp_path,[(0,480,60)])
    with pytest.raises(NotationError):build(s,{'tracks':[],'confirm_defaults':True})
    with pytest.raises(NotationError,match='没有'):build(replace(s,notes=[]),{'confirm_defaults':True})
    s.meter_map[0]['numerator']=5
    with pytest.raises(NotationError,match='拍号'):build(s,{'confirm_defaults':True})


def test_score_resource_limits_fail_before_native_layout(tmp_path):
    s=midi(tmp_path,[(0,480,60)])
    with pytest.raises(NotationError,match='5000|5,000'):build(replace(s,notes=s.notes*5001),{'confirm_defaults':True})
    with pytest.raises(NotationError,match='256'):build(replace(s,duration_tick=480*4*257),{'confirm_defaults':True})


def test_unavailable_worker_returns_recoverable_error(tmp_path,monkeypatch):
    import pianoscope.score_jobs as module
    service=ScoreJobs(SimpleNamespace(score=midi(tmp_path,[(0,480,60)])))
    try:
        def unavailable(*args,**kwargs):raise OSError('cannot exec')
        with monkeypatch.context() as patch:
            patch.setattr(module.subprocess,'Popen',unavailable)
            job=service.begin({'confirm_defaults':True});state=wait(service,job['job_id'])
            assert state['error']['code']=='NOTATION_ENGINE_UNAVAILABLE' and state['error']['recoverable']
        job=service.begin({'confirm_defaults':True});assert wait(service,job['job_id'])['phase']=='preview_ready'
    finally:service.close()


def wait(service,jid):
    until=time.monotonic()+30
    while time.monotonic()<until:
        j=service.get(jid)
        if j['done']:return j
        time.sleep(.02)
    raise TimeoutError(j)


def test_real_worker_atomic_application_stale_cancel_and_export(tmp_path):
    score=midi(tmp_path,[(0,2400,60),(0,480,64)])
    c=SimpleNamespace(score=score);service=ScoreJobs(c)
    try:
        j=service.begin({'confirm_defaults':True});r=wait(service,j['job_id']);assert r['phase']=='preview_ready',r
        p=r['result'];service.apply(p['preview_id'],p['source_revision']);applied=service.applied
        page=service.page(p['notation_id'],0);assert page['glyphs']
        assert all(system['bbox'][2]>100 for system in page['systems'])
        for glyph in page['glyphs']:
            system=page['systems'][glyph['system']]['bbox'];g=glyph['bbox']
            assert system[0]<=g[0] and system[1]<=g[1] and g[0]+g[2]<=system[0]+system[2]+.01 and g[1]+g[3]<=system[1]+system[3]+.01
        score.revision+=1;assert service.summary(applied)['state']=='applied'
        score.notes[0].hand='left'
        with pytest.raises(NotationError,match='过期'):service.apply(p['preview_id'],p['source_revision'])
        assert service.applied is applied
        new=service.begin({'confirm_defaults':True});service.cancel(new['job_id']);assert wait(service,new['job_id'])['cancelled']
        score.notes[0].hand='unassigned'
        target=tmp_path/'existing.musicxml';target.write_text('ORIGINAL')
        token=service.target(p['notation_id'],'musicxml',target)
        c.score=replace(score,score_id='changed')
        with pytest.raises(NotationError):service.export(p['notation_id'],'musicxml',token['target_token'])
        assert target.read_text()=='ORIGINAL'
        c.score=score
        token=service.target(p['notation_id'],'musicxml',target);j=service.export(p['notation_id'],'musicxml',token['target_token'])
        assert wait(service,j['job_id'])['phase']=='completed';assert ET.parse(target).getroot().tag=='score-partwise'
        assert service.cancel(j['job_id']) is False
        original=target.read_bytes();token=service.target(p['notation_id'],'musicxml',target)
        with service.lock:
            j=service.export(p['notation_id'],'musicxml',token['target_token']);assert service.cancel(j['job_id'])
        assert wait(service,j['job_id'])['cancelled'];assert target.read_bytes()==original
        token=service.target(p['notation_id'],'musicxml',target)
        with service.lock:
            j=service.export(p['notation_id'],'musicxml',token['target_token']);c.score=replace(score,score_id='new-song')
        assert wait(service,j['job_id'])['phase']=='completed';assert target.read_bytes()==original
        c.score=score
        token=service.target(p['notation_id'],'pdf',tmp_path/'missing'/'score.pdf');j=service.export(p['notation_id'],'pdf',token['target_token'])
        assert wait(service,j['job_id'])['error']['code']=='EXPORT_FAILED'
        assert service.applied is applied
        j=service.begin({'confirm_defaults':True});score.notes[0].hand='right'
        assert wait(service,j['job_id'])['phase']=='stale'
    finally:service.close()
    assert not service.root.exists()


def test_current_workspace_600_second_parser_boundary(tmp_path):
    score=midi(tmp_path,[(0,480*1200,60)])
    assert score.duration_s==600
    from pianoscope.midi import ScoreError
    with pytest.raises(ScoreError,match='600'):
        midi(tmp_path,[(0,480*1202,60)])


def test_failed_worker_for_previous_song_is_stale_not_current_error(tmp_path):
    score=midi(tmp_path,[(0,20,60)])
    c=SimpleNamespace(score=score);service=ScoreJobs(c)
    try:
        job=service.begin({'confirm_defaults':True})
        c.score=replace(score,score_id='next-song')
        result=wait(service,job['job_id'])
        assert result['phase']=='stale' and result['error'] is None
        assert not service.previews and service.applied is None
    finally:service.close()
