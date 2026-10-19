"""Readable-v2.1: prefer conventional rhythms over performance jitter.

All units are quarter notes. Sixteenth-note onset lattice first; use finer
binary subdivisions for real short runs, triplets only with local evidence.
Every normalization is a notation-only copy with original source provenance.
"""
from collections import defaultdict
from fractions import Fraction as F
from functools import lru_cache
import math

BINARY={F(6):('whole',True),F(4):('whole',False),F(3):('half',True),F(2):('half',False),
 F(3,2):('quarter',True),F(1):('quarter',False),F(3,4):('eighth',True),F(1,2):('eighth',False),
 F(3,8):('16th',True),F(1,4):('16th',False),F(3,16):('32nd',True),F(1,8):('32nd',False),F(1,16):('64th',False)}
TRIPLETS={F(8,3):'whole',F(4,3):'half',F(2,3):'quarter',F(1,3):'eighth',F(1,6):'16th',F(1,12):'32nd'}
DURATIONS={**BINARY,**{d:(kind,False) for d,kind in TRIPLETS.items()}}
LENGTHS=tuple(sorted({F(k,16) for k in range(1,129)}|{F(k,12) for k in range(1,97)}))
RULE_VERSION='readable-v2.1'
ONSET_TOLERANCE=F(1,8)


def rounded(value,division):
    base=value*division;lower=base//1
    return F(lower+(base-lower>=F(1,2)),division)


def onset(note,ppqn):
    return F(note.start_tick,ppqn)


