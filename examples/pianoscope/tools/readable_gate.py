"""Real whole-song worker gate for readable profile 2; no source edits."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pianoscope.dev_paths import artifact_dir,MIDI_ROOT
from types import SimpleNamespace
import hashlib
import json
import shutil
import time
from collections import Counter
from fractions import Fraction
from pianoscope.midi import parse_midi
from pianoscope.hands import preview,assigned
from pianoscope.score_jobs import ScoreJobs

OUT=artifact_dir('samples')/'readable';OUT.mkdir(parents=True,exist_ok=True)

def main():
    results=[]
    for filename,stem in [('Hans Zimmer - First Step - Interstellar.mid','interstellar'),('Rush E.mid','rush-e'),('Interstellar-Main-Theme-MIDI.mid','interstellar-main-theme')]:
        path=MIDI_ROOT/filename;fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
        score=parse_midi(path);values,_=preview(score,dict(type='pitch_split',pitch=60));score=assigned(score,values,{})
        snapshot=[vars(n).copy() for n in score.notes];service=ScoreJobs(SimpleNamespace(score=score))
        try:
            job=service.begin(dict(profile=2,rhythm='auto',confirm_defaults=True))
            until=time.monotonic()+65
            while time.monotonic()<until:
                state=service.get(job['job_id'])
                if state['done']:break
                time.sleep(.05)
            if state['phase']!='preview_ready':raise AssertionError(state)
            summary=service.apply(state['result']['preview_id'],state['result']['source_revision']);item=service.applied
            doc=item['document'];manifest=item['manifest']
            assert set(doc['source_note_index'])=={n.id for n in score.notes}
            assert all(v['notation_event_ids'] for v in doc['source_note_index'].values())
            events={e['id']:e for e in doc['events']}
            for index in doc['source_note_index'].values():
                assert sum(Fraction(*events[eid]['duration']) for eid in index['notation_event_ids'])==Fraction(*index['normalization']['inferred_duration'])
            assert snapshot==[vars(n) for n in score.notes] and hashlib.sha256(path.read_bytes()).hexdigest()==fingerprint
            assert {g['event_id'] for p in manifest['pages'] for g in p['glyphs']}=={e['id'] for e in doc['events']}
            # Save actual outputs via the production atomic export transaction.
            for fmt in ('pdf','musicxml'):
                target=service.target(item['notation_id'],fmt,OUT/(stem+'.'+fmt));export=service.export(item['notation_id'],fmt,target['target_token'])
                while not service.get(export['job_id'])['done']:time.sleep(.01)
                assert service.get(export['job_id'])['phase']=='completed'
            shutil.copy(item['directory']/'document.json',OUT/(stem+'.document.json'))
            shutil.copy(item['directory']/'manifest.json',OUT/(stem+'.layout.json'))
            results.append(dict(filename=filename,source_sha256=fingerprint,notes=len(score.notes),events=len(doc['events']),
                voices=doc['voices'],pages=len(manifest['pages']),seconds=state['seconds'],
                normalization_kinds=dict(Counter(v['normalization']['kind'] for v in doc['source_note_index'].values())),
                source_and_geometry_conserved=True,summary=summary))
            print(stem,len(doc['events']),doc['voices'],len(manifest['pages']),flush=True)
        finally:service.close()
    (artifact_dir('reports')/'readable-gate.json').write_text(json.dumps(dict(success=True,samples=results),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
