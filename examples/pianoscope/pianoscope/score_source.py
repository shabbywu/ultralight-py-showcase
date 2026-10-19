"""Bounded MusicXML source loading. Original bytes are never rewritten."""
from dataclasses import dataclass
from collections import Counter
from pathlib import Path, PurePosixPath
from io import BytesIO
import copy
import hashlib
import re
import stat
import zipfile
import xml.etree.ElementTree as ET
from defusedxml import ElementTree as SafeET

MAX_INPUT = 10 * 1024**2
MAX_ENTRY = 16 * 1024**2
MAX_UNPACKED = 32 * 1024**2
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
ID_REFERENCES = {'part', 'midi-instrument', 'instrument', 'midi-device'}


class ScoreInputError(ValueError):
    def __init__(self, message, code='SCORE_INVALID', locator='', element_id=''):
        super().__init__(message)
        self.code = code
        self.issues = [dict(code=code, message=message, source_locator=locator, element_id=element_id)]


def fail(message, locator='', code='SCORE_UNSUPPORTED'):
    raise ScoreInputError(message, code, locator)


def safe_xml(data):
    """External DOCTYPE is ignored; entities are refused by the parser itself."""
    try:
        parser = SafeET.iterparse(BytesIO(data), events=('start', 'end'),
                                  forbid_dtd=False, forbid_entities=True, forbid_external=True)
        count = depth = 0
        for event, node in parser:
            if event == 'start':
                count += 1
                depth += 1
                if count > 200_000 or depth > 128:
                    fail('XML 节点或嵌套层数超过限制', code='SCORE_LIMIT')
            else:
                depth -= 1
        return parser.root
    except ScoreInputError:
        raise
    except Exception as exc:
        raise ScoreInputError('XML 无法安全读取：' + str(exc), 'SCORE_XML') from exc


@dataclass(frozen=True)
class SourceDocument:
    original_name: str
    original_bytes: bytes
    xml_bytes: bytes
    sha256: str
    container_type: str
    root_entry: str
    # Serialized source tree is kept separately from the mutable working tree.
    preserved_tree: bytes
    locations: dict
    diagnostics: tuple
    working_xml: str

    @property
    def source_id(self):
        return self.sha256


def read_source(path, cancelled=lambda: False):
    path = Path(path)
    with path.open('rb') as stream:
        data = stream.read(MAX_INPUT + 1)
    return source_from_bytes(data, path.name, cancelled)


