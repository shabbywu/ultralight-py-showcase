"""Real native v2 G0 gate. Every invocation writes a new evidence directory."""

import asyncio
import hashlib
import importlib.metadata as metadata
import json
import platform
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import zlib
from datetime import datetime
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def screenshot(view, target):
    pixels = view.copy_pixels().to_rgba()
    stride = pixels.width * 4
    raw = b"".join(
        b"\0" + pixels.data[y * stride : (y + 1) * stride] for y in range(pixels.height)
    )

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    target.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR", struct.pack(">IIBBBBB", pixels.width, pixels.height, 8, 6, 0, 0, 0)
        )
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


HTML = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'self' file:; script-src 'self' file:; style-src 'self' 'unsafe-inline'; img-src 'self' file: data:; connect-src 'none'"><style>
*{box-sizing:border-box}body{margin:0;background:#101b29;color:#e6eefb;font:14px -apple-system,sans-serif}header{padding:12px 16px;display:flex;align-items:center;gap:10px;height:54px}button,select{padding:6px 10px;background:#22354a;color:#e6eefb;border:1px solid #455a70;border-radius:6px}#status{margin-left:auto;color:#77d8cc;font-size:12px}#scroll{height:calc(100vh - 54px);overflow:auto;padding:12px}.page{margin:0 auto 12px;position:relative;background:#fff}canvas{display:block;width:100%}#error{color:#ff8d96}</style>
<header><b>PianoScope · 乐谱合成播放</b><button id="play">播放</button><button id="pause">暂停</button><select id="visit"><option value="">自动选择遍次</option><option value="o2">第 1 遍</option><option value="o4">第 2 遍</option></select><span id="status"></span></header><div id="scroll"></div><div id="error"></div><script src="gate.js"></script></html>"""


JS = r"""(()=>{
const value=x=>Python.to_value(x),pages=MANIFEST.pages,root=document.getElementById('scroll');
let zoom=1,last=null,selected=null,ready=false,highlights=[],error=null;
const items=pages.map((page,i)=>{const box=document.createElement('div'),canvas=document.createElement('canvas'),image=new Image();box.className='page';box.appendChild(canvas);root.appendChild(box);image.src='page-'+(i+1)+'.png';return {page,box,canvas,image}});
function draw(){highlights=[];for(const item of items){const {page,canvas,box,image}=item,w=Math.max(480,innerWidth-32)*zoom,s=w/page.width,dpr=devicePixelRatio;box.style.width=w+'px';canvas.style.height=page.height*s+'px';const pw=Math.round(w*dpr),ph=Math.round(page.height*s*dpr);if(canvas.width!==pw||canvas.height!==ph){canvas.width=pw;canvas.height=ph}const ctx=canvas.getContext('2d');ctx.setTransform(s*dpr,0,0,s*dpr,0,0);ctx.fillStyle='white';ctx.fillRect(0,0,page.width,page.height);ctx.drawImage(image,0,0,page.width,page.height);if(last)for(const g of page.glyphs){if(last.active_element_ids.includes(g.element_id)){ctx.fillStyle='#dc9c37';ctx.globalAlpha=.72;ctx.fillRect(...g.bbox);ctx.globalAlpha=1;highlights.push(g.element_id)}}}if(last)document.getElementById('status').textContent=last.position_s.toFixed(2)+' 秒 · 小节 '+last.measure_number+' · 遍次 '+last.visit_index}
for(const item of items)item.canvas.onclick=async event=>{try{const rect=item.canvas.getBoundingClientRect(),s=rect.width/item.page.width,x=(event.clientX-rect.left)/s,y=(event.clientY-rect.top)/s;const g=item.page.glyphs.find(g=>x>=g.bbox[0]&&x<=g.bbox[0]+g.bbox[2]&&y>=g.bbox[1]&&y<=g.bbox[1]+g.bbox[3]);if(g){selected=g.element_id;last=value(await piano.seek_score(g.element_id,document.getElementById('visit').value||null));draw()}}catch(e){error=String(e);document.getElementById('error').textContent=error}};
document.getElementById('play').onclick=()=>piano.play();document.getElementById('pause').onclick=()=>piano.pause();
Promise.all(items.map(item=>new Promise(resolve=>{if(item.image.complete&&item.image.naturalWidth)resolve();else item.image.onload=resolve;item.image.onerror=()=>{error='底图解码失败'}}))).then(()=>{ready=true;draw()});
async function poll(){try{last=value(piano.get_transport());if(ready)draw()}catch(e){error=String(e)}setTimeout(poll,50)}poll();
window.Gate={get ready(){return ready},get error(){return error},get last(){return last},get selected(){return selected},get highlights(){return highlights},items,zoom(z){zoom=z;draw()},click(id,occ){document.getElementById('visit').value=occ||'';const item=items.find(i=>i.page.glyphs.some(g=>g.element_id===id)),g=item.page.glyphs.find(g=>g.element_id===id),r=item.canvas.getBoundingClientRect(),s=r.width/item.page.width,x=r.left+(g.bbox[0]+g.bbox[2]/2)*s,y=r.top+(g.bbox[1]+g.bbox[3]/2)*s;item.canvas.dispatchEvent(new MouseEvent('click',{clientX:x,clientY:y}));return {error:Math.max(Math.abs((x-r.left)/s-(g.bbox[0]+g.bbox[2]/2))*s,Math.abs((y-r.top)/s-(g.bbox[1]+g.bbox[3]/2))*s)}}};
})();"""


def main():
    from pianoscope.midi_compile import compile_midi, sound_score
    from pianoscope.playback_plan import compile_plan
    from pianoscope.render import render
    from pianoscope.score_mapping import json_value
    from pianoscope.score_model import parse_score
    from pianoscope.score_player import ScorePlayer
    from pianoscope.score_source import read_source

    out = (
        ROOT.parents[1]
        / ".tmp/pianoscope/v2/g0"
        / datetime.now().strftime("run-%Y%m%d-%H%M%S")
    )
    out.mkdir(parents=True, exist_ok=False)
    report = dict(
        status="failed",
        command=sys.argv,
        python=platform.python_version(),
        platform=platform.platform(),
        versions={
            name: metadata.version(name)
            for name in (
                "ultralight-py",
                "verovio",
                "CairoSVG",
                "pypdf",
                "mido",
                "numpy",
                "sounddevice",
                "music21",
                "pymupdf",
                "defusedxml",
            )
        },
        checks=[],
        inputs={},
    )
    player = None

    def check(name, condition, detail=None):
        report["checks"].append(
            dict(name=name, status="passed" if condition else "failed", detail=detail)
        )
        if not condition:
            raise AssertionError(name + ": " + str(detail))

    try:
        check(
            "fixed Python 3.10 native environment",
            sys.version_info[:2] == (3, 10)
            and metadata.version("ultralight-py") == "0.5.0",
        )
        data = {}
        for name in ("temporal", "printed"):
            source_path = ROOT / "tests/fixtures/v2" / (name + ".musicxml")
            directory = out / name
            directory.mkdir()
            (directory / "request.json").write_text(
                json.dumps(dict(source_path=str(source_path)))
            )
            started = time.perf_counter()
            result = subprocess.run(
                [sys.executable, "-m", "pianoscope.v2_worker", str(directory)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            (directory / "worker.log").write_text(result.stderr + result.stdout)
            check(name + " isolated worker exit", result.returncode == 0, result.stderr)
            data[name] = json.loads((directory / "result.json").read_text())
            report["inputs"][name] = dict(
                sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                prepare_seconds=time.perf_counter() - started,
            )
            check(
                name + " all visible source notes/rests have real geometry",
                len(
                    {
                        g["element_id"]
                        for page in data[name]["manifest"]["pages"]
                        for g in page["glyphs"]
                    }
                )
                == (20 if name == "temporal" else 192),
            )
            check(
                name + " original copy byte equality",
                (directory / "source-copy.musicxml").read_bytes()
                == source_path.read_bytes(),
            )
            import pymupdf

            pdf = pymupdf.open(directory / "score.pdf")
            check(
                name + " real A4 PDF",
                all(
                    abs(p.rect.width - 595.2756) < 0.01
                    and abs(p.rect.height - 841.8898) < 0.01
                    for p in pdf
                ),
            )
            if name == "printed":
                check("at least two PDF pages", len(pdf) >= 2, len(pdf))
            for i, page in enumerate(pdf):
                page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).save(
                    str(directory / f"pdf-{i + 1}.png")
                )
        # Independent software import/export, retaining the original MIT license.
        # This export is a separate external-software MusicXML sample, never MIDI-derived.
        from music21 import converter

        independent = converter.parse(ROOT / "tests/fixtures/v2/printed.musicxml")
        check(
            "music21 independently reads all source pitches",
            sum(len(n.pitches) for n in independent.flatten().notes) == 192,
        )
        external = out / "music21-export.musicxml"
        independent.write("musicxml", fp=external)
        external_plan = compile_plan(parse_score(read_source(external)))
        check(
            "external-software export sample loads with source semantics",
            len(external_plan.instances) == 192,
        )
        report["external_sample"] = dict(
            software="music21",
            version=metadata.version("music21"),
            license="MIT original score, exported by music21",
            sha256=hashlib.sha256(external.read_bytes()).hexdigest(),
        )
        # Separately evaluate the candidate native MIDI method; do not assume it works.
        import base64

        import mido

        candidate = subprocess.run(
            [
                sys.executable,
                "-c",
                "import verovio,sys,base64; t=verovio.toolkit(); t.loadFile(sys.argv[1]); print(t.renderToMIDI())",
                str(ROOT / "tests/fixtures/v2/temporal.musicxml"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        (out / "verovio-candidate.log").write_text(candidate.stderr)
        if candidate.returncode == 0:
            candidate_midi = base64.b64decode(candidate.stdout.strip())
            (out / "verovio-candidate.mid").write_bytes(candidate_midi)
            parsed = mido.MidiFile(file=BytesIO(candidate_midi))
            starts = sum(
                m.type == "note_on" and m.velocity > 0
                for tr in parsed.tracks
                for m in tr
            )
            report["verovio_midi_candidate"] = dict(
                status="not_selected",
                note_on_count=starts,
                expected_note_on_count=20,
                reason="authority remains hand-verified Python rational plan; candidate evidence retained",
            )
        plan = compile_plan(
            parse_score(read_source(ROOT / "tests/fixtures/v2/temporal.musicxml"))
        )
        compile_midi(plan)
        player = ScorePlayer()
        check("actual output device open", player.audio.ready, player.audio.error)
        config = dict(
            rate=1.0,
            hand_mode="both",
            tracks=[
                dict(id=p["id"], muted=False, solo=False) for p in plan.document.parts
            ],
        )
        pcm = render(sound_score(plan), config, player.audio.sample_rate)
        check(
            "real SoundFont nonzero PCM",
            float(abs(pcm).max()) > 0,
            float(abs(pcm).max()),
        )
        player.install(plan, pcm)
        report["device"] = player.audio.device
        report["sample_rate"] = player.audio.sample_rate
        report["pcm_bytes"] = pcm.nbytes
        manifest = data["temporal"]["manifest"]
        from ultralight_py import API, Application, Resource

        resources = {
            "index.html": Resource(HTML.encode(), "text/html"),
            "gate.js": Resource(
                JS.replace(
                    "MANIFEST", json.dumps(manifest, ensure_ascii=False)
                ).encode(),
                "text/javascript",
            ),
        }
        for i, page in enumerate(manifest["pages"]):
            resources[f"page-{i + 1}.png"] = Resource(
                (out / "temporal" / f"page-{i + 1}.png").read_bytes(), "image/png"
            )
        with (
            tempfile.TemporaryDirectory(prefix="pianoscope-v2-g0-") as cache,
            API("piano") as api,
            Application(
                assets_root=str(ROOT / "pianoscope/assets"),
                resource_loader=resources.get,
                cache_path=cache,
                force_cpu_renderer=True,
                app_name="PianoScope v2 G0",
            ) as app,
        ):
            for name in (
                "play",
                "pause",
                "stop",
                "seek",
                "seek_score",
                "configure",
                "set_volume",
                "set_loop",
                "get_transport",
            ):
                api.register(getattr(player, name))
            window = app.create_window(800, 600, title="PianoScope v2 G0")
            view = window.view
            api.attach(view)
            view.load_url("file:///index.html")

            async def verify():
                pump = asyncio.create_task(app.run_async(update_interval=1 / 120))
                try:
                    # Let the attached 0.5.0 bridge enter the loaded document;
                    # evaluating against the initial blank document races attach.
                    await asyncio.sleep(0.4)
                    await view.wait_until(
                        lambda: view.evaluate("!!window.Gate&&Gate.ready"), timeout=20
                    )
                    check(
                        "native Canvas bitmap decoded",
                        view.evaluate("Gate.items[0].image.naturalWidth") > 0,
                    )
                    await view.evaluate_async("piano.play()")
                    await view.wait_until(
                        lambda: view.evaluate(
                            'Gate.highlights.includes("a-long")&&Gate.highlights.includes("a-overlap")'
                        ),
                        timeout=8,
                    )
                    snapshot = view.evaluate("Gate.last")
                    check(
                        "DAC snapshot has overlapping independent instances",
                        len(snapshot["active_instance_ids"]) >= 3,
                        snapshot,
                    )
                    check(
                        "actual post-gain output is nonzero",
                        float(abs(player.audio.heard_window()).max()) > 0,
                    )
                    await asyncio.sleep(0.15)
                    screenshot(view, out / "native-playing.png")
                    await view.evaluate_async("piano.pause()")
                    await view.wait_until(
                        lambda: not view.evaluate("Gate.highlights.length"), timeout=3
                    )
                    check(
                        "pause clears sounding highlights",
                        not player.get_transport()["active_instance_ids"],
                    )
                    for zoom in (1, 1.25, 1.5):
                        view.evaluate(f"Gate.zoom({zoom})")
                        for ident, occ, seconds in (
                            ("b-tie", None, 3.5),
                            ("a-long", "o4", 7.5),
                            ("c-tie-cross", None, 10.5),
                            ("a-rest", "o4", 8.5),
                        ):
                            result = view.evaluate(
                                "Gate.click("
                                + json.dumps(ident)
                                + ","
                                + json.dumps(occ)
                                + ")"
                            )
                            await view.wait_until(
                                lambda: abs(player.audio.position - seconds) < 1e-7,
                                timeout=3,
                            )
                            check(
                                f"binding click {ident} {occ} at {zoom}",
                                result["error"] <= 1
                                and abs(player.audio.position - seconds) < 1e-7,
                                result,
                            )
                    for rate in (0.5, 0.75, 1.0):
                        await view.evaluate_async(
                            "piano.configure({rate:" + str(rate) + "})"
                        )
                        await view.evaluate_async("piano.seek(4)")
                        await view.evaluate_async("piano.play()")
                        await view.wait_until(
                            lambda: view.evaluate(
                                'Gate.last.position_s>4.05&&Gate.highlights.includes("b-tie")'
                            ),
                            timeout=4,
                        )
                        snapshot = player.get_transport()
                        check(
                            f"long tied note from inside PCM at rate {rate}",
                            "b-tie" in snapshot["active_element_ids"]
                            and "a-long" not in snapshot["active_element_ids"]
                            and "i2" in snapshot["active_instance_ids"]
                            and float(abs(player.audio.heard_window()).max()) > 0,
                            snapshot,
                        )
                        await view.evaluate_async("piano.pause()")
                    await view.evaluate_async("piano.seek(7.25)")
                    await view.evaluate_async("piano.play()")
                    await view.wait_until(
                        lambda: view.evaluate(
                            'Gate.last.occurrence_id==="o4"&&Gate.highlights.includes("a-long")'
                        ),
                        timeout=4,
                    )
                    check(
                        "actual DAC traverses repeat jump",
                        player.get_transport()["occurrence_id"] == "o4",
                    )
                    await view.evaluate_async("piano.pause()")
                    check(
                        "no page script error",
                        view.evaluate("Gate.error") is None,
                        view.evaluate("Gate.error"),
                    )
                    report["viewport"] = view.evaluate(
                        "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"
                    )
                    report["underruns"] = player.audio.underruns
                finally:
                    player.close()
                    app.close()
                    await pump

            asyncio.run(verify())
        report["status"] = "passed"
    except Exception as exc:
        traceback.print_exc()
        report["error"] = str(exc)
    finally:
        if player and not player.closed:
            player.close()
        report["manual_visual"] = (
            "not_run: review PDF PNGs and native screenshot separately"
        )
        report["physical_audio_visual_latency"] = "not_run"
        (out / "report.json").write_text(
            json.dumps(json_value(report), ensure_ascii=False, indent=2, default=str)
        )
        print(str(out), report["status"], flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
