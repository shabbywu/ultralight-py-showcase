"""Independent music21 structural read/write and actual PDF raster QA inputs."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pianoscope.dev_paths import artifact_dir
from collections import Counter
from fractions import Fraction as F
import json
import mido
from pianoscope.midi import parse_midi
from pianoscope.notation import build,musicxml,serialize
from pianoscope.engraving import engrave

OUT=artifact_dir('samples')/'v11'

def edge_phrase(destination=None):
    """Original finite musical fixture, actual events shared by sound and score."""
    mid=mido.MidiFile(type=1,ticks_per_beat=480);meta=mido.MidiTrack();mid.tracks.append(meta)
    events=[(0,mido.MetaMessage('set_tempo',tempo=500000)),(0,mido.MetaMessage('time_signature',numerator=3,denominator=4)),
        (0,mido.MetaMessage('key_signature',key='C')),(480,mido.MetaMessage('set_tempo',tempo=800000)),
        (1440,mido.MetaMessage('time_signature',numerator=6,denominator=8)),(1440,mido.MetaMessage('key_signature',key='F#')),
        (2880,mido.MetaMessage('time_signature',numerator=4,denominator=4)),(4800,mido.MetaMessage('key_signature',key='Bb'))]
    last=0
    for tick,msg in sorted(events,key=lambda e:e[0]):meta.append(msg.copy(time=tick-last));last=tick
    parts=[[(0,2880,21),(2880,6720,36)],[(0,480,108),(480,960,100),(960,1440,103),(1440,1600,84),(1600,1760,86),(1760,1920,88),(1920,2280,90),(2400,2880,96),(2880,4800,72),(4800,6720,74)]]
    for ch,notes in enumerate(parts):
        track=mido.MidiTrack();mid.tracks.append(track);events=[]
        for a,b,p in notes:events.extend([(a,1,mido.Message('note_on',channel=ch,note=p,velocity=80)),(b,0,mido.Message('note_off',channel=ch,note=p))])
        last=0
        for tick,_,msg in sorted(events,key=lambda e:e[:2]):track.append(msg.copy(time=tick-last));last=tick
    path=destination or OUT/'edge-phrase.mid';path.parent.mkdir(parents=True,exist_ok=True);mid.save(path);return path

def verify(stem,render_pages=None):
    from music21 import converter,stream,chord
    import pymupdf
    doc=json.loads(stem.with_suffix('.document.json').read_text())
    score=converter.parse(stem.with_suffix('.musicxml'))
    import xml.etree.ElementTree as ET
    xml_voices={}
    for measure in ET.parse(stem.with_suffix('.musicxml')).findall('./part/measure'):
        for note in measure.findall('note'):
            xml_voices.setdefault((int(measure.attrib['number']),int(note.findtext('staff','1'))),set()).add(int(note.findtext('voice','1')))
    expected=Counter();actual=Counter();measures={m['id']:m for m in doc['measures']}
    for event in doc['events']:
        m=measures[event['measure_id']]
        expected[(m['number'],event['staff'],(event['staff']-1)*doc.get('voice_stride',2)+event['voice'],event['pitch'],F(*event['onset'])-F(*m['start']),F(*event['duration']))]+=1
    for staff,part in enumerate(score.parts,1):
        for measure in part.getElementsByClass(stream.Measure):
            for note in measure.recurse().notesAndRests:
                # When a measure has a single strand, music21 removes its
                # Voice container. Context lookup may then return the previous
                # measure's voice; use that measure's explicit XML voice ID.
                voice=note.getContextByClass(stream.Voice) if measure.voices else None
                implicit=xml_voices[(measure.number,staff)]
                vid=int(voice.id) if voice else next(iter(implicit)) if len(implicit)==1 else ((staff-1)*doc.get('voice_stride',2)+1)
                pitches=[None] if note.isRest else [int(p.midi) for p in note.pitches]
                for pitch in pitches:actual[(measure.number,staff,vid,pitch,F(note.getOffsetInHierarchy(measure)).limit_denominator(1000000),F(note.duration.quarterLength).limit_denominator(1000000))]+=1
    if actual!=expected:
        raise AssertionError(dict(missing=list((expected-actual).items())[:10],extra=list((actual-expected).items())[:10]))
    score.write('musicxml',fp=stem.with_suffix('.independent.musicxml'))
    pdf=pymupdf.open(stem.with_suffix('.pdf'));pages=[]
    for i,page in enumerate(pdf):
        assert abs(page.rect.width-595.2756)<.01 and abs(page.rect.height-841.8898)<.01
        if render_pages is None or i+1 in render_pages:
            page.get_pixmap(matrix=pymupdf.Matrix(1.25,1.25)).save(str(stem.parent/f'{stem.name}-pdf-{i+1}.png'))
        pages.append(dict(page=i+1,width=page.rect.width,height=page.rect.height))
    return dict(stem=stem.name,independent_reader='music21 9.9.1',semantic_events=sum(actual.values()),all_pitch_duration_staff_voice_measure_offsets_equal=True,pdf_pages=pages)

def prepare_sample(stem,source,rhythm):
    doc=build(source,{'confirm_defaults':True,'rhythm':rhythm,'staff_mode':'pitch'})
    temp=OUT/(stem+'-layout');manifest=engrave(musicxml(doc),source.title,temp)
    import shutil
    for fmt in ('pdf','musicxml'):shutil.copy(temp/('score.'+fmt),OUT/(stem+'.'+fmt))
    (OUT/(stem+'.document.json')).write_text(json.dumps(serialize(doc),ensure_ascii=False))
    (OUT/(stem+'.layout.json')).write_text(json.dumps(manifest))
    shutil.rmtree(temp)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source=parse_midi(ROOT/'pianoscope/resources/demos/first-light.mid');source.title='初光'
    prepare_sample('first-light',source,'straight')
    source=parse_midi(edge_phrase());source.title='边界练习 · 双谱表'
    prepare_sample('edge-phrase',source,'triplets')
    report=dict(success=True,samples=[verify(OUT/'first-light'),verify(OUT/'edge-phrase')])
    (artifact_dir('reports')/'v11-independent-exports.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
