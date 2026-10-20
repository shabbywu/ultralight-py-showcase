"""Connect actual engraving geometry to immutable source and playback IDs."""

import hashlib
import xml.etree.ElementTree as ET
from fractions import Fraction as Q

from .score_source import fail


def layout_input(document):
    root = ET.fromstring(document.source.working_xml)
    for node in root.iter():
        internal = node.attrib.pop("_ps_id", None)
        location = document.source.locations.get(internal, {})
        if node.tag not in ("note", "measure") and not location.get("original_xml_id"):
            node.attrib.pop("id", None)
    return ET.tostring(root, encoding="unicode")


def attach_mapping(document, plan, manifest):
    by_id = {e.id: e for e in document.elements if e.visible}
    measures = {m.id: m for m in document.measures}
    seen = set()
    for pi, page in enumerate(manifest["pages"]):
        if len(page["glyphs"]) > 2000:
            fail("单页几何超过 2,000 个", code="SCORE_LIMIT")
        for gi, glyph in enumerate(page["glyphs"]):
            ident = glyph["event_id"]
            e = by_id.get(ident)
            if (
                e is None
                and glyph.get("kind") in ("rest", "mRest")
                and glyph["measure_id"] in measures
            ):
                # A source staff with no notes can acquire an implicit full-bar
                # rest during engraving. It is a measure anchor, never a new
                # source note or sounding instance.
                mid = glyph["measure_id"]
                glyph.update(
                    element_id=mid,
                    page=pi,
                    measure_uid=mid,
                    onset_qn=Q(0),
                    duration_qn=measures[mid].length,
                    pitch=None,
                    staff_id=None,
                    voice_id=None,
                    glyph_id=f"{pi}:{mid}:implicit-rest:{gi}",
                    spans=[],
                    layout_only=True,
                )
                continue
            if e is None:
                fail("排版器返回未映射的乐谱符号：" + ident, code="SCORE_GEOMETRY")
            seen.add(ident)
            glyph.update(
                element_id=ident,
                page=pi,
                measure_uid=e.measure_uid,
                onset_qn=e.onset,
                duration_qn=e.duration,
                pitch=e.pitch,
                staff_id=e.staff_id,
                voice_id=e.voice_id,
                glyph_id=f"{pi}:{ident}",
                spans=[s for s in plan.display_spans if s["element_id"] == ident],
            )
        for measure in page["measures"]:
            if measure["id"] not in measures:
                fail("排版器改变小节身份：" + measure["id"], code="SCORE_GEOMETRY")
            m = measures[measure["id"]]
            measure.update(
                measure_uid=m.id,
                number=m.number,
                length_qn=m.length,
                occurrences=[o for o in plan.occurrences if o["measure_uid"] == m.id],
            )
            x, y, w, h = measure["bbox"]
            anchors = {}
            for g in page["glyphs"]:
                if g["measure_uid"] == m.id:
                    anchors[g["onset_qn"]] = min(
                        anchors.get(g["onset_qn"], g["bbox"][0]), g["bbox"][0]
                    )
            anchors.setdefault(Q(0), x)
            anchors[m.length] = x + w
            points = sorted(anchors.items())
            extra = {d["onset"] for d in m.directions if d["kind"] == "tempo"}
            for qn in extra:
                if qn not in anchors:
                    for (a, ax), (b, bx) in zip(points, points[1:]):
                        if a <= qn <= b:
                            anchors[qn] = ax + (bx - ax) * float((qn - a) / (b - a))
                            break
            measure["anchors"] = [dict(qn=q, x=ax) for q, ax in sorted(anchors.items())]
        for system in page["systems"]:
            x, y, w, h = system["bbox"]
            if x < 0 or y < 45 or x + w > page["width"] or y + h > page["height"] - 30:
                fail("谱行超出可打印区域，拒绝裁切发布", code="SCORE_GEOMETRY")
    if set(by_id) != seen:
        fail(
            "排版器遗漏符头／休止：" + ", ".join(sorted(set(by_id) - seen)[:10]),
            code="SCORE_GEOMETRY",
        )
    manifest.update(
        source_revision=document.revision,
        playback_revision=plan.revision,
        layout_revision=hashlib.sha256(
            (document.revision + ":a4-v2:" + manifest["engine"]).encode()
        ).hexdigest()[:24],
    )
    return manifest


def json_value(value):
    if isinstance(value, Q):
        return [value.numerator, value.denominator]
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(v) for v in value]
    return value
