"""Targeted actual AppCore mouse interaction check for the UI."""

import argparse
import asyncio
import json
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from pianoscope.app.bridge import register
    from pianoscope.app.controller import Controller
    from tools.native_gate import screenshot

    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=600)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--measure-seconds", type=int, default=0)
    args = parser.parse_args()
    output = (
        ROOT.parents[1]
        / ".tmp/pianoscope/validation"
        / datetime.now().strftime("ui-%Y%m%d-%H%M%S")
    )
    output.mkdir(parents=True)
    report = dict(
        status="failed",
        size=[args.width, args.height],
        renderer="GPU" if args.gpu else "CPU",
        checks=[],
    )

    def capture(view, path):
        if not args.gpu:
            screenshot(view, path)

    from ultralight_py import API, Application, Resource

    c = Controller()
    assets = ROOT / "pianoscope/assets"
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
    resources["config.js"] = Resource(
        (
            "window.APP_ERRORS=[];window.onerror=m=>APP_ERRORS.push(String(m));window.CPU_RENDERER="
            + json.dumps(not args.gpu)
            + ';window.INITIAL_SOURCE="demo:first-light";'
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
            tempfile.TemporaryDirectory(prefix="pianoscope-ui-") as cache,
            API("piano") as api,
            Application(
                assets_root=str(assets),
                resource_loader=loader,
                cache_path=cache,
                force_cpu_renderer=not args.gpu,
                app_name="PianoScope UI check",
            ) as app,
        ):
            register(api, c)
            window = app.create_window(
                args.width, args.height, title="PianoScope UI check"
            )
            view = window.view
            api.attach(view)
            view.load_url("file:///index.html")

            async def verify():
                pump = asyncio.create_task(app.run_async(update_interval=1 / 120))
                try:
                    await asyncio.sleep(0.4)
                    await view.wait_until(
                        lambda: view.evaluate(
                            "window.PIANOSCOPE_READY&&App.document&&!App.loadJob"
                        ),
                        timeout=40,
                    )
                    await asyncio.sleep(0.2)
                    report["viewport"] = view.evaluate(
                        "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"
                    )
                    report["button_geometry"] = view.evaluate(
                        """(()=>{const b=document.getElementById('play'),r=b.getBoundingClientRect(),points=[];for(const x of [.1,.5,.9])for(const y of [.15,.5,.85]){const px=r.left+r.width*x,py=r.top+r.height*y,e=document.elementFromPoint(px,py);points.push({x:px,y:py,hit:e?e.tagName+'#'+e.id:null,button:e?e.closest('button')?.id:null})}return {rect:{x:r.x,y:r.y,width:r.width,height:r.height},points}})()"""
                    )
                    capture(view, output / "before.png")
                    for point in report["button_geometry"]["points"]:
                        await view.evaluate_async("piano.pause()")
                        view.click(round(point["x"]), round(point["y"]))
                        await asyncio.sleep(0.16)
                        passed = c.audio.playing
                        report["checks"].append(
                            dict(
                                name="native play hit",
                                point=point,
                                status="passed" if passed else "failed",
                            )
                        )
                    await view.evaluate_async("piano.pause()")
                    import time

                    from AppKit import (
                        NSApplication,
                        NSEvent,
                        NSEventTypeLeftMouseDown,
                        NSEventTypeLeftMouseUp,
                    )

                    native = next(
                        w
                        for w in NSApplication.sharedApplication().windows()
                        if str(w.title()) == "PianoScope UI check"
                    )
                    native.makeKeyAndOrderFront_(None)
                    view.evaluate(
                        'window.CLICK_PROBE=[];document.addEventListener("click",e=>CLICK_PROBE.push({x:e.clientX,y:e.clientY,target:e.target.id}),true);true'
                    )
                    for point in report["button_geometry"]["points"]:
                        await view.evaluate_async("piano.pause()")
                        for kind in (NSEventTypeLeftMouseDown, NSEventTypeLeftMouseUp):
                            event = NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
                                kind,
                                (
                                    point["x"],
                                    native.contentView().bounds().size.height
                                    - point["y"],
                                ),
                                0,
                                time.monotonic(),
                                native.windowNumber(),
                                None,
                                1,
                                1,
                                1.0,
                            )
                            native.sendEvent_(event)
                        await asyncio.sleep(0.16)
                        report["checks"].append(
                            dict(
                                name="AppKit play hit",
                                point=point,
                                status="passed" if c.audio.playing else "failed",
                            )
                        )
                    report["appkit_events"] = view.evaluate("CLICK_PROBE")
                    await view.evaluate_async("piano.pause()")
                    if not args.probe and not all(
                        x["status"] == "passed" for x in report["checks"]
                    ):
                        raise AssertionError("native play hit region")

                    if not args.probe:

                        def check(name, condition, detail=None):
                            report["checks"].append(
                                dict(
                                    name=name,
                                    status="passed" if condition else "failed",
                                    detail=detail,
                                )
                            )
                            if not condition:
                                raise AssertionError(name + ": " + str(detail))

                        async def click(selector):
                            geometry = view.evaluate(
                                """(()=>{const e=document.querySelector(SELECTOR);if(!e||!e.getClientRects().length)return null;e.scrollIntoView({block:'nearest',inline:'nearest'});const r=e.getBoundingClientRect();const x=r.left+r.width/2,y=r.top+r.height/2,hit=document.elementFromPoint(x,y);return {x,y,exposed:hit===e||e.contains(hit)}})()""".replace(
                                    "SELECTOR", json.dumps(selector)
                                )
                            )
                            if geometry is None:
                                raise AssertionError("control not visible: " + selector)
                            if not geometry["exposed"]:
                                raise AssertionError("control covered: " + selector)
                            if not 0 <= geometry["y"] < report["viewport"]["height"]:
                                raise AssertionError(
                                    "control outside window: "
                                    + selector
                                    + str(geometry)
                                )
                            view.click(round(geometry["x"]), round(geometry["y"]))
                            await asyncio.sleep(0.08)

                        async def text(text):
                            selector = view.evaluate(
                                """(()=>{const b=Array.from(document.querySelectorAll('#modal button')).find(e=>e.textContent===TEXT&&!e.disabled&&e.getClientRects().length);if(!b)return null;if(!b.id)b.id='ui-action-'+Date.now();return '#'+b.id})()""".replace(
                                    "TEXT", json.dumps(text)
                                )
                            )
                            if selector is None:
                                raise AssertionError("button not available: " + text)
                            await click(selector)

                        async def entry(ident):
                            if not view.evaluate(
                                "document.getElementById("
                                + json.dumps(ident)
                                + ").getClientRects().length>0"
                            ):
                                await click("#menu")
                            await click("#" + ident)
                            await view.wait_until(
                                lambda: view.evaluate(
                                    '!document.getElementById("modal").hidden'
                                ),
                                timeout=3,
                            )

                        async def closed():
                            await view.wait_until(
                                lambda: view.evaluate(
                                    'document.getElementById("modal").hidden'
                                ),
                                timeout=15,
                            )

                        check(
                            "no native dropdowns or radios",
                            view.evaluate(
                                'document.querySelectorAll("select,input[type=radio]").length===0'
                            ),
                        )
                        for rate in (0.75, 0.5, 1):
                            await click(
                                '#rate button[value="'
                                + str(rate).replace("0.", ".")
                                + '"]'
                                if rate != 1
                                else '#rate button[value="1"]'
                            )
                            await view.wait_until(
                                lambda: c.config["rate"] == rate, timeout=15
                            )
                            check("segmented rate " + str(rate), c.audio.rate == rate)
                        await click("#sheetMode")
                        await view.wait_until(
                            lambda: view.evaluate(
                                "App.rows.length>0&&!App.sheetRequest"
                            ),
                            timeout=40,
                        )
                        await click('#zoom button[value="1.5"]')
                        check(
                            "segmented zoom",
                            view.evaluate('document.getElementById("zoom").value')
                            == "1.5",
                        )
                        await click('#zoom button[value="1.25"]')
                        view.key_down(39)
                        view.key_up(39)
                        await asyncio.sleep(0.08)
                        check(
                            "segmented native Right arrow selects next option",
                            view.evaluate('document.getElementById("zoom").value')
                            == "1.5",
                        )
                        view.key_down(37)
                        view.key_up(37)
                        await asyncio.sleep(0.08)
                        check(
                            "segmented native Left arrow selects previous option",
                            view.evaluate('document.getElementById("zoom").value')
                            == "1.25",
                        )
                        await click('#zoom button[value="1"]')
                        snapshot = (
                            c.plan.document.source.sha256,
                            c.get_document()["layout_revision"],
                            c.plan.midi_bytes,
                        )
                        await entry("audition")
                        capture(view, output / "audition.png")
                        check(
                            "friendly scope names",
                            view.evaluate(
                                'document.getElementById("modalBody").textContent.includes("上谱表")&&!document.getElementById("modalBody").textContent.includes("P1:")'
                            ),
                        )
                        await text("下谱表")
                        await text("应用试听")
                        await closed()
                        check(
                            "scope applies actual lower staff",
                            c.config["staff_ids"] == ["P1:2"],
                        )
                        pcm = c.audio.pcm
                        await entry("audition")
                        check(
                            "reopen preserves lower staff",
                            view.evaluate(
                                'document.querySelector("#modal [role=radiogroup]").value'
                            )
                            == "1",
                        )
                        await text("上谱表")
                        await text("取消")
                        await closed()
                        check(
                            "cancel scope keeps applied PCM",
                            c.config["staff_ids"] == ["P1:2"] and c.audio.pcm is pcm,
                        )
                        await entry("audition")
                        await click("#modal summary")
                        await click('#modal details input[data-source-id="P1:1"]')
                        await text("应用试听")
                        await closed()
                        await entry("audition")
                        check(
                            "reopen preserves voice subset",
                            not view.evaluate(
                                'Array.from(document.querySelectorAll("#modal input")).find(e=>e.dataset.sourceId==="P1:1").checked'
                            ),
                        )
                        await text("恢复全部范围")
                        await text("应用试听")
                        await closed()
                        check(
                            "restore whole piece scope",
                            c.config["staff_ids"] == ["P1:1", "P1:2"]
                            and c.config["voice_ids"] == ["P1:1", "P1:2"],
                        )
                        await entry("hands")
                        check(
                            "initial hand suggestions do not alter audio",
                            not c.hands
                            and c.get_document()["hand_status"] == "unassigned",
                        )
                        check(
                            "undo disabled without history",
                            view.evaluate(
                                'document.querySelector("#modalActions button").disabled'
                            ),
                        )
                        capture(view, output / "hands.png")
                        check(
                            "hand labels are segmented buttons",
                            view.evaluate(
                                'document.querySelectorAll("#modal [role=radiogroup] button[role=radio]").length===6&&document.querySelectorAll("#modal select,#modal input[type=radio]").length===0'
                            ),
                        )
                        await click(
                            '#modal [aria-label="上谱表手别"] button[value="left"]'
                        )
                        check(
                            "live preview remains uncommitted",
                            not c.hands
                            and "分配预览"
                            in view.evaluate(
                                'document.getElementById("modalBody").textContent'
                            ),
                        )
                        await text("取消")
                        await closed()
                        check("cancel hand suggestions leaves unknown", not c.hands)
                        await entry("hands")
                        await text("确认分配")
                        await closed()
                        check(
                            "single confirmation applies hand labels",
                            c.get_document()["hand_status"] == "confirmed"
                            and bool(c.hands),
                        )
                        await entry("hands")
                        check(
                            "reopen uses saved hand labels",
                            view.evaluate(
                                'Array.from(document.querySelectorAll("#modal [role=radiogroup]")).find(g=>g.getAttribute("aria-label")==="上谱表手别").value'
                            )
                            == "right",
                        )
                        await text("取消")
                        await closed()
                        if args.width <= 1100:
                            await click("#menu")
                        await click('#handQuick button[value="left"]')
                        await view.wait_until(
                            lambda: c.config["hand_mode"] == "left", timeout=15
                        )
                        if args.width <= 1100:
                            await click("#closeSidebar")
                        await view.evaluate_async("piano.seek(0)")
                        report["before_left_play"] = c.get_transport()
                        await click("#play")
                        await view.wait_until(
                            lambda: bool(c.get_transport()["active_instance_ids"]),
                            timeout=3,
                        )
                        ids = set(c.get_transport()["active_instance_ids"])
                        check(
                            "quick left selects actual audible instances",
                            all(
                                n["hand"] == "left"
                                for n in c.plan.instances
                                if n["id"] in ids
                            ),
                        )
                        await click("#play")
                        await entry("hands")
                        await text("撤销上次分配")
                        await view.wait_until(
                            lambda: not c.hands and c.config["hand_mode"] == "both",
                            timeout=15,
                        )
                        check(
                            "undo returns both hands and disables empty undo",
                            view.evaluate(
                                'document.querySelector("#modalActions button").disabled'
                            ),
                        )
                        await text("取消")
                        await closed()
                        check(
                            "source PDF layout and default MIDI survive UI practice",
                            snapshot
                            == (
                                c.plan.document.source.sha256,
                                c.get_document()["layout_revision"],
                                c.plan.midi_bytes,
                            ),
                        )
                        # Hit-test the actual play control after panel expansion too.
                        for panel in ("keyboardToggle", "analysisToggle", "loop"):
                            await click("#" + panel)
                            await asyncio.sleep(0.1)
                            for edge in (0.1, 0.5, 0.9):
                                hit = view.evaluate(
                                    """(()=>{const b=document.getElementById('play'),r=b.getBoundingClientRect(),x=r.left+r.width*EDGE,y=r.top+r.height/2,e=document.elementFromPoint(x,y);return {x,y,hit:e&&e.closest('button')&&e.closest('button').id}})()""".replace(
                                        "EDGE", str(edge)
                                    )
                                )
                                check(
                                    "play exposed with " + panel + " " + str(edge),
                                    0 <= hit["y"] < report["viewport"]["height"]
                                    and hit["hit"] == "play",
                                    hit,
                                )
                                await view.evaluate_async("piano.pause()")
                                view.click(round(hit["x"]), round(hit["y"]))
                                await asyncio.sleep(0.1)
                                check(
                                    "play actual click with " + panel + " " + str(edge),
                                    c.audio.playing,
                                )
                            await view.evaluate_async("piano.pause()")
                            await click("#" + panel)
                        await asyncio.sleep(0.1)
                        capture(view, output / "restored-score.png")
                        await click("#rollMode")
                        await asyncio.sleep(0.1)
                        capture(view, output / "restored-roll.png")
                        await click("#sheetMode")
                        if not view.evaluate(
                            'document.getElementById("keyboard").hidden'
                        ):
                            await click("#keyboardToggle")
                        check(
                            "final no native dropdowns",
                            view.evaluate(
                                'document.querySelectorAll("select,input[type=radio]").length===0'
                            ),
                        )
                        if args.measure_seconds:
                            await click("#play")
                            view.evaluate(
                                "App.beginMeasure(" + str(args.measure_seconds) + ")"
                            )
                            await asyncio.sleep(args.measure_seconds + 0.1)
                            measurement = view.evaluate("App.measurement")
                            measurement["minimum_fps"] = min(measurement["frames"])
                            report["performance"] = measurement
                            check(
                                "targeted playback minimum 30 FPS",
                                measurement["minimum_fps"] >= 30,
                                measurement,
                            )
                            await click("#play")
                        check(
                            "no script errors",
                            not view.evaluate("APP_ERRORS"),
                            view.evaluate("APP_ERRORS"),
                        )

                    report["script_errors"] = view.evaluate("APP_ERRORS")
                    report["status"] = "probed" if args.probe else "passed"
                except Exception:
                    report["failure_transport"] = c.get_transport()
                    report["failure_settings"] = (
                        c.get_practice_settings() if c.plan else None
                    )
                    report["failure_page"] = view.evaluate(
                        '({errors:APP_ERRORS,message:document.getElementById("message").textContent,modal:document.getElementById("modal").hidden,body:document.body.className,clicks:CLICK_PROBE.slice(-20)})'
                    )
                    capture(view, output / "failed.png")
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
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
        print(output, report["status"])
    return int(report["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
