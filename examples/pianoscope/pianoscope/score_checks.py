"""Real AppCore P1 acceptance, using the shipped UI, binding and output device."""
import asyncio
from pianoscope.dev_paths import artifact_dir
import json
from importlib.metadata import version
from pathlib import Path
import resource
import shutil
import time


async def verify_score(view,c,args,report):
    from run import save_view
    root=Path(__file__).resolve().parents[1];checks=[]
    def check(name,condition,detail=None):
        checks.append(dict(name=name,passed=bool(condition),detail=detail));report['assertions']=checks
        if not condition:raise AssertionError(name+': '+str(detail))
    def js(code):return view.evaluate(code)
    async def call(code):return await view.evaluate_async(code)
    await asyncio.sleep(.3)
    await view.wait_until(lambda:js('window.PIANOSCOPE_READY===true && !!window.ScoreView'),timeout=20)
    await view.wait_until(lambda:js('!!PianoScope.score && !PianoScope.job'),timeout=30)
    report['viewport']=js('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})')
    report['versions']={p:version(p) for p in ('ultralight-py','verovio','CairoSVG','pypdf','fonttools','psutil')}
    report['renderer']='CPU' if args.cpu else 'GPU'
    check('actual audio output device',c.audio.ready,c.audio.error)
    await call('piano.play()')
    await asyncio.sleep(.1)
    before=c.get_transport();pcm=c.audio.pcm
    start=time.perf_counter()
    js("document.getElementById('viewScore').click();document.getElementById('rhythm').value='straight';document.getElementById('confirmDefaults').checked=true;document.getElementById('generateNotation').click()")
    await view.wait_until(lambda:js('!!ScoreView.preview && ScoreView.systems.length>0'),timeout=60)
    check('preview generation leaves real playback and PCM intact',c.audio.playing and c.generation==before['generation'] and c.audio.pcm is pcm)
    report['first_notation_seconds']=time.perf_counter()-start
    preview=js('ScoreView.preview');check('all current source notes in preview',preview['notes']==len(c.score.notes))
    check('preview has not replaced applied version',c.notation.applied is None)
    if args.cpu and args.width==800:
        await asyncio.sleep(.12);save_view(view,artifact_dir('screenshots')/'readable-regression-preview-800.png')
        js('ScoreView.openSettings()');await asyncio.sleep(.1);save_view(view,artifact_dir('screenshots')/'readable-regression-settings-800.png')
        js("document.getElementById('closeNotation').click()")
    js("document.getElementById('applyNotation').click()")
    await view.wait_until(lambda:js('!ScoreView.preview && !!ScoreView.applied'),timeout=5)
    revision=c.notation.applied['notation_revision'];check('applied same preview revision',revision==preview['notation_revision'])
    start=time.perf_counter();warm=c.begin_notation(preview['options'])
    await view.wait_until(lambda:c.get_notation_job(warm['job_id'])['done'],timeout=10)
    report['warm_notation_seconds']=time.perf_counter()-start
    check('warm immutable notation/layout cache',c.notation.jobs[warm['job_id']].get('cached') and c.get_notation()['notation_revision']==revision,report['warm_notation_seconds'])
    check('strike line confined to falling view',js("getComputedStyle(document.getElementById('strikeLine')).display==='none'"))
    check('real Canvas base image for every system',js('ScoreView.systems.every(s=>s.image.complete&&s.image.naturalWidth>0&&s.base.width>0)'))
    if args.cpu:
        report['canvas_diagnostics']=js("ScoreView.systems.filter(s=>s.baseReady).slice(0,2).map(s=>({crop:s.crop,scale:s.scale,canvas:{width:s.base.width,height:s.base.height},node:{top:s.node.getBoundingClientRect().top,height:s.node.getBoundingClientRect().height},base:{top:s.base.getBoundingClientRect().top,height:s.base.getBoundingClientRect().height},alpha:Array.from(s.base.getContext('2d').getImageData(0,0,s.base.width,s.base.height).data).filter((x,i)=>i%4===3&&x>0).length}))")
        check('rasterized staff pixels painted into Canvas',all(x['alpha']>100 and x['crop'][2]>100 for x in report['canvas_diagnostics']),report['canvas_diagnostics'])
    else:report['canvas_diagnostics']='GPU Canvas readback unsupported; raster pixels verified in CPU native report'
    if args.cpu:
        await asyncio.sleep(.15);save_view(view,artifact_dir('screenshots')/f'readable-regression-score-{args.width}.png')
    def snapshot_highlights():
        return js("(()=>{const t=Python.to_value(piano.get_transport());ScoreView.draw(t);const expected=[];for(const s of ScoreView.systems)for(const g of s.glyphs)if(g.source_display_spans.some(p=>t.active_note_ids.includes(p.source_note_id)&&p.start_s<=t.position_s&&t.position_s<p.end_s))expected.push(g.event_id);return {actual:ScoreView.highlights,expected,phase:t.phase,position:t.position_s}})()")
    h=snapshot_highlights();check('source-event chord/tie highlighter',h['phase']=='playing' and sorted(h['actual'])==sorted(h['expected']),h)
    await call('piano.pause()');await asyncio.sleep(.15)
    check('pause clears sounding notation',not js('ScoreView.highlights'))
    # All view operations preserve rate, loop, PCM generation and DAC epoch.
    await call('piano.play()');before=c.get_transport()
    js("document.getElementById('keyboardToggle').click();document.getElementById('keyboardToggle').click();document.getElementById('full').click();document.getElementById('focused').click();document.getElementById('viewRoll').click();document.getElementById('viewScore').click();document.getElementById('closeNotation').click();document.getElementById('sidebarToggle').click();document.getElementById('sidebarClose').click()")
    after=c.get_transport()
    check('view/keyboard/sidebar preserve audio clock state',after['phase']=='playing' and all(after[k]==before[k] for k in ('generation','clock_epoch','rate','loop')))
    js("document.getElementById('scoreViewport').dispatchEvent(new WheelEvent('wheel',{deltaY:200}));document.getElementById('scoreViewport').scrollTop=300")
    scroll=js("document.getElementById('scoreViewport').scrollTop")
    await asyncio.sleep(.3)
    check('manual browsing suspends follow without stopping playback',not js('ScoreView.following') and abs(js("document.getElementById('scoreViewport').scrollTop")-scroll)<1 and c.audio.playing)
    before=c.get_transport();js("document.getElementById('backToScore').click()")
    after=c.get_transport();check('restore follow preserves clock',js('ScoreView.following') and after['clock_epoch']==before['clock_epoch'])
    await call('piano.pause()')
    errors=[]
    for zoom in ('1','1.25','1.5'):
        js("document.getElementById('scoreZoom').value="+json.dumps(zoom)+";document.getElementById('scoreZoom').dispatchEvent(new Event('change'))")
        hit=js("(()=>{const s=ScoreView.systems[0],g=s.glyphs.find(g=>g.seek_s>.2&&g.pitch!==null);ScoreView.suspendFollow();document.getElementById('scoreViewport').scrollTop=s.node.offsetTop;const r=s.overlay.getBoundingClientRect(),scale=r.width/s.crop[2],x=r.left+(g.bbox[0]+g.bbox[2]/2-s.crop[0])*scale,y=r.top+(g.bbox[1]+g.bbox[3]/2-s.crop[1])*scale;const result=ScoreView.hit(s,x,y);s.overlay.dispatchEvent(new MouseEvent('click',{clientX:x,clientY:y}));return {result,expected:g.seek_s,error:Math.abs((x-r.left)/scale+s.crop[0]-(g.bbox[0]+g.bbox[2]/2))}})()")
        await asyncio.sleep(.2);errors.append(hit['error'])
        check('real glyph binding seek zoom '+zoom,abs(c.audio.position-hit['result']['time_s'])<1e-6 and abs(hit['result']['time_s']-hit['expected'])<1e-6,hit)
    check('high DPI zoom hit error <=1 CSS px',max(errors)<=1,errors)
    js("document.getElementById('scoreZoom').value='1';document.getElementById('scoreZoom').dispatchEvent(new Event('change'))")
    for kind in ('rest','measure'):
        result=js("""(()=>{const s=ScoreView.systems[0];ScoreView.suspendFollow();document.getElementById('scoreViewport').scrollTop=s.node.offsetTop;let x,y,expected;
        if(KIND==='rest'){const g=s.glyphs.find(g=>g.pitch===null);x=g.bbox[0]+g.bbox[2]/2;y=g.bbox[1]+g.bbox[3]/2;expected=g.seek_s}
        else{const m=s.measures[0];x=m.bbox[0]+m.bbox[2]-2;y=m.bbox[1]+m.bbox[3]/2;expected=m.start_s}
        const r=s.overlay.getBoundingClientRect(),scale=r.width/s.crop[2],cx=r.left+(x-s.crop[0])*scale,cy=r.top+(y-s.crop[1])*scale,hit=ScoreView.hit(s,cx,cy);s.overlay.dispatchEvent(new MouseEvent('click',{clientX:cx,clientY:cy}));return {hit,expected}})()""".replace('KIND',json.dumps(kind)))
        await asyncio.sleep(.12)
        check('native '+kind+' click seek',result['hit'] and abs(result['hit']['time_s']-result['expected'])<1e-8 and abs(c.audio.position-result['expected'])<1e-8,result)
    # Snapshot format exports use production transactions, no arbitrary path API.
    out=artifact_dir('samples')/'readable/legacy-regression';out.mkdir(parents=True,exist_ok=True)
    for fmt in ('pdf','musicxml'):
        target=c.notation.target(c.notation.applied['notation_id'],fmt,out/('first-light.'+fmt))
        job=await call('Python.to_value(piano.begin_score_export('+json.dumps(c.notation.applied['notation_id'])+','+json.dumps(fmt)+','+json.dumps(target['target_token'])+'))')
        await view.wait_until(lambda:c.get_notation_job(job['job_id'])['done'],timeout=10)
        check('atomic real '+fmt+' export',c.get_notation_job(job['job_id'])['phase']=='completed')
    shutil.copy(c.notation.applied['directory']/'document.json',out/'first-light.document.json')
    shutil.copy(c.notation.applied['directory']/'manifest.json',out/'first-light.layout.json')
    from . import dialogs
    original_dialog=dialogs.choose_score_path
    before=c.get_transport()
    try:
        dialogs.choose_score_path=lambda title,format:original_dialog(title,format,auto_cancel=True)
        check('native save dialog cancellation through binding',await call("piano.choose_score_export('pdf').then(Python.to_value)") is None)
    finally:dialogs.choose_score_path=original_dialog
    check('save cancellation keeps transport',c.audio.epoch==before['clock_epoch'])
    for fmt in ('pdf','musicxml'):
        js('ScoreView.exportCheck('+json.dumps(fmt)+')')
        text=js("document.getElementById('exportSummary').textContent")
        check('export check actual format '+fmt,('A4' in text)==(fmt=='pdf'),text)
        if args.cpu and args.width==800:
            await asyncio.sleep(.1);save_view(view,artifact_dir('screenshots')/f'readable-regression-export-{fmt}-800.png')
        js("document.getElementById('closeExport').click()")
    # Audition changes sound but do not invalidate notation or change export scope.
    for rate in (.5,.75,1):
        await call("PianoScope.waitJob(Python.to_value(piano.configure("+str(rate)+",PianoScope.score.tracks,'both')))")
        check('rate keeps notation '+str(rate),c.notation.summary(c.notation.applied)['state']=='applied' and c.notation.applied['notation_revision']==revision)
    await call("PianoScope.waitJob(Python.to_value(piano.configure(1,PianoScope.score.tracks,'left')))")
    check('single-hand audition leaves export source count',c.get_notation()['notes']==len(c.score.notes))
    await call('piano.seek(0)');await call('piano.play()');await asyncio.sleep(.12)
    h=snapshot_highlights();check('single-hand only highlights audible source events',sorted(h['actual'])==sorted(h['expected']),h)
    await call('piano.pause()')
    await call("PianoScope.waitJob(Python.to_value(piano.configure(1,PianoScope.score.tracks,'both')))")
    await call('piano.set_loop(true,0,0.5)');await call('piano.play()')
    positions=[];t0=time.perf_counter()
    while time.perf_counter()-t0<6.3:
        await asyncio.sleep(.04);positions.append(c.get_transport()['position_s'])
    wraps=sum(b<a for a,b in zip(positions,positions[1:]));check('at least ten DAC-clock notation loops',wraps>=10,wraps)
    await call('piano.set_loop(false,0,0.5)');await call('piano.stop()')
    if args.measure_seconds:
        await call('piano.play()');start=time.perf_counter();cpu=time.process_time();fps=[]
        while time.perf_counter()-start<args.measure_seconds:
            await asyncio.sleep(.5);fps.append(js('PianoScope.fps'))
        check('continuous score playback remains active',c.audio.playing)
        report['performance']=dict(duration_s=time.perf_counter()-start,cpu_percent=100*(time.process_time()-cpu)/(time.perf_counter()-start),fps_samples=fps,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,underruns=c.audio.underruns)
        check('user-confirmed FPS target >=30',bool(fps) and min(fps)>=30,dict(min=min(fps),mean=sum(fps)/len(fps),max=max(fps)))
    await call('piano.pause()')
    # Real preview cancellation keeps applied score and PCM.
    before=c.audio.pcm;old=c.notation.applied
    j=await call("Python.to_value(piano.begin_notation({confirm_defaults:true}))")
    check('cancel background notation',js('piano.cancel_notation_job('+json.dumps(j['job_id'])+')') is True)
    check('cancel preserves applied score and PCM',c.notation.applied is old and c.audio.pcm is before)
    # Wrong options / too-complex failure keeps current applied document.
    j=await call("Python.to_value(piano.begin_notation({pickup:'8',confirm_defaults:true}))")
    await view.wait_until(lambda:c.get_notation_job(j['job_id'])['done'],timeout=10)
    check('failure preserves old score',bool(c.get_notation_job(j['job_id'])['error']) and c.notation.applied is old)
    # Staleness due to actual hand reassignment (not synthetic revision numbers).
    p=await call("piano.preview_hands({type:'pitch_split',pitch:60}).then(Python.to_value)")
    await call('PianoScope.waitJob(Python.to_value(piano.apply_hands('+json.dumps(p['preview_id'])+',{})))')
    check('hand dependency marks applied notation stale',c.get_notation()['state']=='stale')
    check('stale score does not break original player',c.audio.pcm is not None and c.score is not None)
    # A real long note crosses both a source tempo change and a barline.
    token=c.token_for_path(root/'tests/fixtures/score-edge-phrase.mid')
    await call('PianoScope.waitJob(Python.to_value(piano.begin_load('+json.dumps(token)+')))')
    js("ScoreView.openSettings();document.getElementById('confirmDefaults').checked=true;document.getElementById('rhythm').value='triplets';document.getElementById('generateNotation').click()")
    await view.wait_until(lambda:js('!!ScoreView.preview&&ScoreView.preview.score_id===PianoScope.score.score_id&&ScoreView.display.preview_id===ScoreView.preview.preview_id'),timeout=30)
    js("document.getElementById('applyNotation').click()")
    await view.wait_until(lambda:js('!ScoreView.preview&&ScoreView.applied.score_id===PianoScope.score.score_id'),timeout=5)
    chain=[e for e in c.notation.applied['document']['events'] if e['pitch']==21]
    check('source tempo-map tie boundary',len(chain)==2 and abs(chain[0]['source_display_spans'][0]['end_s']-2.1)<1e-9 and abs(chain[1]['source_display_spans'][0]['start_s']-2.1)<1e-9,chain)
    await call('piano.seek(1)');await call('piano.play()')
    for rate in (.5,.75,1):
        await call("PianoScope.waitJob(Python.to_value(piano.configure("+str(rate)+",PianoScope.score.tracks,'both')))")
        check('long held note rate '+str(rate),c.audio.playing and c.get_notation()['state']=='applied' and any(n.pitch==21 and n.id in c.get_transport()['active_note_ids'] for n in c.score.notes))
    await call('piano.pause()')
    click=js("(()=>{const s=ScoreView.systems.find(s=>s.glyphs.some(g=>g.pitch===21&&g.seek_s>0)),g=s.glyphs.find(g=>g.pitch===21&&g.seek_s>0),r=s.overlay.getBoundingClientRect(),scale=r.width/s.crop[2],x=r.left+(g.bbox[0]+g.bbox[2]/2-s.crop[0])*scale,y=r.top+(g.bbox[1]+g.bbox[3]/2-s.crop[1])*scale;s.overlay.dispatchEvent(new MouseEvent('click',{clientX:x,clientY:y}));return g.seek_s})()")
    await asyncio.sleep(.15);check('later tie head binding seek',abs(c.audio.position-click)<1e-8 and abs(click-2.1)<1e-8,click)
    await call('piano.set_loop(true,1,3)');await call('piano.play()');await call('piano.seek(5)')
    t=c.get_transport();check('score seek preserves playing intent and loop clamp',t['phase']=='playing' and 1<=t['position_s']<3)
    await call('piano.pause()');await call('piano.set_loop(false,1,3)')
    # UI layout must remain operable at the actual viewport, including drawers.
    js("document.getElementById('viewRoll').click();document.getElementById('viewScore').click();document.getElementById('closeNotation').click()")
    report['layout']=js("(()=>{const v=document.getElementById('scoreViewport').getBoundingClientRect(),play=document.getElementById('play').getBoundingClientRect();return {score:{width:v.width,height:v.height,top:v.top,bottom:v.bottom},play_bottom:play.bottom,horizontal_overflow:document.documentElement.scrollWidth>innerWidth,main_scroll:document.querySelector('main').scrollHeight-document.querySelector('main').clientHeight}})()")
    check('viewport contains score and transport',report['layout']['score']['height']>=150 and report['layout']['play_bottom']<=report['viewport']['height'] and not report['layout']['horizontal_overflow'],report['layout'])
    check('no JavaScript runtime errors',not js('window.APP_ERRORS'),js('window.APP_ERRORS'))
    report['device']=c.audio.device;report['underruns']=c.audio.underruns;report['success']=True
