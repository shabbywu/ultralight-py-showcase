"""Real worker/synth transactions with no device requirement; native tests are separate."""
from pathlib import Path
import asyncio
import hashlib
import os
import time
import pytest
from pianoscope.audio import Audio
from pianoscope.v2_session import Controller

FIXTURES=Path(__file__).parent/'fixtures/v2'


def wait(c,j,phase='candidate_ready'):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        state=c.get_job(j['job_id'])
        if state['phase']==phase or state['done']:
            return state
        time.sleep(.01)
    raise AssertionError('job timed out')


def layout(c):
    j=c.begin_score_layout(c.plan.document.revision)
    assert wait(c,j,'layout_ready')['phase']=='layout_ready',c.get_job(j['job_id'])
    candidate=c.get_layout_candidate(j['job_id'])
    c.publish_score_layout(j['job_id'],candidate['source_revision'],candidate['layout_revision'])
    return j


def load(c,path,engrave=True):
    j=c.begin_score_load(c.token_for_path(path))
    state=wait(c,j)
    assert state['phase']=='candidate_ready',state
    candidate=c.get_candidate(j['job_id'])
    asyncio.run(c.publish_score_load(j['job_id'],candidate['source_sha256']))
    if engrave:layout(c)
    return j


@pytest.fixture
def controller(tmp_path,monkeypatch):
    monkeypatch.setenv('PIANOSCOPE_TMP_DIR',str(tmp_path/'work'))
    c=Controller(audio=Audio())
    yield c
    c.close()


def test_candidate_cancel_failure_and_late_results_keep_old_pcm(controller,tmp_path):
    c=controller
    load(c,FIXTURES/'temporal.musicxml')
    c.audio.position=3.25
    old=(c.plan,c.audio.pcm,c.audio.position,c.audio.epoch)
    b=c.begin_score_load(c.token_for_path(FIXTURES/'printed.musicxml'))
    assert c.audio.pcm is old[1] and c.audio.position==old[2] and c.audio.epoch==old[3]
    assert wait(c,b)['phase']=='candidate_ready'
    c.cancel_job(b['job_id'])
    assert c.plan is old[0] and c.audio.pcm is old[1] and c.audio.position==old[2]
    with pytest.raises(ValueError,match='过期'):
        asyncio.run(c.publish_score_load(b['job_id'],'anything'))
    bad=tmp_path/'bad.musicxml';bad.write_bytes(b'<not-a-score/>')
    fail=c.begin_score_load(c.token_for_path(bad))
    assert wait(c,fail)['phase']=='failed'
    assert c.plan is old[0] and c.audio.pcm is old[1] and c.audio.position==3.25
    loser=c.begin_score_load(c.token_for_path(FIXTURES/'printed.musicxml'))
    winner=c.begin_score_load(c.token_for_path(FIXTURES/'temporal.musicxml'))
    assert wait(c,winner)['phase']=='candidate_ready'
    assert c.get_job(loser['job_id'])['cancelled']
    candidate=c.get_candidate(winner['job_id'])
    asyncio.run(c.publish_score_load(winner['job_id'],candidate['source_sha256']))
    assert c.audio.position==0 and not c.audio.playing
    assert all('future' not in j for j in c.jobs.values() if j['done'])


def test_confirmation_binds_immutable_source_and_expires(controller,tmp_path):
    c=controller
    path=tmp_path/'missing.musicxml'
    path.write_bytes((FIXTURES/'temporal.musicxml').read_bytes().replace(b' tempo="120"',b''))
    original=path.read_bytes()
    j=c.begin_score_load(c.token_for_path(path))
    state=wait(c,j,'needs_confirmation')
    assert 'default_tempo' in state['required']
    with pytest.raises(ValueError,match='过期'):
        c.confirm_score_load(j['job_id'],'wrong',{'default_tempo':120})
    # A changed disk file cannot substitute for the source the user confirmed.
    path.write_bytes(b'changed after confirmation')
    next_job=c.confirm_score_load(j['job_id'],state['source_sha256'],{'default_tempo':120})
    assert wait(c,next_job)['phase']=='candidate_ready'
    candidate=c.get_candidate(next_job['job_id'])
    asyncio.run(c.publish_score_load(next_job['job_id'],candidate['source_sha256']))
    assert c.plan.document.source.original_bytes==original
    with pytest.raises(ValueError,match='过期'):
        c.confirm_score_load(j['job_id'],state['source_sha256'],{'default_tempo':120})


