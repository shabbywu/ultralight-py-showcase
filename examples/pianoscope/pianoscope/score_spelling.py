"""Notation-only key suggestions and stable range-based clef/ottava planning."""
from fractions import Fraction as F
import math

# Krumhansl–Kessler pitch-class profiles, also documented by music21:
# https://music21.org/music21docs/moduleReference/moduleAnalysisDiscrete.html
MAJOR=(6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88)
MINOR=(6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17)
MAJOR_KEYS=('C','Db','D','Eb','E','F','F#','G','Ab','A','Bb','B')
MINOR_KEYS=('Cm','C#m','Dm','Ebm','Em','Fm','F#m','Gm','G#m','Am','Bbm','Bm')


def suggest_key(notes,ppqn):
    histogram=[0.]*12
    for n in notes:
        histogram[n.pitch%12]+=max(.1,min((n.key_off_tick-n.start_tick)/ppqn,4))
    centered=[v-sum(histogram)/12 for v in histogram]
    norm=math.sqrt(sum(v*v for v in centered));candidates=[]
    for keys,profile in ((MAJOR_KEYS,MAJOR),(MINOR_KEYS,MINOR)):
        mean=sum(profile)/12
        for tonic,key in enumerate(keys):
            rotated=[profile[(i-tonic)%12]-mean for i in range(12)]
            divisor=norm*math.sqrt(sum(v*v for v in rotated))
            correlation=sum(a*b for a,b in zip(centered,rotated))/divisor if divisor else 0.
            candidates.append(dict(key=key,correlation=round(correlation,6)))
    candidates.sort(key=lambda c:(-c['correlation'],c['key']))
    winner=candidates[0]
    # Correlation and gap are evidence, never a probability of correctness.
    relative=MINOR_KEYS[(MAJOR_KEYS.index(winner['key'])+9)%12] if winner['key'] in MAJOR_KEYS else MAJOR_KEYS[(MINOR_KEYS.index(winner['key'])+3)%12]
    return dict(key=winner['key'],source='inferred',method='duration-weighted-ks-v1',
        correlation=winner['correlation'],gap=round(winner['correlation']-candidates[1]['correlation'],6),
        alternatives=candidates[1:4],relative_key=relative,requires_confirmation=True)


def ledger_cost(pitch,sign,octave):
    # Written position differs by an octave; source pitch always stays intact.
    pitch-=12*octave
    diatonic=(pitch//12-1)*7+(0,0,1,1,2,3,3,4,4,5,5,6)[pitch%12]
    bottom,top=(30,38) if sign=='G' else (18,26)
    distance=max(bottom-diatonic,diatonic-top,0)
    return (distance//2)**2


def plan_clefs(measures,events,mode):
    """Per-staff dynamic programming with switching costs and tie protection."""
    states=[('G',0),('F',0)]
    if mode=='auto_octaves':states.extend([('G',1),('F',-1)])
    by_measure={}
    for e in events:
        if e['pitch'] is not None:by_measure.setdefault((e['measure_id'],e['staff']),[]).append(e)
    for staff in (1,2):
        default=('G',0) if staff==1 else ('F',0)
        if mode=='standard':chosen=[default]*len(measures)
        else:
            costs={state:(0 if state==default else .5) for state in states};history=[]
            for measure in measures:
                notes=by_measure.get((measure['id'],staff),[])
                tied=any(e['tie_stop'] and e['onset']==measure['start'] for e in notes)
                total=sum(float(e['duration']) for e in notes) or 1
                next_costs={};parents={}
                for state in states:
                    sign,octave=state
                    local=sum(ledger_cost(e['pitch'],sign,octave)*float(e['duration']) for e in notes)/total
                    if notes:local+=2.5*abs(octave)+(.15 if sign!=default[0] else 0)
                    options=[(cost+(0 if prev==state else 7 if not tied else 1e9),prev) for prev,cost in costs.items()]
                    cost,parent=min(options,key=lambda v:(v[0],v[1]!=state,v[1]))
                    next_costs[state]=cost+local;parents[state]=parent
                history.append(parents);costs=next_costs
            state=min(costs,key=lambda s:(costs[s],s!=default,s));chosen=[]
            for parents in reversed(history):chosen.append(state);state=parents[state]
            chosen.reverse()
        for measure,(sign,octave) in zip(measures,chosen):
            measure.setdefault('clefs',{})[str(staff)]=dict(sign=sign,line=2 if sign=='G' else 4,octave=octave)
