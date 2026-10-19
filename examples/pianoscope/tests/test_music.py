import asyncio
import io
import time
from dataclasses import replace
from pathlib import Path
import mido
import numpy as np
import pytest
from pianoscope.midi import parse_midi, TempoMap, ScoreError, Note, Score
from pianoscope.hands import preview, assigned
from pianoscope.analysis import overview, fft_amplitude, analyze
from pianoscope.render import render, audible_notes
from pianoscope.session import Controller, DEMO_ROOT


def midi(tmp_path,tracks,type=1,ppqn=480):
    mid=mido.MidiFile(type=type,ticks_per_beat=ppqn)
    for messages in tracks:mid.tracks.append(mido.MidiTrack(messages))
    p=tmp_path/'fixture.mid';mid.save(p);return p

def on(p=60,t=0,v=100,ch=0):return mido.Message('note_on',note=p,time=t,velocity=v,channel=ch)
def off(p=60,t=480,ch=0):return mido.Message('note_off',note=p,time=t,channel=ch)
def cc(c,v,t=0,ch=0):return mido.Message('control_change',control=c,value=v,time=t,channel=ch)

def test_tempo_integral_and_same_tick_order(tmp_path):
    p=midi(tmp_path,[[mido.MetaMessage('set_tempo',tempo=500000),mido.MetaMessage('set_tempo',tempo=1000000,time=480)], [on(),off(t=960)]])
    s=parse_midi(p)
    assert s.duration_s==1.5
    assert s.notes[0].key_off_s==1.5
    assert s.tempo_map[1]['time_s']==.5
    assert s.tempo_map[1]['quarter_bpm']==60

def test_fifo_velocity_zero_pedal_and_shared_channel(tmp_path):
    p=midi(tmp_path,[[on(),on(t=120),cc(64,127),off(t=120),on(t=120,v=0),cc(64,0,t=120)], [on(p=64),off(p=64,t=120)]])
    s=parse_midi(p);a,b,c=s.notes
    assert (a.pitch,b.pitch,c.pitch)==(60,64,60)
    assert a.key_off_s==.25 and c.key_off_s==.375
    assert a.sustain_end_s==c.sustain_end_s==.5
    assert b.key_off_s==.125 and b.sustain_end_s==.5
    assert len(s.tracks)==2

def test_external_names_do_not_confirm_hands(tmp_path):
    s=parse_midi(midi(tmp_path,[[mido.MetaMessage('track_name',name='Left'),on(),off()]],type=0))
    assert s.notes[0].hand=='unassigned'
    assert s.tracks[0]['suggested_hand']=='left'
    values,counts=preview(s,{'type':'pitch_split','pitch':61})
    assert values=={'n0':'left'} and s.notes[0].hand=='unassigned'
    edited=assigned(s,values,{'n0':'right'})
    assert edited.notes[0].hand=='right' and s.notes[0].hand=='unassigned'
    assert edited.revision==2

@pytest.mark.parametrize('kind',['type2','smpte','empty','broken','long','out','huge'])
def test_invalid_inputs(tmp_path,kind):
    if kind=='broken':p=tmp_path/'bad.mid';p.write_bytes(b'not a midi')
    elif kind=='huge':p=tmp_path/'bad.mid';p.write_bytes(b'0'*(5*1024*1024+1))
    elif kind=='type2':p=midi(tmp_path,[[on(),off()]],type=2)
    elif kind=='smpte':
        p=midi(tmp_path,[[on(),off()]]);data=bytearray(p.read_bytes());data[12:14]=b'\xe7\x28';p.write_bytes(data)
    elif kind=='empty':p=midi(tmp_path,[[]])
    elif kind=='out':p=midi(tmp_path,[[on(p=10),off(p=10)]])
    else:p=midi(tmp_path,[[on(),off(t=480*1202)]])
    with pytest.raises(ScoreError):parse_midi(p)

