#!/usr/bin/env python3
"""Run the independent inventory UI in an Ultralight AppCore window or a browser server."""

from __future__ import annotations

import argparse
import asyncio
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import platform
import sys
import tempfile
import traceback

from reliquary.state import LayoutStore

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "web/dist"
ARTIFACTS = ROOT.parents[1] / ".tmp/ashen-reliquary"


def screenshot(view, path):
    """Write actual CPU view pixels without a Pillow dependency."""
    import struct
    import zlib

    image = view.copy_pixels().to_rgba()

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    stride = image.width * 4
    raw = b"".join(
        b"\0" + image.data[y * stride : (y + 1) * stride] for y in range(image.height)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR", struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
        )
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def native_window_focus(active=True):
    """Activate/deactivate the actual AppCore Cocoa window for focus acceptance."""
    if sys.platform != "darwin":
        return
    import ctypes

    runtime = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    runtime.objc_getClass.argtypes = [ctypes.c_char_p]
    runtime.objc_getClass.restype = ctypes.c_void_p
    runtime.sel_registerName.argtypes = [ctypes.c_char_p]
    runtime.sel_registerName.restype = ctypes.c_void_p
    selector = runtime.sel_registerName
    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        ("objc_msgSend", runtime)
    )
    application = send(
        runtime.objc_getClass(b"NSApplication"), selector(b"sharedApplication")
    )
    if not active:
        send(application, selector(b"deactivate"))
        return
    policy = ctypes.CFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long
    )(("objc_msgSend", runtime))
    policy(application, selector(b"setActivationPolicy:"), 0)
    activate = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)(
        ("objc_msgSend", runtime)
    )
    activate(application, selector(b"activateIgnoringOtherApps:"), True)
    window = send(application, selector(b"mainWindow"))
    if not window:
        windows = send(application, selector(b"windows"))
        index = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong
        )(("objc_msgSend", runtime))
        window = index(windows, selector(b"objectAtIndex:"), 0)
    foreground = ctypes.CFUNCTYPE(
        None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
    )(("objc_msgSend", runtime))
    foreground(window, selector(b"makeKeyAndOrderFront:"), None)


async def drive_application(app, window):
    """Forward native focus metadata; storage remains optional and independent."""
    import contextlib
    native_window_focus(True)
    async def focus_monitor():
        previous=None
        while not window.closed:
            view=window.view
            if view.is_settled:
                current=(view.navigation_id,view.has_focus)
                if current!=previous:
                    view.evaluate("window.__inventoryNativeFocused="+json.dumps(current[1])+";void 0")
                    previous=current
            await asyncio.sleep(1/60)
    monitor=asyncio.create_task(focus_monitor())
    try:
        await app.run_async(update_interval=1/120)
    finally:
        monitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor


