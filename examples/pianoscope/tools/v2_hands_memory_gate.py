"""Actual native mouse/DAC regression for hand labels on a long source score."""

import argparse
import asyncio
import hashlib
import json
import platform
import sys
import tempfile
import time
import traceback
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import pianoscope.v2_session as session
    from pianoscope.pcm_budget import PCM_BUDGET_BYTES
    from pianoscope.render import audible_notes
    from pianoscope.v2_bridge import register
    from run import APP_UPDATE_INTERVAL
    from tools.v2_g0 import screenshot

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    out = (
        ROOT.parents[1]
        / ".tmp/pianoscope/v2"
        / datetime.now().strftime("hands-memory-%Y%m%d-%H%M%S")
    )
    out.mkdir(parents=True)
    original = args.source.resolve().read_bytes()
    report = dict(
        status="failed",
        checks=[],
        renders=[],
        pcm_budget_bytes=PCM_BUDGET_BYTES,
        source_sha256=hashlib.sha256(original).hexdigest(),
        runtime=dict(
            python=sys.version,
            platform=platform.platform(),
            ultralight_py=version("ultralight-py"),
        ),
    )

    def check(name, ok, detail=None):
        report["checks"].append(
            dict(name=name, status="passed" if ok else "failed", detail=detail)
        )
        if not ok:
            raise AssertionError(name + ": " + str(detail))

    from ultralight_py import API, Application, Resource

    c = session.Controller()
    real_render = session.render

    def measured(score, config, sample_rate, *args, **kwargs):
        before = c.audio.pcm.nbytes if c.audio.pcm is not None else 0
        started = time.monotonic()
        pcm = real_render(score, config, sample_rate, *args, **kwargs)
        report["renders"].append(
            dict(
                rate=config["rate"],
                hand_mode=config["hand_mode"],
                sample_rate=sample_rate,
                current_bytes=before,
                candidate_bytes=pcm.nbytes,
                combined_bytes=before + pcm.nbytes,
                audible_notes=len(audible_notes(score, config)),
                elapsed_s=time.monotonic() - started,
                rss_bytes=psutil.Process().memory_info().rss,
            )
        )
        return pcm

    session.render = measured
    assets = ROOT / "pianoscope/assets"
    report["code_sha256"] = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [
            ROOT / "pianoscope/v2_session.py",
            ROOT / "pianoscope/render.py",
            ROOT / "pianoscope/pcm_budget.py",
            ROOT / "pianoscope/assets/v2.js",
        ]
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
            "window.APP_ERRORS=[];window.onerror=m=>APP_ERRORS.push(String(m));window.CPU_RENDERER=true;window.INITIAL_SOURCE="
            + json.dumps(c.token_for_path(args.source))
            + ";"
        ).encode(),
        "text/javascript",
    )
    try:
        with (
            tempfile.TemporaryDirectory(prefix="pianoscope-hands-memory-") as cache,
            API("piano") as api,
            Application(
                assets_root=str(assets),
                resource_loader=resources.get,
                cache_path=cache,
                force_cpu_renderer=True,
                app_name="PianoScope hand memory gate",
            ) as app,
        ):
            register(api, c)
            window = app.create_window(800, 600, title="PianoScope hand memory gate")
            view = window.view
            api.attach(view)
            view.focus()
            view.load_url("file:///index.html")

            async def verify():
                pump = asyncio.create_task(
                    app.run_async(update_interval=APP_UPDATE_INTERVAL)
                )

                async def click(selector):
                    point = view.evaluate(
                        """(()=>{const e=document.querySelector(SELECTOR);if(!e)return null;const r=e.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2,h=document.elementFromPoint(x,y);return {x,y,visible:r.width>0&&r.height>0&&(h===e||e.contains(h))}})()""".replace(
                            "SELECTOR", json.dumps(selector)
                        )
                    )
                    if not point or not point["visible"]:
                        raise AssertionError("control not exposed: " + selector)
                    view.click(round(point["x"]), round(point["y"]))
                    await asyncio.sleep(0.06)

                async def hands():
                    if not view.evaluate(
                        'document.body.classList.contains("sidebar-open")'
                    ):
                        await click("#menu")
                    await click("#hands")

                async def action(text):
                    await view.wait_until(
                        lambda: view.evaluate(
                            'Array.from(document.querySelectorAll("#modal button")).some(b=>b.textContent==='
                            + json.dumps(text)
                            + "&&!b.disabled)"
                        ),
                        timeout=30,
                    )
                    selector = view.evaluate(
                        """(()=>{const b=Array.from(document.querySelectorAll('#modal button')).find(b=>b.textContent===TEXT&&!b.disabled);if(!b)return null;b.id='memory-action';return '#memory-action'})()""".replace(
                            "TEXT", json.dumps(text)
                        )
                    )
                    if selector is None:
                        raise AssertionError("action unavailable: " + text)
                    await click(selector)

                async def closed():
                    await view.wait_until(
                        lambda: view.evaluate(
                            'document.getElementById("modal").hidden'
                        ),
                        timeout=30,
                    )

                def identity():
                    return (id(c.audio.pcm), c.audio.epoch, len(report["renders"]))

                try:
                    await asyncio.sleep(0.4)
                    await view.wait_until(
                        lambda: view.evaluate(
                            "window.PIANOSCOPE_READY&&App.document&&!App.loadJob"
                        ),
                        timeout=60,
                    )
                    report["device"] = c.audio.device
                    report["sample_rate"] = c.audio.sample_rate
                    report["initial_pcm_bytes"] = c.audio.pcm.nbytes
                    midi = c.plan.midi_bytes
                    check(
                        "real source ready in roll without layout",
                        c.audio.ready
                        and view.evaluate('App.view==="roll"&&App.rows.length===0'),
                    )
                    check(
                        "actual song would exceed old duplicate-buffer budget",
                        c.audio.pcm.nbytes * 2 > 192 * 1024**2,
                        c.audio.pcm.nbytes * 2,
                    )
                    await click("#play")
                    await view.wait_until(
                        lambda: c.get_transport()["position_s"] > 0.2, timeout=5
                    )
                    before = identity()
                    position = c.get_transport()["position_s"]
                    started = time.monotonic()
                    await hands()
                    await action("确认分配")
                    await closed()
                    report["first_assignment_elapsed_s"] = time.monotonic() - started
                    check(
                        "native confirm labels reuses PCM with continuous DAC",
                        identity() == before
                        and c.hands
                        and c.audio.playing
                        and c.get_transport()["position_s"] > position,
                    )
                    before = identity()
                    await hands()
                    await action("撤销上次分配")
                    await view.wait_until(lambda: not c.hands, timeout=5)
                    check(
                        "native undo reuses PCM without resetting DAC",
                        identity() == before and c.audio.playing and not c.hand_history,
                    )
                    await action("取消")
                    await closed()
                    await hands()
                    await action("确认分配")
                    await closed()
                    check(
                        "repeated label confirmation still reuses initial PCM",
                        len(report["renders"]) == 1,
                    )
                    for mode in ("left", "right"):
                        if not view.evaluate(
                            'document.body.classList.contains("sidebar-open")'
                        ):
                            await click("#menu")
                        before = identity()
                        await click('#handQuick button[value="' + mode + '"]')
                        await view.wait_until(
                            lambda: c.config["hand_mode"] == mode, timeout=30
                        )
                        check(
                            "native " + mode + " audition renders actual selection",
                            len(report["renders"]) == before[2] + 1
                            and id(c.audio.pcm) != before[0]
                            and all(
                                n.hand == mode for n in audible_notes(c.score, c.config)
                            ),
                        )
                    if view.evaluate(
                        'document.body.classList.contains("sidebar-open")'
                    ):
                        await click("#closeSidebar")
                    await click('#rate button[value=".5"]')
                    await view.wait_until(lambda: c.config["rate"] == 0.5, timeout=30)
                    check(
                        "native half-speed long song exceeds old single-buffer limit and plays",
                        c.audio.pcm.nbytes > 192 * 1024**2
                        and c.audio.rate == 0.5
                        and c.audio.playing,
                        c.audio.pcm.nbytes,
                    )
                    await hands()
                    await click('#modal [aria-label="上谱表手别"] button[value="left"]')
                    await click(
                        '#modal [aria-label="下谱表手别"] button[value="right"]'
                    )
                    before = len(report["renders"])
                    await action("确认分配")
                    await closed()
                    check(
                        "reassignment during right-only half-speed audition prepares new actual sound",
                        len(report["renders"]) == before + 1
                        and c.config["hand_mode"] == "right"
                        and all(
                            n["staff_id"].endswith(":2")
                            for n in c.plan.instances
                            if n["id"]
                            in {a.id for a in audible_notes(c.score, c.config)}
                        ),
                    )
                    await hands()
                    await action("撤销上次分配")
                    await view.wait_until(
                        lambda: c.hands and c.hand_history and len(c.hand_history) == 1,
                        timeout=30,
                    )
                    await action("撤销上次分配")
                    await view.wait_until(
                        lambda: not c.hands and not c.hand_history, timeout=30
                    )
                    check(
                        "undo from filtered audition restores both hands at half speed",
                        c.config["hand_mode"] == "both"
                        and c.config["rate"] == 0.5
                        and c.audio.playing,
                    )
                    await action("取消")
                    await closed()
                    before = identity()
                    await click('#rate button[value=".5"]')
                    await asyncio.sleep(0.1)
                    check(
                        "equivalent speed setting reuses current PCM",
                        identity() == before,
                    )
                    await view.wait_until(
                        lambda: float(abs(c.audio.heard_window()).max()) > 0, timeout=5
                    )
                    check("actual SoundFont output remains nonzero", True)
                    check(
                        "actual double slow-buffer preparation stays within new budget",
                        any(
                            r["current_bytes"] > 192 * 1024**2
                            and r["candidate_bytes"] > 192 * 1024**2
                            for r in report["renders"]
                        )
                        and all(
                            r["combined_bytes"] <= PCM_BUDGET_BYTES
                            for r in report["renders"]
                        ),
                    )
                    check(
                        "source and default MIDI unchanged",
                        args.source.resolve().read_bytes() == original
                        and c.plan.midi_bytes == midi,
                    )
                    check(
                        "zero audio underruns",
                        c.audio.underruns == 0,
                        c.audio.underruns,
                    )
                    check(
                        "no script errors",
                        not view.evaluate("APP_ERRORS"),
                        view.evaluate("APP_ERRORS"),
                    )
                    await view.evaluate_async("piano.pause()")
                    await asyncio.sleep(0.15)
                    screenshot(view, out / "after-assignment-and-slow-audition.png")
                except Exception:
                    report["page"] = view.evaluate(
                        "({text:document.body.innerText,errors:APP_ERRORS})"
                    )
                    raise
                finally:
                    c.close()
                    app.close()
                    await pump

            asyncio.run(verify())
        report["status"] = "passed"
        return 0
    except Exception as exc:
        report["error"] = str(exc)
        traceback.print_exc()
        return 1
    finally:
        session.render = real_render
        if not c.closed:
            c.close()
        report["performance"] = "not_run"
        report["manual_listening"] = "not_run"
        (out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str)
        )
        print(out / "report.json")


if __name__ == "__main__":
    raise SystemExit(main())
