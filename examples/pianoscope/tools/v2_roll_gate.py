"""Targeted real AppCore/DAC regression for roll geometry and strike decoration."""

import argparse
import asyncio
import hashlib
import json
import platform
import struct
import sys
import tempfile
import traceback
import zlib
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pack_native_animation(folder, frames):
    """Package unedited native PNG pixels as lossless APNG, with recorded timing."""

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    result = bytearray(b"\x89PNG\r\n\x1a\n")
    sequence = 0
    header = None
    for i, frame in enumerate(frames):
        raw = (folder / frame["path"]).read_bytes()
        cursor = 8
        blocks = []
        current = None
        while cursor < len(raw):
            length = struct.unpack(">I", raw[cursor : cursor + 4])[0]
            kind = raw[cursor + 4 : cursor + 8]
            data = raw[cursor + 8 : cursor + 8 + length]
            cursor += length + 12
            if kind == b"IHDR":
                current = data
            elif kind == b"IDAT":
                blocks.append(data)
        if i == 0:
            header = current
            result += chunk(b"IHDR", header) + chunk(
                b"acTL", struct.pack(">II", len(frames), 0)
            )
        if current != header:
            raise ValueError("Native recording changed dimensions")
        width, height = struct.unpack(">II", header[:8])
        seconds = (
            frames[i + 1]["wall_s"] - frame["wall_s"]
            if i + 1 < len(frames)
            else frame["wall_s"] - frames[i - 1]["wall_s"]
        )
        delay = max(1, min(65535, round(seconds * 1000)))
        result += chunk(
            b"fcTL",
            struct.pack(">IIIIIHHBB", sequence, width, height, 0, 0, delay, 1000, 0, 0),
        )
        sequence += 1
        for data in blocks:
            if i == 0:
                result += chunk(b"IDAT", data)
            else:
                result += chunk(b"fdAT", struct.pack(">I", sequence) + data)
                sequence += 1
    result += chunk(b"IEND", b"")
    (folder / "held-trails-animated.png").write_bytes(result)