def test_rate_scope_and_hands_do_not_change_source_or_layout(controller):
    c=controller;load(c,FIXTURES/'temporal.musicxml')
    source_hash=c.plan.document.source.sha256
    layout=c.get_document()['layout_revision']
    base_midi=c.plan.midi_bytes
    with pytest.raises(ValueError,match='确认'):
        asyncio.run(c.configure({'hand_mode':'left'}))
    asyncio.run(c.configure({'staff_ids':['P1:2'],'rate':.75}))
    assert len(c.config['allowed_note_ids'])==6
    assignments={e.id:'left' if e.staff_id=='P1:2' else 'right' for e in c.plan.document.elements if e.pitch is not None}
    preview=c.preview_hands(assignments)
    assert c.get_document()['hand_status']=='unassigned'
    asyncio.run(c.apply_hands(preview['preview_id']))
    assert c.get_document()['hand_status']=='confirmed'
    assert c.plan.document.source.sha256==source_hash
    assert c.get_document()['layout_revision']==layout
    assert c.plan.midi_bytes==base_midi
    asyncio.run(c.undo_hands())
    assert c.get_document()['hand_status']=='unassigned'
    asyncio.run(c.configure({'staff_ids':[],'hand_mode':'both'}))
    assert float(abs(c.audio.pcm).max())==0


def test_export_snapshot_cancel_overwrite_and_atomic_failure(controller,tmp_path,monkeypatch):
    c=controller;load(c,FIXTURES/'temporal.musicxml')
    target=tmp_path/'copy.musicxml'
    target.write_bytes(b'old target')
    monkeypatch.setattr('pianoscope.v2_session.choose_score_path',lambda *a,**k:target)
    chosen=c.choose_export(c.plan.document.revision,'source')
    expected=c.plan.document.source.original_bytes
    j=c.begin_export(chosen['snapshot_id'],'source',chosen['target_token'])
    assert wait(c,j,'completed')['phase']=='completed'
    assert target.read_bytes()==expected
    c.cancel_job(j['job_id'])
    assert c.get_job(j['job_id'])['phase']=='completed'
    chosen=c.choose_export(c.plan.document.revision,'source')
    def broken_replace(*args):
        raise OSError('disk failure before atomic replace')
    monkeypatch.setattr('pianoscope.v2_session.os.replace',broken_replace)
    j=c.begin_export(chosen['snapshot_id'],'source',chosen['target_token'])
    assert wait(c,j,'failed')['phase']=='failed'
    assert target.read_bytes()==expected
    assert not list(tmp_path.glob('.pianoscope-*'))


def test_export_token_expires_on_change_but_started_snapshot_completes(controller,tmp_path,monkeypatch):
    c=controller;load(c,FIXTURES/'temporal.musicxml')
    target=tmp_path/'a.mid'
    monkeypatch.setattr('pianoscope.v2_session.choose_score_path',lambda *a,**k:target)
    stale=c.choose_export(c.plan.document.revision,'midi')
    load(c,FIXTURES/'printed.musicxml')
    with pytest.raises(ValueError,match='过期'):
        c.begin_export(stale['snapshot_id'],'midi',stale['target_token'])
    chosen=c.choose_export(c.plan.document.revision,'midi')
    expected=c.plan.midi_bytes
    job=c.begin_export(chosen['snapshot_id'],'midi',chosen['target_token'])
    load(c,FIXTURES/'temporal.musicxml')
    assert wait(c,job,'completed')['phase']=='completed'
    assert target.read_bytes()==expected


