#!/usr/bin/env python3
"""Launch Ashen Reliquary in an ultralight-py window."""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from ultralight_py import API, Application

from reliquary.bridge import GameBridge
from reliquary.game import Game
from reliquary.state import SnapshotStore

ASSETS = Path(__file__).resolve().parent / "web/dist"


def main() -> int:
    """Parse options, wire the native host and run the application."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--width", type=int, default=1152)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument(
        "--state", type=Path, help="Persist snapshots to this JSON file"
    )
    args = parser.parse_args()
    if not (ASSETS / "index.html").exists():
        parser.error(
            "Build the web UI first: npm ci --prefix web && npm run build --prefix web"
        )

    with (
        tempfile.TemporaryDirectory(prefix="reliquary-cache-") as cache,
        API("inventory") as api,
        Application(
            assets_root=str(ASSETS),
            cache_path=cache,
            force_cpu_renderer=args.cpu,
            app_name="AshenReliquary",
        ) as app,
    ):
        game = Game(SnapshotStore(args.state))
        bridge = GameBridge(game)
        api.register_object("backend", bridge, members=GameBridge.MEMBERS)
        window = app.create_window(args.width, args.height, title="Ashen Reliquary")
        api.attach(window.view)
        bridge.connect(window.view)
        _console_subscription = window.view.on(
            "console", lambda event: print("[JS]", event, flush=True)
        )
        window.view.load_url("file:///index.html")
        try:
            asyncio.run(app.run_async(update_interval=1 / 120))
        finally:
            bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