def test_all_off_and_dangling(tmp_path):
    s=parse_midi(midi(tmp_path,[[off(),on(),cc(64,127),off(),cc(120,0,t=480),on(p=64),mido.MetaMessage('end_of_track',time=480)]]))
    assert s.notes[0].key_off_s==1
    assert s.notes[0].sustain_end_s==1.5
    assert s.notes[1].key_off_s==s.duration_s
    assert len(s.warnings)==2

def test_waveform_keeps_impulse_and_fft_calibration():
    x=np.zeros((1000,2),np.float32);x[501]=[1,-.8]
    env=overview(x,10)
    assert max(env['max'])==1 and min(env['min'])==pytest.approx(-.8)
    sr=48000;n=4096;freq=sr*40/n
    signal=.5*np.sin(2*np.pi*freq*np.arange(n)/sr)
    hz,amp=fft_amplitude(signal,sr)
    assert hz[np.argmax(amp)]==pytest.approx(freq)
    assert amp.max()==pytest.approx(.5,rel=.001)
    a=analyze(np.zeros(n),sr)
    assert a['waveform']==[0]*256 and a['spectrum_db']==[-90]*128

def short_score():
    return Score('A4',1.,[dict(id='t0c0',name='Piano',source_channel=0,source_track=0,muted=False,solo=False)],
        [Note('n0','t0c0',69,100,0,.8,.8,'right')],[],[])

def cfg(score,rate=1,mode='both'):return dict(rate=rate,tracks=score.tracks,hand_mode=mode)

@pytest.mark.parametrize('rate',[.5,.75,1])
def test_real_fluidsynth_pitch_and_duration(rate):
    s=short_score();pcm=render(s,cfg(s,rate),48000)
    assert len(pcm)==round((1/rate+2)*48000)
    assert np.max(np.abs(pcm))>.01
    x=pcm[4800:4800+32768].mean(axis=1)
    freq,amp=fft_amplitude(x,48000)
    # Sampled piano contains harmonics; the A4 fundamental stays in the A4 band.
    region=(freq>420)&(freq<460)
    peak=freq[region][np.argmax(amp[region])]
    assert abs(peak-440)<3

def test_real_hands_filter_and_same_pitch_routes():
    s=short_score();s.notes.append(Note('n1','t0c0',69,90,.1,.2,.2,'left'))
    full=render(s,cfg(s),48000);right=render(s,cfg(s,mode='right'),48000)
    assert not np.allclose(full,right)
    # Releasing the short same-pitch left note must leave the long right note alive.
    assert np.sqrt(np.mean(full[20000:24000]**2))>.001
    unknown=replace(s,notes=[replace(n,hand='unassigned') for n in s.notes])
    assert np.max(np.abs(render(unknown,cfg(unknown,mode='left'),48000)))==0

def wait(c,j):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        result=c.get_job(j['job_id'])
        if result['done']:
            assert not result['error'],result
            return result
        time.sleep(.01)
    raise AssertionError('job timed out')

def test_jobs_generation_rollback_cancel_and_hands(tmp_path):
    c=Controller()
    try:
        wait(c,c.begin_load('demo:harmonics'));old=c.score
        bad=tmp_path/'bad.mid';bad.write_bytes(b'broken')
        job=c.begin_load(c.token_for_path(bad))
        while not c.get_job(job['job_id'])['done']:time.sleep(.01)
        assert c.score is old and c.phase=='paused'
        job=c.begin_load('demo:first-light');assert c.cancel_job(job['job_id'])
        assert c.score is old and c.get_job(job['job_id'])['cancelled']
        p=asyncio.run(c.preview_hands({'type':'pitch_split','pitch':65}))
        wait(c,c.apply_hands(p['preview_id'],{'n0':'left'}))
        assert c.score.notes[0].hand=='left'
        wait(c,c.undo_hands());assert [n.hand for n in c.score.notes]==[n.hand for n in old.notes]
        # A later task wins even when the previous queued work finishes late.
        j=c.begin_load('demo:first-light');last=c.begin_load('demo:harmonics');wait(c,last)
        assert c.get_job(j['job_id'])['cancelled'] and c.score.title=='泛音练习'
    finally:c.close()
    assert not any(t.name.startswith('pianoscope-') for t in __import__('threading').enumerate())

