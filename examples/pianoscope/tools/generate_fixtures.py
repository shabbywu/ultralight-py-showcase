"""Generate compact deterministic edge-case SMFs for repeatable native checks."""
from pathlib import Path
import mido
ROOT=Path(__file__).resolve().parents[1]/'tests/fixtures'
def save(name,tracks,kind=1,ppqn=480):
    m=mido.MidiFile(type=kind,ticks_per_beat=ppqn)
    for events in tracks:m.tracks.append(mido.MidiTrack(events))
    m.save(ROOT/name)
def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    on=lambda p,t=0:mido.Message('note_on',note=p,velocity=90,time=t)
    off=lambda p,t=480:mido.Message('note_off',note=p,time=t)
    save('cross-hands.mid',[[mido.MetaMessage('track_name',name='Left'),on(72),on(48),on(61),off(72),off(48,0),off(61,0),on(60),off(60,960)]],0)
    save('same-channel-overlap.mid',[[on(60),off(60,1920)],[on(60,240),off(60,240)]])
    save('tempo-pedal.mid',[[mido.MetaMessage('set_tempo',tempo=500000),mido.MetaMessage('set_tempo',tempo=1000000,time=480)],[on(60),mido.Message('control_change',control=64,value=127,time=120),off(60,360),mido.Message('control_change',control=64,value=0,time=480)]])
    save('all-88.mid',[[on(p) for p in range(21,109)]+[off(p,480 if p==21 else 0) for p in range(21,109)]],0)
    save('single-high.mid',[[on(96),off(96,1920)]],0)
    save('zero-duration.mid',[[on(60),off(60,0)]],0)
    save('empty.mid',[[]],0);save('type2.mid',[[on(60),off(60)]],2)
    save('smpte.mid',[[on(60),off(60)]],0,-6360)
    (ROOT/'broken.mid').write_bytes(b'MThd\0\0')
    from validate_score_outputs import edge_phrase
    edge_phrase(ROOT/'score-edge-phrase.mid')
if __name__=='__main__':main()
