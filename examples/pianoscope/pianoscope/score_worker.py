"""One isolated native score process per preview. No device or UI imports."""
import json
import sys
import traceback
from dataclasses import fields
from pathlib import Path
from .midi import Score,Note
from .notation import build,musicxml,serialize,tempo_for,NotationError

def prepare(request,directory):
    from .engraving import engrave
    data=request['score'];data['notes']=[Note(**n) for n in data['notes']];score=Score(**data)
    doc=build(score,request['options']);xml=musicxml(doc)
    shorts=sum((v.get('normalization') or {}).get('kind')=='short_fill' for v in doc['source_note_index'].values())
    caption=f'练习谱 · 已整理节奏（短音补足 {shorts} 个）；密集速度以范围标记' if doc['profile']==2 else None
    manifest=engrave(xml,score.title,directory,caption=caption)
    by_id={e['id']:e for e in doc['events']};measures={m['id']:m for m in doc['measures']};seen=set();tempo=tempo_for(score)
    for pi,page in enumerate(manifest['pages']):
        if doc['profile']==2:
            for system in page['systems']:
                x,y,w,h=system['bbox']
                if x<0 or y<55 or x+w>page['width'] or y+h>page['height']-40:
                    raise NotationError(f'第 {pi+1} 页谱行超出可打印范围，拒绝发布裁切谱面。')
        if len(page['glyphs'])>2000:raise NotationError('单页符号超过 2,000；请减少制谱范围。')
        for glyph in page['glyphs']:
            event=by_id.get(glyph['event_id'])
            if event is None:raise NotationError('排版器返回未知音符 ID。')
            seen.add(event['id'])
            glyph.update(serialize({k:event[k] for k in ('source_note_ids','hand','pitch','source_display_spans','onset','duration','staff','voice')}))
            glyph['seek_s']=event['source_display_spans'][0]['start_s'] if event['source_display_spans'] else tempo.at(event['onset']*score.ppqn)
        for measure in page['measures']:
            m=measures[measure['id']];measure.update(number=m['number'],start_s=tempo.at(m['start']*score.ppqn),end_s=tempo.at((m['start']+m['length'])*score.ppqn))
            anchors=[]
            # Actual glyph positions anchor every event (including rests).
            for g in page['glyphs']:
                if g['measure_id']==m['id']:
                    from fractions import Fraction
                    anchors.append(dict(qn=Fraction(*g['onset']),x=g['bbox'][0]))
            # Chord heads share an onset. Keep the leftmost actual head.
            unique={}
            for a in anchors:unique[a['qn']]=min(unique.get(a['qn'],a['x']),a['x'])
            x,y,w,h=measure['bbox']
            unique.setdefault(m['start'],x)
            unique[m['start']+m['length']]=x+w
            # Add notated beats AND every original tempo change. Interpolation
            # in source seconds is then valid only inside one tempo segment.
            points=sorted(unique.items());extra=set();unit=Fraction(4,m['meter']['denominator'])
            pos=m['start']
            while pos<m['start']+m['length']:extra.add(pos);pos+=unit
            extra.update(Fraction(t['tick'],score.ppqn) for t in score.tempo_map if m['start']<=Fraction(t['tick'],score.ppqn)<m['start']+m['length'])
            for pos in extra:
                if pos in unique:continue
                for (a,ax),(b,bx) in zip(points,points[1:]):
                    if a<=pos<=b:unique[pos]=ax+(bx-ax)*float((pos-a)/(b-a));break
            measure['anchors']=[dict(time_s=tempo.at(qn*score.ppqn),x=v,qn=[qn.numerator,qn.denominator]) for qn,v in sorted(unique.items())]
    if seen!=set(by_id):raise NotationError('排版器遗漏记谱事件，拒绝发布。')
    manifest.update(notation_id=doc['id'],notation_revision=doc['notation_revision'],layout_revision=('a4-readable-v2.1-' if doc['profile']==2 else 'a4-v1-')+doc['id'])
    Path(directory,'document.json').write_text(json.dumps(serialize(doc),ensure_ascii=False),encoding='utf-8')
    Path(directory,'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')

def main():
    directory=Path(sys.argv[1]);request=json.loads((directory/'request.json').read_text())
    try:
        prepare(request,directory);result=dict(success=True)
    except Exception as exc:
        traceback.print_exc()
        message='本地制谱依赖或资源不可用，请按安装说明检查。' if isinstance(exc,(OSError,ImportError)) else str(exc)
        result=dict(success=False,error=dict(code=getattr(exc,'code','NOTATION_ENGINE_UNAVAILABLE'),message=message,issues=getattr(exc,'issues',[])))
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    return 0 if result['success'] else 1

if __name__=='__main__':raise SystemExit(main())