def test_loop_validation_and_volume(tmp_path):
    c=Controller()
    try:
        wait(c,c.begin_load('demo:harmonics'))
        with pytest.raises(ValueError):asyncio.run(c.set_loop(True,2,2.1))
        asyncio.run(c.set_loop(True,2,3))
        t=asyncio.run(c.seek(20));assert 2<=t['position_s']<3
        asyncio.run(c.stop());assert c.audio.position==0 and c.audio.loop['enabled']
        for value in (float('nan'),-1,2):
            with pytest.raises(ValueError):c.set_volume(value)
    finally:c.close()

def test_track_mute_solo_and_cc_expression_in_real_pcm():
    s=short_score();s.tracks.append(dict(id='t1c0',name='Second',source_channel=0,source_track=1,muted=False,solo=False))
    s.notes.append(Note('n1','t1c0',72,90,0,.8,.8,'left'))
    all_pcm=render(s,cfg(s),48000)
    tracks=[dict(t,muted=t['id']=='t1c0') for t in s.tracks]
    muted=render(s,dict(rate=1,tracks=tracks,hand_mode='both'),48000)
    solo=render(s,dict(rate=1,tracks=[dict(t,solo=t['id']=='t0c0') for t in s.tracks],hand_mode='both'),48000)
    assert np.allclose(muted,solo) and not np.allclose(muted,all_pcm)
    s.controls=[dict(time_s=0,source_channel=0,control=11,value=0)]
    assert np.max(np.abs(render(s,cfg(s),48000)))<1e-5

def test_voice_isolation_matches_sum_for_shared_pitch():
    s=short_score();s.tracks.append(dict(id='t1c0',name='Second',source_channel=0,source_track=1,muted=False,solo=False))
    s.notes.append(Note('n1','t1c0',69,90,.1,.2,.2,'left'))
    full=render(s,cfg(s),48000)
    separate=[]
    for tid in ('t0c0','t1c0'):
        separate.append(render(s,dict(rate=1,hand_mode='both',tracks=[dict(t,solo=t['id']==tid) for t in s.tracks]),48000))
    # Floating summation differences are bounded; a shared-channel note-off would diverge substantially.
    assert np.max(np.abs(full-separate[0]-separate[1]))<1e-5

@pytest.mark.parametrize('what',['tracks','events','notes'])
def test_input_count_limits(tmp_path,what):
    if what=='tracks':tracks=[[on(ch=i%9),off(ch=i%9)] for i in range(17)]
    elif what=='notes':tracks=[[on(v=1) for _ in range(50001)]]
    else:tracks=[[cc(7,100) for _ in range(200001)]]
    with pytest.raises(ScoreError):parse_midi(midi(tmp_path,tracks))

def test_cancelled_load_visible_immediately_and_no_late_publish():
    c=Controller()
    try:
        wait(c,c.begin_load('demo:harmonics'));old=c.score
        j=c.configure(.5,c.score.tracks,'both');start=time.monotonic();assert c.cancel_job(j['job_id'])
        assert c.get_job(j['job_id'])['cancelled'] and time.monotonic()-start<1
        time.sleep(.1)
        assert c.score is old and c.config['rate']==1
    finally:c.close()

def test_completed_jobs_do_not_retain_pcm_versions():
    c=Controller()
    try:
        for i in range(4):wait(c,c.begin_load('demo:harmonics'))
        assert all('future' not in j for j in c.jobs.values())
        assert c.audio.pcm.nbytes<192*1024*1024 and not c.audio.pcm.flags.writeable
    finally:c.close()

def test_all_sound_off_cuts_actual_release_voices(tmp_path):
    p=midi(tmp_path,[[on(),cc(120,0,t=480),mido.MetaMessage('end_of_track',time=480)]],type=0)
    s=parse_midi(p);pcm=render(s,cfg(s),48000)
    assert np.max(np.abs(pcm[:20000]))>.01
    # All-sound-off kills release voices too; ordinary note-off leaves a tail.
    assert np.max(np.abs(pcm[26000:33000]))<1e-7