async def verify(view, store, output, report, *, standalone=False):
    """Use native View input against the independent DOM renderer."""
    from ultralight_py import KeyCode, MouseButton, Modifiers

    await view.wait_settled(timeout=25)
    await view.wait_until(
        lambda: view.evaluate(
            '!!window.Reliquary && !!document.querySelector("[data-item]")'
        ),
        timeout=25,
    )
    await view.wait_until(
        lambda: view.evaluate(
            "Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)"
        ),
        timeout=15,
    )
    native_window_focus(True)
    await asyncio.sleep(0.5)
    view.focus()

    def evaluate(code):
        return view.evaluate(code, copy=True)

    def state():
        return json.loads(view.evaluate("JSON.stringify(Reliquary.snapshot())"))

    def check(name, passed, detail=None):
        report["checks"].append(dict(name=name, passed=bool(passed), detail=detail))
        if not passed:
            raise AssertionError(f"{name}: {detail}")

    async def point(selector):
        evaluate(
            "document.querySelector("
            + json.dumps(selector)
            + ').scrollIntoView({block:"center",inline:"center"});void 0'
        )
        await asyncio.sleep(0.15)
        return evaluate(
            "(()=>{const r=document.querySelector("
            + json.dumps(selector)
            + ").getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()"
        )

    async def click(selector):
        p = await point(selector)
        view.mouse_move(round(p["x"]), round(p["y"]))
        view.mouse_down(round(p["x"]), round(p["y"]), button=MouseButton.LEFT)
        view.mouse_up(round(p["x"]), round(p["y"]), button=MouseButton.LEFT)
        await asyncio.sleep(0.2)

    async def shift_click(selector):
        p=await point(selector)
        view.mouse_move(round(p["x"]),round(p["y"]))
        view.key_down(KeyCode.GK_SHIFT,modifiers=Modifiers.SHIFT)
        view.mouse_down(round(p["x"]),round(p["y"]),button=MouseButton.LEFT)
        view.mouse_up(round(p["x"]),round(p["y"]),button=MouseButton.LEFT)
        view.key_up(KeyCode.GK_SHIFT)
        await asyncio.sleep(.2)

    async def drag(
        item_id,
        x,
        y,
        *,
        rotate=False,
        cancel=False,
        blur=False,
        assert_active=False,
        target_container="bag",
    ):
        start = await point('[data-item="' + item_id + '"]')
        # All fixture destinations are in the visible Bag, in integer cells.
        end = evaluate(
            (
                '(()=>{const r=document.querySelector("[data-container=CONTAINER]").getBoundingClientRect();const scale=r.width/document.querySelector("[data-container=CONTAINER]").offsetWidth;const a=document.querySelector('
                + json.dumps('[data-item="' + item_id + '"]')
                + ").getBoundingClientRect();return {x:r.left+X*40*scale+a.width/2,y:r.top+Y*40*scale+a.height/2}})()"
            )
            .replace("X", str(x))
            .replace("Y", str(y))
            .replace("CONTAINER", target_container)
        )
        evaluate(
            "(()=>{const before=Reliquary.snapshot();window.__watch={running:true,samples:0,violations:[]};const watch=window.__watch;function sample(){if(!watch.running)return;watch.samples++;const now=Reliquary.snapshot();for(const old of before.items){if(old.id===ID)continue;const item=now.items.find(i=>i.id===old.id);if(JSON.stringify(item)!==JSON.stringify(old))watch.violations.push(old.id);}requestAnimationFrame(sample);}requestAnimationFrame(sample);})()".replace(
                "ID", json.dumps(item_id)
            )
        )
        view.mouse_move(round(start["x"]), round(start["y"]))
        view.mouse_down(round(start["x"]), round(start["y"]), button=MouseButton.LEFT)
        await asyncio.sleep(0.1)
        for n in range(1, 11):
            view.mouse_move(
                round(start["x"] + (end["x"] - start["x"]) * n / 10),
                round(start["y"] + (end["y"] - start["y"]) * n / 10),
            )
            await asyncio.sleep(0.025)
        report.setdefault("drag_diagnostics", []).append(
            json.loads(
                evaluate(
                    "JSON.stringify({active:!!Reliquary.view.drag,documentFocus:document.hasFocus(),cancellations:window.__cancelEvents})"
                )
            )
        )
        if assert_active:
            check("mouse fallback starts real drag", evaluate("!!Reliquary.view.drag"))
        if rotate:
            view.key_down(KeyCode.GK_R)
            view.key_up(KeyCode.GK_R)
            await asyncio.sleep(0.1)
        if blur:
            report["focus_before"] = evaluate("document.hasFocus()")
            native_window_focus(False)
            view.unfocus()
            await asyncio.sleep(0.1)
            report["focus_unfocused"] = evaluate("document.hasFocus()")
            view.focus()
            await asyncio.sleep(0.15)
            report["focus_restored"] = evaluate("document.hasFocus()")
        if cancel:
            view.key_down(KeyCode.GK_ESCAPE)
            view.key_up(KeyCode.GK_ESCAPE)
            await asyncio.sleep(0.1)
        sample = evaluate(
            "(()=>{__watch.running=false;return {samples:__watch.samples,violations:__watch.violations}})()"
        )
        check(
            "unrelated items fixed in every drag frame",
            sample["samples"] > 0 and not sample["violations"],
            sample,
        )
        view.mouse_up(round(end["x"]), round(end["y"]), button=MouseButton.LEFT)
        await asyncio.sleep(0.25)

    evaluate(
        "window.__hov=[];Reliquary.engine.on('hover',e=>__hov.push({phase:e.phase,itemId:e.itemId,hasContext:!!e.anchor&&!!e.position&&!!e.pointer&&!!e.modifiers}));void 0"
    )
    evaluate(
        "window.__cancelEvents=[];Reliquary.engine.on('cancel',e=>__cancelEvents.push(e));void 0"
    )
    original = state()
    check(
        "versioned snapshot and default capacities",
        original["schemaVersion"] == 1
        and [
            (c["width"], c["height"])
            for c in original["containers"]
            if c["kind"] == "grid"
        ]
        == [(12, 12), (12, 6)],
    )
    check("all demo items seeded", len(original["items"]) == 20, original)
    screenshot(view, output / "initial.png")
    await drag("seed-15", 9, 2, cancel=True)
    check("Escape leaves exact state unchanged", state() == original)
    check(
        "hover enter and leave carry full context",
        evaluate(
            "__hov.some(e=>e.phase==='enter')&&__hov.some(e=>e.phase==='leave')&&__hov.every(e=>e.hasContext)"
        ),
    )
    await drag("seed-15", 6, 0)
    check("collision leaves exact state unchanged", state() == original)
    await drag("seed-15", 9, 2, rotate=True)
    rotated = next(i for i in state()["items"] if i["id"] == "seed-15")
    check(
        "native R and release commit rotation",
        rotated["position"] == dict(container="bag", x=9, y=2, rotation=1),
        rotated,
    )
    await drag("seed-15", 11, 5)
    check(
        "out of bounds does not clamp or move",
        next(i for i in state()["items"] if i["id"] == "seed-15") == rotated,
    )
    # Double click ring through native events; the business handler equips it.
    ring_point = await point('[data-item="seed-12"]')
    for _ in range(2):
        view.mouse_move(round(ring_point["x"]), round(ring_point["y"]))
        view.mouse_down(
            round(ring_point["x"]), round(ring_point["y"]), button=MouseButton.LEFT
        )
        view.mouse_up(
            round(ring_point["x"]), round(ring_point["y"]), button=MouseButton.LEFT
        )
        await asyncio.sleep(0.06)
    await asyncio.sleep(0.2)
    check(
        "double click equips ring",
        next(i for i in state()["items"] if i["id"] == "seed-12")["position"][
            "container"
        ]
        == "ring1",
    )
    before_transfer = state()
    await shift_click('[data-item="seed-13"]')
    check(
        "native Shift click transfers across containers",
        next(i for i in state()["items"] if i["id"] == "seed-13")["position"][
            "container"
        ]
        == "ground",
    )
    check(
        "shortcut leaves unrelated items fixed",
        all(
            next(i for i in state()["items"] if i["id"] == old["id"]) == old
            for old in before_transfer["items"]
            if old["id"] != "seed-13"
        ),
    )
    await click(".demo-toolbar button:nth-of-type(4)")
    await point('[data-item="seed-13"]')
    screenshot(view, output / "ground.png")
    await shift_click('[data-item="seed-13"]')
    check(
        "Ground drawer supports return transfer",
        next(i for i in state()["items"] if i["id"] == "seed-13")["position"][
            "container"
        ]
        == "bag",
    )
    await shift_click('[data-item="seed-9"]')
    check(
        "flask shortcut transfer",
        next(i for i in state()["items"] if i["id"] == "seed-9")["position"][
            "container"
        ]
        == "bag",
    )
    await click(".demo-toolbar button:nth-of-type(4)")
    p = await point('[data-item="seed-9"]')
    view.mouse_move(round(p["x"]), round(p["y"]))
    await asyncio.sleep(0.1)
    await click('[aria-label="Bind slot 2"]')
    await click(".quickbar > div:nth-child(2) > button:first-child")
    check(
        "quickbar activation delegates consumption to business",
        next(i for i in state()["items"] if i["id"] == "seed-9")["quantity"] == 7,
    )
    view.key_down(KeyCode.GK_2)
    view.key_up(KeyCode.GK_2)
    await asyncio.sleep(0.1)
    check(
        "quickbar keyboard shortcut consumes through core command",
        next(i for i in state()["items"] if i["id"] == "seed-9")["quantity"] == 6,
    )
    # Cross-container equip, gem insertion and reversible extraction use real drags/buttons.
    await drag("chest", 0, 0, target_container="chest")
    check(
        "native drag equips chest",
        next(i for i in state()["items"] if i["id"] == "chest")["position"]["container"]
        == "chest",
    )
    await drag("gem", 0, 0, target_container="saint-socket")
    socketed = next(
        i for i in state()["items"] if i["position"]["container"] == "saint-socket"
    )
    check(
        "native socket takes exactly one gem",
        next(i for i in state()["items"] if i["id"] == "gem")["quantity"] == 5,
    )
    p = await point('[data-item="' + socketed["id"] + '"]')
    view.mouse_move(round(p["x"]), round(p["y"]))
    await asyncio.sleep(0.1)
    await click(".character-panel button:nth-of-type(1)")
    check(
        "native extraction merges gem back",
        next(i for i in state()["items"] if i["id"] == "gem")["quantity"] == 6
        and not any(
            i["position"]["container"] == "saint-socket" for i in state()["items"]
        ),
    )
    # Select and prepare a split; cancelling must preserve quantity and identity.
    p = await point('[data-item="gem"]')
    view.mouse_move(round(p["x"]), round(p["y"]))
    await asyncio.sleep(0.1)
    await click(".character-panel div button")
    before_split = state()
    await drag("gem", 10, 4, cancel=True)
    check("native split cancellation creates no item", state() == before_split)
    p = await point('[data-item="gem"]')
    view.mouse_move(round(p["x"]), round(p["y"]))
    await asyncio.sleep(0.1)
    await click(".character-panel div button")
    await drag("gem", 10, 4)
    split_candidates = [i for i in state()["items"] if i["id"].startswith("split-")]
    check("split instance exists", bool(split_candidates), state())
    split_item = split_candidates[0]
    check(
        "native split commits selected quantity",
        split_item["quantity"] == 1
        and next(i for i in state()["items"] if i["id"] == "gem")["quantity"] == 5,
    )
    # Bind the split via UI; merging redirects the reference to the surviving stack.
    p = await point('[data-item="' + split_item["id"] + '"]')
    view.mouse_move(round(p["x"]), round(p["y"]))
    await asyncio.sleep(0.1)
    await click('[aria-label="Bind slot 1"]')
    check(
        "quickbar binds an existing item",
        state()["shortcuts"]["1"]["item"] == split_item["id"],
    )
    await drag(split_item["id"], 11, 0)
    check(
        "native merge redirects quickbar",
        state()["shortcuts"]["1"]["item"] == "gem"
        and next(i for i in state()["items"] if i["id"] == "gem")["quantity"] == 6,
    )
    before_scale = state()
    evaluate(
        "document.querySelector('.framework-grids').style.transform='scale(.85)';document.querySelector('.framework-grids').style.transformOrigin='top left';void 0"
    )
    await drag("seed-15", 9, 3)
    scaled = next(i for i in state()["items"] if i["id"] == "seed-15")
    check(
        "scaled grid hit test uses logical cells",
        scaled["position"]["x"] == 9 and scaled["position"]["y"] == 3,
        scaled,
    )
    screenshot(view, output / "scaled.png")
    evaluate("document.querySelector('.framework-grids').style.transform='';void 0")
    normal = state()
    for fragmented in (False, True):
        fixture = json.loads(json.dumps(normal))
        fixture["shortcuts"] = {}
        fixture["items"] = [
            i for i in fixture["items"] if i["position"]["container"] != "bag"
        ]
        fixture["items"] += [
            dict(
                id=f"block-{x}-{y}",
                definition="enamel-ring",
                quantity=1,
                position=dict(container="bag", x=x, y=y),
            )
            for y in range(6)
            for x in range(12)
            if not fragmented or (x + y) % 2 == 0
        ]
        check(
            "valid fragmented/full fixture",
            evaluate("Reliquary.engine.load(" + json.dumps(fixture) + ").ok"),
        )
        before = state()
        await drag("chest", 0, 0)
        check(
            "fragmented/full inventory rejects without rearrangement",
            state() == before,
            dict(fragmented=fragmented),
        )
    check(
        "restore all fixture items",
        evaluate("Reliquary.engine.load(" + json.dumps(normal) + ").ok"),
    )
    fallback_snapshot = state()
    evaluate(
        "window.__originalPointer=window.PointerEvent;window.PointerEvent=undefined;Reliquary.view.mount();void 0"
    )
    await drag("seed-15", 9, 4, cancel=True, assert_active=True)
    check(
        "mouse fallback cancellation preserves exact snapshot",
        state() == fallback_snapshot,
    )
    evaluate(
        "window.PointerEvent=window.__originalPointer;Reliquary.view.mount();void 0"
    )
    native_window_focus(True)
    await asyncio.sleep(0.3)
    view.focus()
    report["focus_native"] = view.has_focus
    before_blur = state()
    await drag("seed-15", 9, 4, blur=True)
    check("loss of focus cancels drag", state() == before_blur)
    before_reload = state()
    await click(".demo-toolbar button:nth-of-type(2)")
    check(
        "complete snapshot persisted",
        standalone or json.loads(store.load_snapshot()) == before_reload,
    )
    evaluate("window.__previousReliquary=window.Reliquary;void 0")
    view.load_url("file:///index.html")
    await view.wait_settled(timeout=20)
    await view.wait_until(lambda:view.is_settled,timeout=20)
    await view.wait_until(lambda:view.evaluate("!!window.Reliquary && window.Reliquary!==window.__previousReliquary && !!document.querySelector('[data-container=bag]')"),timeout=20)
    await view.wait_until(
        lambda: view.evaluate(
            '!!window.Reliquary && !!document.querySelector("[data-item]")'
        ),
        timeout=20,
    )
    check("reload restores complete snapshot", state() == before_reload)
    await view.wait_until(
        lambda: view.evaluate(
            "Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)"
        ),
        timeout=15,
    )
    native_window_focus(True)
    await asyncio.sleep(0.35)
    screenshot(view, output / "final.png")
    evaluate(
        "window.__hov=[];Reliquary.engine.on('hover',e=>__hov.push({phase:e.phase}));void 0"
    )
    p = await point('[data-item="gem"]')
    view.mouse_move(0, 0)
    await asyncio.sleep(0.05)
    view.mouse_move(round(p["x"]), round(p["y"]))
    await view.wait_until(
        lambda: view.evaluate("Reliquary.view.hover?.itemId==='gem'"), timeout=3
    )
    evaluate("window.__hov=[];Reliquary.view.destroy();void 0")
    check(
        "destroy ends hover and clears DOM",
        evaluate(
            "__hov.some(e=>e.phase==='leave')&&document.querySelector('.framework-grids').children.length===0"
        ),
    )
    evaluate("Reliquary.view.mount();void 0")
    check("remount keeps inventory unchanged", state() == before_reload)
    report["snapshot"] = state()
    report["viewport"] = evaluate(
        "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Serve the built standalone web UI on localhost",
    )
    parser.add_argument("--port", type=int, default=4175)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run frontend-only, without the Python bridge",
    )
    parser.add_argument("--width", type=int, default=1152)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument(
        "--state",
        type=Path,
        help="Optional JSON state file; default is memory for this session",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Native mouse/key checks with isolated demo state",
    )
    parser.add_argument("--output", type=Path, default=ARTIFACTS / "native")
    args = parser.parse_args()
    if not (ASSETS / "index.html").exists():
        parser.error("Build the web UI first: cd web && npm install && npm run build")
    if args.browser:
        handler = partial(SimpleHTTPRequestHandler, directory=str(ASSETS))
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
            print(f"Ashen Reliquary: http://127.0.0.1:{args.port}/", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return 0
    from ultralight_py import API, Application

    report = dict(
        success=False,
        platform=platform.platform(),
        standalone=args.standalone,
        checks=[],
    )
    args.output.mkdir(parents=True, exist_ok=True)
    errors = []
    try:
        store = LayoutStore(None if args.smoke else args.state)
        with (
            tempfile.TemporaryDirectory(prefix="reliquary-cache-") as cache,
            API("inventory") as api,
            Application(
                assets_root=str(ASSETS),
                cache_path=cache,
                force_cpu_renderer=args.cpu or args.smoke,
                app_name="AshenReliquary",
            ) as app,
        ):
            for name in ("load_snapshot", "save_snapshot", "load_layout", "reset"):
                api.register(getattr(store, name))
            window = app.create_window(
                args.width, args.height, title="Ashen Reliquary — Inventory Lab"
            )
            if not args.standalone:
                api.attach(window.view)

            def console(event):
                print("[JS]", event, flush=True)
                if str(event.get("level", "")).lower() in ("error", "2"):
                    errors.append(event)

            subscription = window.view.on("console", console)
            window.view.load_url("file:///index.html")
            if args.smoke:

                async def smoke():
                    pump = asyncio.create_task(drive_application(app,window))
                    try:
                        await asyncio.wait_for(
                            verify(
                                window.view,
                                store,
                                args.output,
                                report,
                                standalone=args.standalone,
                            ),
                            70,
                        )
                        if errors:
                            raise AssertionError(f"JavaScript errors: {errors}")
                        report["success"] = True
                    finally:
                        app.close()
                        await pump

                asyncio.run(smoke())
            else:
                asyncio.run(drive_application(app,window))
        return 0
    except Exception as exc:
        report["error"] = str(exc)
        traceback.print_exc()
        return 1
    finally:
        if args.smoke:
            report["console_errors"] = errors
            (args.output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                "Ashen Reliquary native smoke: "
                + ("PASS" if report["success"] else "FAIL"),
                flush=True,
            )


if __name__ == "__main__":
    sys.exit(main())