def main():
    from pianoscope.v2_bridge import register
    from pianoscope.v2_session import Controller
    from run import APP_UPDATE_INTERVAL
    from tools.v2_g0 import screenshot

    parser = argparse.ArgumentParser()
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--effects-off", action="store_true")
    parser.add_argument(
        "--record",
        action="store_true",
        help="CPU-only lossless native frames before the performance window",
    )
    parser.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args()
    out = (
        ROOT.parents[1]
        / ".tmp/pianoscope/v2"
        / datetime.now().strftime("roll-%Y%m%d-%H%M%S")
    )
    out.mkdir(parents=True)
    report = dict(
        status="failed",
        renderer="GPU" if args.gpu else "CPU",
        checks=[],
        runtime=dict(
            python=sys.version,
            platform=platform.platform(),
            ultralight_py=version("ultralight-py"),
        ),
    )

    def check(name, condition, detail=None):
        report["checks"].append(
            dict(name=name, status="passed" if condition else "failed", detail=detail)
        )
        if not condition:
            raise AssertionError(name + ": " + str(detail))

    from ultralight_py import API, Application, Resource

    c = Controller()
    assets = ROOT / "pianoscope/assets"
    fixture = ROOT / "tests/fixtures/v2/roll-articulation.musicxml"
    original = fixture.read_bytes()
    report["host_update_interval_s"] = APP_UPDATE_INTERVAL
    report["source_sha256"] = hashlib.sha256(original).hexdigest()
    report["assets_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in assets.iterdir()
        if p.suffix in (".html", ".css", ".js")
    }
    resources = {
        p.name: Resource(
            p.read_bytes(),
            {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}[
                p.suffix
            ],
        )
        for p in assets.iterdir()
        if p.suffix in (".html", ".css", ".js")
    }
    resources["index.html"] = resources["v2.html"]
    resources["config.js"] = Resource(
        (
            "window.APP_ERRORS=[];window.onerror=m=>APP_ERRORS.push(String(m));window.CPU_RENDERER="
            + json.dumps(not args.gpu)
            + ";window.INITIAL_SOURCE="
            + json.dumps(c.token_for_path(fixture))
            + ";"
        ).encode(),
        "text/javascript",
    )

    def loader(name):
        if name in resources:
            return resources[name]
        data = c.resource(name)
        return Resource(data, "image/png") if data is not None else None

    try:
        with (
            tempfile.TemporaryDirectory(prefix="pianoscope-roll-") as cache,
            API("piano") as api,
            Application(
                assets_root=str(assets),
                resource_loader=loader,
                cache_path=cache,
                force_cpu_renderer=not args.gpu,
                app_name="PianoScope roll gate",
            ) as app,
        ):
            register(api, c)
            window = app.create_window(
                1440 if args.gpu else 800,
                900 if args.gpu else 600,
                title="PianoScope roll gate",
            )
            view = window.view
            api.attach(view)
            view.focus()
            view.load_url("file:///index.html")

            async def verify():
                pump = asyncio.create_task(
                    app.run_async(update_interval=APP_UPDATE_INTERVAL)
                )
                try:
                    await asyncio.sleep(0.4)
                    await view.wait_until(
                        lambda: view.evaluate(
                            "window.PIANOSCOPE_READY&&App.document&&!App.loadJob"
                        ),
                        timeout=40,
                    )
                    report["viewport"] = view.evaluate(
                        "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"
                    )
                    check("actual output device ready", c.audio.ready, c.audio.error)
                    check(
                        "manual seven attacks and one held chain",
                        len(c.plan.instances) == 7
                        and sum(len(n["element_ids"]) == 2 for n in c.plan.instances)
                        == 1,
                    )
                    import io

                    import mido

                    midi = c.plan.midi_bytes
                    check(
                        "independent SMF reader sees seven attacks",
                        sum(
                            m.type == "note_on" and m.velocity > 0
                            for t in mido.MidiFile(file=io.BytesIO(midi)).tracks
                            for m in t
                        )
                        == 7,
                    )
                    view.evaluate(
                        'App.setView("roll");document.getElementById("lift").value="35";document.getElementById("lift").dispatchEvent(new Event("input"));true'
                    )
                    await asyncio.sleep(0.15)
                    cells = view.evaluate("App.rollDiagnostics.cells")
                    repeat = [r for r in cells if r["pitch"] == 72]
                    held = [r for r in cells if r["pitch"] == 48]
                    check(
                        "visible repeated attacks have four CSS pixel gaps",
                        len(repeat) >= 2
                        and all(abs(r["gap"] - 4) < 1e-7 for r in repeat),
                        repeat,
                    )
                    full = view.evaluate(
                        "(()=>{const p=new PianoRollRenderer({},true);p.setNotes(App.notes,App.document.playback_revision);return p.geometry(new KeyboardLayout([48,72],'focused',800),0,600,600,85)})()"
                    )
                    all_repeat = [r for r in full if r["pitch"] == 72]
                    check(
                        "all six attacks and terminal release geometry",
                        len(all_repeat) == 6
                        and all(abs(r["gap"] - 4) < 1e-7 for r in all_repeat[:-1])
                        and all_repeat[-1]["gap"] == 0,
                        all_repeat,
                    )
                    source_notes = {n["id"]: n for n in c.plan.instances}
                    line = view.evaluate("App.rollDiagnostics.line")
                    check(
                        "leading edges and audible durations unchanged",
                        all(
                            abs(
                                r["bottom"]
                                - (line - source_notes[r["id"]]["onset_s"] * 85)
                            )
                            < 1e-7
                            and abs(r["bottom"] - r["top"] - r["height"]) < 1e-7
                            for r in cells
                        ),
                    )
                    check(
                        "real tie remains one uncut cell",
                        len(held) == 1
                        and held[0]["gap"] == 0
                        and abs(held[0]["height"] - 340) < 1e-7,
                        held,
                    )
                    geometry_edges = view.evaluate(
                        """(()=>{const p=new PianoRollRenderer({},true),n=(id,on,off,pitch)=>({id,pitch,onset_s:on,key_off_s:off,hand:'unassigned'}),notes=[n('held',0,2,60),n('overlap',1,1.5,60),n('tiny1',0,.01,62),n('tiny2',.01,.02,62),n('rest1',0,.5,64),n('rest2',1,2,64)];p.setNotes(notes,'r');const cells=p.geometry(new KeyboardLayout([60,62,64],'focused',800),0,600,600,85);return {overlap:cells.filter(c=>c.pitch===60).every(c=>c.gap===0),tiny:cells.filter(c=>c.pitch===62).every(c=>c.height>=1&&c.gap<=.375),rest:cells.filter(c=>c.pitch===64).every(c=>c.gap===0),notesUntouched:notes[2].key_off_s===.01}})()"""
                    )
                    check(
                        "overlapping voices, short attacks and natural rests preserved",
                        all(geometry_edges.values()),
                        geometry_edges,
                    )
                    if not args.gpu:
                        screenshot(view, out / "separated-notes.png")
                    view.evaluate('document.getElementById("full").click();true')
                    await view.evaluate_async("piano.play()")
                    await view.wait_until(
                        lambda: view.evaluate(
                            "App.rollDiagnostics.impacts>=3&&App.rollDiagnostics.particles>0"
                        ),
                        timeout=4,
                    )
                    await asyncio.sleep(0.11)
                    fx = view.evaluate("App.rollDiagnostics")
                    report["strike_sample"] = fx
                    check(
                        "DAC attacks create bounded real Canvas trails",
                        0 < fx["particles"] <= fx["particle_limit"]
                        and fx["pulses"] > 0,
                        fx,
                    )
                    key_widths = view.evaluate(
                        'Array.from(document.querySelectorAll("#keys .key")).map(k=>({pitch:Number(k.dataset.pitch),width:k.getBoundingClientRect().width}))'
                    )
                    widths = {k["pitch"]: k["width"] for k in key_widths}
                    check(
                        "strike glow spans the actual whole key width",
                        any(e["kind"] == "attack" for e in fx["effects"])
                        and all(
                            abs(e["width"] - widths[e["pitch"]]) < 0.25
                            for e in fx["effects"]
                        ),
                        fx["effects"],
                    )
                    check(
                        "held bass emitted only once",
                        sum(x["pitch"] == 48 for x in fx["history"]) == 1,
                        fx["history"],
                    )
                    check(
                        "actual SoundFont output nonzero",
                        float(abs(c.audio.heard_window()).max()) > 0,
                    )
                    if not args.gpu:
                        screenshot(view, out / "strike-trails.png")
                    await view.evaluate_async("piano.pause()")
                    await asyncio.sleep(0.1)
                    check(
                        "pause clears all strike residue",
                        view.evaluate(
                            "App.rollDiagnostics.particles===0&&App.rollDiagnostics.pulses===0&&App.rollDiagnostics.emitters.length===0"
                        ),
                    )
                    before = view.evaluate("App.rollDiagnostics.impacts")
                    await view.evaluate_async("piano.seek(2.5)")
                    await view.evaluate_async("piano.play()")
                    await asyncio.sleep(0.25)
                    check(
                        "seek/resume inside a held note creates no false attack",
                        view.evaluate("App.rollDiagnostics.impacts") == before,
                    )
                    held_a = view.evaluate("App.rollDiagnostics.trails")
                    await asyncio.sleep(0.09)
                    held_b = view.evaluate("App.rollDiagnostics")
                    previous = {p["id"]: p for p in held_a}
                    check(
                        "held notes continuously emit moving curved trails without new attacks",
                        len(held_b["emitters"]) == 2
                        and len(held_b["trails"]) > 8
                        and held_b["pulses"] == 0
                        and any(
                            p["id"] in previous
                            and abs(p["y"] - previous[p["id"]]["y"]) > 1
                            for p in held_b["trails"]
                        ),
                        held_b,
                    )
                    if not args.gpu:
                        screenshot(view, out / "held-trails.png")
                    if args.record and not args.gpu:
                        import time

                        report["recording"] = []
                        for i in range(12):
                            frame = out / ("trail-frame-%02d.png" % i)
                            report["recording"].append(
                                dict(
                                    path=frame.name,
                                    wall_s=time.monotonic(),
                                    transport=view.evaluate("App.transport.position_s"),
                                )
                            )
                            screenshot(view, frame)
                            await asyncio.sleep(0.04)
                        pack_native_animation(out, report["recording"])

                    await view.evaluate_async("piano.pause()")
                    await view.evaluate_async("piano.seek(3.6)")
                    await view.evaluate_async("piano.play()")
                    await view.wait_until(
                        lambda: view.evaluate(
                            "!App.rollDiagnostics.emitters.some(e=>e.pitch===72)&&App.rollDiagnostics.trails.some(p=>p.pitch===72)"
                        ),
                        timeout=2,
                    )
                    released = view.evaluate("App.rollDiagnostics")
                    check(
                        "real key release stops emission while airborne trails continue",
                        not any(e["pitch"] == 72 for e in released["emitters"])
                        and any(
                            p["pitch"] == 72 and p["opacity"] > 0
                            for p in released["trails"]
                        ),
                        released,
                    )
                    await view.wait_until(
                        lambda: view.evaluate(
                            "!App.rollDiagnostics.trails.some(p=>p.pitch===72)"
                        ),
                        timeout=1,
                    )
                    check("release trails dissipate without a new note", True)
                    await view.evaluate_async("piano.pause()")
                    await view.evaluate_async("piano.set_loop(true,.1,.6)")
                    await view.evaluate_async("piano.stop()")
                    await view.wait_until(
                        lambda: view.evaluate(
                            'App.transport.phase==="ready"&&App.transport.position_s===0'
                        ),
                        timeout=3,
                    )
                    before = view.evaluate("App.rollDiagnostics.impacts")
                    await view.evaluate_async("piano.play()")
                    await asyncio.sleep(0.18)
                    check(
                        "loop A inside held notes invents no initial attack",
                        view.evaluate("App.rollDiagnostics.impacts") == before,
                    )
                    await view.evaluate_async("piano.pause()")
                    await view.evaluate_async("piano.set_loop(false,0,4)")
                    # Production state machine, isolated from the active renderer.
                    # These manually authored snapshots test short-frame/reset boundaries.
                    rules = view.evaluate(
                        """(()=>{const p=new PianoRollRenderer({unassigned:'#aaa'},true),n={id:'n',pitch:60,onset_s:1,key_off_s:2,hand:'unassigned'};p.setNotes([n],'r');const s=(seq,pos,epoch=1)=>({seq,position_s:pos,clock_epoch:epoch,playback_revision:'r',phase:'playing',volume:1,rate:1,loop:{enabled:true,a_s:1,b_s:2},active_instance_ids:['n'],sustained_instance_ids:[]});p.observe(s(1,.95),true,0);p.observe(s(2,1.01),true,60);p.observe(s(2,1.01),true,70);const once=p.impactCount;p.observe(s(3,1.5,2),true,80);const seek=p.impactCount;p.observe(s(4,1.95,2),true,100);p.observe(s(5,1.02,2),true,160);const loop=p.impactCount;p.setEnabled(false);const cleared=!p.particles.length&&!p.pulses.length;p.reducedMotion=true;p.setEnabled(true);p.reset();p.observe(s(6,.95),true,180);p.observe(s(7,1.01),true,240);return {once,seek,loop,cleared,reducedParticles:p.particles.length,reducedPulses:p.pulses.length}})()"""
                    )
                    check(
                        "same snapshot once, seek reset, valid loop re-strike",
                        rules["once"] == 1
                        and rules["seek"] == 1
                        and rules["loop"] == 2,
                        rules,
                    )
                    check(
                        "disabled and reduced-motion modes",
                        rules["cleared"]
                        and rules["reducedParticles"] == 0
                        and rules["reducedPulses"] == 1,
                        rules,
                    )
                    # Exercise the real visible effect switch, not just a JS setter.
                    rect = view.evaluate(
                        '(()=>{const r=document.getElementById("rollEffects").getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()'
                    )
                    view.click(round(rect["x"]), round(rect["y"]))
                    await asyncio.sleep(0.1)
                    check(
                        "native effect switch disables particles",
                        not view.evaluate("App.rollDiagnostics.enabled"),
                    )
                    view.click(round(rect["x"]), round(rect["y"]))
                    await asyncio.sleep(0.1)
                    check(
                        "native effect switch re-enables",
                        view.evaluate("App.rollDiagnostics.enabled"),
                    )
                    await view.evaluate_async("piano.stop()")
                    await view.evaluate_async("piano.set_loop(true,0,4)")
                    await view.evaluate_async("piano.play()")
                    if args.effects_off:
                        view.click(round(rect["x"]), round(rect["y"]))
                        await asyncio.sleep(0.1)
                    report["effects_enabled"] = view.evaluate(
                        "App.rollDiagnostics.enabled"
                    )
                    # Allow the actual loop editor resize and audio start to settle.
                    await asyncio.sleep(0.25)
                    report["measurement_warmup_s"] = 0.25
                    view.evaluate("App.beginMeasure(" + str(args.seconds) + ")")
                    await asyncio.sleep(args.seconds + 0.1)
                    performance = view.evaluate("App.measurement")
                    performance["minimum_fps"] = min(performance["frames"])
                    report["performance"] = performance
                    check(
                        "actual roll playback minimum 30 FPS",
                        len(performance["frames"]) == args.seconds
                        and performance["minimum_fps"] >= 30,
                        performance,
                    )
                    check(
                        "particles stay bounded across actual loop wraps",
                        view.evaluate(
                            "App.rollDiagnostics.particles<=App.rollDiagnostics.particle_limit"
                        ),
                    )
                    check(
                        "no device underrun", c.audio.underruns == 0, c.audio.underruns
                    )
                    check(
                        "source file and compiled MIDI unchanged",
                        fixture.read_bytes() == original and c.plan.midi_bytes == midi,
                    )
                    check(
                        "no script errors",
                        not view.evaluate("APP_ERRORS"),
                        view.evaluate("APP_ERRORS"),
                    )
                    report["status"] = "passed"
                except Exception:
                    report["page"] = json.loads(
                        view.evaluate(
                            "JSON.stringify({errors:window.APP_ERRORS||[],text:document.body.innerText,roll:window.App?App.rollDiagnostics:null})"
                        )
                    )
                    if not args.gpu:
                        screenshot(view, out / "failed.png")
                    raise
                finally:
                    c.close()
                    app.close()
                    await pump

            asyncio.run(verify())
    except Exception as exc:
        traceback.print_exc()
        report["error"] = str(exc)
    finally:
        c.close()
        (out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
        print(out, report["status"])
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
