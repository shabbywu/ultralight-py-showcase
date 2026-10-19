"""Real AppCore regression for folder browsing, assignment, and source diagnostics."""
import asyncio
from pianoscope.dev_paths import artifact_dir,MIDI_ROOT
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

async def verify_library(view,controller,args,report):
    from run import save_view
    from .dialogs import choose_path
    from .notation import dependency
    root=Path(__file__).resolve().parents[1]
    checks=[];report['assertions']=checks
    def check(name,ok,detail=None):
        checks.append(dict(name=name,passed=bool(ok),detail=detail))
        if not ok:raise AssertionError(name+': '+str(detail))
    def js(code):return view.evaluate(code)
    async def call(code):return await view.evaluate_async(code)
    async def settled():await view.wait_until(lambda:js('PianoScope.score!==null&&PianoScope.job===null'),timeout=45)
    async def screenshot(name):
        await asyncio.sleep(.25)
        if args.cpu:save_view(view,artifact_dir('screenshots')/name)
    await view.wait_until(lambda:js('window.PIANOSCOPE_READY===true'),timeout=15)
    await settled()
    check('real output device',controller.audio.ready,controller.audio.device)
    # The directory picker is a real NSOpenPanel, cancellation preserves everything.
    pcm=controller.audio.pcm;before=controller.generation
    check('native folder picker cancellation',choose_path(auto_cancel=True,folder=True) is None)
    await call('piano.play()');await asyncio.sleep(.2)
    with tempfile.TemporaryDirectory(prefix='PianoScope 曲库 ') as folder:
        path=Path(folder)
        for i in range(24):shutil.copyfile(root/'tests/fixtures/cross-hands.mid',path/f'练习 {i:02d}.MID')
        result=await call('piano.open_midi_folder('+json.dumps(folder)+').then(Python.to_value)')
        js('PianoScope.setLibrary('+json.dumps(result)+')')
        check('folder lists all 24 opaque entries',len(result['songs'])==24 and js("document.querySelectorAll('#librarySongs button').length===24"))
        check('folder browsing preserves DAC playback and PCM',controller.audio.pcm is pcm and controller.generation==before and controller.audio.playing)
        js("document.getElementById('sidebarToggle').click();document.getElementById('songSearch').value='23';document.getElementById('songSearch').dispatchEvent(new Event('input'))")
        check('song search filters filenames',js("document.querySelectorAll('#librarySongs button').length===1 && document.querySelector('#librarySongs button').textContent==='练习 23'"))
        js("document.querySelector('#librarySongs button').click()")
        await view.wait_until(lambda:controller.loaded_source==result['songs'][-1]['file_token'] and js('PianoScope.score.source_token==='+json.dumps(result['songs'][-1]['file_token'])),timeout=30)
        check('entry beyond old 16-token limit loads via binding',controller.loaded_source==result['songs'][23]['file_token'])
        check('list survives song refresh',js("document.querySelectorAll('#librarySongs button').length===1 && document.querySelector('#librarySongs .active')!==null"))
        js("document.getElementById('songSearch').value='';document.getElementById('songSearch').dispatchEvent(new Event('input'));document.getElementById('sidebarToggle').click()")
        await screenshot('library-many-800.png')
        js("document.getElementById('settings').click()")
        await asyncio.sleep(.15)
        check('track assignment hides pitch split',js("!document.getElementById('editor').hidden && document.getElementById('splitField').hidden && !document.getElementById('trackSettings').hidden"))
        await screenshot('hands-tracks-800.png')
        js("document.getElementById('rule').value='pitch_split';document.getElementById('rule').dispatchEvent(new Event('change'));document.getElementById('preview').click();document.getElementById('split').value='61';document.getElementById('split').dispatchEvent(new Event('change'))")
        await asyncio.sleep(.2)
        check('in-flight hand preview cannot revive changed rule',js("document.getElementById('applyHands').disabled"))
        js("document.getElementById('split').value='60';document.getElementById('split').dispatchEvent(new Event('change'));document.getElementById('preview').click()")
        await view.wait_until(lambda:js("!document.getElementById('applyHands').disabled"),timeout=5)
        check('pitch assignment shows relevant controls only',js("!document.getElementById('splitField').hidden && document.getElementById('trackSettings').hidden && document.getElementById('splitSummary').textContent.includes('左手')"))
        check('assignment actions fit 800x600',js("(()=>{const r=document.getElementById('applyHands').getBoundingClientRect();return r.bottom<=innerHeight&&r.right<=innerWidth})()"))
        check('assignment preview is not commit',all(n.hand=='unassigned' for n in controller.score.notes))
        await screenshot('hands-pitch-800.png')
        js("document.getElementById('split').value='61';document.getElementById('split').dispatchEvent(new Event('change'))")
        check('changed split invalidates previous preview',js("document.getElementById('applyHands').disabled && document.getElementById('previewHint').hidden"))
        js("document.getElementById('preview').click()")
        await view.wait_until(lambda:js("!document.getElementById('applyHands').disabled"),timeout=5)
        js("document.getElementById('applyHands').click()")
        await view.wait_until(lambda:controller.score.hand_assignment['source']=='manual' and js('PianoScope.job===null && !document.getElementById("tracks").disabled && PianoScope.score.revision==='+str(controller.score.revision)),timeout=30)
        check('pitch assignment applies',all(n.hand==('left' if n.pitch<61 else 'right') for n in controller.score.notes))
        js("document.getElementById('tracks').click()")
        check('audition track editor remains available',js("!document.getElementById('trackSettings').hidden && document.querySelector('.track-row .muted').offsetParent!==null"))
        js("document.getElementById('closeEditor').click()")
    # Keep an actual applied score while both complex sources fail.
    await call("PianoScope.waitJob(Python.to_value(piano.begin_load('demo:first-light')))")
    js("ScoreView.openSettings();document.getElementById('confirmDefaults').checked=true;document.getElementById('generateNotation').click()")
    await view.wait_until(lambda:js('ScoreView.preview!==null'),timeout=30)
    await call('ScoreView.apply()');applied=controller.notation.applied
    report['custom_midis']=[]
    library=await call('piano.open_midi_folder('+json.dumps(str(MIDI_ROOT))+').then(Python.to_value)')
    js('PianoScope.setLibrary('+json.dumps(library)+')')
    if js("document.getElementById('sidebar').hidden"):js("document.getElementById('sidebarToggle').click()")
    await screenshot('library-800.png')
    if js("!document.getElementById('sidebar').hidden"):js("document.getElementById('sidebarClose').click()")
    for filename in ('Rush E.mid','Hans Zimmer - First Step - Interstellar.mid'):
        path=MIDI_ROOT/filename
        if not path.exists():raise FileNotFoundError('Native reproduction requires local user MIDI: '+filename)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        token={'file_token':next(item['file_token'] for item in library['songs'] if item['filename']==filename)}
        await call('PianoScope.waitJob(Python.to_value(piano.begin_load('+json.dumps(token)+')))')
        p=await call("piano.preview_hands({type:'pitch_split',pitch:60}).then(Python.to_value)")
        await call('PianoScope.waitJob(Python.to_value(piano.apply_hands('+json.dumps(p['preview_id'])+',{})))')
        pcm=controller.audio.pcm;source=controller.score;dep=dependency(source)
        js("ScoreView.openSettings();document.getElementById('rhythm').value='straight';document.getElementById('confirmDefaults').checked=true;document.getElementById('generateNotation').click()")
        await view.wait_until(lambda:js("ScoreView.job===null && !document.getElementById('notationSettings').hidden && document.querySelector('#notationIssues button')!==null"),timeout=30)
        state=next(j for j in reversed(list(controller.notation.jobs.values())) if j['kind']=='preview')
        error=state['error'];issues=error['issues']
        check(filename+' fails with real source diagnostics',error['code']=='NOTATION_TOO_COMPLEX' and bool(issues) and all(i.get('source_event') for i in issues),len(issues))
        check(filename+' failure preserves PCM/source/old score',controller.audio.pcm is pcm and controller.score is source and dependency(source)==dep and controller.notation.applied is applied)
        check(filename+' conditional staff fields hide irrelevant controls',js("document.getElementById('staffSplitField').hidden && Array.from(document.querySelectorAll('.notation-track select')).every(s=>s.hidden)"))
        check(filename+' previous file settings do not omit tracks',js("Array.from(document.querySelectorAll('#notationTracks input')).every(i=>i.checked)"))
        if filename.startswith('Hans'):await screenshot('interstellar-issues-800.png')
        else:await screenshot('rush-e-issues-800.png')
        target=issues[0]['start_s']
        js("document.querySelector('#notationIssues button').click()")
        await view.wait_until(lambda:controller.phase=='paused' and abs(controller.audio.position-target)<1e-5,timeout=5)
        check(filename+' issue click uses real pause/seek',not controller.audio.playing and not js('ScoreView.active') and abs(controller.audio.position-target)<1e-5)
        check(filename+' original file unchanged',hashlib.sha256(path.read_bytes()).hexdigest()==digest)
        report['custom_midis'].append(dict(filename=filename,sha256=digest,notes=len(source.notes),issues=len(issues),reasons=dict(Counter(i['reason'] for i in issues)),first_issue=issues[0]))
    check('no native JavaScript errors',js('window.APP_ERRORS.length===0'),js('window.APP_ERRORS'))
    report['viewport']=js('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})')
    report['success']=True
