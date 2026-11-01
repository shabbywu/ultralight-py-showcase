"""Native product flow gate with simulated MIDI input and real AppCore/audio."""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    run_root = (
        ROOT.parents[1]
        / ".tmp/pianoscope/validation"
        / datetime.now().strftime("product-%Y%m%d-%H%M%S-%f")
    )
    os.environ["PIANOSCOPE_DATA_DIR"] = str(run_root / "data")
    os.environ["PIANOSCOPE_TMP_DIR"] = str(run_root / "work")
    from ultralight_py import API, Application, Resource

    from pianoscope.app.bridge import register
    from pianoscope.app.controller import Controller
    from tools.native_gate import screenshot

    root = ROOT
    out = run_root
    out.mkdir(parents=True, exist_ok=True)
    print("Evidence:", out)
    c = Controller()
    assets = root / "pianoscope/assets"

    class MidiStub:
        def list_inputs(self):
            return dict(available=True, inputs=[dict(name="Test MIDI")])

        def status(self):
            return dict(opened=True, selected="Test MIDI", available=True, error=None)

        def drain(self, limit=256):
            return []

        def close(self):
            pass

    c.practice.midi = MidiStub()
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
        b"window.APP_ERRORS=[];window.onerror=m=>APP_ERRORS.push(String(m));window.CPU_RENDERER=true;window.START_ON_HOME=true;window.INITIAL_SOURCE=null;",
        "text/javascript",
    )

    def loader(name):
        if name in resources:
            return resources[name]
        data = c.resource(name)
        return Resource(data, "image/png") if data else None

    with (
        API("piano") as api,
        Application(
            assets_root=str(assets),
            resource_loader=loader,
            cache_path=os.environ.get("PIANOSCOPE_PROFILE_PROBE", str(out / "profile")),
            force_cpu_renderer=True,
            app_name="PianoScope product check",
        ) as app,
    ):
        register(api, c)
        w = app.create_window(
            int(sys.argv[1]) if len(sys.argv) > 1 else 1440,
            int(sys.argv[2]) if len(sys.argv) > 2 else 960,
            title="PianoScope product check",
        )
        v = w.view
        api.attach(v)
        v.load_url("file:///index.html")

        async def check():
            pump = asyncio.create_task(app.run_async(update_interval=1 / 120))
            try:
                await asyncio.sleep(0.5)
                await v.wait_until(
                    lambda: v.evaluate("window.PIANOSCOPE_READY"), timeout=20
                )
                stage = os.environ.get("PIANOSCOPE_STORAGE_STAGE")
                if stage:
                    if stage == "write":
                        v.evaluate("localStorage.setItem('restart-probe','persisted')")
                    else:
                        assert (
                            v.evaluate("localStorage.getItem('restart-probe')")
                            == "persisted"
                        )
                    print("Persistent storage", stage, "passed")
                    return
                from pianoscope.practice.midi import MidiEvent

                v.evaluate("document.getElementById('midiMonitor').click()")
                await v.wait_until(lambda: c.monitor.ready, timeout=15)
                assert c.plan is None, "home monitoring unexpectedly loaded a score"
                c.monitor.submit(MidiEvent("note_on", 60, 90, 0, 0))
                await asyncio.sleep(0.15)
                c.monitor.submit(MidiEvent("note_off", 60, 0, 0, 0))
                await v.evaluate_async("document.querySelector('[data-demo]').click()")
                await v.wait_until(
                    lambda: v.evaluate(
                        "document.getElementById('homeTitle').textContent.startsWith('初光')"
                    ),
                    timeout=20,
                )
                await asyncio.sleep(0.3)
                screenshot(
                    v,
                    out
                    / (
                        "home-"
                        + str(w.width if hasattr(w, "width") else sys.argv[-1])
                        + ".png"
                    ),
                )
                v.evaluate("document.getElementById('enterWorkspace').click()")
                await v.wait_until(
                    lambda: v.evaluate(
                        "App.document&&!App.loadJob&&!document.getElementById('workbench').hidden"
                    ),
                    timeout=40,
                )
                await asyncio.sleep(0.4)
                screenshot(v, out / "workbench.png")
                v.evaluate("document.getElementById('sheetMode').click()")
                await v.wait_until(
                    lambda: v.evaluate("App.document.layout_ready&&!App.sheetRequest"),
                    timeout=40,
                )
                await asyncio.sleep(0.4)
                screenshot(v, out / "sheet.png")
                v.evaluate(
                    "document.getElementById('practiceMode').click();document.getElementById('play').click()"
                )
                await v.wait_until(lambda: c.practice.state == "countdown", timeout=15)
                await v.evaluate_async("piano.stop()")
                await asyncio.sleep(0.1)
                assert c.practice.store.history()["total"] == 0, (
                    "count-in cancellation created session"
                )
                v.evaluate(
                    "document.getElementById('countIn').checked=false;document.getElementById('play').click()"
                )
                await v.wait_until(lambda: c.practice.state == "playing", timeout=15)
                session = c.practice.session_id
                await asyncio.sleep(0.25)
                screenshot(v, out / "practice.png")
                await v.evaluate_async("piano.pause()")
                assert c.practice.state == "paused"
                assert c.monitor.ready, "pausing practice stopped live piano"
                await v.evaluate_async("piano.play()")
                assert c.practice.session_id == session
                await asyncio.sleep(0.15)
                await v.evaluate_async("piano.stop()")
                assert c.practice.store.history()["total"] == 1
                assert c.practice.store.history()["items"][0]["status"] == "stopped"
                assert c.monitor.ready, "stopping practice stopped live piano"
                screenshot(v, out / "result.png")
                v.evaluate("document.getElementById('backLibrary').click()")
                await v.wait_until(
                    lambda: v.evaluate("!document.getElementById('homePage').hidden"),
                    timeout=5,
                )
                v.evaluate("document.getElementById('historyTab').click()")
                await asyncio.sleep(0.3)
                v.evaluate("document.querySelector('#historyRows button').click()")
                await asyncio.sleep(0.3)
                screenshot(v, out / "history.png")
                v.evaluate("document.getElementById('enterWorkspace').click()")
                await v.wait_until(
                    lambda: v.evaluate("!document.getElementById('workbench').hidden"),
                    timeout=10,
                )
                v.evaluate(
                    "App.setView('roll');document.getElementById('followMode').click()"
                )
                await v.wait_until(lambda: c.follow is not None, timeout=15)
                assert c.follow is not None
                await asyncio.sleep(0.1)
                follow = c.follow
                await v.wait_until(
                    lambda: follow.snapshot()["stage"] == "waiting", timeout=10
                )
                position = follow.position
                v.evaluate(
                    "window.followModeErrors=[];window.followModeObserver=new MutationObserver(records=>{for(const r of records){if(r.target.id==='auditionMode'&&(r.oldValue||'').split(' ').includes('chosen'))followModeErrors.push('audition was selected during follow')}});followModeObserver.observe(document.getElementById('activityMode'),{subtree:true,attributes:true,attributeFilter:['class'],attributeOldValue:true})"
                )
                assert not v.evaluate(
                    "document.getElementById('workspacePanic').disabled"
                )
                v.evaluate(
                    "document.getElementById('workspacePanic').click();document.getElementById('accompanimentMute').click()"
                )
                await v.wait_until(lambda: c.audio.volume == 0, timeout=5)
                assert c.follow is follow and follow.state == "playing"
                v.evaluate("document.getElementById('followSettings').click()")
                await v.wait_until(
                    lambda: v.evaluate("!document.getElementById('modal').hidden"),
                    timeout=5,
                )
                assert (
                    v.evaluate("document.getElementById('modalTitle').textContent")
                    == "跟弹设置"
                )
                v.evaluate("document.getElementById('closeModal').click()")
                v.evaluate(
                    "App.setView('roll');window.followHeights=[];window.followHeightTimer=setInterval(()=>followHeights.push(document.getElementById('roll').getBoundingClientRect().height),16)"
                )
                await asyncio.sleep(0.1)
                assert follow.position == position, (
                    "follow advanced without correct keys"
                )
                await asyncio.sleep(0.4)
                heights = v.evaluate(
                    "clearInterval(followHeightTimer);followHeights", copy=True
                )
                assert max(heights) - min(heights) < 1, (
                    "follow status toggled roll viewport height"
                )
                assert not v.evaluate("!!document.getElementById('enterFollow')")
                assert (
                    v.evaluate(
                        "followModeObserver.disconnect();followModeErrors.length"
                    )
                    == 0
                ), "follow transiently selected audition"
                v.evaluate(
                    "document.getElementById('message').textContent='请先在首页连接 MIDI 输入设备';document.getElementById('message').hidden=false"
                )
                await v.wait_until(
                    lambda: v.evaluate("document.getElementById('message').hidden"),
                    timeout=5,
                )
                import time

                for pitch in follow.snapshot()["target_pitches"]:
                    follow.event(
                        MidiEvent("note_on", pitch, 90, 0, time.monotonic_ns())
                    )
                await asyncio.sleep(0.1)
                assert follow.position > position, "correct held chord did not advance"
                await c.pause()
                position = follow.position
                await asyncio.sleep(0.1)
                assert follow.position == position, "paused follow advanced"
                await c.stop()
                record = c.practice.store.history()["items"][0]
                assert record["follow"] is not None
                assert c.practice.store.comparison(record["id"]) is None
                errors = v.evaluate("APP_ERRORS", copy=True)
                print(
                    json.dumps(
                        {
                            "errors": errors,
                            "homeTitle": v.evaluate(
                                "document.getElementById('homeTitle').textContent"
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                assert not errors
            except Exception:
                print(
                    v.evaluate(
                        "({errors:APP_ERRORS,body:document.body.innerText})", copy=True
                    )
                )
                raise
            finally:
                c.close()
                app.close()
                await pump

        asyncio.run(check())


if __name__ == "__main__":
    main()
