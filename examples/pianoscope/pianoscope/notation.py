"""Versioned, deterministic practice notation, independent of PCM and audition.

QN are exact Fractions. Profile 1: nearest endpoint, half-way rounds later;
straight grid 1/4 QN; triplet profile union of 1/4 and 1/3 QN grids.
Profile 1 endpoints move <=1/10 QN and allow two voices. Profile 2 uses
readable-v2.1 inference and four voices. Both conserve all selected source IDs.
"""
from dataclasses import dataclass,field
from fractions import Fraction as F
from collections import defaultdict,Counter
from bisect import bisect_right
from hashlib import sha256
import json
import math
import xml.etree.ElementTree as ET
from .midi import TempoMap

PROFILE=1
TOLERANCE=F(1,10)
MAX_MEASURES=256
MAX_NOTES=5000
KEYS={'Cb':-7,'Gb':-6,'Db':-5,'Ab':-4,'Eb':-3,'Bb':-2,'F':-1,'C':0,'G':1,'D':2,'A':3,'E':4,'B':5,'F#':6,'C#':7,
      'Abm':-7,'Ebm':-6,'Bbm':-5,'Fm':-4,'Cm':-3,'Gm':-2,'Dm':-1,'Am':0,'Em':1,'Bm':2,'F#m':3,'C#m':4,'G#m':5,'D#m':6,'A#m':7}
DURATIONS={F(4):('whole',False),F(3):('half',True),F(2):('half',False),F(3,2):('quarter',True),F(1):('quarter',False),F(3,4):('eighth',True),F(1,2):('eighth',False),F(1,4):('16th',False),F(1,3):('eighth',False)}

class NotationError(ValueError):
    def __init__(self,message,code='NOTATION_TOO_COMPLEX',issues=None):
        super().__init__(message);self.code=code;self.issues=issues or []

def rational(value):
    value=F(value);return [value.numerator,value.denominator]

def tempo_for(score):
    return TempoMap(score.ppqn,[(m['tick'],m.get('tempo_us',round(60e6/m['quarter_bpm']))) for m in score.tempo_map])

def dependency(score):
    """Audition/mute/volume/rate revisions deliberately excluded."""
    raw=[score.score_id,score.source_fingerprint,[(n.id,n.hand,n.hand_source) for n in score.notes]]
    return sha256(json.dumps(raw,separators=(',',':')).encode()).hexdigest()

@dataclass(frozen=True)
class Options:
    rhythm:str='straight'
    staff_mode:str='hands'
    split:int=60
    tracks:tuple=()
    staff_tracks:dict=field(default_factory=dict)
    meter:str='source'
    key:str='source'
    pickup:str='0'
    confirm_defaults:bool=False
    profile:int=PROFILE
    clef_mode:str='standard'

    @classmethod
    def read(cls,raw,score):
        try:
            data=dict(raw)
            data.setdefault('clef_mode','auto_octaves' if data.get('profile')==2 else 'standard')
            data['tracks']=tuple(data['tracks'] if 'tracks' in data else (t['id'] for t in score.tracks))
            opt=cls(**data)
            if (opt.profile,opt.rhythm) not in ((1,'straight'),(1,'triplets'),(2,'auto')) or opt.staff_mode not in ('hands','pitch','tracks'):raise ValueError()
            if not isinstance(opt.split,int) or not 21<=opt.split<=108:raise ValueError()
            if not isinstance(opt.confirm_defaults,bool):raise ValueError()
            valid={t['id'] for t in score.tracks}
            if not opt.tracks or len(set(opt.tracks))!=len(opt.tracks) or not set(opt.tracks)<=valid:raise ValueError()
            if opt.staff_mode=='tracks' and any(opt.staff_tracks.get(t) not in (1,2) for t in opt.tracks):raise ValueError()
            if opt.meter not in ('source','2/4','3/4','4/4','6/8') or opt.key not in ('source','auto',*KEYS):raise ValueError()
            if opt.clef_mode not in ('auto','auto_octaves','standard'):raise ValueError()
            if F(opt.pickup)<0:raise ValueError()
        except (TypeError,ValueError,ZeroDivisionError):
            raise NotationError('请检查制谱选项与所选轨道。','NOTATION_OPTIONS_REQUIRED')
        return opt

