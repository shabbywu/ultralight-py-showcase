"""Independent MuseScore reader: whole readable scores -> editable MSCZ + PDF."""
import argparse
import sys
from pathlib import Path
import tempfile
import hashlib
import json
import subprocess
import zipfile
import plistlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pianoscope.dev_paths import artifact_dir

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--executable',required=True,type=Path);args=parser.parse_args()
    exe=args.executable.resolve();metadata=plistlib.loads((exe.parent.parent/'Info.plist').read_bytes())
    results=[];out=artifact_dir('samples')/'readable'
    with tempfile.TemporaryDirectory(prefix='pianoscope-readable-reader-') as temp:
        base=Path(temp);jobs=[];hashes={}
        for stem in ('interstellar','rush-e','interstellar-main-theme'):
            source=out/(stem+'.musicxml');hashes[stem]=hashlib.sha256(source.read_bytes()).hexdigest()
            for fmt in ('mscz','pdf'):jobs.append({'in':str(source),'out':str(base/(stem+'.musescore.'+fmt))})
        request=base/'jobs.json';request.write_text(json.dumps(jobs))
        run=subprocess.run([str(exe),'-j',str(request)],capture_output=True,text=True,timeout=150)
        (artifact_dir('reports')/'readable-musescore.log').write_text(run.stdout+run.stderr)
        assert run.returncode==0,run.stderr[-2000:]
        for stem in ('interstellar','rush-e','interstellar-main-theme'):
            assert hashlib.sha256((out/(stem+'.musicxml')).read_bytes()).hexdigest()==hashes[stem]
            for fmt in ('mscz','pdf'):
                source=base/(stem+'.musescore.'+fmt);assert source.exists();(out/source.name).write_bytes(source.read_bytes())
            with zipfile.ZipFile(out/(stem+'.musescore.mscz')) as archive:assert any(p.endswith('.mscx') for p in archive.namelist())
            results.append(dict(stem=stem,source_sha256=hashes[stem],editable_mscz=True,pdf_exists=True))
    report=dict(success=True,exit_code=run.returncode,version=metadata.get('CFBundleShortVersionString')+'.'+metadata.get('CFBundleVersion'),samples=results)
    (artifact_dir('reports')/'readable-musescore.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(report)

if __name__=='__main__':main()
