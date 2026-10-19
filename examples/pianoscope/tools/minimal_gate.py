"""First gate: real AppCore -> JS binding -> FluidSynth -> output device."""
import asyncio
import json
import platform
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pianoscope.dev_paths import artifact_dir
import numpy as np
import sounddevice as sd
from ultralight_py import API, Application, Resource
from pianoscope.synth import Synth
from pianoscope.dialogs import choose_path

async def main():
    report = {'platform': platform.platform(), 'python': platform.python_version(), 'success': False}
    async def probe():
        def render():
            with Synth() as s:
                s.note_on(0,69,100)
                a=s.samples(24000); s.note_off(0,69)
                return np.concatenate([a,s.samples(24000)]),s.version
        pcm, ver = await asyncio.to_thread(render)
        report['fluidsynth']=ver; report['peak']=float(np.max(np.abs(pcm)))
        report['devices']=str(sd.query_devices()); report['sample_rate']=48000
        sd.play(pcm,48000); await asyncio.to_thread(sd.wait)
        report['device_output_completed']=True
        return {'peak':report['peak'], 'samples':pcm[::100,0].tolist()}
    async def dialog():
        result=choose_path(auto_cancel=True)
        report['native_dialog_cancel']=result is None
        return result is None
    html=b'''<!doctype html><meta charset="utf-8"><h1>PianoScope</h1><canvas id="c" width="1000" height="300"></canvas><script>
const p=piano; window.ready=true;
async function gate(){let r=Python.to_value(await p.probe());let c=document.querySelector('canvas').getContext('2d');c.strokeStyle='#80cfbf';c.beginPath();r.samples.forEach((y,i)=>{let x=i*1000/r.samples.length;c.lineTo(x,150-y*400)});c.stroke();return r.peak>0 && await p.dialog();}
</script>'''
    with API('piano') as api, Application(resource_loader=lambda _:Resource(html,'text/html'),force_cpu_renderer=True,app_name='PianoScopeGate') as app:
        api.register(probe); api.register(dialog)
        w=app.create_window(1100,600,title='PianoScope · 最小闭环');api.attach(w.view);w.view.load_url('file:///index.html')
        pump=asyncio.create_task(app.run_async())
        try:
            await w.view.wait_settled(15)
            await w.view.wait_until(lambda:w.view.evaluate('window.ready===true'),15)
            assert await w.view.evaluate_async('gate()')
            report['success']=True
        except Exception as exc:
            report['error']=repr(exc); raise
        finally:
            sd.stop(); app.close(); await pump
            dest=artifact_dir('reports')/'minimal-gate.json'
            dest.write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