def nearest(value,profile):
    grids=[F(1,4)] if profile=='straight' else [F(1,4),F(1,3)]
    candidates=[]
    for grid in grids:
        base=value//grid
        candidates.extend((base*grid,(base+1)*grid))
    return min(candidates,key=lambda x:(abs(x-value),-x))

def split_duration(start,end,triplets):
    """Split syncopation at the next beat, then use legal dotted symbols."""
    pieces=[]
    while start<end:
        limit=end
        if start.denominator!=1:limit=min(limit,F(math.floor(start)+1))
        choices=[d for d in DURATIONS if (triplets or d!=F(1,3)) and d<=limit-start]
        if not choices:raise NotationError('量化后出现无法表示的复合时值；请更换节奏配置。')
        duration=max(choices);pieces.append((start,duration));start+=duration
    return pieces

def build(score,raw,cancelled=lambda:False):
    opt=Options.read(raw,score)
    selected=[n for n in score.notes if n.track_id in opt.tracks]
    if not selected:raise NotationError('当前曲目没有可制谱音符。')
    if len(selected)>MAX_NOTES:raise NotationError(f'制谱范围超过 {MAX_NOTES} 个源音符；请选择较少轨道。')
    if not score.source_fingerprint:raise NotationError('缺少原始 MIDI 来源，请重新打开文件。')
    meters=score.meter_map if opt.meter=='source' else [dict(tick=0,numerator=int(opt.meter[0]),denominator=int(opt.meter[2]),source='user')]
    key_analysis=None
    if opt.key=='auto':
        from .score_spelling import suggest_key
        key_analysis=suggest_key(selected,score.ppqn);keys=[dict(tick=0,**key_analysis)]
    else:keys=score.key_map if opt.key=='source' else [dict(tick=0,key=opt.key,source='user')]
    if not opt.confirm_defaults and any(x.get('source')=='default' for x in [*meters,*keys,*score.tempo_map]):
        raise NotationError('请确认缺失元数据的默认拍号、无升降调号与速度。','NOTATION_OPTIONS_REQUIRED')
    meter_by={F(m['tick'],score.ppqn):m for m in meters}
    for q,m in meter_by.items():
        if (m['numerator'],m['denominator']) not in ((2,4),(3,4),(4,4),(6,8)):
            raise NotationError(f'tick {m["tick"]} 的拍号暂不支持。')
    if 0 not in meter_by:raise NotationError('缺少开头拍号。')
    pickup=F(opt.pickup);first=meter_by[F(0)];full=F(first['numerator']*4,first['denominator'])
    valid_pickup=(pickup*48).denominator==1 if opt.profile==2 else nearest(pickup,opt.rhythm)==pickup
    if pickup and (pickup>=full or not valid_pickup):raise NotationError('弱起长度需小于完整小节并符合所选网格。','NOTATION_OPTIONS_REQUIRED')
    measures=[];q=F(0);end=F(max(score.duration_tick,max(n.key_off_tick for n in selected)),score.ppqn)
    meter=first
    while q<end or not measures:
        if q in meter_by:meter=meter_by[q]
        length=pickup if not measures and pickup else F(meter['numerator']*4,meter['denominator'])
        if any(q<p<q+length for p in meter_by):raise NotationError(f'第 {len(measures)+1} 小节中途变拍，暂不支持。')
        measures.append(dict(id=f'm{len(measures)+1}',number=len(measures)+1,start=q,length=length,meter=dict(meter),pickup=bool(not measures and pickup)))
        q+=length
        if len(measures)>MAX_MEASURES:raise NotationError('谱面超过 256 小节；请选择较短的 MIDI。')
    starts=[m['start'] for m in measures]
    quantized=[];warnings=[];issues=[];normalizations={}
    if opt.profile==2:
        from . import readable
        prepared=readable.quantize(selected,score.ppqn)
    split_value=(lambda a,b,rest=False:readable.split(a,b,rest)) if opt.profile==2 else (lambda a,b,rest=False:split_duration(a,b,opt.rhythm=='triplets'))
    for n in selected:
        if cancelled():raise InterruptedError('已取消')
        start=F(n.start_tick,score.ppqn);stop=F(n.key_off_tick,score.ppqn)
        if opt.profile==2:
            if stop<start:raise NotationError('原始音符时值为负值')
            a,b,record=prepared[n.id];normalizations[n.id]=record
        else:a=nearest(start,opt.rhythm);b=nearest(stop,opt.rhythm)
        mi=max(0,bisect_right(starts,a)-1)+1
        reason=None
        if opt.profile==1 and stop<=start:reason='原始音符时值为零或负值'
        elif a==b:reason='量化后短音塌缩'
        elif opt.profile==1 and max(abs(a-start),abs(b-stop))>TOLERANCE:reason='端点偏移超过 1/10 拍容差'
        if reason:
            issues.append(dict(source_note_id=n.id,source_event=n.source_event,measure=mi,reason=reason,
                track_id=n.track_id,pitch=n.pitch,start_tick=n.start_tick,key_off_tick=n.key_off_tick,
                start_s=n.start_s,duration_qn=rational(stop-start),start_delta=rational(a-start),end_delta=rational(b-stop)))
            continue
        if a!=start or b!=stop:warnings.append(dict(measure=mi,source_note_id=n.id,start_delta=rational(a-start),end_delta=rational(b-stop),message=f'第 {mi} 小节：{n.id} 已整理记谱节奏',kind=normalizations.get(n.id,{}).get('kind','quantized'),normalization=normalizations.get(n.id)))
        staff=opt.staff_tracks[n.track_id] if opt.staff_mode=='tracks' else (2 if n.hand=='left' else 1 if n.hand=='right' else 2 if n.pitch<opt.split else 1) if opt.staff_mode=='hands' else 2 if n.pitch<opt.split else 1
        quantized.append((a,b,staff,n))
    if opt.profile==2:
        quantized=readable.align_releases(quantized,normalizations)
        by_warning={w['source_note_id']:w for w in warnings}
        for a,b,staff,n in quantized:
            if normalizations[n.id].get('release_alignment'):
                warning=by_warning.get(n.id)
                values=dict(measure=max(1,bisect_right(starts,a)),source_note_id=n.id,start_delta=rational(a-F(n.start_tick,score.ppqn)),end_delta=rational(b-F(n.key_off_tick,score.ppqn)),message='整理音长以衔接相邻起音',kind='duration_aligned',normalization=normalizations[n.id])
                if warning:warning.update(values)
                else:warnings.append(values)
    if issues:
        counts=Counter(i['reason'] for i in issues)
        summary='；'.join(f'{reason} {count} 个' for reason,count in counts.items())
        raise NotationError(f'{len(issues)} 个源音符无法按当前节奏生成：{summary}。首处在第 {issues[0]["measure"]} 小节。',issues=issues)
    if opt.profile==2:
        final=max(b for a,b,staff,n in quantized)
        while measures[-1]['start']+measures[-1]['length']<final:
            last=measures[-1];q=last['start']+last['length'];meter=meter_by.get(q,last['meter']);length=F(meter['numerator']*4,meter['denominator'])
            measures.append(dict(id=f'm{len(measures)+1}',number=len(measures)+1,start=q,length=length,meter=dict(meter),pickup=False));starts.append(q)
            if len(measures)>MAX_MEASURES:raise NotationError('谱面超过 256 小节；请选择较短的 MIDI。')
    # Same-onset/same-duration distinct pitches form chords; identical pitches
    # must keep separate voices and separate source identities.
    groups=[];bucket={}
    for a,b,staff,n in sorted(quantized,key=lambda v:(v[0],-v[1],v[2],v[3].pitch,v[3].id)):
        key=(a,b,staff)
        group=next((g for g in bucket.get(key,[]) if n.pitch not in {v.pitch for v in g['notes']}),None)
        if group is None:
            group=dict(start=a,end=b,staff=staff,notes=[]);groups.append(group);bucket.setdefault(key,[]).append(group)
        group['notes'].append(n)
    max_voices=4 if opt.profile==2 else 2
    ends={1:[F(-1)]*max_voices,2:[F(-1)]*max_voices}
    for group in groups:
        def fits(e):
            if e>group['start']:return False
            if opt.profile==2 and e>=0:
                try:readable.split(e,group['start'])
                except NotationError:return False
            return True
        available=next((v for v,e in enumerate(ends[group['staff']]) if fits(e)),None)
        if available is None:
            if opt.profile==2:
                try:groups=readable.arrange(quantized,max_voices)
                except NotationError as exc:
                    for issue in exc.issues:
                        issue.setdefault('measure',bisect_right(starts,F(*issue.get('onset',[0,1]))))
                    raise
                break
            mi=bisect_right(starts,group['start']);ids=[n.id for n in group['notes']]
            label='四个' if max_voices==4 else '两个'
            raise NotationError(f'第 {mi} 小节谱表 {group["staff"]} 超过{label}声部：'+', '.join(ids),issues=[dict(measure=mi,source_note_ids=ids,reason=f'超过{label}声部')])
        group['voice']=available+1;ends[group['staff']][available]=group['end']
    tempo=tempo_for(score);events=[];source_index={n.id:dict(pitch=n.pitch,source_event=n.source_event,track_id=n.track_id,hand=n.hand,
        start_tick=n.start_tick,key_off_tick=n.key_off_tick,start_s=n.start_s,key_off_s=n.key_off_s,notation_event_ids=[],normalization=normalizations.get(n.id)) for n in selected}
    voices={staff:max([g['voice'] for g in groups if g['staff']==staff] or [1]) for staff in (1,2)}
    def pieces(a,b):
        boundaries=sorted({a,b,*[F(k['tick'],score.ppqn) for k in keys if a<F(k['tick'],score.ppqn)<b]})
        return [part for begin,finish in zip(boundaries,boundaries[1:]) for part in split_value(begin,finish,True)]
    def add(m,staff,voice,a,d,notes):
        for j,n in enumerate(notes or [None]):
            eid=f'e{len(events)}';event=dict(id=eid,measure_id=m['id'],staff=staff,voice=voice,onset=a,duration=d,
                pitch=n.pitch if n else None,hand=n.hand if n else 'unassigned',source_note_ids=[n.id] if n else [],
                chord=bool(j),tie_start=False,tie_stop=False,source_display_spans=[])
            events.append(event)
            if n:source_index[n.id]['notation_event_ids'].append(eid)
    for m in measures:
        for staff in (1,2):
            active_voices=sorted({g['voice'] for g in groups if g['staff']==staff and g['start']<m['start']+m['length'] and g['end']>m['start']}) or [1]
            for voice in (active_voices if opt.profile==2 else range(1,voices[staff]+1)):
                cursor=m['start'];limit=cursor+m['length']
                for g in groups:
                    if g['staff']!=staff or g['voice']!=voice:continue
                    a=max(g['start'],m['start']);b=min(g['end'],limit)
                    if a>=b:continue
                    if cursor<a:
                        for pos,dur in pieces(cursor,a):add(m,staff,voice,pos,dur,[])
                    # Key changes split voices at exact notated positions.
                    boundaries=sorted({a,b,*[F(k['tick'],score.ppqn) for k in keys if a<F(k['tick'],score.ppqn)<b]})
                    for begin,finish in zip(boundaries,boundaries[1:]):
                        try:parts=split_value(begin,finish)
                        except NotationError as exc:raise NotationError(f'第 {m["number"]} 小节：{exc}',issues=[dict(measure=m['number'],source_note_ids=[n.id for n in g['notes']],reason=str(exc))])
                        for pos,dur in parts:add(m,staff,voice,pos,dur,g['notes'])
                    cursor=b
                if cursor<limit:
                    for pos,dur in pieces(cursor,limit):add(m,staff,voice,pos,dur,[])
    by_id={e['id']:e for e in events};source_notes={n.id:n for n in selected}
    for nid,index in source_index.items():
        chain=[by_id[i] for i in index['notation_event_ids']];n=source_notes[nid]
        for i,e in enumerate(chain):
            e['tie_stop']=i>0;e['tie_start']=i<len(chain)-1
            a=n.start_s if i==0 else max(n.start_s,min(n.key_off_s,tempo.at(e['onset']*score.ppqn)))
            b=n.key_off_s if i==len(chain)-1 else max(a,min(n.key_off_s,tempo.at((e['onset']+e['duration'])*score.ppqn)))
            e['source_display_spans']=[dict(source_note_id=nid,start_s=a,end_s=b,boundary_source='source_on_off / notation_tick via source_tempo_map')]
    if set(source_index)!={n.id for n in selected} or any(not v['notation_event_ids'] for v in source_index.values()):raise AssertionError('source conservation')
    dep=dependency(score)
    from .score_spelling import plan_clefs
    plan_clefs(measures,events,opt.clef_mode)
    identity=sha256((score.source_fingerprint+dep+json.dumps(vars(opt),sort_keys=True,separators=(',',':'))+(readable.RULE_VERSION if opt.profile==2 else '')).encode()).hexdigest()[:24]
    doc=dict(id=identity,score_id=score.score_id,source_fingerprint=score.source_fingerprint,source_dependency=dep,
        notation_revision=identity,profile=opt.profile,title=score.title,options=vars(opt),measures=measures,events=events,
        source_note_index=source_index,warnings=warnings,unassigned_notes=sum(n.hand=='unassigned' for n in selected),
        metadata_sources=dict(meters=meters,keys=keys,tempos=score.tempo_map,original_keys=score.key_map),key_analysis=key_analysis,voices=voices,voice_stride=max_voices,ppqn=score.ppqn)
    return doc

