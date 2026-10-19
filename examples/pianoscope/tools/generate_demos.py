"""Original deterministic compositions, no third-party MIDI recordings. Seed: 0."""
import hashlib
import json
from pathlib import Path
import mido
ROOT=Path(__file__).resolve().parents[1]/'pianoscope/resources/demos'

def write(slug,title,parts,duration):
    mid=mido.MidiFile(type=1,ticks_per_beat=480)
    meta=mido.MidiTrack();mid.tracks.append(meta)
    meta.extend([mido.MetaMessage('set_tempo',tempo=500000),mido.MetaMessage('time_signature',numerator=4,denominator=4)])
    hands={}
    for i,(hand,notes) in enumerate(parts):
        tr=mido.MidiTrack();mid.tracks.append(tr);tr.append(mido.MetaMessage('track_name',name=hand))
        ev=[]
        for start,length,pitch,vel in notes:
            ev.extend([(round(start*960),1,mido.Message('note_on',channel=i,note=pitch,velocity=vel)),(round((start+length)*960),0,mido.Message('note_off',channel=i,note=pitch))])
        # An explicitly notated pedal passage.
        if slug=='first-light':
            ev.extend([(round(4*960),0,mido.Message('control_change',channel=i,control=64,value=127)),(round(7.9*960),0,mido.Message('control_change',channel=i,control=64,value=0))])
        tick=0
        for t,_,msg in sorted(ev,key=lambda e:e[:2]):msg.time=t-tick;tick=t;tr.append(msg)
        tr.append(mido.MetaMessage('end_of_track',time=round(duration*960)-tick))
        hands[f't{i+1}c{i}']=hand
    path=ROOT/(slug+'.mid');mid.save(path)
    path.with_suffix('.hands.json').write_text(json.dumps(dict(title=title,seed=0,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),tracks=hands),ensure_ascii=False,indent=2))

def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    right=[];left=[]
    progression=[[48,52,55],[45+12,48+12,52+12],[53,57,60],[55,59,62]]
    melody=[60,64,67,72,71,67,64,62,60,62,65,69,67,64,62,60]
    for bar in range(44):
        t=bar*2
        chord=progression[(bar//2)%4]
        for k,p in enumerate(chord):left.append((t+k*.5,.8,max(48,p-12 if p>60 else p),65+(bar%4)*3))
        for k in range(4):
            if (bar+k)%13!=12:right.append((t+k*.5,.38,melody[(bar*4+k)%len(melody)],78+(k%3)*5))
    # C4 belongs to the left hand; simultaneous E4/G4 to the right.
    left[0]=(0,.8,60,78);right[0]=(0,.8,64,88);right.append((0,.8,67,86))
    write('first-light','初光',[('left',left),('right',right)],88)
    write('harmonics','泛音练习',[('left',[(8,3,60,85),(16,3,48,85)]),('right',[(0,2,69,100),(4,2,69,70),(8,3,64,85),(8,3,67,85),(12,2,72,90),(20,3,69,92)])],24)
if __name__=='__main__':main()