def onset_cohorts(notes,ppqn):
    """Bound chord spread; never merge repeated same-pitch attacks or runs."""
    by_track=defaultdict(set)
    for n in notes:by_track[getattr(n,'track_id',None)].add(n.start_tick)
    rapid=set()
    for track,ticks in by_track.items():
        times=sorted(ticks)
        for a,b,c in zip(times,times[1:],times[2:]):
            x,y=b-a,c-b
            if F(ppqn,16)<=min(x,y) and max(x,y)<=F(ppqn,8) and abs(x-y)<=max(2,min(x,y)/5):
                rapid.update((track,t) for t in (a,b,c))
    groups=[]
    for n in sorted(notes,key=lambda n:(n.start_tick,n.id)):
        a=onset(n,ppqn);long=n.key_off_tick-n.start_tick>=F(ppqn,4)
        last=groups[-1] if groups else None
        protected=(getattr(n,'track_id',None),n.start_tick) in rapid
        if last and a-last[0]<F(1,8) and (
            a==last[0] or long and not protected and all(v.key_off_tick-v.start_tick>=F(ppqn,4) and (getattr(v,'track_id',None),v.start_tick) not in rapid for v in last[1])
        ) and (getattr(n,'track_id',None),n.pitch) not in {(getattr(v,'track_id',None),v.pitch) for v in last[1]}:
            last[1].append(n)
        else:groups.append((a,[n]))
    return [(sorted(onset(n,ppqn) for n in ns)[len(ns)//2],ns) for _,ns in groups]


def onset_grids(notes,ppqn):
    return cohort_grids(onset_cohorts(notes,ppqn),ppqn)


def cohort_grids(cohorts,ppqn):
    beats=defaultdict(list)
    for a,ns in cohorts:beats[math.floor(a)].append((a,ns))
    grids={}
    for beat,groups in beats.items():
        positions=sorted({a for a,ns in groups})
        # Require at least two off-beat attacks close to the same triplet
        # family. An isolated slightly early/late note is insufficient evidence.
        triplets=[]
        offbeat=[a for a in positions if abs(rounded(a,4)-a)>F(1,24)]
        wide=sorted({a for b in (beat-1,beat,beat+1) for a,ns in beats.get(b,[])})
        thirds={int(rounded(a,3)*3) for a in wide if abs(rounded(a,3)-a)<=F(1,48)}
        if any({p,p+2,p+4}<=thirds for p in thirds) and all(abs(rounded(a,3)-a)<=F(1,48) for a in offbeat):triplets.append(3)
        for div in (3,6,12):
            fitted=[a for a in positions if abs(rounded(a,div)-a)<=F(1,48)]
            points={int(rounded(a,div)*div) for a in fitted}
            run=any({p,p+1,p+2}<=points for p in points)
            if div==3:run=run or any({p,p+1}<=points and p%3==1 for p in points)
            if run and len(offbeat)>=2 and all(abs(rounded(a,div)-a)<=F(1,48) for a in offbeat):
                triplets.append(div)
        if triplets:grids[beat]=min(triplets);continue
        short=[F(n.key_off_tick-n.start_tick,ppqn) for _,ns in groups for n in ns if n.key_off_tick>n.start_tick]
        minimum=16 if any(d<F(3,32) for d in short) else 8 if any(d<F(3,16) for d in short) else 4
        for div in (4,8,16):
            if div<minimum:continue
            snaps=[rounded(a,div) for a in positions]
            if len(set(snaps))<len(snaps):continue
            if all(abs(rounded(a,div)-a)<=ONSET_TOLERANCE for a,ns in groups):
                grids[beat]=div;break
        else:grids[beat]=16
    return grids


def quantize(notes,ppqn):
    cohorts=onset_cohorts(notes,ppqn);grids=cohort_grids(cohorts,ppqn);result={}
    for a,ns in cohorts:
        div=grids[math.floor(a)]
        for n in ns:
            start,end,record=normalize(n,ppqn,div,a)
            record['chord_cohort_size']=len(ns)
            result[n.id]=(start,end,record)
    return result


@lru_cache(maxsize=8192)
def release(ticks,ppqn,division=4):
    raw=F(ticks,ppqn)
    if ticks==0:return F(1,16),dict(kind='short_fill',gate=[1,1],early_release_ticks=0,fit_error=[0,1],needs_review=True)
    if ticks<0:raise ValueError('原始音符时值为负值')
    unit=min(F(1,4),F(1,division)) if division in (4,8,16) else F(1,4)
    lengths={d for d in LENGTHS if (d/unit).denominator==1 or division%3==0 and (d*division).denominator==1}
    # Keep the search bounded even for long held notes.
    for gate in (F(1),F(19,20),F(99,100)):
        target=raw/gate
        for div in (int(1/unit),division):
            center=round(target*div)
            lengths.update(F(k,div) for k in range(max(1,center-2),center+3))
    best=None
    for length in sorted(lengths):
        error,gate,early=min((abs(F(ticks+early,ppqn)-length*gate),gate,early)
            for gate in (F(1),F(19,20),F(99,100)) for early in (0,1))
        tolerance=max(F(2,ppqn),unit/2)
        fit=F(0) if error<=tolerance else error
        whole=int(length//4);fragments=spell(length-whole*4)
        complexity=1 if length in DURATIONS else whole+len(fragments) if fragments is not None else 1000000
        rank=(fit,complexity,abs(length-raw),error,-gate,early,length)
        if best is None or rank<best[0]:best=(rank,length,gate,early,error)
    _,length,gate,early,error=best
    return length,dict(kind='release_recovered' if gate!=1 or early else 'duration_aligned',
        gate=[gate.numerator,gate.denominator],early_release_ticks=early,
        fit_error=[error.numerator,error.denominator],needs_review=error>max(F(2,ppqn),unit/2))


def normalize(note,ppqn,division,anchor=None):
    start=F(note.start_tick,ppqn);point=onset(note,ppqn) if anchor is None else anchor
    a=rounded(point,division)
    if division%3==0:a=min((a,rounded(point,4)),key=lambda v:(abs(v-point),v.denominator%3==0,-v))
    duration,record=release(note.key_off_tick-note.start_tick,ppqn,division)
    record=dict(record,rule_version=RULE_VERSION,onset_division=division,
        original_duration=[note.key_off_tick-note.start_tick,ppqn],
        inferred_duration=[duration.numerator,duration.denominator],
        onset_tolerance=[ONSET_TOLERANCE.numerator,ONSET_TOLERANCE.denominator])
    record['needs_review']=record['needs_review'] or abs(a-start)>ONSET_TOLERANCE
    return a,a+duration,record


@lru_cache(maxsize=4096)
def spell(length,rest=False):
    """Minimum symbols on a 1/48 QN lattice; no greedy residual loss."""
    units=length*48
    if units.denominator!=1 or units<0:return None
    count=int(units)
    # A caller splits at beat boundaries, so this DP is at most one beat.
    best=[None]*(count+1);best[0]=()
    binary=length.denominator&(length.denominator-1)==0
    for i in range(1,count+1):
        for duration in sorted(DURATIONS,reverse=True):
            if binary and duration in TRIPLETS:continue
            if rest and DURATIONS[duration][1]:continue
            size=int(duration*48)
            if size<=i and best[i-size] is not None:
                candidate=(duration,)+best[i-size]
                rank=lambda seq:(len(seq),sum(d in TRIPLETS for d in seq),tuple(-d for d in seq))
                if best[i] is None or rank(candidate)<rank(best[i]):best[i]=candidate
    return best[count]


def split(start,end,rest=False):
    from .notation import NotationError
    result=[]
    while start<end:
        if not rest and end-start in DURATIONS:
            result.append((start,end-start));break
        # Preserve whole/half/dotted values at beats; split fractional positions
        # before crossing the next beat so ties and tuplet groups stay readable.
        limit=min(end,F(math.floor(start)+1)) if start.denominator!=1 else end
        remaining=limit-start
        if start.denominator==1 and remaining>4:
            length=max(d for d in DURATIONS if d<=remaining and d>=1 and (not rest or not DURATIONS[d][1]))
            parts=(length,)
        else:parts=spell(remaining,rest)
        if parts is None:raise NotationError('整理后出现无法表示的混合节奏，请检查此处音符。')
        for duration in parts:result.append((start,duration));start+=duration
    return result


def arrange(quantized,max_voices=4):
    """Pack onset cohorts, then segment partial chord releases with ties.

    Different note lengths alone do not require different voices. Prefer a free
    rhythmic strand, compact only when needed, and never put overlapping same
    pitches into one voice. Caller retains every original note and source span.
    """
    from .notation import NotationError
    cohorts=[];by_start={}
    for a,b,staff,n in sorted(quantized,key=lambda v:(v[0],v[2],v[3].pitch,v[3].id)):
        key=(a,staff)
        cohort=next((c for c in by_start.get(key,[]) if n.pitch not in {v[2].pitch for v in c['members']}),None)
        if cohort is None:
            cohort=dict(start=a,staff=staff,members=[]);cohorts.append(cohort);by_start.setdefault(key,[]).append(cohort)
        cohort['members'].append((a,b,n))
    bins={1:[[] for _ in range(max_voices)],2:[[] for _ in range(max_voices)]}
    for cohort in cohorts:
        staff=cohort['staff'];members=cohort['members'];a=cohort['start'];end=max(b for _,b,_ in members)
        candidates=[]
        for voice,existing in enumerate(bins[staff]):
            overlap=[(x,y,n) for x,y,n in existing if y>a]
            if existing and not overlap:
                try:split(max(y for x,y,n in existing),a)
                except NotationError:continue
            if any(x<b and a<y and n.pitch==new.pitch for x,y,n in overlap for _,b,new in members):continue
            # Avoid a new tiny mixed-lattice fragment that cannot be spelled.
            intervals=overlap+members;points=sorted({q for x,y,n in intervals for q in (x,y)})
            valid=True
            for x,y in zip(points,points[1:]):
                if any(start<=x<stop for start,stop,n in intervals):
                    try:split(x,y)
                    except NotationError:valid=False;break
            if not valid:continue
            center=sum(n.pitch for _,_,n in members)/len(members)
            distance=abs(center-sum(n.pitch for _,_,n in overlap)/len(overlap)) if overlap else 0
            candidates.append(((bool(overlap),len(points) if overlap else 0,distance,voice),voice))
        if not candidates:
            raise NotationError('同音重叠或混合节奏无法在四个声部内完整表示。',issues=[dict(source_note_ids=[n.id for _,_,n in members],reason='同音重叠或混合节奏超过四声部',onset=[a.numerator,a.denominator])])
        voice=min(candidates)[1];bins[staff][voice].extend(members)
    result=[]
    for staff,voices in bins.items():
        for voice,notes in enumerate(voices,1):
            if not notes:continue
            points=sorted({q for a,b,n in notes for q in (a,b)})
            for a,b in zip(points,points[1:]):
                active=sorted((n for x,y,n in notes if x<=a<y),key=lambda n:(n.pitch,n.id))
                if active:result.append(dict(start=a,end=b,staff=staff,voice=voice,notes=active))
    return sorted(result,key=lambda g:(g['start'],g['staff'],g['voice']))


def align_releases(quantized,records):
    """Close only unspellable <1/16-QN rests before a staff's next attack.

    This is an explicit notation-only adjustment, never a change to source off
    times. It avoids representing humanization as 1/48-QN rest fragments.
    """
    from bisect import bisect_left
    from .notation import NotationError
    attacks={staff:sorted({a for a,b,s,n in quantized if s==staff}) for staff in (1,2)}
    result=[]
    for a,b,staff,n in quantized:
        # A zero source has one explicit short-fill symbol. Never disguise it as
        # a release adjustment or extend it to another attack.
        if records[n.id]['kind']=='short_fill':
            result.append((a,b,staff,n));continue
        values=attacks[staff];i=bisect_left(values,b)
        if i<len(values) and 0<values[i]-b<F(1,16) and spell(values[i]-b) is None:
            end=values[i]
            try:split(a,end)
            except NotationError:pass
            else:
                delta=end-b;b=end;record=records[n.id]
                record.update(kind='duration_aligned',needs_review=True,release_alignment=[delta.numerator,delta.denominator],inferred_duration=[(b-a).numerator,(b-a).denominator])
        result.append((a,b,staff,n))
    return result
