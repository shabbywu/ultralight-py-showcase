"""原生排版及真实几何提取，仅在隔离乐谱工作器中运行。

坐标从 Verovio 内部 viewBox 换算为外层像素，符头边界取实际字形路径，
不估算音高，也不使用包含符干的整个音符边框替代符头。"""

from __future__ import annotations

import ctypes.util
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Collection
from pathlib import Path
from types import ModuleType
from typing import NoReturn

from pianoscope.paths import RESOURCES
from pianoscope.score.source import ScoreInputError as NotationError
from pianoscope.types import Cancelled, PathInput, Record

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"


def deny_external_resource(url: str, resource_type: str) -> NoReturn:
    """拒绝 CairoSVG 的外部资源读取并抛出 NotationError，确保排版仅使用本地受控资源。"""
    raise NotationError("排版资源禁止外部读取：" + str(resource_type))


def cairo_module() -> ModuleType:
    # cairocffi uses find_library; macOS Homebrew is not in dyld's search path.
    # This temporary resolver is confined to an isolated worker process.
    """在隔离排版进程中临时定位 Homebrew Cairo，返回 cairosvg 模块。

    导入结束后恢复 ctypes 库定位函数，不改变主进程的动态库搜索。
    """
    original = ctypes.util.find_library

    def find(name: str) -> str | None:
        """先调用系统库定位器，仅对 Cairo 名称补充已知 Homebrew 路径。"""
        result = original(name)
        if result or name not in ("cairo", "cairo-2", "libcairo-2"):
            return result
        for base in ("/opt/homebrew/lib", "/usr/local/lib"):
            candidate = Path(base) / "libcairo.2.dylib"
            if candidate.exists():
                return str(candidate)
        return None

    ctypes.util.find_library = find
    try:
        import cairosvg

        return cairosvg
    finally:
        ctypes.util.find_library = original


def text_paths(text: str, x: float, baseline: float, size: float) -> ET.Element:
    """用随包中文字体把文本转为 SVG 路径；坐标、基线和字号使用 SVG 用户单位。"""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.ttLib import TTFont

    font = TTFont(RESOURCES / "fonts/NotoSansCJKsc-Regular.otf")
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    scale = size / font["head"].unitsPerEm
    group = ET.Element(f"{{{SVG}}}g")
    for char in text:
        name = cmap.get(ord(char))
        if not name:
            raise ValueError(f"字体不支持标题字符：{char}")
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(pen)
        ET.SubElement(
            group,
            f"{{{SVG}}}path",
            d=pen.getCommands(),
            transform=f"translate({x},{baseline}) scale({scale},{-scale})",
        )
        x += glyphs[name].width * scale
    font.close()
    return group


