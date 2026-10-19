from io import BytesIO
from pathlib import Path
import stat
import zipfile
import pytest
from pianoscope.score_source import source_from_bytes,ScoreInputError
from pianoscope.score_model import parse_score

RAW=(Path(__file__).parent/'fixtures/v2/temporal.musicxml').read_bytes()


def test_utf16_and_nested_external_resource_locations():
    text=RAW.decode().replace('encoding="UTF-8"','encoding="UTF-16"')
    source=source_from_bytes(text.encode('utf-16'))
    assert len(parse_score(source).elements)==20
    data=RAW.replace(b'<work>',b'<credit-image source="https://invalid.example/x"/><work>',1)
    source=source_from_bytes(data)
    assert b'credit-image' in source.original_bytes and 'credit-image' not in source.working_xml
    assert any(v['tag']=='credit-image' for v in source.locations.values())


def test_real_zip_bomb_symlink_and_normalized_duplicate_paths():
    for kind in ('ratio','symlink','duplicate'):
        stream=BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as z:
            if kind=='ratio':z.writestr('huge','0'*100_000)
            elif kind=='symlink':
                info=zipfile.ZipInfo('link');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,'/etc/passwd')
            else:
                z.writestr('score',b'a');z.writestr('./score',b'b')
        with pytest.raises(ScoreInputError):source_from_bytes(stream.getvalue(),'bad.mxl')


def test_node_depth_and_unsupported_extension_boundaries():
    data=b'<score-partwise version="4.0">'+b'<x>'*130+b'</x>'*130+b'</score-partwise>'
    with pytest.raises(ScoreInputError,match='嵌套'):source_from_bytes(data)
    with pytest.raises(ScoreInputError,match='MIDI'):source_from_bytes(RAW,'hidden.mid')
    with pytest.raises(ScoreInputError,match='XML'):source_from_bytes(b'MThd\0\0\0\6','fake.xml')


def test_legal_unicode_source_ids_are_preserved():
    data=RAW.replace(b'id="pickup-g"','id="音符_甲"'.encode())
    source=source_from_bytes(data)
    assert '音符_甲' in source.locations
    assert parse_score(source).elements[0].id=='音符_甲'
