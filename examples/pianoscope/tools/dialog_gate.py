"""Native cancel check; --interactive records an actual user-selected MIDI."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pianoscope.dev_paths import artifact_dir
from ultralight_py import Application, Resource
from pianoscope.dialogs import choose_path
from pianoscope.midi import parse_midi
ROOT=Path(__file__).resolve().parents[1]
async def main(interactive):
    report={'success':False,'mode':'interactive' if interactive else 'cancel-only','selection':'unverified'}
    with Application(resource_loader=lambda _:Resource(b'<h1>PianoScope</h1>','text/html'),force_cpu_renderer=True) as app:
        w=app.create_window(700,400,title='PianoScope 文件选择验收');w.view.load_url('file:///index.html')
        pump=asyncio.create_task(app.run_async())
        try:
            await w.view.wait_settled(10)
            report['native_cancel']=choose_path(auto_cancel=True) is None
            if interactive:
                chosen=choose_path()
                if chosen:
                    score=parse_midi(chosen);report['selection']='passed';report['selected_filename']=chosen.name;report['notes']=len(score.notes)
                else:report['selection']='cancelled'
            report['success']=report['native_cancel'] and (not interactive or report['selection']=='passed')
        finally:app.close();await pump
    (artifact_dir('reports')/'native-dialog.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(report)
    return 0 if report['success'] else 1
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--interactive',action='store_true')
    raise SystemExit(asyncio.run(main(parser.parse_args().interactive)))
