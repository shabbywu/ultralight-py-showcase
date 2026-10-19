import asyncio
from pathlib import Path
from pianoscope.dev_paths import MIDI_ROOT
from types import SimpleNamespace
import shutil
import pytest
from pianoscope.session import Controller
from pianoscope.midi import parse_midi
from pianoscope.notation import build,NotationError
from pianoscope.hands import preview,assigned

ROOT=Path(__file__).resolve().parents[1]


def library_controller():
    # Listing only needs capability state, never a sound device or a MIDI parse.
    return SimpleNamespace(library_epoch=0,closed=False,library=None,library_tokens={})


def test_folder_snapshot_many_tokens_case_extensions_and_no_recursive_scan(tmp_path):
    for i in range(24):shutil.copyfile(ROOT/'tests/fixtures/cross-hands.mid',tmp_path/f'{i:02d}.MID')
    (tmp_path/'readme.txt').write_text('not MIDI')
    child=tmp_path/'nested';child.mkdir();(child/'hidden.mid').touch()
    c=library_controller()
    result=asyncio.run(Controller.open_midi_folder(c,str(tmp_path)))
    assert len(result['songs'])==24 and len(c.library_tokens)==24
    assert [item['filename'] for item in result['songs']]==[f'{i:02d}.MID' for i in range(24)]
    assert all(set(item)=={'file_token','title','filename'} for item in result['songs'])
    assert len({item['file_token'] for item in result['songs']})==24
    assert all(parse_midi(c.library_tokens[item['file_token']]).notes for item in result['songs'])
    old_tokens=c.library_tokens
    with pytest.raises(ValueError):asyncio.run(Controller.open_midi_folder(c,tmp_path/'readme.txt'))
    assert c.library is result and c.library_tokens is old_tokens


def test_folder_empty_and_limit_are_explicit_and_atomic(tmp_path):
    c=library_controller();empty=asyncio.run(Controller.open_midi_folder(c,tmp_path))
    assert empty['songs']==[]
    for i in range(1001):(tmp_path/f'{i}.mid').touch()
    with pytest.raises(ValueError,match='1,000'):asyncio.run(Controller.open_midi_folder(c,tmp_path))
    assert c.library is empty and not c.library_tokens


def test_late_folder_scan_cannot_replace_newer_selection(tmp_path,monkeypatch):
    import threading
    slow=tmp_path/'slow';fast=tmp_path/'fast';slow.mkdir();fast.mkdir()
    started=threading.Event();release=threading.Event();original=Path.iterdir
    def iterdir(path):
        if path==slow:started.set();release.wait(3)
        yield from original(path)
    monkeypatch.setattr(Path,'iterdir',iterdir)
    c=library_controller()
    async def scenario():
        first=asyncio.create_task(Controller.open_midi_folder(c,slow))
        await asyncio.to_thread(started.wait,2)
        latest=await Controller.open_midi_folder(c,fast);release.set()
        with pytest.raises(ValueError,match='已改变'):await first
        assert c.library is latest and c.library['folder_name']=='fast'
    asyncio.run(scenario())


@pytest.mark.parametrize('filename,counts',[
    ('Rush E.mid',{'原始音符时值为零或负值':32,'量化后短音塌缩':30,'端点偏移超过 1/10 拍容差':39}),
    ('Hans Zimmer - First Step - Interstellar.mid',{'量化后短音塌缩':67,'端点偏移超过 1/10 拍容差':28}),
])
def test_user_midis_report_real_source_locations_without_mutation(filename,counts):
    from collections import Counter
    path=MIDI_ROOT/filename
    if not path.exists():pytest.skip('User-provided MIDI is local only')
    score=parse_midi(path);mapping,_=preview(score,{'type':'pitch_split','pitch':60});score=assigned(score,mapping,{})
    snapshot=[vars(n).copy() for n in score.notes]
    with pytest.raises(NotationError) as exc:build(score,{'confirm_defaults':True})
    assert Counter(i['reason'] for i in exc.value.issues)==counts
    sources={n.id:n for n in score.notes}
    for issue in exc.value.issues:
        n=sources[issue['source_note_id']]
        assert issue['source_event']==n.source_event and issue['start_s']==n.start_s
        assert issue['start_tick']==n.start_tick and issue['key_off_tick']==n.key_off_tick
    assert snapshot==[vars(n) for n in score.notes]
