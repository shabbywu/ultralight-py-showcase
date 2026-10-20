"""隔离的 MusicXML 排版与演奏编译入口，输出可核验源副本、MIDI、PDF 和映射。"""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import replace
from pathlib import Path

from pianoscope.score.engraving_input import engraving_input
from pianoscope.score.mapping import attach_mapping, json_value
from pianoscope.score.midi import compile_midi
from pianoscope.score.model import parse_score
from pianoscope.score.plan import compile_plan
from pianoscope.score.source import read_source
from pianoscope.types import PathInput, Record


def prepare(
    source_path: PathInput,
    directory: PathInput,
    settings: Record | None = None,
    original_name: str | None = None,
    source_revision: str | None = None,
) -> Record:
    """在隔离进程中读取源语义、编译 MIDI、排版谱面并附真实源几何映射。

    写出源文件逐字节副本、MIDI、PDF 和结构化结果；需要确认时仅返回确认请求。
    source_revision 可绑定调用方快照，所有播放时值仍来自原 MusicXML。
    """
    from pianoscope.score.engraving import engrave

    source = read_source(source_path)
    if original_name:
        source = replace(source, original_name=original_name)
    document = parse_score(source, settings)
    if source_revision:
        document.revision = source_revision
    if document.needs_confirmation:
        return dict(
            status="needs_confirmation",
            source_sha256=source.sha256,
            required=document.needs_confirmation,
            title=document.title,
        )
    plan = compile_plan(document, settings)
    compile_midi(plan)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    intermediate, repairs = engraving_input(document, plan, directory)
    manifest = engrave(
        intermediate,
        document.title,
        directory,
        layout_options={"breaks": "encoded"},
        hidden_ids={e.id for e in document.elements if not e.visible},
    )
    manifest["source_repairs"] = repairs
    attach_mapping(document, plan, manifest)
    (directory / "source-copy").with_suffix(
        Path(source.original_name).suffix
    ).write_bytes(source.original_bytes)
    # The renderer's sanitized XML is explicitly a working file, never the original.
    (directory / "score.musicxml").rename(directory / "layout-working.mei")
    (directory / "score.mid").write_bytes(plan.midi_bytes)
    data = dict(
        status="ready",
        source_sha256=source.sha256,
        source_name=source.original_name,
        title=document.title,
        manifest=manifest,
        diagnostics=plan.diagnostics,
        source_locations=source.locations,
        occurrences=plan.occurrences,
        instances=plan.instances,
        display_spans=plan.display_spans,
        tempos=plan.tempos,
        controls=plan.controls,
        duration_s=plan.duration_s,
        source_revision=document.revision,
        playback_revision=plan.revision,
        midi_precision=plan.midi_precision,
        midi_event_map=plan.midi_event_map,
    )
    (directory / "prepared.json").write_text(
        json.dumps(json_value(data), ensure_ascii=False), encoding="utf-8"
    )
    return data


def main() -> int:
    """读取命令行作业目录的 request.json，将成功或带源定位的失败写入 result.json。

    成功返回退出码 0，准备失败返回 1；原生错误堆栈写入子进程日志。
    """
    directory = Path(sys.argv[1])
    request = json.loads((directory / "request.json").read_text())
    try:
        result = prepare(
            request["source_path"],
            directory,
            request.get("settings"),
            request.get("original_name"),
            request.get("source_revision"),
        )
        (directory / "result.json").write_text(
            json.dumps(json_value(result), ensure_ascii=False), encoding="utf-8"
        )
        return 0
    except Exception as exc:
        traceback.print_exc()
        result = dict(
            status="failed",
            error=str(exc),
            code=getattr(exc, "code", "SCORE_PREPARE_FAILED"),
            issues=getattr(exc, "issues", []),
        )
        (directory / "result.json").write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
