"""Verified source-to-MEI repairs for the fixed Verovio MusicXML importer.

MEI remains a derived layout intermediate. It never supplies playback timing.
"""

import xml.etree.ElementTree as ET
from fractions import Fraction as Q
from pathlib import Path

from .score_mapping import layout_input
from .score_source import XML_ID, fail

MEI = "http://www.music-encoding.org/ns/mei"
TAG = "{" + MEI + "}"
DUR = {
    "whole": "1",
    "half": "2",
    "quarter": "4",
    "eighth": "8",
    "16th": "16",
    "32nd": "32",
    "64th": "64",
}


def engraving_input(document, plan, directory):
    import verovio

    toolkit = verovio.toolkit()
    toolkit.resetXmlIdSeed(1)
    if not toolkit.loadData(layout_input(document)):
        fail("MusicXML 原生排版导入失败：" + toolkit.getLog(), code="SCORE_LAYOUT")
    root = ET.fromstring(toolkit.getMEI())
    source = ET.fromstring(document.source.working_xml)
    original = {n.get("id"): n for n in source.iter()}
    elements = {e.id: e for e in document.elements}
    by_id = {n.get(XML_ID): n for n in root.iter() if n.get(XML_ID)}
    repairs = []
    for chord in list(root.iter(TAG + "chord")):
        notes = list(chord.iter(TAG + "note"))
        if not notes or any(n.get(XML_ID) not in elements for n in notes):
            fail("排版和弦缺少源身份", code="SCORE_GEOMETRY")
        semantic = [elements[n.get(XML_ID)] for n in notes]
        if len({e.duration for e in semantic}) == 1:
            continue
        # MEI supports per-note duration inside a chord. The shortest member
        # supplies its stem; a hidden spacer retains the source cursor advance.
        first = semantic[0]
        shortest = min(semantic, key=lambda e: e.duration)
        for n, e in zip(notes, semantic):
            raw = original[e.id]
            kind = raw.findtext("type")
            if kind not in DUR:
                fail("异时值和弦缺少可验证 type", code="SCORE_LAYOUT")
            n.set("dur", DUR[kind])
            n.set("dur.ppq", str(raw.findtext("duration")))
            dots = len(raw.findall("dot"))
            if dots:
                n.set("dots", str(dots))
        raw = original[shortest.id]
        chord.set("dur", DUR[raw.findtext("type")])
        chord.set("dur.ppq", raw.findtext("duration"))
        chord.attrib.pop("dots", None)
        if raw.findall("dot"):
            chord.set("dots", str(len(raw.findall("dot"))))
        gap = first.duration - shortest.duration
        if gap:
            # Layout-only invisible spacing uses exact divisions. No visible
            # rest, rewritten source voice, or inferred rhythmic grid is added.
            parent = next(n for n in root.iter() if chord in list(n))
            index = list(parent).index(chord) + 1
            while gap:
                duration = next(
                    (
                        Q(4, int(d))
                        for d in ("1", "2", "4", "8", "16", "32", "64")
                        if Q(4, int(d)) <= gap
                    ),
                    None,
                )
                if duration is None:
                    fail("此异时值和弦的隐藏布局间隔未经验证", code="SCORE_LAYOUT")
                parent.insert(
                    index, ET.Element(TAG + "space", {"dur": str(int(4 / duration))})
                )
                index += 1
                gap -= duration
        repairs.append(
            dict(kind="chord_member_durations", element_ids=[e.id for e in semantic])
        )
    # The fixed importer drops the second-ending continuation tie. Add the
    # source-declared relation only where the actual finite path proves it.
    ties = {
        (n.get("startid", "").lstrip("#"), n.get("endid", "").lstrip("#"))
        for n in root.iter(TAG + "tie")
    }
    for instance in plan.instances:
        for a, b in zip(instance["element_ids"], instance["element_ids"][1:]):
            if (a, b) in ties:
                continue
            if not original[a].findall("notations/tied") or not original[b].findall(
                "notations/tied"
            ):
                continue
            measure = by_id[elements[a].measure_uid]
            ident = "ps-tie-" + a + "-" + b
            ET.SubElement(
                measure,
                TAG + "tie",
                {XML_ID: ident, "startid": "#" + a, "endid": "#" + b},
            )
            ties.add((a, b))
            repairs.append(dict(kind="ending_tie", element_ids=[a, b]))
    ET.register_namespace("", MEI)
    text = ET.tostring(root, encoding="unicode")
    Path(directory, "layout-intermediate.mei").write_text(text, encoding="utf-8")
    return text, repairs