def outline_text(root: ET.Element, resource_path: PathInput) -> None:
    """原地把 SVG 文字叶节点转换为随包中文字体或本地 SMuFL 路径。

    不依赖宿主字体；缺失字形或音乐字体资源时抛出 ValueError。
    """

    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.ttLib import TTFont

    font = TTFont(RESOURCES / "fonts/NotoSansCJKsc-Regular.otf")
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    upem = font["head"].unitsPerEm
    for parent in list(root.iter()):
        for text in list(parent):
            if text.tag != f"{{{SVG}}}text":
                continue
            parts = []

            def walk(node: ET.Element, size: float = 0, family: str = "") -> None:
                """递归继承字号与字体族，收集文字叶节点的字形、缩放和前进宽度。"""
                size = float(node.attrib.get("font-size", str(size)).replace("px", ""))
                family = node.attrib.get("font-family", family)
                if not list(node) and node.text and node.text.strip():
                    for char in node.text:
                        if family in (
                            "Leipzig",
                            "Bravura",
                            "Leland",
                            "Petaluma",
                            "Gootville",
                        ):
                            path = (
                                Path(resource_path)
                                / family
                                / (f"{ord(char):04X}" + ".xml")
                            )
                            if not path.exists():
                                raise ValueError("缺少音乐文字字形：" + str(path))
                            group = ET.fromstring(path.read_text())
                            scale = size / 1000
                            metrics = ET.parse(
                                Path(resource_path) / (family + ".xml")
                            ).getroot()
                            metric = next(
                                g
                                for g in metrics
                                if g.attrib.get("c") == f"{ord(char):04X}"
                            )
                            parts.append(
                                (
                                    group,
                                    scale,
                                    float(
                                        metric.attrib.get("h-a-x", metric.attrib["w"])
                                    )
                                    * scale,
                                )
                            )
                        else:
                            name = cmap.get(ord(char))
                            if not name:
                                raise ValueError("字体不支持字符：" + char)
                            pen = SVGPathPen(glyphs)
                            glyphs[name].draw(pen)
                            g = ET.Element(f"{{{SVG}}}g")
                            ET.SubElement(
                                g,
                                f"{{{SVG}}}path",
                                d=pen.getCommands(),
                                transform="scale(1,-1)",
                            )
                            scale = size / upem
                            parts.append((g, scale, glyphs[name].width * scale))
                for child in node:
                    walk(child, size, family)

            walk(text)
            x = float(text.attrib.get("x", 0))
            y = float(text.attrib.get("y", 0))
            width = sum(p[2] for p in parts)
            anchor = text.attrib.get("text-anchor", "start")
            if anchor == "end":
                x -= width
            elif anchor == "middle":
                x -= width / 2
            result = ET.Element(f"{{{SVG}}}g")
            for glyph, scale, advance in parts:
                g = ET.SubElement(
                    result,
                    f"{{{SVG}}}g",
                    transform=f"translate({x},{y}) scale({scale})",
                )
                g.append(glyph)
                x += advance
            parent.insert(list(parent).index(text), result)
            parent.remove(text)
    font.close()


