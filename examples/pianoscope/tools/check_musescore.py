"""Optional independent native reader verification, never a runtime dependency."""
import argparse
import sys
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
import tempfile
import plistlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pianoscope.dev_paths import artifact_dir

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--executable',required=True,type=Path)
    args=parser.parse_args();exe=args.executable.resolve()
    info=exe.parent.parent/'Info.plist'
    metadata=plistlib.loads(info.read_bytes()) if info.exists() else {}
    version=metadata.get('CFBundleShortVersionString','unknown')+'.'+metadata.get('CFBundleVersion','unknown')
    pairs=[('v11/first-light.musicxml','v11/first-light.musescore.pdf'),('v11/edge-phrase.musicxml','v11/edge-phrase.musescore.mscz'),('g0/score.musicxml','g0/phrase.musescore.mscz')]
    results=[]
    fingerprints={source:hashlib.sha256((artifact_dir('samples')/source).read_bytes()).hexdigest() for source,_ in pairs}
    with tempfile.TemporaryDirectory(prefix='pianoscope-reader-') as temporary:
        base=Path(temporary);jobs=[]
        for index,(source_name,output_name) in enumerate(pairs):
            jobs.append({'in':str(artifact_dir('samples')/source_name),'out':str(base/(str(index)+Path(output_name).suffix))})
        request=base/'jobs.json';request.write_text(json.dumps(jobs))
        process=subprocess.run([str(exe),'-j',str(request)],capture_output=True,text=True,timeout=120)
        log=artifact_dir('reports')/'musescore-final-batch.log';log.write_text(process.stdout+process.stderr)
        if process.returncode:raise RuntimeError(str(log))
        for job,(_,output_name) in zip(jobs,pairs):
            prepared=Path(job['out']);assert prepared.exists()
            (artifact_dir('samples')/output_name).write_bytes(prepared.read_bytes())
    for source_name,output_name in pairs:
        source=artifact_dir('samples')/source_name;output=artifact_dir('samples')/output_name
        fingerprint=fingerprints[source_name]
        assert hashlib.sha256(source.read_bytes()).hexdigest()==fingerprint
        result=dict(source=str(source),source_sha256=fingerprint,output=str(output),output_bytes=output.stat().st_size,exit_code=process.returncode,log=str(log))
        if output.suffix=='.pdf':
            import pymupdf
            pdf=pymupdf.open(output);result['pages']=len(pdf)
            pdf[0].get_pixmap().save(str(output.parent/'first-light-musescore-reader.png'))
        else:
            with zipfile.ZipFile(output) as archive:
                result['editable_score']=any(p.endswith('.mscx') for p in archive.namelist())
                assert result['editable_score']
        results.append(result)
    report=dict(success=True,version=version,mode='native independent converter import and write; no product runtime dependency',samples=results)
    (artifact_dir('reports')/'v11-musescore.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False));return 0

if __name__=='__main__':raise SystemExit(main())
