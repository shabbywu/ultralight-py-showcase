"""One-file, short native check for the affected notation/UI/export path."""
import asyncio
import hashlib
import json
import shutil
from .dev_paths import MIDI_ROOT,artifact_dir


async def verify_readability(view,c,args,report):
    from run import save_view
    checks=[];report['assertions']=checks;report['audio_test']=True
    def check(name,ok,detail=None):
        checks.append(dict(name=name,passed=bool(ok),detail=detail))
        if not ok:raise AssertionError(name+': '+str(detail))
    def js(code):return view.evaluate(code)
    async def call(code):return await view.evaluate_async(code)
    await view.wait_until(lambda:js('window.PIANOSCOPE_READY===true && !!PianoScope.score && !PianoScope.job'),timeout=40)
    path=args.file or MIDI_ROOT/'Interstellar-Main-Theme-Left-Right-Hand.mid'
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if not args.file:
        token=c.token_for_path(path)
        await call('PianoScope.waitJob(Python.to_value(piano.begin_load('+json.dumps(token)+')))')
    hands={'t0c0':'right','t1c1':'left'}
    p=await call('piano.preview_hands('+json.dumps(dict(type='tracks',tracks=hands))+').then(Python.to_value)')
    await call('PianoScope.waitJob(Python.to_value(piano.apply_hands('+json.dumps(p['preview_id'])+',{})))')
    original=[vars(n).copy() for n in c.score.notes];pcm=c.audio.pcm;generation=c.generation
    js("document.getElementById('viewScore').click()")
    check('automatic clef and missing-key defaults',js("document.getElementById('clefMode').value==='auto_octaves' && document.getElementById('notationKey').value==='auto'"))
    check('real binding suggests B with relative G-sharp minor',js("document.getElementById('keySuggestion').textContent.includes('B 大调') && document.getElementById('keySuggestion').textContent.includes('G# 小调')"))
    js("document.getElementById('staffMode').value='tracks';document.getElementById('staffMode').dispatchEvent(new Event('change'));document.querySelectorAll('.notation-track').forEach(r=>r.querySelector('select').value=r.dataset.track==='t0c0'?'1':'2');document.getElementById('confirmDefaults').checked=true")
    if args.cpu:
        await asyncio.sleep(.1);save_view(view,artifact_dir('screenshots')/'readability-settings-800.png')
    await call('PianoScope.togglePlay()')
    js("document.getElementById('generateNotation').click()")
    await view.wait_until(lambda:js('!!ScoreView.preview && !!ScoreView.display && ScoreView.display.preview_id===ScoreView.preview.preview_id && !document.getElementById("applyNotation").disabled'),timeout=65)
    check('generation preserves original PCM and device playback',c.audio.pcm is pcm and c.generation==generation and c.audio.playing)
    preview=js('ScoreView.preview');check('preview reports B-major suggestion',preview['key_analysis']['key']=='B')
    js("document.getElementById('applyNotation').click()")
    await view.wait_until(lambda:js('!!ScoreView.applied && !ScoreView.preview'),timeout=5)
    item=c.notation.applied;doc=item['document'];manifest=item['manifest']
    bar=[e for e in doc['events'] if e['measure_id']=='m36']
    check('measure 36 uses binary rhythms',all(e['duration'][1]%3 for e in bar),len(bar))
    check('all 1566 source notes have real glyphs',len(doc['source_note_index'])==1566 and {g['event_id'] for p in manifest['pages'] for g in p['glyphs']}=={e['id'] for e in doc['events']})
    check('range-dependent clefs and octave marks',doc['measures'][0]['clefs']['1']['sign']=='F' and any(m['clefs']['2']['octave']==-1 for m in doc['measures']))
    check('actual Canvas resources decoded',js('ScoreView.systems.every(s=>s.image.complete && s.image.naturalWidth>0)'))
    await call('PianoScope.togglePlay()')
    hit=js("""(()=>{const s=ScoreView.systems.find(s=>s.glyphs.some(g=>g.pitch!==null&&g.measure_id==='m36')),g=s.glyphs.find(g=>g.pitch!==null&&g.measure_id==='m36'&&g.source_display_spans[0].end_s-g.source_display_spans[0].start_s>.3);ScoreView.suspendFollow();document.getElementById('scoreViewport').scrollTop=s.node.offsetTop;const r=s.overlay.getBoundingClientRect(),scale=r.width/s.crop[2],x=r.left+(g.bbox[0]+g.bbox[2]/2-s.crop[0])*scale,y=r.top+(g.bbox[1]+g.bbox[3]/2-s.crop[1])*scale;const hit=ScoreView.hit(s,x,y);s.overlay.dispatchEvent(new MouseEvent('click',{clientX:x,clientY:y}));return {hit,expected:g.seek_s}})()""")
    await asyncio.sleep(.08)
    check('clef/ottava glyph uses actual binding seek',hit['hit'] and abs(c.audio.position-hit['expected'])<1e-6,hit)
    await call('PianoScope.togglePlay()')
    await view.wait_until(lambda:js('PianoScope.transport.phase==="playing" && Math.abs(PianoScope.transport.position_s-'+str(hit['expected'])+')<.5'),timeout=3)
    js('ScoreView.restoreFollow()');await asyncio.sleep(.12)
    highlights=js("""(()=>{const t=Python.to_value(piano.get_transport());ScoreView.draw(t);const expected=[],r=document.getElementById('scoreViewport').getBoundingClientRect();for(const s of ScoreView.systems){const b=s.node.getBoundingClientRect();if(b.bottom<r.top||b.top>r.bottom)continue;for(const g of s.glyphs)if(g.source_display_spans.some(p=>t.active_note_ids.includes(p.source_note_id)&&p.start_s<=t.position_s&&t.position_s<p.end_s))expected.push(g.event_id)}return {expected,actual:ScoreView.highlights,position:t.position_s,phase:t.phase}})()""")
    check('simplified score highlights original DAC source notes',highlights['phase']=='playing' and bool(highlights['expected']) and sorted(highlights['expected'])==sorted(highlights['actual']),highlights)
    if args.cpu:
        await asyncio.sleep(.08);save_view(view,artifact_dir('screenshots')/'readability-measure-36-800.png')
    await call('PianoScope.togglePlay()')
    out=artifact_dir('samples')/'readability';out.mkdir(parents=True,exist_ok=True)
    for fmt in ('pdf','musicxml'):
        target=c.notation.target(item['notation_id'],fmt,out/('after.'+fmt))
        job=await call('Python.to_value(piano.begin_score_export('+json.dumps(item['notation_id'])+','+json.dumps(fmt)+','+json.dumps(target['target_token'])+'))')
        await view.wait_until(lambda:c.get_notation_job(job['job_id'])['done'],timeout=10)
        check('atomic '+fmt+' export',c.get_notation_job(job['job_id'])['phase']=='completed')
    shutil.copy(item['directory']/'document.json',out/'after.document.json');shutil.copy(item['directory']/'manifest.json',out/'after.layout.json')
    check('original notes and MIDI bytes unchanged',original==[vars(n) for n in c.score.notes] and hashlib.sha256(path.read_bytes()).hexdigest()==digest)
    check('no JavaScript errors',js('!window.APP_ERRORS.length'),js('window.APP_ERRORS'))
    report.update(success=True,viewport=js('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})'),source_sha256=digest,
        notes=len(doc['source_note_index']),events=len(doc['events']),pages=len(manifest['pages']),measure36_events=len(bar),key_analysis=doc['key_analysis'],audio_device=c.audio.device,performance='not measured; short targeted native check only')