def test_folder_list_is_bounded_nonrecursive_and_keeps_song(controller,tmp_path):
    c=controller;load(c,FIXTURES/'temporal.musicxml')
    old=c.audio.pcm
    folder=tmp_path/'library';folder.mkdir()
    (folder/'UPPER.MUSICXML').write_bytes(b'not parsed during scan')
    (folder/'ignored.mid').write_bytes(b'MThd')
    (folder/'sub').mkdir();(folder/'sub/hidden.xml').write_bytes(b'x')
    library=asyncio.run(c.open_score_folder(folder))
    assert [s['name'] for s in library['songs']]==['UPPER.MUSICXML']
    assert c.audio.pcm is old
    for i in range(1000):(folder/f'{i}.xml').touch()
    with pytest.raises(ValueError,match='1,000'):
        asyncio.run(c.open_score_folder(folder))
    assert c.get_score_library()==library


@pytest.mark.parametrize('attribute,child,count,visible',[(' print-object="no"','',20,False),('','<cue/>',19,True)])
def test_actual_worker_distinguishes_hidden_and_cue_notes(controller,tmp_path,attribute,child,count,visible):
    path=tmp_path/'special.musicxml'
    path.write_bytes((FIXTURES/'temporal.musicxml').read_bytes().replace(b'<note id="pickup-g">',f'<note id="pickup-g"{attribute}>{child}'.encode(),1))
    load(controller,path)
    assert len(controller.plan.instances)==count
    ids={g['element_id'] for p in controller.active['data']['manifest']['pages'] for g in p['glyphs']}
    assert ('pickup-g' in ids)==visible
    assert controller.plan.document.source.original_bytes==path.read_bytes()


@pytest.mark.parametrize('kind',['voices','five','seven','unicode','c-clef'])
def test_profile_cases_have_real_geometry(controller,tmp_path,kind):
    from test_v2_profile import xml,note
    if kind in ('five','seven'):
        count=5 if kind=='five' else 7
        tm=f'<time-modification><actual-notes>{count}</actual-notes><normal-notes>4</normal-notes></time-modification>'
        text=xml(''.join(note('t'+str(i),duration=4,extra=tm) for i in range(count)),divisions=count)
    elif kind=='voices':
        text=xml(note('lead',duration=48,type='whole',voice='melody')+'<backup><duration>48</duration></backup>'+note('bass',octave=3,duration=48,type='whole',staff=2,voice='low'))
        count=2
    elif kind=='unicode':
        text=xml(note('音符_甲',duration=48,type='whole'));count=1
    else:
        text=xml(note('c-clef-note',duration=48,type='whole'),clef='C');count=1
    path=tmp_path/'profile.musicxml';path.write_text(text)
    load(controller,path)
    assert len(controller.plan.instances)==count
    glyphs=[g for p in controller.active['data']['manifest']['pages'] for g in p['glyphs']]
    source_ids={e.id for e in controller.plan.document.elements}
    assert source_ids<={g['element_id'] for g in glyphs}
    if kind=='voices':
        assert {e.voice_id for e in controller.plan.document.elements}=={'melody','low'}