def geometry(svg: str, hidden_ids: Collection[str] = ()) -> Record:
    """从实际 SVG 字形路径提取像素坐标中的符头、休止、小节和谱行边界。

    hidden_ids 为源隐藏元素；不估算音高或使用含符干的整体边框代替符头。
    """
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.svgLib.path import parse_path

    root = ET.fromstring(svg)
    width, height = map(float, root.attrib["viewBox"].split()[2:])
    inner = root.find(f"{{{SVG}}}svg")
    iw, ih = map(float, inner.attrib["viewBox"].split()[2:])
    sx, sy = width / iw, height / ih
    margin = inner.find(f"{{{SVG}}}g")
    tx, ty = map(
        float,
        re.search(r"translate\(([^)]+)\)", margin.attrib["transform"])[1]
        .replace(",", " ")
        .split(),
    )
    defs = {e.attrib["id"]: e for e in root.iter() if "id" in e.attrib}
    systems = []
    measures = []
    glyphs = []

    def box(rect: ET.Element) -> list[float]:
        """把内部 viewBox 矩形转换为外层像素坐标 [x, y, width, height]。"""
        a = rect.attrib
        return [
            (float(a["x"]) + tx) * sx,
            (float(a["y"]) + ty) * sy,
            float(a["width"]) * sx,
            float(a["height"]) * sy,
        ]

    for system in margin.findall(f"{{{SVG}}}g[@class='system']"):
        rects = system.findall(f".//{{{SVG}}}g/{{{SVG}}}rect")
        if not rects:
            raise ValueError("排版器未返回谱行几何")
        # Verovio's system bbox is its own connecting barline only. Union all
        # actual descendants, including staves, noteheads, ledger lines and ties.
        bounds = [box(rect) for rect in rects]
        left = min(b[0] for b in bounds)
        top = min(b[1] for b in bounds)
        right = max(b[0] + b[2] for b in bounds)
        bottom = max(b[1] + b[3] for b in bounds)
        sid = len(systems)
        systems.append(dict(id=sid, bbox=[left, top, right - left, bottom - top]))
        for measure in system.findall(f"{{{SVG}}}g[@class='measure']"):
            mid = measure.attrib["id"]
            local = []
            for elem in measure.iter(f"{{{SVG}}}g"):
                kind = elem.attrib.get("class")
                if kind not in ("note", "rest", "mRest"):
                    continue
                eid = elem.attrib["id"]
                if eid in hidden_ids:
                    continue
                head = elem.find(f"{{{SVG}}}g[@class='notehead']/{{{SVG}}}use")
                if head is not None:
                    transform = head.attrib["transform"]
                    vals = re.fullmatch(
                        r"translate\(([-\d.]+),?\s*([-\d.]+)\) scale\(([-\d.]+),?\s*([-\d.]+)\)",
                        transform,
                    )
                    if not vals:
                        raise ValueError("未知符头坐标变换：" + transform)
                    x, y, a, b = map(float, vals.groups())
                    symbol = defs[head.attrib[f"{{{XLINK}}}href"][1:]]
                    path = symbol.find(f"{{{SVG}}}path")
                    if path.attrib.get("transform") != "scale(1,-1)":
                        raise ValueError("未知符头路径变换")
                    pen = BoundsPen(None)
                    parse_path(path.attrib["d"], pen)
                    glyph_left, bottom, glyph_right, top = pen.bounds
                    bounds = [
                        (x + glyph_left * a + tx) * sx,
                        (y - top * b + ty) * sy,
                        (glyph_right - glyph_left) * a * sx,
                        (top - bottom) * b * sy,
                    ]
                else:
                    rect = elem.find(f"{{{SVG}}}g/{{{SVG}}}rect")
                    if rect is None:
                        raise ValueError("缺少休止几何：" + eid)
                    bounds = box(rect)
                item = dict(
                    event_id=eid, system=sid, measure_id=mid, bbox=bounds, kind=kind
                )
                glyphs.append(item)
                local.append(bounds)
            # Barlines give true measure extents, including empty space/rests.
            paths = measure.findall(f"{{{SVG}}}g[@class='barLine']/{{{SVG}}}path")
            right = (
                max(
                    (float(re.search(r"M([\d.]+)", p.attrib["d"])[1]) + tx) * sx
                    for p in paths
                )
                if paths
                else max(b[0] + b[2] for b in local)
            )
            left = (
                measures[-1]["bbox"][0] + measures[-1]["bbox"][2]
                if measures and measures[-1]["system"] == sid
                else systems[sid]["bbox"][0]
            )
            sb = systems[sid]["bbox"]
            measures.append(
                dict(id=mid, system=sid, bbox=[left, sb[1], right - left, sb[3]])
            )
    return dict(
        width=width, height=height, systems=systems, measures=measures, glyphs=glyphs
    )


