"""G0: known original musical phrase -> native engraving -> real DAC + binding.

Run from examples/pianoscope: .venv/bin/python tools/score_gate.py
This gate is intentionally independent of the later quantization implementation.
"""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pianoscope.dev_paths import artifact_dir
import asyncio
import json
import time
import subprocess
import tempfile
from xml.etree.ElementTree import Element,SubElement as S,tostring
import mido
from pianoscope.midi import parse_midi
from pianoscope.engraving import engrave
from pianoscope.session import Controller
from pianoscope.bridge import register
from run import save_view

OUT=artifact_dir('samples')/'g0'

def phrase():
    OUT.mkdir(parents=True,exist_ok=True)
    events=[]
    for bar in range(40):
        base=bar*4
        for pitch in (64,67):events.append((1,base,1,pitch))
        events.extend([(1,base+1,1,72 if bar%2 else 71),(1,base+2,1,69)])
        if bar%2==0:events.append((2,base,6,48+(bar//2%4)*2))
    mid=mido.MidiFile(type=1,ticks_per_beat=480)
    meta=mido.MidiTrack([mido.MetaMessage('set_tempo',tempo=400000),mido.MetaMessage('time_signature',numerator=4,denominator=4)])
    mid.tracks.append(meta)
    for staff in (1,2):
        tr=mido.MidiTrack();mid.tracks.append(tr);ordered=[]
        for st,start,dur,pitch in events:
            if st==staff:
                ordered.extend([(start*480,1,mido.Message('note_on',note=pitch,velocity=80,channel=staff-1)),((start+dur)*480,0,mido.Message('note_off',note=pitch,channel=staff-1))])
        last=0
        for tick,_,msg in sorted(ordered,key=lambda x:x[:2]):msg.time=tick-last;last=tick;tr.append(msg)
        tr.append(mido.MetaMessage('end_of_track',time=160*480-last))
    midi=OUT/'phrase.mid';mid.save(midi);score=parse_midi(midi);score.title='初光 · 原生制谱验证'
    source={(n.track_id,n.start_s/0.4,n.pitch):n for n in score.notes}
    root=Element('score-partwise',version='4.0');work=S(root,'work');S(work,'work-title').text='初光 · 原生制谱验证'
    pl=S(root,'part-list');p=S(pl,'score-part',id='P1');S(p,'part-name').text='Piano';part=S(root,'part',id='P1');mapping={}
    for bar in range(40):
        m=S(part,'measure',number=str(bar+1),id=f'm{bar+1}')
        if bar==0:
            a=S(m,'attributes');S(a,'divisions').text='4';S(S(a,'key'),'fifths').text='0';t=S(a,'time');S(t,'beats').text='4';S(t,'beat-type').text='4';S(a,'staves').text='2'
            for st,sign,line in [(1,'G',2),(2,'F',4)]:
                c=S(a,'clef',number=str(st));S(c,'sign').text=sign;S(c,'line').text=str(line)
        for staff in (1,2):
            if staff==2:S(S(m,'backup'),'duration').text='16'
            if staff==1:segments=[(0,1,64),(0,1,67),(1,1,72 if bar%2 else 71),(2,1,69),(3,1,None)]
            else:segments=[(0,4 if bar%2==0 else 2,48+((bar//2)%4)*2)]+([] if bar%2==0 else [(2,2,None)])
            for ix,(beat,dur,pitch) in enumerate(segments):
                eid=f'g{bar}s{staff}e{ix}';n=S(m,'note',id=eid)
                if staff==1 and ix==1:S(n,'chord')
                if pitch is None:S(n,'rest')
                else:
                    p=S(n,'pitch');step,alter=[('C',0),('C',1),('D',0),('E',-1),('E',0),('F',0),('F',1),('G',0),('A',-1),('A',0),('B',-1),('B',0)][pitch%12]
                    S(p,'step').text=step
                    if alter:S(p,'alter').text=str(alter)
                    S(p,'octave').text=str(pitch//12-1)
                    start=bar*4+beat if staff==1 else bar//2*8
                    note=next(v for (tid,q,p),v in source.items() if tid==f't{staff}c{staff-1}' and abs(q-start)<1e-8 and p==pitch)
                    mapping[eid]=dict(source_note_ids=[note.id],start_s=max(note.start_s,(bar*4+beat)*.4),end_s=min(note.key_off_s,(bar*4+beat+dur)*.4))
                S(n,'duration').text=str(dur*4)
                if staff==2 and pitch is not None:S(n,'tie',type='start' if bar%2==0 else 'stop')
                S(n,'voice').text=str(staff);S(n,'type').text={1:'quarter',2:'half',4:'whole'}[dur];S(n,'staff').text=str(staff)
                if staff==2 and pitch is not None:S(S(n,'notations'),'tied',type='start' if bar%2==0 else 'stop')
    return score,tostring(root,encoding='unicode'),mapping


def main():
    report=dict(success=False,checks=[])
    def check(name,condition,detail=None):
        report['checks'].append(dict(name=name,passed=bool(condition),detail=detail))
        if not condition:raise AssertionError(name+': '+str(detail))
    c=None
    try:
        if '--prepare' not in sys.argv:
            subprocess.run([sys.executable,__file__,'--prepare'],check=True)
            prepared=json.loads((OUT/'prepared.json').read_text());manifest=prepared['manifest'];mapping=prepared['mapping']
            score=parse_midi(OUT/'phrase.mid');report['checks'].extend(prepared['checks']);report['engrave_seconds']=prepared['engrave_seconds']
        else:
            score,xml,mapping=phrase()
        start=time.perf_counter();manifest=engrave(xml,score.title,OUT) if '--prepare' in sys.argv else manifest
        if '--prepare' in sys.argv:report['engrave_seconds']=time.perf_counter()-start
        check('at least two real PDF pages',len(manifest['pages'])>=2,len(manifest['pages']))
        actual={g['event_id'] for p in manifest['pages'] for g in p['glyphs']}
        check('all source IDs survived engraving',set(mapping)<=actual)
        if '--prepare' in sys.argv:
            from music21 import converter
            independent=converter.parse(OUT/'score.musicxml')
            independent.write('musicxml',fp=OUT/'independent-roundtrip.musicxml')
            read_notes=[int(p.midi) for n in independent.stripTies().flatten().notes for p in n.pitches]
            check('independent editable MusicXML reader conserves source pitches',sorted(read_notes)==sorted(n.pitch for n in score.notes),len(read_notes))
            import pymupdf
            pdf=pymupdf.open(OUT/'score.pdf');check('PDF page count',len(pdf)==len(manifest['pages']))
            check('real A4 PDF dimensions',all(abs(p.rect.width-595.2756)<.01 and abs(p.rect.height-841.8898)<.01 for p in pdf))
            for i,p in enumerate(pdf):p.get_pixmap(matrix=pymupdf.Matrix(1,1)).save(str(OUT/f'pdf-{i+1}.png'))
            (OUT/'prepared.json').write_text(json.dumps(dict(manifest=manifest,mapping=mapping,checks=report['checks'],engrave_seconds=report['engrave_seconds'])))
            return 0
        from ultralight_py import API,Application,Resource
        c=Controller();job=c.begin_load(c.token_for_path(OUT/'phrase.mid'))
        while not c.get_job(job['job_id'])['done']:time.sleep(.02)
        check('real piano output device',c.audio.ready,c.audio.error)
        page=manifest['pages'][0]
        for g in page['glyphs']:g.update(mapping.get(g['event_id'],{}))
        html='''<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#142728;color:#eee;font:14px sans-serif}canvas{width:100%;display:block}button{padding:8px}#scroller{height:520px;overflow:auto}</style><button id="jump">原生双谱表 · 点击符头跳转</button><span id="status"></span><div id="scroller"><canvas id="score"></canvas></div><script src="gate.js"></script>'''
        js='''(()=>{const value=x=>Python.to_value(x),page=PAGE,canvas=document.getElementById('score'),ctx=canvas.getContext('2d'),image=new Image();let zoom=1,highlights=[],last=null;window.ready=false;image.onload=()=>{window.ready=true;draw()};image.src='page.png';function draw(){const dpr=devicePixelRatio,w=innerWidth*zoom,s=w/page.width;canvas.style.width=w+'px';canvas.style.height=page.height*s+'px';canvas.width=Math.round(w*dpr);canvas.height=Math.round(page.height*s*dpr);ctx.setTransform(s*dpr,0,0,s*dpr,0,0);ctx.fillStyle='#f8f5e8';ctx.fillRect(0,0,page.width,page.height);ctx.drawImage(image,0,0,page.width,page.height);highlights=[];if(last&&last.phase==='playing')for(const g of page.glyphs){if((g.source_note_ids||[]).some(id=>last.active_note_ids.includes(id))&&g.start_s<=last.position_s&&last.position_s<g.end_s){ctx.fillStyle='#e8ac40';ctx.globalAlpha=.7;ctx.fillRect(...g.bbox);ctx.globalAlpha=1;highlights.push(g.event_id)}}}canvas.onclick=async e=>{const r=canvas.getBoundingClientRect(),s=r.width/page.width,x=(e.clientX-r.left)/s,y=(e.clientY-r.top)/s;const g=page.glyphs.find(g=>g.source_note_ids&&x>=g.bbox[0]&&x<=g.bbox[0]+g.bbox[2]&&y>=g.bbox[1]&&y<=g.bbox[1]+g.bbox[3]);if(g){last=value(await piano.seek(g.start_s));draw()}};setInterval(()=>{last=value(piano.get_transport());draw()},50);window.Gate={image,page,canvas,get highlights(){return highlights},zoom(value){zoom=value;draw()}};})();'''.replace('PAGE',json.dumps(page))
        resources={'index.html':Resource(html.encode(),'text/html'),'gate.js':Resource(js.encode(),'text/javascript'),'page.png':Resource((OUT/'page-1.png').read_bytes(),'image/png')}
        with tempfile.TemporaryDirectory(prefix='pianoscope-g0-') as cache,API('piano') as api,Application(assets_root=str(ROOT/'pianoscope/assets'),resource_loader=resources.get,force_cpu_renderer=True,app_name='PianoScopeG0',cache_path=cache) as app:
            register(api,c);window=app.create_window(800,600,title='PianoScope G0');view=window.view;api.attach(view);view.load_url('file:///index.html')
            async def verify():
                pump=asyncio.create_task(app.run_async(update_interval=1/120))
                try:
                    await asyncio.sleep(.4)
                    await view.wait_until(lambda:view.evaluate('window.ready===true'),timeout=15)
                    check('native Canvas image loaded',view.evaluate('Gate.image.naturalWidth')==round(page['width']*2))
                    await view.evaluate_async('piano.play()')
                    await view.wait_until(lambda:len(view.evaluate('Gate.highlights'))>=2,timeout=5)
                    check('DAC active chord on Canvas',len(view.evaluate('Gate.highlights'))>=2)
                    await asyncio.sleep(.06);save_view(view,artifact_dir('screenshots')/'v11-g0-native.png')
                    await view.evaluate_async('piano.pause()');await asyncio.sleep(.1)
                    check('pause clears active highlights',not view.evaluate('Gate.highlights'))
                    errors=[]
                    for zoom in (1,1.25,1.5):
                        view.evaluate(f'Gate.zoom({zoom})')
                        target=next(g for g in page['glyphs'] if g.get('start_s',0)>.5)
                        result=view.evaluate("(()=>{const {page,canvas}=Gate;const g=page.glyphs.find(g=>g.event_id==="+json.dumps(target['event_id'])+"),r=canvas.getBoundingClientRect(),s=r.width/page.width,x=r.left+(g.bbox[0]+g.bbox[2]/2)*s,y=r.top+(g.bbox[1]+g.bbox[3]/2)*s;canvas.dispatchEvent(new MouseEvent('click',{clientX:x,clientY:y}));return {x,y,error:Math.abs((x-r.left)/s-(g.bbox[0]+g.bbox[2]/2))}})()")
                        await asyncio.sleep(.15);errors.append(result['error'])
                        check('binding seek at zoom '+str(zoom),abs(c.audio.position-target['start_s'])<1e-6)
                    check('CSS hit geometry <=1px',max(errors)<=1,errors)
                    report['viewport']=view.evaluate('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})')
                    report['device']=c.audio.device;report['underruns']=c.audio.underruns
                finally:c.close();app.close();await pump
            asyncio.run(verify())
        report['success']=True
    except Exception as exc:
        import traceback
        traceback.print_exc();report['error']=str(exc)
    finally:
        if c and not c.closed:c.close()
        (artifact_dir('reports')/('g0-prepare.json' if '--prepare' in sys.argv else 'g0.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('G0',report['success']);return 0 if report['success'] else 1

if __name__=='__main__':raise SystemExit(main())