def test_cancel_export_before_commit_keeps_target_and_cleans_temporary(controller,tmp_path,monkeypatch):
    import threading
    c=controller;load(c,FIXTURES/'temporal.musicxml')
    target=tmp_path/'preserved.mid';target.write_bytes(b'original target')
    monkeypatch.setattr('pianoscope.v2_session.choose_score_path',lambda *a,**k:target)
    at_sync=threading.Event();release=threading.Event()
    original_sync=os.fsync
    def blocked_sync(fd):
        original_sync(fd);at_sync.set();assert release.wait(5)
    monkeypatch.setattr('pianoscope.v2_session.os.fsync',blocked_sync)
    choice=c.choose_export(c.plan.document.revision,'midi')
    job=c.begin_export(choice['snapshot_id'],'midi',choice['target_token'])
    try:
        assert at_sync.wait(5)
        assert c.cancel_job(job['job_id'])
        assert target.read_bytes()==b'original target'
    finally:release.set()
    c.pool.shutdown(wait=True)
    assert c.get_job(job['job_id'])['phase']=='cancelled'
    assert target.read_bytes()==b'original target'
    assert not list(tmp_path.glob('.pianoscope-*'))


def test_actual_workers_are_deterministic_and_reject_thirty_three_pages(tmp_path):
    import json
    from pianoscope.score_process import run_preparation
    from pianoscope.score_source import ScoreInputError
    from test_v2_profile import xml,note
    results=[]
    for name in ('one','two'):
        folder=tmp_path/name;folder.mkdir()
        (folder/'request.json').write_text(json.dumps(dict(source_path=str((FIXTURES/'temporal.musicxml').resolve()))))
        result=run_preparation(folder)
        results.append((result['manifest'],result['instances'],result['midi_event_map'],(folder/'score.mid').read_bytes()))
    assert results[0]==results[1]
    text=xml(note('start',duration=48,type='whole'))
    extra=''.join('<measure id="page'+str(i)+'" number="'+str(i+1)+'"><print new-page="yes"/>'+note('np'+str(i),duration=48,type='whole')+'</measure>' for i in range(1,33))
    path=tmp_path/'too-many-pages.musicxml';path.write_text(text.replace('</part>',extra+'</part>'))
    folder=tmp_path/'overflow';folder.mkdir();(folder/'request.json').write_text(json.dumps(dict(source_path=str(path))))
    with pytest.raises(ScoreInputError,match='32 页'):run_preparation(folder)
    assert not (folder/'score.pdf').exists()


def test_roll_load_skips_worker_and_pdf_export_is_independent(controller,tmp_path,monkeypatch):
    c=controller
    real=c._prepare_layout
    calls=[]
    def recorded(*args):
        calls.append(True)
        return real(*args)
    monkeypatch.setattr(c,'_prepare_layout',recorded)
    load(c,FIXTURES/'expressions.musicxml',engrave=False)
    assert not calls and not c.get_document()['layout_ready']
    assert not calls and c.get_document()['pages']==0
    assert not list(c.active['folder'].glob('*.png')) and not list(c.active['folder'].glob('*.pdf'))
    pcm,epoch,plan=c.audio.pcm,c.audio.epoch,c.plan
    target=tmp_path/'lazy.pdf'
    monkeypatch.setattr('pianoscope.v2_session.choose_score_path',lambda *a,**k:target)
    chosen=c.choose_export(c.plan.document.revision,'pdf')
    job=c.begin_export(chosen['snapshot_id'],'pdf',chosen['target_token'])
    assert wait(c,job,'completed')['phase']=='completed',c.get_job(job['job_id'])
    from pypdf import PdfReader
    assert len(PdfReader(target).pages)>0 and len(calls)==1
    assert c.plan is plan and c.audio.pcm is pcm and c.audio.epoch==epoch and not c.get_document()['layout_ready']
    layout(c)
    assert len(calls)==2 and c.get_document()['layout_ready']
    assert c.plan is plan and c.audio.pcm is pcm and c.audio.epoch==epoch
    assert c.begin_score_layout(plan.document.revision)['ready']