def engrave(
    xml: str,
    title: str,
    directory: PathInput,
    cancelled: Cancelled = lambda: False,
    caption: str | None = None,
    layout_options: Record | None = None,
    hidden_ids: Collection[str] = (),
) -> Record:
    """直接排版派生 MusicXML／MEI，写出实际 SVG、PNG 和 A4 PDF，返回几何清单。

    只在隔离进程调用；源编码分页溢出时有界重排一次。取消抛出 InterruptedError，
    无真实几何、页面超限或重排后仍越界时拒绝结果，不发布裁切谱面。
    """
    import verovio

    cairo = cairo_module()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    toolkit = verovio.toolkit()
    toolkit.resetXmlIdSeed(1)
    toolkit.setOptions(
        dict(
            svgBoundingBoxes=True,
            svgViewBox=True,
            pageWidth=2100,
            pageHeight=2970,
            pageMarginTop=180,
            pageMarginBottom=220 if caption else 120,
            pageMarginLeft=100,
            pageMarginRight=100,
            scale=40,
            header="none",
            footer="none",
        )
    )
    if layout_options:
        toolkit.setOptions(layout_options)
    if not toolkit.loadData(xml):
        raise ValueError("原生排版失败：" + toolkit.getLog())
    count = toolkit.getPageCount()
    if not 1 <= count <= 32:
        raise NotationError("谱面超过 32 页限制")
    reflowed = False
    if layout_options and layout_options.get("breaks") == "encoded":
        # Encoded page breaks may describe a different paper/staff size. Check
        # actual native geometry before rasterizing; reflow the derived score
        # once rather than clipping any source music to our fixed A4 output.
        overflow = False
        for page in range(1, count + 1):
            if cancelled():
                raise InterruptedError("已取消")
            data = geometry(toolkit.renderToSVG(page), hidden_ids)
            for system in data["systems"]:
                x, y, w, h = system["bbox"]
                overflow |= (
                    x < 0
                    or y < 45
                    or x + w > data["width"]
                    or y + h > data["height"] - 30
                )
        if overflow:
            toolkit.setOptions({"breaks": "auto"})
            toolkit.resetXmlIdSeed(1)
            if not toolkit.loadData(xml):
                raise ValueError("A4 重新分页失败：" + toolkit.getLog())
            count = toolkit.getPageCount()
            if not 1 <= count <= 32:
                raise NotationError("谱面超过 32 页限制")
            reflowed = True
    pages = []
    decoded_bytes = 0
    image_scale = 2
    for page in range(1, count + 1):
        if cancelled():
            raise InterruptedError("已取消")
        svg = toolkit.renderToSVG(page)
        data = geometry(svg, hidden_ids)
        if page == 1:
            while (
                image_scale > 0.5
                and count
                * math.ceil(data["width"] * image_scale)
                * math.ceil(data["height"] * image_scale)
                * 4
                > 128 * 1024 * 1024
            ):
                image_scale -= 0.25
        data["image_scale"] = image_scale
        decoded_bytes += (
            math.ceil(data["width"] * image_scale)
            * math.ceil(data["height"] * image_scale)
            * 4
        )
        if decoded_bytes > 128 * 1024 * 1024:
            raise NotationError("谱面底图超过 128 MiB 解码预算，请减少范围。")
        root = ET.fromstring(svg)
        outline_text(root, toolkit.getResourcePath())
        # Bounds are diagnostic geometry, never paint them into exports.
        for parent in root.iter():
            for child in list(parent):
                if "bounding-box" in child.attrib.get("class", ""):
                    parent.remove(child)
        if page == 1:
            root.append(text_paths(title[:80], 40, 35, 18))
            if caption:
                root.append(text_paths(caption, 40, 53, 10))
        root.append(
            text_paths(
                f"{page} / {count}", data["width"] / 2 - 20, data["height"] - 22, 11
            )
        )
        svg = ET.tostring(root, encoding="utf-8")
        (directory / f"page-{page}.svg").write_bytes(svg)
        cairo.surface.PDFSurface.convert(
            bytestring=svg,
            write_to=str(directory / f"page-{page}.pdf"),
            output_width=210 / 25.4 * 96,
            output_height=297 / 25.4 * 96,
            url_fetcher=deny_external_resource,
        )
        # Same SVG and outer viewBox; rasterize at 2x for high-DPI Canvas.
        cairo.surface.PNGSurface.convert(
            bytestring=svg,
            write_to=str(directory / f"page-{page}.png"),
            scale=image_scale,
            url_fetcher=deny_external_resource,
        )
        pages.append(data)
    from pypdf import PdfWriter

    writer = PdfWriter()
    for page in range(1, count + 1):
        writer.append(str(directory / f"page-{page}.pdf"))
    writer.add_metadata({"/Title": title, "/Creator": "PianoScope / Verovio 5.6.0"})
    writer.write(str(directory / "score.pdf"))
    writer.close()
    (directory / "score.musicxml").write_text(xml, encoding="utf-8")
    return dict(
        pages=pages,
        engine=toolkit.getVersion(),
        layout_policy="a4-reflow" if reflowed else "encoded",
        layout_diagnostics=[
            dict(
                code="A4_REFLOW",
                message="源分页超出 A4 可打印区域，派生谱面已重新分页；原文件完整保留",
            )
        ]
        if reflowed
        else [],
    )
