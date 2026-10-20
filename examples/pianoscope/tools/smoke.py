"""Real AppCore checks; device, structural and human evidence stay separate."""

import asyncio
import hashlib
import json
import os
import platform
import resource
import struct
import time
from importlib.metadata import version

import psutil

from pianoscope.score.mapping import json_value


async def verify(view, c, args, report):
    def check(name, condition, detail=None):
        report["checks"].append(
            dict(
                name=name,
                status="passed" if condition else "failed",
                detail=json_value(detail),
            )
        )
        if not condition:
            raise AssertionError(name + ": " + str(detail))

    async def call(source):
        return await view.evaluate_async(source, copy=True)

    await asyncio.sleep(0.4)
    await view.wait_until(
        lambda: view.evaluate(
            "window.PIANOSCOPE_READY===true&&!!App.document&&!App.loadJob"
        ),
        timeout=60,
    )
    check("real MusicXML document published", c.plan is not None)
    check("fixed native binding", version("ultralight-py") == "0.6.1")
    check(
        "no JavaScript errors",
        not view.evaluate("APP_ERRORS"),
        view.evaluate("APP_ERRORS", copy=True),
    )
    check(
        "default roll is ready without engraving",
        view.evaluate('App.view==="roll"&&App.rows.length===0')
        and not c.get_document()["layout_ready"],
    )
    # Exercise the same records/arrays consumed directly by the settings UI.
    shared = view.evaluate("window.containerProbe = piano.get_practice_settings()")
    check(
        "API records round-trip as original Python containers", isinstance(shared, dict)
    )
    original_staffs = list(shared["staff_ids"])
    view.evaluate(
        'containerProbe.staves[0].name="JS probe";'
        'containerProbe.staff_ids.push("probe");true'
    )
    check(
        "native JS property and array writes reach Python",
        shared["staves"][0]["name"] == "JS probe"
        and shared["staff_ids"] == original_staffs + ["probe"],
    )
    shared["staves"][0]["name"] = "Python probe"
    check(
        "Python writes appear through native JS array methods",
        view.evaluate(
            "Array.isArray(containerProbe.staves)&&"
            'containerProbe.staves.map(s=>s.name).includes("Python probe")'
        ),
    )
    view.evaluate("delete window.containerProbe")
    check(
        "editing a returned settings record does not apply a command",
        c.get_practice_settings()["staff_ids"] == original_staffs,
    )
    check(
        "async configuration captures native JS arrays before caller mutation",
        await call(
            """(async()=>{
              const settings=piano.get_practice_settings();
              const changes={staff_ids:settings.staff_ids.slice(),voice_ids:settings.voice_ids.slice()};
              const expected=changes.staff_ids.join(',');
              const pending=piano.configure(changes);
              changes.staff_ids.push('invalid-after-call');
              await pending;
              return piano.get_practice_settings().staff_ids.join(',')===expected;
            })()"""
        ),
    )
    report["initial_worker"] = "not_started: lazy staff layout"
    view.evaluate('document.getElementById("sheetMode").click();true')
    await view.wait_until(
        lambda: view.evaluate("App.rows.length>0&&!App.sheetRequest"), timeout=60
    )
    check(
        "Canvas score rows exist after staff request",
        view.evaluate("App.rows.length") > 0,
    )
    check("initial load waits for play", not c.audio.playing and c.audio.position == 0)
    if args.width <= 850:
        check(
            "small window hides sidebar and spectrum; roll needs keyboard",
            view.evaluate(
                '!document.getElementById("keyboard").hidden&&document.getElementById("analysis").hidden&&!document.body.classList.contains("sidebar-open")'
            ),
        )
    report["viewport"] = view.evaluate(
        "({css_width:innerWidth,css_height:innerHeight,dpr:devicePixelRatio,canvas_backing_ratio:CPU_RENDERER?1:Math.min(2,devicePixelRatio)})",
        copy=True,
    )
    if platform.system() == "Darwin":
        from AppKit import NSApplication

        windows = [
            w
            for w in NSApplication.sharedApplication().windows()
            if str(w.title()) == "PianoScope"
        ]
        if windows:
            native = windows[0]
            points = native.contentView().bounds()
            physical = native.contentView().convertRectToBacking_(points)
            report["viewport"]["native_content_points"] = [
                points.size.width,
                points.size.height,
            ]
            report["viewport"]["native_content_backing_pixels"] = [
                physical.size.width,
                physical.size.height,
            ]
    report["device"] = c.audio.device
    report["reference_machine"] = dict(
        machine=platform.machine(),
        processor=platform.processor(),
        logical_cpus=psutil.cpu_count(),
        memory_bytes=psutil.virtual_memory().total,
    )
    report["process_tree"] = [
        dict(pid=p.pid, name=p.name())
        for p in [psutil.Process(), *psutil.Process().children(recursive=True)]
    ]
    if os.environ.get("PIANOSCOPE_NETWORK_DENIED") == "1":
        import socket

        with socket.socket() as probe:
            try:
                probe.connect(("1.1.1.1", 443))
            except PermissionError as exc:
                report["offline_policy"] = dict(
                    network="sandbox deny network*", probe=str(exc)
                )
            else:
                raise AssertionError("offline sandbox did not deny connect")
        check(
            "network denied while native XML load and playback remain available", True
        )
    report["versions"] = {
        name: version(name)
        for name in (
            "ultralight-py",
            "verovio",
            "CairoSVG",
            "pypdf",
            "defusedxml",
            "mido",
            "numpy",
            "sounddevice",
        )
    }
    original_path = c.active["source_path"]
    original_token = c.token_for_path(original_path)
    original_hash = c.plan.document.source.sha256
    report["input_sha256"] = original_hash
    report["requested_layout_worker"] = c.active["data"]["worker_metrics"]
    await call("piano.seek(2)")
    check("real binding seek", abs(c.audio.position - 2) < 1e-8)
    target = next(e for e in c.plan.document.elements if e.visible and e.onset > 0)
    expected = c.plan.seek_target(target.id, c.audio.position)["start_s"]
    for zoom in (1, 1.25, 1.5):
        view.evaluate(
            'document.getElementById("zoom").value='
            + json.dumps(str(zoom))
            + ';document.getElementById("zoom").dispatchEvent(new Event("change"));true'
        )
        script = """(()=>{const id=IDENT,row=App.rows.find(r=>r.page.glyphs.some(g=>g.element_id===id)),g=row.page.glyphs.find(g=>g.element_id===id),r=row.canvas.getBoundingClientRect(),x=r.left+(g.bbox[0]+g.bbox[2]/2)*row.scale,y=r.top+(g.bbox[1]+g.bbox[3]/2-row.top)*row.scale;row.canvas.dispatchEvent(new MouseEvent('click',{clientX:x,clientY:y}));return {error:Math.max(Math.abs((x-r.left)/row.scale-(g.bbox[0]+g.bbox[2]/2)),Math.abs((y-r.top)/row.scale+row.top-(g.bbox[1]+g.bbox[3]/2)))*row.scale}})()""".replace(
            "IDENT", json.dumps(target.id)
        )
        geometry = view.evaluate(script, copy=True)
        await view.wait_until(
            lambda: abs(c.audio.position - expected) < 1e-7, timeout=5
        )
        check("native cropped-row click " + str(zoom), geometry["error"] <= 1, geometry)
    view.evaluate(
        'document.getElementById("zoom").value="1";document.getElementById("zoom").dispatchEvent(new Event("change"));true'
    )
    for mode, expected_count in (("full", 88), ("focused", None)):
        view.evaluate("document.getElementById(" + json.dumps(mode) + ").click();true")
        keys = view.evaluate(
            '({count:document.querySelectorAll("#keys .key").length,white:document.querySelectorAll("#keys .white").length,black:document.querySelectorAll("#keys .black").length})',
            copy=True,
        )
        check(
            "keyboard " + mode,
            keys["count"] == expected_count if expected_count else keys["count"] > 0,
            keys,
        )
        if mode == "full":
            check(
                "52 white and 36 black keys",
                keys["white"] == 52 and keys["black"] == 36,
                keys,
            )
    if args.audio_test:
        check("actual output device", c.audio.ready, c.audio.error)
        await call("piano.seek(2)")
        await call("piano.play()")
        await view.wait_until(lambda: c.get_transport()["position_s"] > 2.1, timeout=5)
        check(
            "DAC progresses with real instances",
            bool(c.get_transport()["active_instance_ids"]),
            c.get_transport(),
        )
        check("post-gain device output", float(abs(c.audio.heard_window()).max()) > 0)
        # Polling may publish another transport before the next Canvas frame.
        # Compare highlights with the snapshot actually consumed by that frame.
        before_paint = view.evaluate("App.lastPaint.seq")
        await view.wait_until(
            lambda: view.evaluate(
                "App.lastPaint.seq>"
                + str(before_paint)
                + "&&App.lastPaint.ids.length>0"
            ),
            timeout=5,
        )
        paint = view.evaluate(
            "({paint:App.lastPaint,transport:App.lastPaint.transport})", copy=True
        )
        check(
            "same DAC snapshot IDs actually painted",
            set(paint["paint"]["ids"]) == set(paint["transport"]["active_element_ids"]),
            paint,
        )
        before = c.get_transport()
        pcm = c.audio.pcm
        view.evaluate(
            'App.setView("roll");App.setView("sheet");document.getElementById("analysisToggle").click();document.getElementById("analysisToggle").click();true'
        )
        check(
            "views preserve PCM/epoch",
            c.audio.pcm is pcm
            and c.get_transport()["clock_epoch"] == before["clock_epoch"],
        )
        view.evaluate(
            'document.getElementById("sheet").dispatchEvent(new Event("wheel"));document.getElementById("sheet").scrollTop=150;true'
        )
        await asyncio.sleep(0.2)
        check(
            "manual browse suspends follow",
            not view.evaluate("App.follow")
            and view.evaluate('document.getElementById("sheet").scrollTop') > 100,
        )
        epoch = c.audio.epoch
        view.evaluate('document.getElementById("current").click();true')
        await asyncio.sleep(0.1)
        check(
            "resume follow preserves clock",
            view.evaluate("App.follow") and c.audio.epoch == epoch,
        )
        await call("piano.set_volume(0)")
        await asyncio.sleep(0.15)
        check(
            "mute suppresses IDs and analysis",
            not c.get_transport()["active_instance_ids"]
            and not any(c.get_analysis()["waveform"]),
        )
        await call("piano.set_volume(.65)")
        before = c.plan
        pcm = c.audio.pcm
        epoch = c.audio.epoch
        result = await call("piano.choose_score(true)")
        check(
            "real native open cancel preserves current",
            result is None
            and c.plan is before
            and c.audio.pcm is pcm
            and c.audio.epoch == epoch,
        )
        result = await call("piano.choose_score_folder(true)")
        check(
            "real native folder cancel preserves current",
            result is None and c.plan is before,
        )
        result = await call(
            "piano.choose_export("
            + json.dumps(c.plan.document.revision)
            + ',"pdf",true)'
        )
        check(
            "real native save cancel creates no job",
            result is None and c.plan is before,
        )
        # The invalid PNG is a failure injection into the actual native decoder.
        keep_resource = c.resource
        c.resource = lambda name: (
            b"injected invalid PNG"
            if name.startswith("score-")
            else keep_resource(name)
        )
        try:
            view.evaluate('App.load("demo:harmonics");true')
            await view.wait_until(
                lambda: (
                    c.plan.document.source.sha256 != original_hash
                    and view.evaluate("App.loadJob===null&&!App.sheetRequest")
                ),
                timeout=40,
            )
            check(
                "decode failure keeps new roll/audio usable without partial staff layout",
                not c.get_document()["layout_ready"]
                and view.evaluate("App.rows.length===0")
                and not c.audio.playing
                and c.audio.position == 0,
            )
        finally:
            c.resource = keep_resource
        view.evaluate(
            'document.querySelector("#sheet .sheet-status button").click();true'
        )
        await view.wait_until(
            lambda: view.evaluate("App.rows.length>0&&!App.sheetRequest"), timeout=40
        )
        check(
            "complete lazy layout publishes without autoplay",
            c.audio.position == 0
            and not c.audio.playing
            and view.evaluate("App.document.source_sha256")
            == c.plan.document.source.sha256,
        )
        for element_id in ("b-rest", "B", "c-tie-cross"):
            # These targets exercise distinct seek roles through the actual binding.
            if element_id == "b-rest":
                element_id = next(
                    e.id
                    for e in c.plan.document.elements
                    if e.pitch is None and e.visible
                )
            expected = c.plan.seek_target(element_id, c.audio.position)
            seek = await call("piano.seek_score(" + json.dumps(element_id) + ",null)")
            check(
                "real binding source seek " + element_id,
                abs(seek["position_s"] - expected["start_s"]) < 1e-8
                and seek["seek_target"]["occurrence_id"] == expected["occurrence_id"],
                seek["seek_target"],
            )
        second = await call('piano.seek_score("a-long","o4")')
        check(
            "explicit second occurrence binding",
            second["seek_target"]["occurrence_id"] == "o4"
            and abs(second["position_s"] - 7.5) < 1e-8,
        )
        view.evaluate("App.load(" + json.dumps(original_token) + ");true")
        await view.wait_until(
            lambda: (
                c.plan.document.source.sha256 == original_hash
                and view.evaluate("App.loadJob===null")
            ),
            timeout=40,
        )
        await view.wait_until(
            lambda: view.evaluate("App.rows.length>0&&!App.sheetRequest"), timeout=40
        )
        await call("piano.set_loop(true,.5,1)")
        await call("piano.seek(.5)")
        await call("piano.play()")
        await view.wait_until(
            lambda: (
                "小节"
                in view.evaluate('document.getElementById("loopVisits").textContent')
            ),
            timeout=3,
        )
        check(
            "loop endpoints display occurrence labels",
            True,
            view.evaluate(
                'document.getElementById("loopVisits").textContent', copy=True
            ),
        )
        wraps = 0
        previous = c.get_transport()["position_s"]
        epoch = c.audio.epoch
        deadline = time.monotonic() + 10
        while wraps < 10 and time.monotonic() < deadline:
            await asyncio.sleep(0.025)
            position = c.get_transport()["position_s"]
            if position < previous - 0.1:
                wraps += 1
            previous = position
        check(
            "ten real DAC loop wraps",
            wraps >= 10 and c.audio.epoch == epoch,
            dict(wraps=wraps, epoch=epoch),
        )
        await call("piano.stop()")
        check(
            "stop retains selection and resets position",
            c.audio.position == 0
            and c.audio.loop == dict(enabled=True, a_s=0.5, b_s=1),
        )
        await call("piano.play()")
        check("play after stop clamps to A", c.audio.position >= 0.5)
        await call("piano.pause()")
        await call("piano.set_loop(false,.5,1)")
        source_revision = c.plan.document.revision
        layout_revision = c.get_document()["layout_revision"]
        midi = c.plan.midi_bytes
        for rate in (0.5, 0.75, 1.0):
            await call("piano.configure({rate:" + str(rate) + "})")
            check(
                "real PCM rate " + str(rate),
                c.audio.rate == rate
                and c.plan.document.revision == source_revision
                and c.get_document()["layout_revision"] == layout_revision,
            )
        await call("piano.configure({staff_ids:[]})")
        check("empty staff audition is silent", float(abs(c.audio.pcm).max()) == 0)
        await call("piano.configure({staff_ids:null})")
        assignments = {
            e.id: "right" if e.staff_id == c.get_document()["staff_ids"][0] else "left"
            for e in c.plan.document.elements
            if e.pitch is not None
        }
        preview = c.preview_hands(assignments)
        await call("piano.apply_hands(" + json.dumps(preview["preview_id"]) + ")")
        await call('piano.configure({hand_mode:"left"})')
        await call("piano.seek(1)")
        await call("piano.play()")
        await view.wait_until(
            lambda: len(c.get_transport()["active_instance_ids"]) > 0, timeout=5
        )
        active = set(c.get_transport()["active_instance_ids"])
        check(
            "left audition reports only confirmed left instances",
            all(n["hand"] == "left" for n in c.plan.instances if n["id"] in active)
            and bool(active),
        )
        await call("piano.pause()")
        check(
            "source/layout/base MIDI survive audition",
            c.plan.document.revision == source_revision
            and c.get_document()["layout_revision"] == layout_revision
            and c.plan.midi_bytes == midi,
        )
        await call('piano.configure({hand_mode:"both"})')
        await call("piano.undo_hands()")
        check(
            "hand undo restores unassigned",
            c.get_document()["hand_status"] == "unassigned",
        )
        await call("App.refresh()")
        # Accepted targets are harness-supplied; native dialog cancellation above
        # is real. No human save/overwrite-button interaction is claimed.
        if args.smoke_report:
            import pianoscope.app.controller as session

            output = args.smoke_report.parent / (args.smoke_report.stem + "-exports")
            output.mkdir(parents=True, exist_ok=True)
            original_choose = session.choose_score_path
            report["exports"] = {}
            try:
                for format, suffix in (
                    ("pdf", "pdf"),
                    ("source", "musicxml"),
                    ("midi", "mid"),
                ):
                    target = output / ("score." + suffix)
                    session.choose_score_path = lambda *a, **k: target
                    chosen = await call(
                        "piano.choose_export("
                        + json.dumps(c.plan.document.revision)
                        + ","
                        + json.dumps(format)
                        + ")"
                    )
                    job = await call(
                        "piano.begin_export("
                        + json.dumps(chosen["snapshot_id"])
                        + ","
                        + json.dumps(format)
                        + ","
                        + json.dumps(chosen["target_token"])
                        + ")"
                    )
                    await view.wait_until(
                        lambda: c.get_job(job["job_id"])["done"], timeout=10
                    )
                    check(
                        "real atomic export " + format,
                        c.get_job(job["job_id"])["phase"] == "completed"
                        and target.is_file(),
                    )
                    report["exports"][format] = dict(
                        path=str(target),
                        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                        bytes=target.stat().st_size,
                    )
                check(
                    "native source copy byte equality",
                    (output / "score.musicxml").read_bytes()
                    == c.plan.document.source.original_bytes,
                )
                check(
                    "native MIDI byte equality",
                    (output / "score.mid").read_bytes() == c.plan.midi_bytes,
                )
            finally:
                session.choose_score_path = original_choose
        await call("piano.retry_audio()")
        check(
            "real device retry awaits manual play",
            c.audio.ready and not c.audio.playing,
        )
    await view.wait_until(
        lambda: view.evaluate('App.transport.phase!=="playing"'), timeout=3
    )
    await asyncio.sleep(0.12)
    if args.cpu and args.smoke_report:
        from tools.native_gate import screenshot

        path = args.smoke_report.with_suffix(".png")
        screenshot(view, path)
        report["screenshot_readback_pixels"] = list(
            struct.unpack(">II", path.read_bytes()[16:24])
        )
        if not args.measure_seconds:
            view.evaluate(
                'App.setView("roll");if(document.getElementById("keyboard").hidden)document.getElementById("keyboardToggle").click();document.getElementById("lift").value="35";document.getElementById("lift").dispatchEvent(new Event("input"));true'
            )
            await asyncio.sleep(0.15)
            check(
                "strike line persisted at 35 percent",
                view.evaluate('document.getElementById("liftText").textContent')
                == "35%",
            )
            screenshot(
                view, args.smoke_report.with_name(args.smoke_report.stem + "-roll.png")
            )
    if args.measure_seconds:
        if not args.audio_test:
            raise ValueError("发布性能必须使用 --audio-test")
        await call("piano.stop()")
        await call("piano.set_loop(true,0," + str(c.plan.duration_s) + ")")
        view.evaluate(
            'App.setView("sheet");App.setFollow(true);if(innerWidth<=850&&!document.getElementById("keyboard").hidden)document.getElementById("keyboardToggle").click();true'
        )
        await call("piano.play()")
        cpu = time.process_time()
        wall = time.monotonic()
        view.evaluate("App.beginMeasure(" + str(args.measure_seconds) + ")")
        await asyncio.sleep(args.measure_seconds + 0.15)
        metrics = view.evaluate("App.measurement", copy=True)
        metrics["cpu_percent"] = (
            100 * (time.process_time() - cpu) / (time.monotonic() - wall)
        )
        metrics["rss_bytes"] = psutil.Process().memory_info().rss
        metrics["peak_rss_bytes"] = resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss * (1 if platform.system() == "Darwin" else 1024)
        metrics["minimum_fps"] = min(metrics["frames"])
        metrics["mean_fps"] = sum(metrics["frames"]) / len(metrics["frames"])
        metrics["page_changes_included"] = True
        metrics["underruns"] = c.audio.underruns
        report["performance"] = metrics
        metrics["last_paint_snapshot"] = view.evaluate("App.lastPaint", copy=True)
        check(
            "every complete wall-clock window >=30 actual frames",
            len(metrics["frames"]) == int(args.measure_seconds)
            and metrics["minimum_fps"] >= 30,
            metrics,
        )
        check(
            "clock still playing after measurement",
            c.get_transport()["phase"] == "playing",
            c.get_transport(),
        )
        check("zero device underrun", c.audio.underruns == 0, c.audio.underruns)
    report["physical_audio_visual_latency"] = "not_run"
    report["manual_listening"] = "not_run"
    check(
        "source disk bytes unchanged",
        hashlib.sha256(original_path.read_bytes()).hexdigest() == original_hash,
    )
    check(
        "no final script errors",
        not view.evaluate("APP_ERRORS"),
        view.evaluate("APP_ERRORS", copy=True),
    )