def test_lazy_layout_cancel_stale_and_failure_preserve_published_audio(controller,monkeypatch):
    c=controller;load(c,FIXTURES/'temporal.musicxml',engrave=False)
    pcm,epoch=c.audio.pcm,c.audio.epoch
    j=c.begin_score_layout(c.plan.document.revision)
    assert wait(c,j,'layout_ready')['phase']=='layout_ready'
    candidate=c.get_layout_candidate(j['job_id'])
    c.cancel_job(j['job_id'])
    with pytest.raises(ValueError,match='过期'):c.publish_score_layout(j['job_id'],candidate['source_revision'],candidate['layout_revision'])
    assert c.audio.pcm is pcm and c.audio.epoch==epoch and not c.get_document()['layout_ready']
    j=c.begin_score_layout(c.plan.document.revision)
    assert wait(c,j,'layout_ready')['phase']=='layout_ready'
    candidate=c.get_layout_candidate(j['job_id'])
    load(c,FIXTURES/'printed.musicxml',engrave=False)
    with pytest.raises(ValueError,match='过期'):c.publish_score_layout(j['job_id'],candidate['source_revision'],candidate['layout_revision'])
    pcm,epoch=c.audio.pcm,c.audio.epoch
    def failed(*args):raise ValueError('native layout failure')
    monkeypatch.setattr(c,'_prepare_layout',failed)
    j=c.begin_score_layout(c.plan.document.revision)
    assert wait(c,j,'layout_ready')['phase']=='failed'
    assert c.audio.pcm is pcm and c.audio.epoch==epoch and not c.get_document()['layout_ready']


def test_practice_settings_reopen_preserves_scope_labels_and_undo_mode(controller):
    c=controller;load(c,FIXTURES/'temporal.musicxml')
    original=(c.plan.document.source.sha256,c.get_document()['layout_revision'],c.plan.midi_bytes)
    state=c.get_practice_settings()
    assert [s['name'] for s in state['staves']]==['上谱表','下谱表']
    assert state['staff_ids']==['P1:1','P1:2'] and not state['can_undo']
    asyncio.run(c.configure({'staff_ids':[],'voice_ids':['P1:2']}))
    state=c.get_practice_settings()
    assert state['staff_ids']==[] and state['voice_ids']==['P1:2']
    asyncio.run(c.configure({'staff_ids':['P1:2']}))
    labels={e.id:'left' if e.staff_id=='P1:2' else 'right' for e in c.plan.document.elements if e.pitch is not None}
    preview=c.preview_hands(labels)
    assert c.get_practice_settings()['hand_status']=='unassigned'
    asyncio.run(c.apply_hands(preview['preview_id']))
    state=c.get_practice_settings()
    assert [s['hand'] for s in state['staves']]==['right','left'] and state['can_undo']
    asyncio.run(c.configure({'hand_mode':'left'}))
    assert c.get_transport()['hand_mode']=='left'
    asyncio.run(c.undo_hands())
    state=c.get_practice_settings()
    assert state['hand_status']=='unassigned' and state['hand_mode']=='both' and not state['can_undo']
    assert state['staff_ids']==['P1:2'] and state['voice_ids']==['P1:2']
    assert (c.plan.document.source.sha256,c.get_document()['layout_revision'],c.plan.midi_bytes)==original


def test_practice_state_preserves_mixed_per_note_labels(controller):
    c=controller;load(c,FIXTURES/'temporal.musicxml')
    upper=[e for e in c.plan.document.elements if e.pitch is not None and e.staff_id=='P1:1']
    assignments={upper[0].id:'left',upper[1].id:'right'}
    p=c.preview_hands(assignments);asyncio.run(c.apply_hands(p['preview_id']))
    state=c.get_practice_settings()
    assert state['staves'][0]['hand']=='mixed'
    pcm=c.audio.pcm
    lower={e.id:'left' for e in c.plan.document.elements if e.pitch is not None and e.staff_id=='P1:2'}
    p=c.preview_hands(lower)
    assert c.audio.pcm is pcm and c.hands==assignments
    asyncio.run(c.apply_hands(p['preview_id']))
    assert all(c.hands[k]==v for k,v in assignments.items())
    assert c.get_practice_settings()['staves'][0]['hand']=='mixed'
