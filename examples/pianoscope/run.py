#!/usr/bin/env python3
"""MusicXML PianoScope native AppCore entry; no server or browser runtime."""

import argparse
import asyncio
import json
import platform
import tempfile
import traceback
from importlib.metadata import version
from pathlib import Path

from pianoscope.dialogs import before_window_close
from pianoscope.v2_bridge import register
from pianoscope.v2_session import Controller

ROOT = Path(__file__).resolve().parent
# Poll AppCore frequently enough to service native display/input callbacks.
# This is a host wake interval; the audio device remains the transport clock.
APP_UPDATE_INTERVAL = 1 / 240


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=960)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--audio-test", action="store_true")
    parser.add_argument("--measure-seconds", type=float, default=0)
    parser.add_argument("--smoke-report", type=Path)
    args = parser.parse_args()
    report = dict(
        status="failed",
        platform=platform.platform(),
        python=platform.python_version(),
        audio_test=args.audio_test,
        checks=[],
    )
    controller = None

    def remove_observer():
        pass

    try:
        if version("ultralight-py") != "0.5.0":
            raise RuntimeError("需要 ultralight-py==0.5.0")
        from ultralight_py import API, Application, Resource

        controller = Controller()
        source = (
            controller.token_for_path(args.file) if args.file else "demo:first-light"
        )
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
        config = (
            "window.APP_ERRORS=[];window.onerror=function(m,u,l,c){APP_ERRORS.push({message:String(m),url:u,line:l,column:c})};window.CPU_RENDERER="
            + json.dumps(args.cpu)
            + ";window.INITIAL_SOURCE="
            + json.dumps(source)
            + ";"
        )
        resources["config.js"] = Resource(config.encode(), "text/javascript")
        resources["index.html"] = resources["v2.html"]

        def resource_loader(name):
            if name in resources:
                return resources[name]
            data = controller.resource(name)
            return Resource(data, "image/png") if data is not None else None

        with (
            tempfile.TemporaryDirectory(prefix="pianoscope-v2-") as cache,
            API("piano") as api,
            Application(
                assets_root=str(assets),
                resource_loader=resource_loader,
                cache_path=cache,
                app_name="PianoScope",
                force_cpu_renderer=args.cpu,
            ) as app,
        ):
            register(api, controller)
            window = app.create_window(args.width, args.height, title="PianoScope")
            remove_observer = before_window_close("PianoScope", controller.close)
            api.attach(window.view)
            window.view.load_url("file:///index.html")
            if args.smoke:

                async def smoke():
                    pump = asyncio.create_task(
                        app.run_async(update_interval=APP_UPDATE_INTERVAL)
                    )
                    try:
                        from pianoscope.v2_checks import verify

                        await verify(window.view, controller, args, report)
                    except Exception:
                        try:
                            report["page_state"] = window.view.evaluate(
                                "({errors:window.APP_ERRORS,text:document.body.innerText,ready:window.PIANOSCOPE_READY})"
                            )
                        except Exception:
                            pass
                        raise
                    finally:
                        controller.close()
                        app.close()
                        await pump

                asyncio.run(smoke())
            else:
                try:
                    asyncio.run(app.run_async(update_interval=APP_UPDATE_INTERVAL))
                finally:
                    controller.close()
        report["status"] = "passed"
        return 0
    except Exception as exc:
        traceback.print_exc()
        report["error"] = str(exc)
        return 1
    finally:
        remove_observer()
        if controller and not controller.closed:
            controller.close()
        if args.smoke_report:
            args.smoke_report.parent.mkdir(parents=True, exist_ok=True)
            args.smoke_report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str)
            )
        if args.smoke:
            print("PianoScope v2 native: " + report["status"], flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