def serialize(doc):
    if isinstance(doc,F):return rational(doc)
    if isinstance(doc,dict):return {k:serialize(v) for k,v in doc.items()}
    if isinstance(doc,(list,tuple)):return [serialize(v) for v in doc]
    return doc

def pitch_spelling(pitch,key):
    values=[('C',0),('D',-1),('D',0),('E',-1),('E',0),('F',0),('G',-1),('G',0),('A',-1),('A',0),('B',-1),('B',0)] if KEYS[key]<0 else [('C',0),('C',1),('D',0),('D',1),('E',0),('F',0),('F',1),('G',0),('G',1),('A',0),('A',1),('B',0)]
    step,alter=values[pitch%12]
    # Keys with seven accidentals require B#/Cb rather than cancellation marks.
    if key in ('C#','A#m') and pitch%12==0:return 'B',1,pitch//12-2
    if key in ('Cb','Abm') and pitch%12==11:return 'C',-1,pitch//12
    return step,alter,pitch//12-1

def musicxml(doc):
    E=ET.SubElement
    root=ET.Element('score-partwise',version='4.0');E(E(root,'work'),'work-title').text=doc['title']
    identification=E(root,'identification');encoding=E(identification,'encoding');E(encoding,'software').text='PianoScope profile '+str(doc['profile'])
    misc=E(identification,'miscellaneous')
    E(misc,'miscellaneous-field',name='pianoscope-source-fingerprint').text=doc['source_fingerprint']
    E(misc,'miscellaneous-field',name='pianoscope-notation-revision').text=doc['notation_revision']
    E(misc,'miscellaneous-field',name='pianoscope-ppqn').text=str(doc['ppqn'])
    E(misc,'miscellaneous-field',name='pianoscope-source-note-index').text=json.dumps(doc['source_note_index'],ensure_ascii=False,separators=(',',':'))
    E(misc,'miscellaneous-field',name='pianoscope-source-metadata').text=json.dumps(doc['metadata_sources'],ensure_ascii=False,separators=(',',':'))
    pl=E(root,'part-list');E(E(pl,'score-part',id='P1'),'part-name').text='Piano';part=E(root,'part',id='P1')
    divisions=math.lcm(doc['ppqn'],48 if doc['profile']==2 else 12)
    from .readable import DURATIONS as READABLE_DURATIONS,TRIPLETS
    durations=READABLE_DURATIONS if doc['profile']==2 else DURATIONS
    tuplets=set(TRIPLETS) if doc['profile']==2 else {F(1,3)}
    stride=doc.get('voice_stride',2)
    grouped=defaultdict(list)
    for event in doc['events']:grouped[event['measure_id']].append(event)
    key_changes={F(k['tick'],doc['ppqn']):k for k in doc['metadata_sources']['keys']}
    def key_at(pos):return next(k for q,k in sorted(key_changes.items(),reverse=True) if q<=pos)
    def clef_at(measure,staff):
        return measure.get('clefs',{}).get(str(staff),dict(sign='G' if staff==1 else 'F',line=2 if staff==1 else 4,octave=0))
    def octave_direction(measure,staff,kind,octave):
        direction=E(measure,'direction',placement='above' if octave>0 else 'below')
        E(E(direction,'direction-type'),'octave-shift',type=kind,size='8',number=str(staff))
        E(direction,'staff').text=str(staff)
    for mi,m in enumerate(doc['measures']):
        measure=E(part,'measure',number=str(m['number']),id=m['id'])
        if m['pickup']:measure.set('implicit','yes')
        k=key_at(m['start']);previous=doc['measures'][mi-1] if mi else None
        meter_changed=not previous or any(previous['meter'][a]!=m['meter'][a] for a in ('numerator','denominator'))
        # Key state includes any change inside the preceding measure.
        key_changed=not previous or key_at(m['start']-F(1,divisions))['key']!=k['key']
        clef_changes=[staff for staff in (1,2) if not previous or any(clef_at(m,staff)[a]!=clef_at(previous,staff)[a] for a in ('sign','line'))]
        attrs=E(measure,'attributes') if mi==0 or meter_changed or key_changed or clef_changes else None
        if mi==0:E(attrs,'divisions').text=str(divisions)
        if mi==0 or key_changed:
            key=E(attrs,'key');E(key,'fifths').text=str(KEYS[k['key']]);E(key,'mode').text='minor' if k['key'].endswith('m') else 'major'
        if meter_changed:
            meter=E(attrs,'time');E(meter,'beats').text=str(m['meter']['numerator']);E(meter,'beat-type').text=str(m['meter']['denominator'])
        if mi==0:
            E(attrs,'staves').text='2'
        for staff in clef_changes:
            state=clef_at(m,staff);clef=E(attrs,'clef',number=str(staff))
            E(clef,'sign').text=state['sign'];E(clef,'line').text=str(state['line'])
        local_tempos=[t for t in doc['metadata_sources']['tempos'] if m['start']<=F(t['tick'],doc['ppqn'])<m['start']+m['length']]
        if doc['profile']==2:
            # Dense MIDI tempo ramps are playback data, not hundreds of stacked
            # metronome labels. Preserve every exact sound + offset; print one
            # per-measure range. No tempo-map event is removed or quantized.
            for tempo in local_tempos:
                sound=E(measure,'sound',tempo=format(tempo['quarter_bpm'],'.12g'))
                E(sound,'offset').text=str(int((F(tempo['tick'],doc['ppqn'])-m['start'])*divisions))
            if local_tempos:
                values=[t['quarter_bpm'] for t in local_tempos]
                label=lambda v:format(v,'.2f').rstrip('0').rstrip('.')
                text=label(values[0]) if max(values)-min(values)<.01 else label(min(values))+'–'+label(max(values))
                direction=E(measure,'direction',placement='above');met=E(E(direction,'direction-type'),'metronome')
                E(met,'beat-unit').text='quarter';E(met,'per-minute').text=text
                E(direction,'offset').text=str(int((F(local_tempos[0]['tick'],doc['ppqn'])-m['start'])*divisions));E(direction,'staff').text='1'
        else:
            for tempo in local_tempos:
                pos=F(tempo['tick'],doc['ppqn'])
                direction=E(measure,'direction',placement='above');met=E(E(direction,'direction-type'),'metronome');E(met,'beat-unit').text='quarter';E(met,'per-minute').text=format(tempo['quarter_bpm'],'.12g')
                E(direction,'offset').text=str(int((pos-m['start'])*divisions));E(direction,'staff').text='1';E(direction,'sound',tempo=format(tempo['quarter_bpm'],'.12g'))
        first=True
        for staff in (1,2):
            staff_voices=sorted({e['voice'] for e in grouped[m['id']] if e['staff']==staff})
            for voice in staff_voices:
                if not first:E(E(measure,'backup'),'duration').text=str(int(m['length']*divisions))
                first=False
                if voice==staff_voices[0]:
                    octave=clef_at(m,staff)['octave'];old_octave=clef_at(previous,staff)['octave'] if previous else 0
                    if old_octave!=octave:
                        if old_octave:octave_direction(measure,staff,'stop',old_octave)
                        if octave:octave_direction(measure,staff,'down' if octave>0 else 'up',octave)
                events=[e for e in grouped[m['id']] if e['staff']==staff and e['voice']==voice]
                accidental_state={}
                timed=[e for e in events if not e['chord']]
                positions={e['id']:i for i,e in enumerate(timed)}
                for i,e in enumerate(events):
                    if staff==1 and voice==1 and e['onset'] in key_changes and e['onset']!=m['start'] and not e['chord']:
                        key=E(E(measure,'attributes'),'key');E(key,'fifths').text=str(KEYS[key_changes[e['onset']]['key']]);accidental_state={}
                    note=E(measure,'note',id=e['id'])
                    if e['chord']:E(note,'chord')
                    full_rest=doc['profile']==2 and e['pitch'] is None and e['onset']==m['start'] and e['duration']==m['length']
                    if e['pitch'] is None:E(note,'rest',**({'measure':'yes'} if full_rest else {}))
                    else:
                        p=E(note,'pitch');step,alter,octave=pitch_spelling(e['pitch'],key_at(e['onset'])['key']);E(p,'step').text=step
                        if alter:E(p,'alter').text=str(alter)
                        E(p,'octave').text=str(octave)
                    E(note,'duration').text=str(int(e['duration']*divisions))
                    for tag,kind in [('tie_stop','stop'),('tie_start','start')]:
                        if e[tag]:E(note,'tie',type=kind)
                    E(note,'voice').text=str((staff-1)*stride+voice)
                    kind,dotted=durations[e['duration']]
                    if not full_rest:E(note,'type').text=kind
                    if dotted and not full_rest:E(note,'dot')
                    if e['duration'] in tuplets:
                        tm=E(note,'time-modification');E(tm,'actual-notes').text='3';E(tm,'normal-notes').text='2';E(tm,'normal-type').text=kind
                    if e['pitch'] is not None and doc['voices'][staff]>1:E(note,'stem').text='up' if voice%2 else 'down'
                    E(note,'staff').text=str(staff)
                    # Beams include every short-note level, never bridge rests,
                    # beat groups or different tuplet families.
                    levels={'eighth':1,'16th':2,'32nd':3,'64th':4}
                    group=e['duration']*3 if e['duration'] in tuplets else F(3,2) if m['meter']['denominator']==8 else F(1)
                    index=positions[e['id']] if not e['chord'] else None
                    def connected(j,level=1):
                        if not 0<=j<len(timed):return False
                        other=timed[j];other_kind=durations[other['duration']][0]
                        return other['pitch'] is not None and levels.get(other_kind,0)>=level and (other['duration'] in tuplets)==(e['duration'] in tuplets) and (other['onset']-m['start'])//group==(e['onset']-m['start'])//group
                    if kind in levels and e['pitch'] is not None and index is not None:
                        for level in range(1,levels[kind]+1):
                            prev=connected(index-1,level);nxt=connected(index+1,level)
                            if prev or nxt:E(note,'beam',number=str(level)).text='continue' if prev and nxt else 'end' if prev else 'begin'
                            elif level>1 and (connected(index-1) or connected(index+1)):
                                E(note,'beam',number=str(level)).text='forward hook' if connected(index+1) else 'backward hook'
                    if e['tie_start'] or e['tie_stop'] or e['duration'] in tuplets:
                        notation=E(note,'notations')
                        for tag,t in [('tie_stop','stop'),('tie_start','start')]:
                            if e[tag]:E(notation,'tied',type=t)
                        if e['duration'] in tuplets and index is not None:
                            def adjacent_tuplet(j):
                                return 0<=j<len(timed) and timed[j]['duration']==e['duration'] and (timed[j]['onset']-m['start'])//group==(e['onset']-m['start'])//group
                            if not adjacent_tuplet(index-1):E(notation,'tuplet',type='start',number='1',bracket='yes')
                            if not adjacent_tuplet(index+1):E(notation,'tuplet',type='stop',number='1')
            if mi==len(doc['measures'])-1 and clef_at(m,staff)['octave']:
                octave_direction(measure,staff,'stop',clef_at(m,staff)['octave'])
    return '<?xml version="1.0" encoding="utf-8"?>\n'+ET.tostring(root,encoding='unicode')
