"""Whole downloaded MIDI -> native preview/apply/export/DAC-clock acceptance."""

import asyncio
import hashlib
import json
import resource
import shutil
import time
from collections import Counter

from pianoscope.dev_paths import MIDI_ROOT, artifact_dir


async def verify_readable(view, c, args, report):
    from run import save_view

    out = artifact_dir("samples") / "readable"
    out.mkdir(parents=True, exist_ok=True)
    checks = []
    report["assertions"] = checks
    report["songs"] = []

    def check(name, ok, detail=None):
        checks.append(dict(name=name, passed=bool(ok), detail=detail))
        if not ok:
            raise AssertionError(name + ": " + str(detail))

    def js(code):
        return view.evaluate(code)

    async def call(code):
        return await view.evaluate_async(code)

    async def shot(name):
        if args.cpu:
            await asyncio.sleep(0.2)
            save_view(view, artifact_dir("screenshots") / name)

    async def wait_ready():
        await view.wait_until(
            lambda: js(
                "window.PIANOSCOPE_READY===true && !!PianoScope.score && !PianoScope.job"
            ),
            timeout=45,
        )

    await asyncio.sleep(0.3)
    await wait_ready()
    check("real output available", c.audio.ready, c.audio.error)
    report["viewport"] = js(
        "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"
    )
    report["renderer"] = "CPU" if args.cpu else "GPU"
    folder = await call(
        "piano.open_midi_folder("
        + json.dumps(str(MIDI_ROOT))
        + ").then(Python.to_value)"
    )
    js("PianoScope.setLibrary(" + json.dumps(folder) + ")")
    previous = None
    for filename, stem, notes, voices, shorts in [
        ("Hans Zimmer - First Step - Interstellar.mid", "interstellar", 1205, 2, 0),
        ("Rush E.mid", "rush-e", 1842, 3, 32),
        ("Interstellar-Main-Theme-MIDI.mid", "interstellar-main-theme", 1566, 4, 0),
    ]:
        if args.readable_song and args.readable_song != stem:
            continue
        path = MIDI_ROOT / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        token = {
            "file_token": next(
                s["file_token"] for s in folder["songs"] if s["filename"] == filename
            )
        }
        await call(
            "PianoScope.waitJob(Python.to_value(piano.begin_load("
            + json.dumps(token)
            + ")))"
        )
        # Actual conditional assignment UI, as requested, not a replacement MIDI.
        js("document.getElementById('settings').click()")
        await view.wait_until(
            lambda: js("!document.getElementById('editor').hidden"), timeout=5
        )
        js(
            "document.getElementById('rule').value='pitch_split';document.getElementById('rule').dispatchEvent(new Event('change'));document.getElementById('split').value='60';document.getElementById('split').dispatchEvent(new Event('change'));document.getElementById('preview').click()"
        )
        await view.wait_until(
            lambda: js("!document.getElementById('applyHands').disabled"), timeout=5
        )
        revision = c.score.revision
        js("document.getElementById('applyHands').click()")
        await view.wait_until(
            lambda: (
                c.score.revision > revision
                and js(
                    "PianoScope.score.revision==="
                    + str(c.score.revision)
                    + ' && !document.getElementById("settings").disabled'
                )
            ),
            timeout=40,
        )
        check(
            stem + " all source notes assigned via UI",
            len(c.score.notes) == notes
            and all(
                n.hand == ("left" if n.pitch < 60 else "right") for n in c.score.notes
            ),
        )
        pcm = c.audio.pcm
        generation = c.generation
        original = [vars(n).copy() for n in c.score.notes]
        await call("piano.play()")
        await asyncio.sleep(0.1)
        js(
            "ScoreView.openSettings();document.getElementById('confirmDefaults').checked=true"
        )
        check(
            stem + " automatic readable default",
            js("document.getElementById('rhythm').value==='auto'"),
        )
        js("document.getElementById('generateNotation').click()")
        await view.wait_until(
            lambda: js(
                '!!ScoreView.preview && ScoreView.preview.score_id===PianoScope.score.score_id && ScoreView.display && ScoreView.display.preview_id===ScoreView.preview.preview_id && !document.getElementById("applyNotation").disabled'
            ),
            timeout=65,
        )
        check(
            stem + " generation preserves actual playback and PCM",
            c.audio.playing and c.audio.pcm is pcm and c.generation == generation,
        )
        check(
            stem + " preview does not replace old applied score",
            c.notation.applied is previous,
        )
        p = js("ScoreView.preview")
        check(
            stem + " full preview and inference counts",
            p["profile"] == 2
            and p["notes"] == notes
            and max(p["voices"].values()) == voices
            and p["normalization_counts"].get("short_fill", 0) == shorts,
            p,
        )
        await shot(stem + "-readable-preview-" + str(args.width) + ".png")
        js("document.getElementById('applyNotation').click()")
        await view.wait_until(
            lambda: js(
                "!ScoreView.preview && !!ScoreView.applied && ScoreView.applied.score_id===PianoScope.score.score_id"
            ),
            timeout=5,
        )
        previous = c.notation.applied
        doc = previous["document"]
        manifest = previous["manifest"]
        check(
            stem + " whole source conserved",
            set(doc["source_note_index"]) == {n.id for n in c.score.notes}
            and all(n["notation_event_ids"] for n in doc["source_note_index"].values()),
        )
        check(
            stem + " actual canvas pages loaded",
            js(
                "ScoreView.systems.every(s=>s.image.complete && s.image.naturalWidth>0 && s.base.width>0)"
            ),
        )
        check(
            stem + " source and original file unchanged",
            original == [vars(n) for n in c.score.notes]
            and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
        )

        # Compare actual highlights to original DAC snapshot on visible systems.
        async def highlight_check(label):
            await asyncio.sleep(0.2)
            js("ScoreView.draw(Python.to_value(piano.get_transport()))")
            await asyncio.sleep(0.06)
            h = js(
                """(()=>{const t=Python.to_value(piano.get_transport());ScoreView.draw(t);const r=document.getElementById('scoreViewport').getBoundingClientRect(),expected=[],visible=[];for(const s of ScoreView.systems){const b=s.node.getBoundingClientRect();if(b.bottom<r.top||b.top>r.bottom)continue;visible.push({page:s.page,id:s.id,painted:s.painted,bounds:[b.top,b.bottom]});for(const g of s.glyphs)if(g.pitch!==null&&g.source_display_spans.some(p=>t.active_note_ids.includes(p.source_note_id)&&p.start_s<=t.position_s&&t.position_s<p.end_s))expected.push(g.event_id)}return {actual:ScoreView.highlights,expected,phase:t.phase,position:t.position_s,viewActive:ScoreView.active,displayState:ScoreView.display.state,sourceMatches:ScoreView.display.score_id===t.score_id,hand:t.hand_mode,seq:t.seq,signature:ScoreView.drawSignature,visible,tracks:PianoScope.score.tracks,volume:t.volume}})()"""
            )
            check(
                stem + " DAC source highlights " + label,
                h["phase"] == "playing"
                and sorted(h["actual"]) == sorted(h["expected"]),
                h,
            )

        await highlight_check("normal")
        await call("piano.pause()")
        for zoom in ("1", "1.25", "1.5"):
            result = js(
                """(()=>{document.getElementById('scoreZoom').value=ZOOM;document.getElementById('scoreZoom').dispatchEvent(new Event('change'));ScoreView.suspendFollow();const s=ScoreView.systems[0],g=s.glyphs.find(g=>g.pitch!==null&&g.seek_s>.2);document.getElementById('scoreViewport').scrollTop=s.node.offsetTop;const r=s.overlay.getBoundingClientRect(),scale=r.width/s.crop[2],x=r.left+(g.bbox[0]+g.bbox[2]/2-s.crop[0])*scale,y=r.top+(g.bbox[1]+g.bbox[3]/2-s.crop[1])*scale,hit=ScoreView.hit(s,x,y);s.overlay.dispatchEvent(new MouseEvent('click',{clientX:x,clientY:y}));return {hit,expected:g.seek_s,error:Math.abs((x-r.left)/scale+s.crop[0]-(g.bbox[0]+g.bbox[2]/2))}})()""".replace(
                    "ZOOM", json.dumps(zoom)
                )
            )
            await asyncio.sleep(0.15)
            check(
                stem + " real glyph click " + zoom,
                result["hit"]
                and abs(c.audio.position - result["expected"]) < 1e-6
                and result["error"] <= 1,
                result,
            )
        js(
            "document.getElementById('scoreZoom').value='1';document.getElementById('scoreZoom').dispatchEvent(new Event('change'));ScoreView.restoreFollow()"
        )
        # Source held note extends across at least one notated tie boundary.
        long = next(
            (
                n
                for n in c.score.notes
                if n.key_off_s - n.start_s > 0.8
                and len(doc["source_note_index"][n.id]["notation_event_ids"]) > 1
            ),
            None,
        )
        check(stem + " actual tied source available", long is not None)
        tied = next(
            e
            for e in doc["events"]
            if long.id in e["source_note_ids"]
            and e["tie_stop"]
            and e["source_display_spans"][0]["end_s"]
            > e["source_display_spans"][0]["start_s"]
        )
        rejected_rates = []
        for rate in (0.5, 0.75, 1):
            required = round((c.score.duration_s / rate + 2) * c.audio.sample_rate) * 8
            if required > 192 * 1024 * 1024:
                before_pcm = c.audio.pcm
                before_rate = c.config["rate"]
                job = await call(
                    "Python.to_value(piano.configure("
                    + str(rate)
                    + ",PianoScope.score.tracks,'both'))"
                )
                await view.wait_until(
                    lambda: c.get_job(job["job_id"])["done"], timeout=20
                )
                state = c.get_job(job["job_id"])
                check(
                    stem + " over-budget rate safely rejected " + str(rate),
                    bool(state["error"])
                    and c.audio.pcm is before_pcm
                    and c.config["rate"] == before_rate
                    and c.notation.applied is previous,
                    state,
                )
                rejected_rates.append(
                    dict(rate=rate, required_pcm_bytes=required, error=state["error"])
                )
                continue
            await call(
                "PianoScope.waitJob(Python.to_value(piano.configure("
                + str(rate)
                + ",PianoScope.score.tracks,'both')))"
            )
            await call(
                "piano.seek(" + str(tied["source_display_spans"][0]["start_s"]) + ")"
            )
            await call("piano.play()")
            await highlight_check("tie rate " + str(rate))
            await call("piano.pause()")
            check(
                stem + " rate keeps notation revision " + str(rate),
                c.notation.applied is previous,
            )
        if shorts:
            zero_ids = {n.id for n in c.score.notes if n.start_tick == n.key_off_tick}
            zero = next(n for n in c.score.notes if n.id in zero_ids)
            await call("piano.seek(" + str(zero.start_s) + ")")
            await call("piano.play()")
            await asyncio.sleep(0.1)
            check(
                "zero sources never acquire invented sounding spans",
                all(
                    p["start_s"] == p["end_s"]
                    for e in doc["events"]
                    if zero_ids.intersection(e["source_note_ids"])
                    for p in e["source_display_spans"]
                ),
            )
            check(
                "zero source never in active DAC ids",
                not zero_ids.intersection(c.get_transport()["active_note_ids"]),
            )
            await call("piano.pause()")
        # Hand/track audition remains separate from export and notation.
        for hand in ("left", "right", "both"):
            await call(
                "PianoScope.waitJob(Python.to_value(piano.configure(1,PianoScope.score.tracks,"
                + json.dumps(hand)
                + ")))"
            )
            await call("piano.seek(1)")
            await call("piano.play()")
            await asyncio.sleep(0.15)
            active = c.get_transport()["active_note_ids"]
            lookup = {n.id: n for n in c.score.notes}
            check(
                stem + " hand audition " + hand,
                all(hand == "both" or lookup[nid].hand == hand for nid in active)
                and c.get_notation()["notes"] == notes,
            )
            await call("piano.pause()")
        tracks = [dict(t, muted=i == 0) for i, t in enumerate(c.score.tracks)]
        await call(
            "PianoScope.waitJob(Python.to_value(piano.configure(1,"
            + json.dumps(tracks)
            + ",'both')))"
        )
        check(
            stem + " track audition leaves full export scope",
            c.get_notation()["notes"] == notes and c.notation.applied is previous,
        )
        tracks = [dict(t, muted=False) for t in c.score.tracks]
        await call(
            "PianoScope.waitJob(Python.to_value(piano.configure(1,"
            + json.dumps(tracks)
            + ",'both')))"
        )
        await call("piano.set_loop(true,1,1.5)")
        await call("piano.play()")
        positions = []
        start = time.perf_counter()
        while time.perf_counter() - start < 5.8:
            await asyncio.sleep(0.04)
            positions.append(c.get_transport()["position_s"])
        wraps = sum(b < a for a, b in zip(positions, positions[1:]))
        check(
            stem + " ten actual DAC A-B loops",
            wraps >= 10 and all(1 <= p < 1.5 for p in positions),
            wraps,
        )
        await call("piano.set_loop(false,1,1.5)")
        await call("piano.pause()")
        # Both actual formats use the applied version and real atomic save worker.
        for fmt in ("pdf", "musicxml"):
            target = c.notation.target(
                previous["notation_id"], fmt, out / (stem + "." + fmt)
            )
            j = await call(
                "Python.to_value(piano.begin_score_export("
                + json.dumps(previous["notation_id"])
                + ","
                + json.dumps(fmt)
                + ","
                + json.dumps(target["target_token"])
                + "))"
            )
            await view.wait_until(
                lambda: c.get_notation_job(j["job_id"])["done"], timeout=10
            )
            check(
                stem + " real atomic export " + fmt,
                c.get_notation_job(j["job_id"])["phase"] == "completed",
            )
        shutil.copy(
            previous["directory"] / "document.json", out / (stem + ".document.json")
        )
        shutil.copy(
            previous["directory"] / "manifest.json", out / (stem + ".layout.json")
        )
        # Current settings expose adjustments and retain usable generation controls.
        js("ScoreView.openSettings()")
        await shot(stem + "-readable-settings-" + str(args.width) + ".png")
        check(
            stem + " adjustment review has source warning links",
            js(
                "document.querySelectorAll('#notationWarnings .warning-link').length>0 && !document.getElementById('notationSettings').hidden"
            ),
        )
        if shorts:
            js(
                "(()=>{const s=document.querySelector('#notationWarnings select');s.value='short_fill';s.dispatchEvent(new Event('change'));document.querySelector('#notationWarnings select').scrollIntoView({block:'start'})})()"
            )
            check(
                stem + " short-fill review category",
                js(
                    "document.querySelector('#notationWarnings select').value==='short_fill' && document.querySelector('#notationWarnings p').textContent.endsWith('/ "
                    + str(shorts)
                    + "') && document.querySelectorAll('#notationWarnings .warning-link').length===20"
                ),
            )
            await shot(stem + "-readable-short-fill-" + str(args.width) + ".png")
            js("document.querySelector('#notationWarnings .warning-link').click()")
            check(
                stem + " warning link locates without seeking audio",
                js(
                    "document.getElementById('notationSettings').hidden && !ScoreView.following"
                )
                and c.notation.applied is previous,
            )
        js("document.getElementById('closeNotation').click()")
        # Background cancellation/failure keep current applied score and PCM.
        before = c.audio.pcm
        j = c.begin_notation(
            dict(profile=2, rhythm="auto", confirm_defaults=True, pickup="1")
        )
        check(stem + " cancel pending readable job", c.cancel_notation_job(j["job_id"]))
        bad = c.begin_notation(
            dict(profile=2, rhythm="auto", confirm_defaults=True, pickup="8")
        )
        await view.wait_until(
            lambda: c.get_notation_job(bad["job_id"])["done"], timeout=10
        )
        check(
            stem + " readable failure preserves score and PCM",
            c.get_notation_job(bad["job_id"])["error"]
            and c.notation.applied is previous
            and c.audio.pcm is before,
        )
        await call("piano.seek(0)")
        await call("piano.play()")
        js("ScoreView.restoreFollow()")
        # Warm up FPS accounting after the earlier preparation and UI work.
        await asyncio.sleep(1.5)
        js(
            "document.getElementById('scoreViewport').dispatchEvent(new WheelEvent('wheel',{deltaY:200}));document.getElementById('scoreViewport').scrollTop=500"
        )
        manual = js("document.getElementById('scoreViewport').scrollTop")
        await asyncio.sleep(0.2)
        check(
            stem + " manual browsing preserves playback",
            c.audio.playing
            and not js("ScoreView.following")
            and abs(js("document.getElementById('scoreViewport').scrollTop") - manual)
            < 1,
        )
        js("ScoreView.restoreFollow()")
        perf = None
        if args.measure_seconds:
            start = time.perf_counter()
            cpu = time.process_time()
            fps = []
            underruns = c.audio.underruns
            transport_before = c.get_transport()
            states = []
            while time.perf_counter() - start < args.measure_seconds:
                await asyncio.sleep(0.5)
                fps.append(js("PianoScope.fps"))
                states.append(c.get_transport())
            perf = dict(
                seconds=time.perf_counter() - start,
                fps_min=min(fps),
                fps_mean=sum(fps) / len(fps),
                fps_max=max(fps),
                fps_samples=fps,
                cpu_percent=100
                * (time.process_time() - cpu)
                / (time.perf_counter() - start),
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                underruns=c.audio.underruns - underruns,
                transport_before=transport_before,
                transport_after=c.get_transport(),
                phase_changes=[
                    (i, s["phase"], s["position_s"], s["clock_epoch"])
                    for i, s in enumerate(states)
                    if s["phase"] != "playing"
                ],
            )
            check(
                stem + " whole song score >=30 FPS",
                c.audio.playing and min(fps) >= 30,
                perf,
            )
        await shot(stem + "-readable-playing-" + str(args.width) + ".png")
        await call("piano.pause()")
        report["songs"].append(
            dict(
                filename=filename,
                stem=stem,
                source_sha256=digest,
                notes=notes,
                pages=len(manifest["pages"]),
                voices=doc["voices"],
                notation_revision=previous["notation_revision"],
                normalization_kinds=dict(
                    Counter(
                        v["normalization"]["kind"]
                        for v in doc["source_note_index"].values()
                    )
                ),
                rejected_rates=rejected_rates,
                performance=perf,
            )
        )
        print("Native readable " + stem + ": PASS", flush=True)
    check(
        "no native JavaScript errors",
        js("window.APP_ERRORS.length===0"),
        js("window.APP_ERRORS"),
    )
    report["success"] = True
