"""Independent process verification of real XML/MXL, SMF and PDF artifacts."""

import hashlib
import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def independent(directory):
    """This child imports independent readers, never the product compiler."""
    from importlib.metadata import version

    import mido
    import pymupdf
    from music21 import converter

    directory = Path(directory)
    raw = ET.fromstring((directory / "source-copy.musicxml").read_bytes())
    expected = []
    for n in raw.findall(".//note"):
        pitch = n.find("pitch")
        if pitch is not None:
            expected.append(
                (
                    pitch.findtext("step"),
                    int(pitch.findtext("alter", "0")),
                    int(pitch.findtext("octave")),
                )
            )

    def pitches(score):
        output = []
        for n in score.flatten().notes:
            for p in n.pitches:
                output.append(
                    (p.step, int(p.accidental.alter) if p.accidental else 0, p.octave)
                )
        return sorted(output)

    score = converter.parse(directory / "source-copy.musicxml")
    assert pitches(score) == sorted(expected)
    score.write("musicxml", fp=directory / "reader-roundtrip.musicxml")
    # Import the actual MXL container as a separate reader operation.
    mxl = directory / "source-copy.mxl"
    with zipfile.ZipFile(mxl, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles></container>',
        )
        archive.writestr(
            "score.musicxml", (directory / "source-copy.musicxml").read_bytes()
        )
    assert pitches(converter.parse(mxl)) == sorted(expected)
    midi = mido.MidiFile(directory / "score.mid")
    count = sum(m.type == "note_on" and m.velocity > 0 for t in midi.tracks for m in t)
    assert count == len(expected)
    pdf = pymupdf.open(directory / "score.pdf")
    assert len(pdf) >= 2
    for i, page in enumerate(pdf):
        assert (
            abs(page.rect.width - 595.2756) < 0.01
            and abs(page.rect.height - 841.8898) < 0.01
        )
        page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).save(
            str(directory / f"reader-pdf-{i + 1}.png")
        )
    result = dict(
        status="passed",
        xml_notes=len(expected),
        mxl_notes=len(expected),
        midi_note_ons=count,
        pdf_pages=len(pdf),
        versions={name: version(name) for name in ("music21", "mido", "pymupdf")},
        source_sha256=hashlib.sha256(
            (directory / "source-copy.musicxml").read_bytes()
        ).hexdigest(),
    )
    (directory / "independent.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )


def main():
    from pianoscope.score_process import run_preparation

    output = (
        ROOT.parents[1]
        / ".tmp/pianoscope/v2"
        / datetime.now().strftime("independent-%Y%m%d-%H%M%S")
    )
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status="failed", platform=platform.platform(), commands=[])
    try:
        for name in ("printed", "symbols"):
            directory = output / name
            directory.mkdir()
            source = ROOT / "tests/fixtures/v2" / (name + ".musicxml")
            (directory / "request.json").write_text(
                json.dumps(dict(source_path=str(source)))
            )
            prepared = run_preparation(directory)
            if name == "symbols":
                assert len(prepared["instances"]) == 9
                first = prepared["instances"][0]
                assert first["velocity"] == 45 and first["key_off_s"] == 0.125
                classes = {
                    n.get("class")
                    for n in ET.fromstring(
                        (directory / "page-1.svg").read_bytes()
                    ).iter()
                }
                assert {
                    "beam",
                    "slur",
                    "fing",
                    "dynam",
                    "hairpin",
                    "fermata",
                } <= classes, classes
                continue
            command = [sys.executable, __file__, "--reader", str(directory)]
            process = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True, timeout=60
            )
            (directory / "reader.log").write_text(process.stdout + process.stderr)
            report["commands"].append(
                dict(command=command, exit_code=process.returncode)
            )
            if process.returncode:
                raise RuntimeError(process.stderr)
            report["reader"] = json.loads((directory / "independent.json").read_text())
        # Native versions are probed separately from AppCore/Cairo processes.
        import sounddevice

        from pianoscope.synth import Synth

        with Synth(48000) as synth:
            report["fluidsynth"] = synth.version
        report["portaudio"] = sounddevice.get_portaudio_version()
        report["status"] = "passed"
    except Exception as exc:
        import traceback

        traceback.print_exc()
        report["error"] = str(exc)
    finally:
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str)
        )
        print(output, report["status"])
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reader":
        independent(sys.argv[2])
    else:
        raise SystemExit(main())
