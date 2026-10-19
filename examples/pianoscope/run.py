#!/usr/bin/env python3
"""PianoScope AppCore entry point; no server or browser process."""
import argparse
import asyncio
from pianoscope.dev_paths import artifact_dir
from importlib.metadata import version
import json
import logging
import platform
from pathlib import Path
import resource
import struct
import tempfile
import time
import traceback
import zlib

from pianoscope.session import Controller
from pianoscope.bridge import register
from pianoscope.dialogs import before_window_close

ROOT=Path(__file__).resolve().parent
CAPTURE_PREFIX=''

def save_view(view,path):
    img=view.copy_pixels().to_rgba();stride=img.width*4
    raw=b''.join(b'\0'+img.data[y*stride:(y+1)*stride] for y in range(img.height))
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    path=Path(path);path=path.with_name(CAPTURE_PREFIX+path.name);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',img.width,img.height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))

async def verify(view,controller,args,report):
    await view.wait_until(lambda:view.evaluate('window.PIANOSCOPE_READY === true'),timeout=15)
    await view.wait_until(lambda:view.evaluate('PianoScope.score !== null && PianoScope.job === null'),timeout=45)
    checks=[]
    def check(name,condition,detail=None):
        checks.append(dict(name=name,passed=bool(condition),detail=detail))
        report['assertions']=checks
        if not condition:raise AssertionError(name+': '+str(detail))
    def js(expression):return view.evaluate(expression)
    async def call(expression):return await view.evaluate_async(expression)
    check('bridge read-only session',js('piano.session.ready === true && piano.session.score_id === PianoScope.score.score_id'))
    check('session properties reject writes',js("(()=>{const phase=piano.session.phase;try{piano.session.phase='closed'}catch(e){}return piano.session.phase===phase})()"))
    check('demo trusted hands',js("PianoScope.notes.some(n=>n.hand==='left') && PianoScope.notes.some(n=>n.hand==='right')"))
    check('real SoundFont PCM',float(abs(controller.audio.pcm).max())>.001)
    report['pcm_peak']=float(abs(controller.audio.pcm).max());report['prepare_seconds']=controller.prepare_seconds
    geometry=[]
    for mode in ('full','focused'):
        for width in (1000,1280,1440):
            result=js(f'PianoScope.geometry({json.dumps(mode)},{width})');geometry.append(dict(mode=mode,width=width,**result))
            check(f'geometry {mode} {width}',result['error']<=1,result)
            if mode=='full':check('88=52+36',result['keys']==88 and result['whites']==52 and result['blacks']==36)
    report['geometry']=geometry
    t=await call('piano.pause().then(Python.to_value)');check('pause clears active keys',t['phase']=='paused' and not t['active_note_ids'])
    t=await call('piano.seek(3.25).then(Python.to_value)');check('seek source seconds',abs(t['position_s']-3.25)<1e-6)
    t=await call('piano.set_loop(true,2,2.5).then(Python.to_value)');check('loop clamps seek',2<=t['position_s']<2.5)
    t=await call('piano.stop().then(Python.to_value)');check('stop keeps loop',t['position_s']==0 and t['loop']['enabled'])
    await call('piano.set_loop(false,2,2.5)')
    await call("PianoScope.waitJob(Python.to_value(piano.configure(0.5,PianoScope.score.tracks,'both')))")
    check('rate rebuilt PCM',controller.config['rate']==.5 and len(controller.audio.pcm)==round((controller.score.duration_s/.5+2)*controller.audio.sample_rate))
    await call("PianoScope.waitJob(Python.to_value(piano.configure(1,PianoScope.score.tracks,'left')))")
    check('single hand changes PCM',controller.config['hand_mode']=='left')
    p=await call("piano.preview_hands({type:'pitch_split',pitch:60}).then(Python.to_value)")
    check('preview does not commit',controller.score.hand_assignment['source']=='bundled')
    await call('PianoScope.waitJob(Python.to_value(piano.apply_hands('+json.dumps(p['preview_id'])+",{n0:'right'})))")
    check('explicit note override',controller.score.notes[0].hand=='right')
    await call('PianoScope.waitJob(Python.to_value(piano.undo_hands()))')
    check('undo restores bundled note',controller.score.notes[0].hand=='left')
    await call("PianoScope.waitJob(Python.to_value(piano.configure(1,PianoScope.score.tracks,'both')))")
    from pianoscope.native_checks import interactions
    await interactions(view,controller,ROOT,check)
    if args.audio_test:
        report['audio_device']=controller.audio.device
        check('actual output device available',controller.audio.ready,controller.audio.error)
        await call('piano.set_loop(true,0,0.5)')
        t=await call('piano.play().then(Python.to_value)');check('JS starts actual output',t['phase']=='playing' and t['audio_ready'])
        await asyncio.sleep(.15)
        before=js('Python.to_value(piano.get_transport())')
        js("document.getElementById('sidebarToggle').click();document.getElementById('sidebarToggle').click()")
        after=js('Python.to_value(piano.get_transport())')
        check('sidecar toggle preserves actual playback',after['phase']=='playing' and all(after[k]==before[k] for k in ('generation','clock_epoch','rate','loop')))
        revision=controller.score.revision
        js("document.getElementById('tracks').click();document.getElementById('applyTracks').click()")
        await view.wait_until(lambda:controller.score.revision>revision and js('PianoScope.job===null'),timeout=15)
        check('track configuration preserves playing intent',controller.audio.playing and controller.phase=='playing')
        js("(()=>{const c=document.getElementById('overview'),r=c.getBoundingClientRect();c.dispatchEvent(new MouseEvent('mousedown',{clientX:r.left+1,clientY:r.top+20,bubbles:true}));document.dispatchEvent(new MouseEvent('mousemove',{clientX:r.left+200,clientY:r.top+20,bubbles:true}));document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))})()")
        await view.wait_until(lambda:controller.audio.playing and js('!PianoScope.interacting'),timeout=5)
        check('invalid loop drag restores playing intent and valid bounds',controller.audio.loop['a_s']==0 and controller.audio.loop['b_s']==.5)
        before=js('Python.to_value(piano.get_transport())')
        for _ in range(20):js("PianoScope.setMode(PianoScope.geometry('full',1000).keys===88 ? 'full':'focused');PianoScope.setMode('focused')")
        after=js('Python.to_value(piano.get_transport())')
        check('view switch preserves playing rate and loop',after['phase']=='playing' and after['rate']==before['rate'] and after['loop']==before['loop'])
        start=time.perf_counter();cpu=time.process_time();positions=[]
        seconds=5.3
        while time.perf_counter()-start<seconds:
            await asyncio.sleep(.05)
            snapshot=js('Python.to_value(piano.get_transport())');positions.append(snapshot['position_s'])
            check_condition=0<=snapshot['position_s']<.5
            if not check_condition:raise AssertionError('loop position escaped: '+repr(snapshot))
        wraps=sum(b<a for a,b in zip(positions,positions[1:]))
        check('ten DAC-clock loops',wraps>=10,wraps)
        if args.measure_seconds>0:
            await call('piano.set_loop(false,0,0.5)');await call('piano.stop()');await call('piano.play()')
            start=time.perf_counter();cpu=time.process_time();fps_values=[]
            while time.perf_counter()-start<args.measure_seconds:
                await asyncio.sleep(.5);fps_values.append(js('PianoScope.fps'))
            check('continuous playback remains active',controller.audio.playing)
            report['fps_samples']=fps_values
        report['performance']=dict(workload='first-light continuous' if args.measure_seconds>0 else 'first-light 0.5s loop',duration_s=time.perf_counter()-start,cpu_percent=100*(time.process_time()-cpu)/(time.perf_counter()-start),fps=js('PianoScope.fps'),underruns=controller.audio.underruns,loop_wraps=wraps,output_latency_s=float(controller.audio.stream.latency),peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        await call('piano.set_loop(false,0,8)');await call('piano.seek(0)')
        js("document.getElementById('analysisToggle').click()")
        await asyncio.sleep(.35)
        frame=js('Python.to_value(piano.get_analysis(-1))')
        if args.cpu:save_view(view,artifact_dir('screenshots')/'pianoscope-playing.png')
        before=js('Python.to_value(piano.get_transport())')
        js("(()=>{const slider=document.getElementById('strikePosition');slider.value=30;slider.dispatchEvent(new Event('input',{bubbles:true}));PianoScope.setMode('full');PianoScope.setMode('focused')})()")
        await asyncio.sleep(.08)
        after=js('Python.to_value(piano.get_transport())')
        check('move strike line preserves actual playback',after['phase']=='playing' and all(after[k]==before[k] for k in ('generation','clock_epoch','rate','loop')) and js("document.getElementById('strikePosition').value==='30'"))
        if args.cpu:save_view(view,artifact_dir('screenshots')/'pianoscope-adjustable-line.png')
        markers=js("Array.from(document.querySelectorAll('.strike-hit')).map(hit=>{const h=hit.getBoundingClientRect(),key=document.querySelector('.key[data-midi=\"'+hit.dataset.midi+'\"]').getBoundingClientRect();return Math.abs(h.left+h.width/2-key.left-key.width/2)})")
        check('pressed-note markers align with sounding keys',bool(markers) and max(markers)<=1,markers)
        js("(()=>{const slider=document.getElementById('strikePosition');slider.value=0;slider.dispatchEvent(new Event('input',{bubbles:true}))})()")
        check('post-gain analysis from actual output',frame and max(abs(x) for x in frame['waveform'])>0,frame and frame['seq'])
        js('piano.set_volume(0)');await asyncio.sleep(.15)
        frame=js('Python.to_value(piano.get_analysis(-1))');check('zero volume analysis',frame and max(abs(x) for x in frame['waveform'])==0 and max(frame['spectrum_db'])==-90)
        js('piano.set_volume(0.65)');await call('piano.pause()')
        frame=js('Python.to_value(piano.get_analysis(-1))');check('paused analysis silent',frame and max(abs(x) for x in frame['waveform'])==0)
        await call('piano.set_loop(false,0,0.5)')
        token=controller.token_for_path(ROOT/'tests/fixtures/same-channel-overlap.mid')
        await call('PianoScope.waitJob(Python.to_value(piano.begin_load('+json.dumps(token)+')))')
        p=await call("piano.preview_hands({type:'tracks',tracks:{t0c0:'left',t1c0:'right'}}).then(Python.to_value)")
        await call('PianoScope.waitJob(Python.to_value(piano.apply_hands('+json.dumps(p['preview_id'])+',{})))')
        await call('PianoScope.togglePlay()')
        await view.wait_until(lambda:js("document.querySelector('[data-midi=\"60\"]').classList.contains('key-both')"),timeout=2)
        check('same key shows both hands',js("document.querySelector('[data-midi=\"60\"]').classList.contains('key-both')"))
        await view.wait_until(lambda:js("Python.to_value(piano.get_transport()).tail_active"),timeout=5)
        check('release tail retains source duration',controller.audio.position==controller.score.duration_s)
        await view.wait_until(lambda:js("Python.to_value(piano.get_transport()).phase==='ended'"),timeout=5)
        t=await call('piano.play().then(Python.to_value)');check('replay after ended starts at zero',t['position_s']<.1)
        await call('piano.stop()')
        await call("PianoScope.waitJob(Python.to_value(piano.begin_load('demo:first-light')))")
    else:
        old_ready=controller.audio.ready;controller.audio.ready=False
        t=await call('piano.play().then(Python.to_value)');check('missing device rejects playback',t['phase']=='error' and not t['audio_ready'])
        controller.audio.ready=old_ready
        t=await call('piano.retry_audio().then(Python.to_value)')
        check('retry waits for user play',t['phase']!='playing')
        report['audio_device']='not required by offline native smoke'
    # Real view captures: parsed notes, actual synthesized overview, no mock frames.
    await call('piano.pause()');await call('piano.seek(16)')
    js("if(!document.getElementById('analysis').hidden)document.getElementById('analysisToggle').click()")
    js("PianoScope.setMode('focused')");await asyncio.sleep(.6)
    for mode in ('focused','full'):
        js('PianoScope.setMode('+json.dumps(mode)+')');await asyncio.sleep(.25)
        dom=js("Array.from(document.querySelectorAll('.key')).map(k=>({midi:+k.dataset.midi,x:k.getBoundingClientRect().x,width:k.getBoundingClientRect().width}))")
        check('real DOM key count '+mode,len(dom)==(88 if mode=='full' else js("PianoScope.geometry('focused',1000).keys")))
        if args.cpu:
            prefix='pianoscope-' if (args.width,args.height)==(1440,960) else f'pianoscope-{args.width}x{args.height}-'
            save_view(view,artifact_dir('screenshots')/(prefix+mode+'.png'))
    report['layout']=js("(()=>{const roll=document.getElementById('roll').getBoundingClientRect(),keys=document.getElementById('keys').getBoundingClientRect(),main=document.querySelector('main');return {roll_top:roll.top,roll_height:roll.height,keyboard_height:keys.height,main_scroll:main.scrollHeight-main.clientHeight,sidebar_hidden:document.getElementById('sidebar').hidden,horizontal_overflow:document.documentElement.scrollWidth>innerWidth}})()")
    check('main layout fits without scrolling',report['layout']['main_scroll']<=1 and not report['layout']['horizontal_overflow'],report['layout'])
    if args.cpu:
        was_hidden=js("document.getElementById('sidebar').hidden")
        if was_hidden:js("document.getElementById('sidebarToggle').click()")
        await asyncio.sleep(.15)
        save_view(view,artifact_dir('screenshots')/(prefix+'sidecar.png'))
        if was_hidden:js("document.getElementById('sidebarClose').click()")
    forbidden=['仅需求提示','03-A','03-B','FR-','AC-','TASK-','共享几何','binding','PCM','FFT','松开后应用']
    body=js('document.body.innerText')
    check('product copy excludes implementation notes',not any(s in body for s in forbidden))
    check('keyboard and controls inside viewport',js("document.getElementById('keys').getBoundingClientRect().bottom <= innerHeight && document.getElementById('play').getBoundingClientRect().bottom <= innerHeight"))
    report['screenshots']='CPU View.copy_pixels' if args.cpu else 'GPU View has no CPU pixel surface; use --cpu to capture'
    report['renderer']='CPU' if args.cpu else 'GPU'
    report['viewport']=js('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})')
    report['fixture']=controller.score.title
    report['sample_rate']=controller.audio.sample_rate
    report['pcm_bytes']=controller.audio.pcm.nbytes
    report['completed_jobs_keep_pcm']=any('future' in j for j in controller.jobs.values() if j['done'])
    report['underruns']=controller.audio.underruns
    report['versions']={name:version(name) for name in ('ultralight-py','mido','numpy','sounddevice')}
    report['success']=True

def main():
    global CAPTURE_PREFIX
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--width',type=int,default=1440);parser.add_argument('--height',type=int,default=960)
    parser.add_argument('--cpu',action='store_true');parser.add_argument('--file',type=Path)
    parser.add_argument('--readability-smoke',action='store_true');parser.add_argument('--readable-smoke',action='store_true');parser.add_argument('--library-smoke',action='store_true');parser.add_argument('--score-smoke',action='store_true');parser.add_argument('--smoke',action='store_true');parser.add_argument('--audio-test',action='store_true')
    parser.add_argument('--smoke-report',type=Path);parser.add_argument('--measure-seconds',type=float,default=0)
    parser.add_argument('--readable-song',choices=('interstellar','rush-e','interstellar-main-theme'))
    parser.add_argument('--capture-prefix',default='')
    args=parser.parse_args();CAPTURE_PREFIX=args.capture_prefix;report=dict(success=False,platform=platform.platform(),python=platform.python_version(),audio_test=args.audio_test)
    if args.smoke_report is None and (args.smoke or args.score_smoke or args.library_smoke or args.readable_smoke or args.readability_smoke):
        args.smoke_report=artifact_dir('reports')/'native-latest.json'
    logging.basicConfig(filename=Path(tempfile.gettempdir())/'pianoscope.log',level=logging.INFO,encoding='utf-8')
    controller=None;remove_close_observer=lambda:None
    try:
        if version('ultralight-py')!='0.5.0':raise RuntimeError('Requires ultralight-py==0.5.0')
        from ultralight_py import API,Application,Resource
        controller=Controller();assets=ROOT/'pianoscope/assets'
        mime={'html':'text/html','css':'text/css','js':'text/javascript'}
        resources={p.name:Resource(p.read_bytes(),mime[p.suffix[1:]]) for p in assets.iterdir() if p.is_file()}
        source=controller.token_for_path(args.file) if args.file else 'demo:first-light'
        resources['config.js']=Resource(('window.APP_ERRORS=[];window.onerror=function(message,url,line,column){window.APP_ERRORS.push({message:message,url:url,line:line,column:column})};window.INITIAL_SOURCE='+json.dumps(source)+';window.CPU_RENDERER='+json.dumps(args.cpu)+';if(window.CPU_RENDERER)document.documentElement.classList.add("cpu-renderer");').encode(),'text/javascript')
        html=(assets/'index.html').read_text().replace('<script src="keyboard.js">','<script src="config.js"></script><script src="keyboard.js">')
        resources['index.html']=Resource(html.encode(),'text/html')
        def load_resource(name):
            if name in resources:return resources[name]
            data=controller.notation.resource(name)
            return Resource(data,'image/png') if data else None
        with tempfile.TemporaryDirectory(prefix='pianoscope-') as cache:
            with API('piano') as api, Application(assets_root=str(assets),resource_loader=load_resource,cache_path=cache,app_name='PianoScope',force_cpu_renderer=args.cpu) as app:
                register(api,controller)
                remove_close_observer=before_window_close('PianoScope',controller.close)
                window=app.create_window(args.width,args.height,title='PianoScope');api.attach(window.view);window.view.load_url('file:///index.html')
                if args.smoke or args.score_smoke or args.library_smoke or args.readable_smoke or args.readability_smoke:
                    async def smoke():
                        pump=asyncio.create_task(app.run_async(update_interval=1/120))
                        try:
                            if args.readability_smoke:
                                from pianoscope.readability_checks import verify_readability
                                await asyncio.wait_for(verify_readability(window.view,controller,args,report),160)
                            elif args.readable_smoke:
                                from pianoscope.readable_checks import verify_readable
                                await asyncio.wait_for(verify_readable(window.view,controller,args,report),360+3*max(0,args.measure_seconds))
                            elif args.library_smoke:
                                from pianoscope.library_checks import verify_library
                                await asyncio.wait_for(verify_library(window.view,controller,args,report),180)
                            elif args.score_smoke:
                                from pianoscope.score_checks import verify_score
                                await asyncio.wait_for(verify_score(window.view,controller,args,report),180+max(0,args.measure_seconds))
                            else:await asyncio.wait_for(verify(window.view,controller,args,report),120+max(0,args.measure_seconds))
                        except Exception:
                            try:report['page_state']=window.view.evaluate("({ready:window.PIANOSCOPE_READY,errors:window.APP_ERRORS,text:document.body.innerText.slice(0,1800)})")
                            except Exception:pass
                            raise
                        finally:controller.close();app.close();await pump
                    asyncio.run(smoke())
                else:
                    try:app.run()
                    finally:controller.close()
        return 0
    except Exception as exc:
        report['error']=str(exc);traceback.print_exc();return 1
    finally:
        remove_close_observer()
        if controller and not controller.closed:controller.close()
        if args.smoke_report:
            args.smoke_report.parent.mkdir(parents=True,exist_ok=True)
            args.smoke_report.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
        if args.smoke or args.score_smoke or args.library_smoke or args.readable_smoke or args.readability_smoke:print('PianoScope native smoke: '+('PASS' if report['success'] else 'FAIL'),flush=True)
if __name__=='__main__':raise SystemExit(main())