def source_from_bytes(data, name='score.musicxml', cancelled=lambda: False):
    if len(data) > MAX_INPUT:
        fail('乐谱文件超过 10 MiB', code='SCORE_LIMIT')
    if cancelled():
        raise InterruptedError('已取消')
    suffix = Path(name).suffix.lower()
    if suffix not in ('.xml', '.musicxml', '.mxl'):
        fail('请打开 MusicXML／MXL 乐谱；MIDI 只作为派生文件导出')
    xml, entry, kind = data, '', 'xml'
    if suffix == '.mxl':
        kind = 'mxl'
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                infos = archive.infolist()
                if len(infos) > 256:
                    fail('MXL 超过 256 个条目', code='SCORE_LIMIT')
                names = set()
                total = 0
                payload = {}
                for info in infos:
                    if cancelled():
                        raise InterruptedError('已取消')
                    p = PurePosixPath(info.filename)
                    mode = info.external_attr >> 16
                    if (p.is_absolute() or '..' in p.parts or '\\' in info.filename
                            or ':' in info.filename or '\x00' in info.filename
                            or stat.S_ISLNK(mode) or info.flag_bits & 1):
                        fail('MXL 包含不安全的路径／链接／加密条目', info.filename, 'SCORE_CONTAINER')
                    normalized = str(p)
                    if normalized in names:
                        fail('MXL 条目重复', info.filename, 'SCORE_CONTAINER')
                    names.add(normalized)
                    if info.is_dir():
                        continue
                    if info.file_size > MAX_ENTRY or info.file_size > max(1, info.compress_size) * 100:
                        fail('MXL 单项大小／解压倍率超过限制', info.filename, 'SCORE_LIMIT')
                    # Actual streaming counts, including entries not used as the score.
                    chunks, size = [], 0
                    with archive.open(info) as stream:
                        while True:
                            chunk = stream.read(64 * 1024)
                            if not chunk:
                                break
                            if cancelled():
                                raise InterruptedError('已取消')
                            size += len(chunk)
                            total += len(chunk)
                            if size > MAX_ENTRY or total > MAX_UNPACKED or size > max(1, info.compress_size) * 100:
                                fail('MXL 实际解压大小／倍率超过限制', info.filename, 'SCORE_LIMIT')
                            chunks.append(chunk)
                    payload[normalized] = b''.join(chunks)
                if 'META-INF/container.xml' not in payload:
                    fail('MXL 缺少 META-INF/container.xml', code='SCORE_CONTAINER')
                container = safe_xml(payload['META-INF/container.xml'])
                if container.tag.split('}')[-1] != 'container':
                    fail('MXL container 根节点错误', code='SCORE_CONTAINER')
                roots = [n for n in container.iter() if n.tag.split('}')[-1] == 'rootfile'
                         and n.get('media-type') in (None, 'application/vnd.recordare.musicxml+xml')]
                if len(roots) != 1:
                    fail('MXL 必须只有一个明确的乐谱入口', code='SCORE_CONTAINER')
                entry = roots[0].get('full-path', '')
                if entry not in payload:
                    fail('MXL 乐谱入口不存在', entry, 'SCORE_CONTAINER')
                xml = payload[entry]
        except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
            raise ScoreInputError('MXL 容器损坏：' + str(exc), 'SCORE_CONTAINER') from exc
    root = safe_xml(xml)
    if root.tag != 'score-partwise' or root.get('version') not in ('3.1', '4.0'):
        fail('首版支持 MusicXML 3.1／4.0 score-partwise；请在外部制谱软件转换', '/' + root.tag + '[1]')
    digest = hashlib.sha256(data).hexdigest()
    preserved = ET.tostring(root, encoding='utf-8')
    working = copy.deepcopy(root)
    counts = Counter(n.get('id') or n.get(XML_ID) for n in working.iter() if n.tag not in ID_REFERENCES)
    locations, diagnostics = {}, []
    def visit(node, locator):
        if cancelled():
            raise InterruptedError('已取消')
        original_id = node.get('id') or node.get(XML_ID)
        valid = node.tag not in ID_REFERENCES and original_id and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', original_id) and counts[original_id] == 1
        internal = original_id if valid else 'ps-' + hashlib.sha256((digest + locator).encode()).hexdigest()[:24]
        locations[internal] = dict(source_locator=locator, original_xml_id=original_id, tag=node.tag)
        if original_id and not valid and node.tag not in ID_REFERENCES:
            diagnostics.append(dict(code='SOURCE_ID_REPLACED', message='重复或不适用的源 ID；使用稳定内部身份',
                                    element_id=internal, source_locator=locator))
        node.attrib.pop(XML_ID, None)
        node.set('_ps_id', internal)
        if node.tag not in ID_REFERENCES:
            node.set('id', internal)
        counter = Counter()
        for child in list(node):
            counter[child.tag] += 1
            child_path = f'{locator}/{child.tag}[{counter[child.tag]}]'
            if child.tag in ('{http://www.w3.org/2001/XInclude}include', 'image', 'link', 'bookmark'):
                node.remove(child)
                diagnostics.append(dict(code='RESOURCE_NOT_LOADED', message='外部资源不加载，原件保留', source_locator=child_path))
                continue
            for key in list(child.attrib):
                if key.endswith('href') or key in ('source', 'font-family'):
                    child.attrib.pop(key)
                    diagnostics.append(dict(code='RESOURCE_NOT_LOADED', message='外部资源引用未加载，原件保留', source_locator=child_path))
            visit(child, child_path)
    visit(working, '/score-partwise[1]')
    return SourceDocument(name, bytes(data), xml, digest, kind, entry, preserved, locations,
                          tuple(diagnostics), ET.tostring(working, encoding='unicode'))
