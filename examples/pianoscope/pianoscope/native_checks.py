"""Additional actual-JS/AppCore interaction checks, used by the native runner."""
import asyncio
import json
from pathlib import Path

async def interactions(view,controller,root,check):
    def js(code):return view.evaluate(code)
    async def call(code):return await view.evaluate_async(code)
    async def load(path):
        return await call('(async()=>{const token=Python.to_value(await piano.open_path('+json.dumps(str(path))+'));return await PianoScope.waitJob(Python.to_value(piano.begin_load(token)))})()')
    check('brand and import in sidecar, no global header',js("!document.querySelector('header') && document.getElementById('open').closest('#sidebar')!==null && document.querySelector('.brand').closest('#sidebar')!==null"))
    check('keyboard controls remain directly in main',js("['full','focused','names','motion','strikePosition'].every(id=>document.getElementById(id).closest('main')!==null)"))
    was_hidden=js("document.getElementById('sidebar').hidden")
    if was_hidden:js("document.getElementById('sidebarToggle').click()")
    check('sidecar opens import and sample controls',js("!document.getElementById('sidebar').hidden && document.getElementById('sidebarToggle').getAttribute('aria-expanded')==='true' && document.getElementById('open').getBoundingClientRect().width>0"))
    if js("window.matchMedia('(max-width:1100px)').matches"):
        js("document.getElementById('tracks').focus();document.getElementById('tracks').dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}))")
        check('compact sidecar traps focus',js("document.activeElement===document.getElementById('sidebarClose')"))
        js("document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        await asyncio.sleep(.05)
        check('Escape closes compact sidecar and restores focus',js("document.getElementById('sidebar').hidden && document.activeElement===document.getElementById('sidebarToggle')"))
    else:
        js("document.getElementById('sidebarClose').click()")
        check('desktop sidecar can collapse',js("document.getElementById('sidebar').hidden"))
        js("document.getElementById('sidebarToggle').click()")
    await load(root/'tests/fixtures/cross-hands.mid')
    check('external Type 0 remains unassigned',js("PianoScope.notes.every(n=>n.hand==='unassigned') && PianoScope.score.tracks[0].suggested_hand==='left'"))
    old=controller.score.score_id
    await load(root/'tests/fixtures/broken.mid')
    check('failed import preserves previous score',controller.score.score_id==old and controller.phase=='paused')
    # Keyboard focus must preserve native editing and button actions.
    await call('piano.seek(0.2)')
    js("document.getElementById('loopA').focus();document.getElementById('loopA').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))")
    check('input arrows do not seek',abs(controller.audio.position-.2)<1e-5)
    js("document.activeElement.blur();document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}))")
    await asyncio.sleep(.1)
    check('Home seeks to start',controller.audio.position==0)
    await call('piano.seek(0.2)')
    js("document.getElementById('names').click()")
    check('note name toggle',js("document.querySelectorAll('.key .keyname').length>0 && Array.from(document.querySelectorAll('.key .keyname')).every(x=>x.textContent==='')"))
    js("document.getElementById('names').click();document.getElementById('settings').click()")
    await asyncio.sleep(.15)
    check('hand settings open and pause',js("!document.getElementById('editor').hidden") and controller.phase!='playing')
    js("document.getElementById('rule').value='pitch_split';document.getElementById('split').value='60';document.getElementById('preview').click()")
    await view.wait_until(lambda:js("!document.getElementById('applyHands').disabled"),timeout=5)
    check('preview is not a commit',all(n.hand=='unassigned' for n in controller.score.notes))
    js("document.getElementById('applyHands').click()")
    await view.wait_until(lambda:js("PianoScope.job===null && PianoScope.score.hand_assignment.source==='manual'"),timeout=15)
    check('UI applies threshold assignment',controller.score.notes[0].hand=='right' and controller.score.notes[1].hand=='left')
    # A point on the high C note selects it; box selection includes the chord.
    await call('piano.seek(0.2)');await asyncio.sleep(.6)
    js("(()=>{PianoScope.setMode('focused');PianoScope.draw();const r=document.getElementById('roll').getBoundingClientRect();const k=document.querySelector('[data-midi=\"72\"]').getBoundingClientRect();document.getElementById('roll').dispatchEvent(new MouseEvent('mousedown',{clientX:k.x+k.width/2,clientY:r.bottom-12,bubbles:true}));document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));})()")
    check('individual note selection',js("!document.getElementById('selectionBar').hidden"))
    revision=controller.score.revision
    js("document.querySelector('#selectionBar [data-assign=left]').click()")
    await view.wait_until(lambda:controller.score.revision>revision and js('PianoScope.job===null'),timeout=15)
    check('cross-hand explicit correction',controller.score.notes[0].hand=='left')
    js("(()=>{const r=document.getElementById('roll').getBoundingClientRect();document.getElementById('roll').dispatchEvent(new MouseEvent('mousedown',{clientX:r.left+1,clientY:r.top+1,bubbles:true}));document.dispatchEvent(new MouseEvent('mousemove',{clientX:r.right-1,clientY:r.bottom-1,bubbles:true}));document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));})()")
    check('box selects multiple notes',js("parseInt(document.getElementById('selectedLabel').textContent)>=2"))
    await call('PianoScope.waitJob(Python.to_value(piano.undo_hands()))')
    check('undo note correction',controller.score.notes[0].hand=='right')
    await load(root/'tests/fixtures/single-high.mid')
    check('single pitch expands octave and locates central C outside',js("PianoScope.geometry('focused',1000).high-PianoScope.geometry('focused',1000).low>=12 && document.getElementById('central').textContent.includes('左侧')"))
    await load(root/'tests/fixtures/all-88.mid')
    check('all-range fixture retains exactly 88 keys',js("PianoScope.geometry('focused',1000).keys===88 && PianoScope.score.used_pitches.length===88"))
    await load(root/'tests/fixtures/zero-duration.mid')
    await asyncio.sleep(.15)
    check('zero-duration MIDI keeps finite drawing',controller.score.duration_s==0 and js('window.APP_ERRORS.length===0'))
    await call("PianoScope.waitJob(Python.to_value(piano.begin_load('demo:first-light')))")
    # Both rendering layers use actual DOM origins at current device pixel ratio.
    for mode in ('full','focused'):
        js('PianoScope.setMode('+json.dumps(mode)+')')
        result=js("(()=>{const l=new KeyboardLayout(PianoScope.score.used_pitches,"+json.dumps(mode)+",document.getElementById('keys').clientWidth),origin=document.getElementById('roll').getBoundingClientRect().left;return Math.max(...Array.from(document.querySelectorAll('.key')).map(b=>{let k=l.byMidi[+b.dataset.midi],r=b.getBoundingClientRect();return Math.abs(origin+k.center-r.left-r.width/2)}))})()")
        check('actual DOM/Canvas alignment '+mode,result<=1,result)
        for expanded in (False,True):
            js("if(document.getElementById('analysis').hidden === "+str(expanded).lower()+")document.getElementById('analysisToggle').click()")
            await asyncio.sleep(.05)
            visible=js("['full','focused','names','motion','strikePosition','play','stop','analysisToggle','volume','keys'].every(id=>{const r=document.getElementById(id).getBoundingClientRect();return r.width>0 && r.height>0 && r.left>=0 && r.top>=0 && r.right<=innerWidth+1 && r.bottom<=innerHeight+1})")
            check('compact controls visible '+mode+(' expanded' if expanded else ' collapsed'),visible)
            for lift in (0,30,60):
                js("(()=>{const slider=document.getElementById('strikePosition');slider.value="+str(lift)+";slider.dispatchEvent(new Event('input',{bubbles:true}))})()")
                line=js("""(()=>{const line=document.getElementById('strikeLine').getBoundingClientRect(),roll=document.getElementById('roll').getBoundingClientRect(),lift=+document.getElementById('strikePosition').value,y=line.top+line.height/2;
                let canvasError=0,drawn=0;const original=KeyboardLayout.prototype.noteRect;
                try{KeyboardLayout.prototype.noteRect=function(...args){const r=original.apply(this,args);canvasError=Math.max(canvasError,Math.abs(args[1]+roll.top-y));drawn++;return r};PianoScope.draw()}finally{KeyboardLayout.prototype.noteRect=original}
                return {rollError:Math.abs(y-(roll.bottom-roll.height*lift/100)),canvasError,drawn,label:document.querySelector('.strike-label').textContent,saved:localStorage.getItem('strikeLift')===String(lift)}})()""")
                check('adjustable strike line '+mode+(' expanded ' if expanded else ' collapsed ')+str(lift),line['rollError']<=1 and line['canvasError']<=1 and line['drawn']>0 and line['saved'] and line['label']=='现在 · 按下',line)
    js("""(()=>{const label=document.querySelector('.strike-label'),roll=document.getElementById('roll').getBoundingClientRect();label.dispatchEvent(new MouseEvent('mousedown',{button:0,bubbles:true}));document.dispatchEvent(new MouseEvent('mousemove',{clientY:roll.top-100,bubbles:true}));document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))})()""")
    check('drag strike line clamps upper bound',js("document.getElementById('strikePosition').value==='60' && document.getElementById('selectionBar').hidden"))
    js("""(()=>{const label=document.querySelector('.strike-label'),roll=document.getElementById('roll').getBoundingClientRect();label.dispatchEvent(new MouseEvent('mousedown',{button:0,bubbles:true}));document.dispatchEvent(new MouseEvent('mousemove',{clientY:roll.bottom+100,bubbles:true}));document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))})()""")
    check('drag strike line restores bottom',js("document.getElementById('strikePosition').value==='0'"))
    js("if(document.getElementById('analysis').hidden)document.getElementById('analysisToggle').click();if(document.getElementById('loop').getAttribute('aria-pressed')!=='true')document.getElementById('loop').click()")
    await view.wait_until(lambda:js("!document.getElementById('loopInputs').hidden"),timeout=3)
    combo=js("(()=>{const main=document.querySelector('main');return {scroll:main.scrollHeight-main.clientHeight,visible:['keys','play','stop','loopInputs','analysis','wave','spectrum'].every(id=>{const r=document.getElementById(id).getBoundingClientRect();return r.width>0 && r.height>0 && r.right<=innerWidth+1 && r.bottom<=innerHeight+1})}})()")
    check('loop inputs and analysis fit together',combo['visible'] and combo['scroll']<=1,combo)
    js("document.getElementById('loop').click()")
    await view.wait_until(lambda:js("document.getElementById('loopInputs').hidden"),timeout=3)
    js("if(!document.getElementById('analysis').hidden)document.getElementById('analysisToggle').click()")
