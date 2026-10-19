"""Connect actual engraving geometry to immutable source and playback IDs."""
from fractions import Fraction as Q
import hashlib
import xml.etree.ElementTree as ET
from .score_source import fail


def layout_input(document):
    root = ET.fromstring(document.source.working_xml)
    for node in root.iter():
        node.attrib.pop('_ps_id', None)
    return ET.tostring(root, encoding='unicode')


def attach_mapping(document, plan, manifest):
    by_id = {e.id: e for e in document.elements if e.visible}
    measures = {m.id: m for m in document.measures}
    seen = set()
    for pi, page in enumerate(manifest['pages']):
        if len(page['glyphs']) > 2000:
            fail('单页几何超过 2,000 个', code='SCORE_LIMIT')
        for glyph in page['glyphs']:
            ident = glyph['event_id']
            e = by_id.get(ident)
            if e is None:
                fail('排版器返回未映射的乐谱符号：' + ident, code='SCORE_GEOMETRY')
            seen.add(ident)
            glyph.update(element_id=ident, page=pi, measure_uid=e.measure_uid,
                         onset_qn=e.onset, duration_qn=e.duration, pitch=e.pitch,
                         staff_id=e.staff_id, voice_id=e.voice_id,
                         glyph_id=f'{pi}:{ident}',
                         spans=[s for s in plan.display_spans if s['element_id'] == ident])
        for measure in page['measures']:
            if measure['id'] not in measures:
                fail('排版器改变小节身份：' + measure['id'], code='SCORE_GEOMETRY')
            m = measures[measure['id']]
            measure.update(measure_uid=m.id, number=m.number, length_qn=m.length,
                           occurrences=[o for o in plan.occurrences if o['measure_uid'] == m.id])
        for system in page['systems']:
            x, y, w, h = system['bbox']
            if x < 0 or y < 45 or x + w > page['width'] or y + h > page['height'] - 30:
                fail('谱行超出可打印区域，拒绝裁切发布', code='SCORE_GEOMETRY')
    if set(by_id) != seen:
        fail('排版器遗漏符头／休止：' + ', '.join(sorted(set(by_id) - seen)[:10]), code='SCORE_GEOMETRY')
    manifest.update(source_revision=document.revision, playback_revision=plan.revision,
                    layout_revision=hashlib.sha256((document.revision + ':a4-v2:' + manifest['engine']).encode()).hexdigest()[:24])
    return manifest


def json_value(value):
    if isinstance(value, Q):
        return [value.numerator, value.denominator]
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(v) for v in value]
    return value
