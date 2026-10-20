"""Supplement G0 with bounded workers, exact MXL copies and glyph checks."""

import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from pianoscope.score.process import run_preparation

    output = (
        ROOT.parents[1]
        / ".tmp/pianoscope/validation/native"
        / datetime.now().strftime("outputs-%Y%m%d-%H%M%S")
    )
    output.mkdir(parents=True, exist_ok=False)
    checks = []

    def check(name, condition, detail=None):
        checks.append(
            dict(name=name, status="passed" if condition else "failed", detail=detail)
        )
        assert condition, (name, detail)

    metrics = {}
    for name in ("temporal", "printed"):
        directory = output / name
        directory.mkdir()
        source = ROOT / "tests/fixtures/musicxml" / (name + ".musicxml")
        (directory / "request.json").write_text(
            json.dumps(dict(source_path=str(source)))
        )
        result = run_preparation(directory)
        metrics[name] = result["worker_metrics"]
        if name == "temporal":
            svg = ET.fromstring((directory / "page-1.svg").read_bytes())
            nodes = {n.get("id"): n for n in svg.iter() if n.get("id")}

            def head(ident):
                return next(
                    n.get("{http://www.w3.org/1999/xlink}href")
                    for n in nodes[ident].iter()
                    if n.tag.endswith("use")
                )

            check(
                "whole notehead retained",
                head("a-long").startswith("#E0A2"),
                head("a-long"),
            )
            check(
                "short chord member has a half notehead",
                head("a-chord-short").startswith("#E0A3"),
                head("a-chord-short"),
            )
            tie = nodes["ps-tie-a-long-c-tie-cross"]
            check(
                "second ending cross-staff tie has a real rendered path",
                any(n.tag.endswith("path") for n in tie.iter()),
            )
    mxl = output / "temporal.mxl"
    with zipfile.ZipFile(mxl, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="score" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles></container>',
        )
        z.writestr(
            "score", (ROOT / "tests/fixtures/musicxml/temporal.musicxml").read_bytes()
        )
    directory = output / "mxl"
    directory.mkdir()
    (directory / "request.json").write_text(json.dumps(dict(source_path=str(mxl))))
    result = run_preparation(directory)
    metrics["mxl"] = result["worker_metrics"]
    check(
        "MXL original container copy is byte identical",
        (directory / "source-copy.mxl").read_bytes() == mxl.read_bytes(),
    )
    check(
        "XML and MXL compile identical SMF",
        (directory / "score.mid").read_bytes()
        == (output / "temporal/score.mid").read_bytes(),
    )
    check(
        "all bounded workers below 512 MiB and 60s",
        all(
            m["peak_rss_bytes"] <= 512 * 1024**2 and m["elapsed_seconds"] <= 60
            for m in metrics.values()
        ),
        metrics,
    )
    (output / "report.json").write_text(
        json.dumps(
            dict(status="passed", checks=checks, metrics=metrics),
            ensure_ascii=False,
            indent=2,
        )
    )
    print(output)


if __name__ == "__main__":
    main()
