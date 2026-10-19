"""Real AppCore/DAC: roll-first, lazy layout, ornaments and snapshot exports."""
from pathlib import Path
from datetime import datetime
from importlib.metadata import version
import argparse
import asyncio
import hashlib
import io
import json
import platform
import sys
import tempfile
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pianoscope.v2_session import Controller
from pianoscope.v2_bridge import register
from tools.v2_g0 import screenshot
from run import APP_UPDATE_INTERVAL


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=ROOT/'tests/fixtures/v2/expressions.musicxml')
    parser.add_argument('--gpu',action='store_true')
    parser.add_argument('--seconds',type=int,default=10,help='0 skips performance measurement for focused interaction checks')
    args=parser.parse_args()
    if args.seconds<0:parser.error('--seconds must be nonnegative')
    out=ROOT.parents[1]/'.tmp/pianoscope/v2'/datetime.now().strftime('loading-%Y%m%d-%H%M%S');out.mkdir(parents=True)
    original=args.source.resolve().read_bytes()
    report=dict(status='failed',checks=[],source_sha256=hashlib.sha256(original).hexdigest(),renderer='GPU' if args.gpu else 'CPU',runtime=dict(python=sys.version,platform=platform.platform(),ultralight_py=version('ultralight-py')))
    def check(name,condition,detail=None):
        report['checks'].append(dict(name=name,status='passed' if condition else 'failed',detail=detail))
        if not condition:raise AssertionError(name+': '+str(detail))
    from ultralight_py import API,Application,Resource
    c=Controller();assets=ROOT/'pianoscope/assets'
    report['assets_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in assets.iterdir() if p.suffix in ('.html','.css','.js')}
    resources={p.name:Resource(p.read_bytes(),{'.html':'text/html','.css':'text/css','.js':'text/javascript'}[p.suffix]) for p in assets.iterdir() if p.suffix in ('.html','.css','.js')}
    resources['index.html']=resources['v2.html']
    resources['config.js']=Resource(('window.APP_ERRORS=[];window.onerror=m=>APP_ERRORS.push(String(m));window.CPU_RENDERER='+json.dumps(not args.gpu)+';window.INITIAL_SOURCE='+json.dumps(c.token_for_path(args.source))+';').encode(),'text/javascript')
    def loader(name):
        if name in resources:return resources[name]
        data=c.resource(name)
        return Resource(data,'image/png') if data is not None else None
    try:
        with tempfile.TemporaryDirectory(prefix='pianoscope-loading-') as cache,API('piano') as api,Application(assets_root=str(assets),resource_loader=loader,cache_path=cache,force_cpu_renderer=not args.gpu,app_name='PianoScope loading gate') as app:
            register(api,c);window=app.create_window(1440 if args.gpu else 800,900 if args.gpu else 600,title='PianoScope loading gate');view=window.view
            api.attach(view);view.focus();started=time.monotonic();view.load_url('file:///index.html')
            async def verify():
                pump=asyncio.create_task(app.run_async(update_interval=APP_UPDATE_INTERVAL))
                try:
                    await asyncio.sleep(.4)
                    await view.wait_until(lambda:view.evaluate('window.PIANOSCOPE_READY&&App.document&&!App.loadJob'),timeout=60)
                    report['ready_elapsed_s']=time.monotonic()-started
                    report['viewport']=view.evaluate('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})')
                    check('default roll visible with keyboard',view.evaluate('App.view==="roll"&&!document.getElementById("rollArea").hidden&&document.getElementById("sheet").hidden&&!document.getElementById("keyboard").hidden'))
                    check('initial ready skips engraving and page decode',not c.get_document()['layout_ready'] and view.evaluate('App.rows.length===0&&!App.sheetRequest') and all(j['kind']=='load' for j in c.jobs.values()) and not list(c.active['folder'].glob('*.png')) and not list(c.active['folder'].glob('*.pdf')))
                    check('initial load awaits manual play',not c.audio.playing and c.audio.position==0)
                    check('real device ready',c.audio.ready,c.audio.error)
                    import mido
                    midi=c.plan.midi_bytes
                    count=sum(e.type=='note_on' and e.velocity>0 for t in mido.MidiFile(file=io.BytesIO(midi)).tracks for e in t)
                    check('independent SMF reader matches instances',count==len(c.plan.instances),count)
                    report['duration_s']=c.plan.duration_s;report['diagnostics']=c.get_diagnostics()
                    if args.source.name=='expressions.musicxml':check('manual ornament count',count==27,count)
                    await view.evaluate_async('piano.play()')
                    await view.wait_until(lambda:c.get_transport()['position_s']>.2 and float(abs(c.audio.heard_window()).max())>0,timeout=5)
                    check('real DAC advances with audible SoundFont output',True)
                    pcm,revision=c.audio.pcm,c.plan.revision
                    await view.evaluate_async('piano.set_loop(true,0,'+str(c.plan.duration_s)+')')
                    epoch=c.audio.epoch
                    await asyncio.sleep(.3)
                    if args.seconds:
                        view.evaluate('App.beginMeasure('+str(args.seconds)+');true');await asyncio.sleep(args.seconds+.15)
                        metrics=view.evaluate('App.measurement');report['performance']=dict(metrics,minimum_fps=min(metrics['frames']),mean_fps=sum(metrics['frames'])/args.seconds,underruns=c.audio.underruns)
                        check('each one-second roll window meets 30 FPS',len(metrics['frames'])==args.seconds and min(metrics['frames'])>=30,metrics['frames'])
                    else:report['performance']=dict(status='not_run')
                    check('zero audio underruns',c.audio.underruns==0,c.audio.underruns)
                    if not args.gpu:screenshot(view,out/'default-roll.png')
                    view.evaluate('document.getElementById("sheetMode").click();true')
                    await view.wait_until(lambda:c.current_layout_job is not None,timeout=3)
                    cancelled=c.current_layout_job
                    view.evaluate('document.getElementById("rollMode").click();true');await asyncio.sleep(.15)
                    check('switching back cancels pending engraving',c.get_job(cancelled)['cancelled'] and not c.get_document()['layout_ready'] and view.evaluate('!App.sheetRequest'))
                    resource=c.resource
                    c.resource=lambda name:b'invalid PNG injection' if name.startswith('score-') else resource(name)
                    view.evaluate('document.getElementById("sheetMode").click();true')
                    await view.wait_until(lambda:c.current_layout_job!=cancelled and view.evaluate('!App.sheetRequest'),timeout=70)
                    check('native decode failure commits no partial layout',view.evaluate('document.getElementById("sheet").textContent.includes("底图加载失败")&&App.rows.length===0') and not c.get_document()['layout_ready'] and c.audio.pcm is pcm and c.audio.epoch==epoch and c.plan.revision==revision)
                    c.resource=resource
                    sheet_started=time.monotonic()
                    view.evaluate('document.querySelector("#sheet .sheet-status button").click();true')
                    await view.wait_until(lambda:view.evaluate('App.rows.length>0&&!App.sheetRequest'),timeout=70)
                    report['layout_elapsed_s']=time.monotonic()-sheet_started
                    check('real pages decode and commit on demand',c.get_document()['layout_ready'] and c.get_document()['pages']>0)
                    check('layout preserves PCM, playback revision and DAC epoch',c.audio.pcm is pcm and c.audio.epoch==epoch and c.plan.revision==revision and c.audio.playing)
                    report['layout_worker']=c.active['data']['worker_metrics']
                    report['sheet_geometry']=view.evaluate('({scrollY,body:document.body.scrollTop,sheet:document.getElementById("sheet").getBoundingClientRect().y,header:document.querySelector(".top").getBoundingClientRect().y,play:document.getElementById("play").getBoundingClientRect().y})')
                    check('header and playback controls remain visible',0<=report['sheet_geometry']['header']<100 and 0<=report['sheet_geometry']['play']<report['viewport']['height'],report['sheet_geometry'])
                    await asyncio.sleep(.2)
                    if not args.gpu:screenshot(view,out/'lazy-sheet.png')
                    view.evaluate('document.getElementById("rollMode").click();document.getElementById("sheetMode").click();true')
                    check('cached view switch keeps same player',c.audio.pcm is pcm and c.audio.epoch==epoch and view.evaluate('App.rows.length>0&&!App.sheetRequest'))
                    import pianoscope.v2_session as session
                    choose=session.choose_score_path;report['exports']={}
                    try:
                        for kind,suffix in (('pdf','.pdf'),('source',args.source.suffix),('midi','.mid')):
                            target=out/('export'+suffix);session.choose_score_path=lambda *a,**k:target
                            choice=c.choose_export(c.plan.document.revision,kind)
                            job=c.begin_export(choice['snapshot_id'],kind,choice['target_token'])
                            await view.wait_until(lambda:c.get_job(job['job_id'])['done'],timeout=70)
                            check('real snapshot export '+kind,c.get_job(job['job_id'])['phase']=='completed',c.get_job(job['job_id']))
                            report['exports'][kind]=dict(bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),path=str(target))
                        check('source export equals original bytes',(out/('export'+args.source.suffix)).read_bytes()==original)
                        check('MIDI export equals compiled performance',(out/'export.mid').read_bytes()==midi)
                        from pypdf import PdfReader
                        check('PDF opens independently',len(PdfReader(out/'export.pdf').pages)==c.get_document()['pages'])
                    finally:session.choose_score_path=choose
                    await view.evaluate_async('piano.pause()')
                    check('source file unchanged',args.source.resolve().read_bytes()==original)
                    check('no JavaScript errors',not view.evaluate('APP_ERRORS'),view.evaluate('APP_ERRORS'))
                except Exception:
                    report['state']=view.evaluate('({ready:window.PIANOSCOPE_READY,view:window.App&&App.view,text:document.body.innerText,errors:window.APP_ERRORS})')
                    report['jobs']=[c.get_job(j) for j in c.jobs]
                    raise
                finally:
                    c.close();app.close();await pump
            asyncio.run(verify())
        report['status']='passed';return 0
    except Exception as exc:
        report['error']=str(exc);traceback.print_exc();return 1
    finally:
        if not c.closed:c.close()
        report['manual_listening']='not_run';report['physical_audio_visual_latency']='not_run'
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
        print(out/'report.json')


if __name__=='__main__':raise SystemExit(main())
