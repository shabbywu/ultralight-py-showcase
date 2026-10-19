"""Isolated MusicXML layout/compilation worker, also used by the G0 gate."""
from pathlib import Path
import json
import sys
import traceback
from dataclasses import replace
from .score_source import read_source
from .score_model import parse_score
from .playback_plan import compile_plan
from .midi_compile import compile_midi
from .score_mapping import layout_input, attach_mapping, json_value
from .score_engraving import engraving_input


def prepare(source_path, directory, settings=None, original_name=None, source_revision=None):
    from .engraving import engrave
    source = read_source(source_path)
    if original_name:
        source=replace(source,original_name=original_name)
    document = parse_score(source, settings)
    if source_revision:
        document.revision=source_revision
    if document.needs_confirmation:
        return dict(status='needs_confirmation', source_sha256=source.sha256,
                    required=document.needs_confirmation, title=document.title)
    plan = compile_plan(document, settings)
    compile_midi(plan)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    intermediate, repairs = engraving_input(document, plan, directory)
    manifest = engrave(intermediate, document.title, directory, layout_options={'breaks': 'encoded'},
                       hidden_ids={e.id for e in document.elements if not e.visible})
    manifest['source_repairs'] = repairs
    attach_mapping(document, plan, manifest)
    (directory / 'source-copy' ).with_suffix(Path(source.original_name).suffix).write_bytes(source.original_bytes)
    # The renderer's sanitized XML is explicitly a working file, never the original.
    (directory / 'score.musicxml').rename(directory / 'layout-working.mei')
    (directory / 'score.mid').write_bytes(plan.midi_bytes)
    data = dict(status='ready', source_sha256=source.sha256, source_name=source.original_name,
                title=document.title, manifest=manifest, diagnostics=plan.diagnostics,
                source_locations=source.locations,
                occurrences=plan.occurrences, instances=plan.instances, display_spans=plan.display_spans,
                tempos=plan.tempos, controls=plan.controls, duration_s=plan.duration_s,
                source_revision=document.revision, playback_revision=plan.revision,
                midi_precision=plan.midi_precision, midi_event_map=plan.midi_event_map)
    (directory / 'prepared.json').write_text(json.dumps(json_value(data), ensure_ascii=False), encoding='utf-8')
    return data


def main():
    directory = Path(sys.argv[1])
    request = json.loads((directory / 'request.json').read_text())
    try:
        result = prepare(request['source_path'], directory, request.get('settings'), request.get('original_name'),request.get('source_revision'))
        (directory / 'result.json').write_text(json.dumps(json_value(result), ensure_ascii=False), encoding='utf-8')
        return 0
    except Exception as exc:
        traceback.print_exc()
        result = dict(status='failed', error=str(exc), code=getattr(exc, 'code', 'SCORE_PREPARE_FAILED'),
                      issues=getattr(exc, 'issues', []))
        (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
