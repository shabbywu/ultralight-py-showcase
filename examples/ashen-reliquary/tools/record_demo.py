"""Record real AppCore pixels and native input for the GitHub Pages gallery."""

import asyncio
import json
import tempfile
import time
from pathlib import Path

from PIL import Image
from ultralight_py import API, Application, KeyCode, Modifiers, MouseButton, View

from reliquary.bridge import GameBridge
from reliquary.game import Game
from reliquary.models import Item, ItemShortcut
from reliquary.state import SnapshotStore

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
OUTPUT = WORKSPACE / ".tmp/ashen-reliquary/recording"
MEDIA = WORKSPACE / "site/assets"


async def record(app: Application, view: View, game: Game) -> None:
    """Drive real View input while capturing independently timed pixel frames."""
    await view.wait_until(
        lambda: view.is_ready and bool(view.evaluate("!!window.Reliquary?.view")),
        timeout=20,
    )
    await view.wait_until(
        lambda: bool(
            view.evaluate(
                "Array.from(document.images).every(i=>i.complete&&i.naturalWidth)"
            )
        ),
        timeout=20,
    )
    view.focus()
    await asyncio.sleep(0.5)
    frames: list[Path] = []
    timestamps: list[float] = []
    running = True

    def image() -> Image.Image:
        """Copy current native pixels into an independent Pillow image."""
        pixels = view.copy_pixels().to_rgba()
        return Image.frombytes(
            "RGBA", (pixels.width, pixels.height), bytes(pixels.data)
        ).convert("RGB")

    async def capture() -> None:
        """Sample rendered pixels without changing the page or composing overlays."""
        while running:
            started = time.monotonic()
            frame = image().resize((1080, 750), Image.Resampling.LANCZOS)
            path = OUTPUT / "frames" / f"{len(frames):04}.png"
            frame.save(path)
            frames.append(path)
            timestamps.append(started)
            await asyncio.sleep(max(0.001, 0.1 - (time.monotonic() - started)))

    def item(item_id: str) -> Item:
        """Read an item from the backend to confirm the visible operation."""
        return next(i for i in game.snapshot().items if i.id == item_id)

    def point(selector: str, *, corner: bool = False) -> tuple[int, int]:
        """Read native viewport coordinates without modifying application state."""
        with view.evaluate_handle(
            "selector=>{const r=document.querySelector(selector).getBoundingClientRect();return [r.left,r.top,r.width,r.height]}"
        ) as query:
            rect = query.call(selector).to_python(copy=True)
        return round(rect[0] + (10 if corner else rect[2] / 2)), round(
            rect[1] + (10 if corner else rect[3] / 2)
        )

    async def click(selector: str, *, double: bool = False) -> None:
        """Click actual controls through native View input."""
        x, y = point(selector)
        for _ in range(2 if double else 1):
            view.mouse_move(x, y)
            view.mouse_down(x, y, button=MouseButton.LEFT)
            view.mouse_up(x, y, button=MouseButton.LEFT)
            await asyncio.sleep(0.07)
        await asyncio.sleep(0.7)

    async def drag(
        item_id: str,
        target: str,
        *,
        cell: tuple[int, int] | None = None,
        rotate: bool = False,
        split: bool = False,
    ) -> None:
        """Record a held item moving through real native mouse and keyboard events."""
        start = point(f'[data-item="{item_id}"]', corner=True)
        end = point(target, corner=cell is not None)
        if cell is not None:
            end = (end[0] + cell[0] * 40, end[1] + cell[1] * 40)
        if split:
            view.key_down(KeyCode.GK_CONTROL, modifiers=Modifiers.CTRL)
        view.mouse_move(*start)
        view.mouse_down(*start, button=MouseButton.LEFT)
        await asyncio.sleep(0.2)
        if rotate:
            view.key_down(KeyCode.GK_R)
            view.key_up(KeyCode.GK_R)
        for step in range(1, 17):
            view.mouse_move(
                round(start[0] + (end[0] - start[0]) * step / 16),
                round(start[1] + (end[1] - start[1]) * step / 16),
            )
            await asyncio.sleep(0.055)
        await asyncio.sleep(0.25)
        view.mouse_up(*end, button=MouseButton.LEFT)
        if split:
            view.key_up(KeyCode.GK_CONTROL)
        await asyncio.sleep(0.8)

    recorder = asyncio.create_task(capture())
    try:
        await asyncio.sleep(1.2)
        await click('[data-item="seed-12"]', double=True)
        assert item("seed-12").position.container == "ring1"
        await drag("chest", '[data-container="chest"]')
        assert item("chest").position.container == "chest"
        await drag("seed-15", '[data-container="bag"]', cell=(9, 2), rotate=True)
        assert item("seed-15").position.rotation == 1
        await drag("gem", '[data-shortcut="1"]')
        reference = game.snapshot().shortcuts["1"]
        assert isinstance(reference, ItemShortcut) and reference.item_id == "gem"
        await drag("gem", '[data-container="saint-socket"]')
        assert item("gem").quantity == 5
        gem = next(
            i for i in game.snapshot().items if i.position.container == "saint-socket"
        )
        view.mouse_move(*point(f'[data-item="{gem.id}"]'))
        await asyncio.sleep(0.6)
        await click(".character-panel button:first-of-type")
        assert item("gem").quantity == 6
        await drag("gem", '[data-container="bag"]', cell=(10, 4), split=True)
        assert item("gem").quantity == 3
        await click(".demo-toolbar button:nth-of-type(1)")
        assert len(game.snapshot().items) == 22
        await click(".demo-toolbar button:nth-of-type(4)")
        view.evaluate(
            "document.querySelector('[data-container=ground]').scrollIntoView({block:'center'}); void 0"
        )
        await asyncio.sleep(1)
        # A second creation originates entirely in Python, while Ground is visible.
        assert game.create_relic().ok
        await asyncio.sleep(1.5)
        view.evaluate("window.scrollTo(0,0); void 0")
        await click(".demo-toolbar button:nth-of-type(4)")
        view.mouse_move(1380, 80)
        await asyncio.sleep(1)
        image().save(MEDIA / "ashen-reliquary.png")
        await asyncio.sleep(0.5)
    finally:
        running = False
        await recorder
    images = [Image.open(path).convert("RGB") for path in frames]
    durations = [
        max(1, round((b - a) * 1000)) for a, b in zip(timestamps, timestamps[1:])
    ] + [100]
    images[0].save(MEDIA / "ashen-reliquary-poster.png")
    images[0].save(
        MEDIA / "ashen-reliquary-demo.webp",
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        quality=80,
        method=4,
    )
    (OUTPUT / "recording.json").write_text(
        json.dumps(
            {
                "frames": len(frames),
                "duration_ms": sum(durations),
                "timestamps": timestamps,
                "snapshot_revision": game.snapshot().revision,
            },
            indent=2,
        )
    )
    print(f"Recorded {len(frames)} real frames, {sum(durations) / 1000:.1f}s")


def main() -> None:
    """Launch an isolated CPU AppCore window and save gallery media."""
    (OUTPUT / "frames").mkdir(parents=True, exist_ok=True)
    game = Game(SnapshotStore(), choose=lambda definitions: definitions[-1])
    bridge = GameBridge(game)
    with (
        tempfile.TemporaryDirectory(prefix="reliquary-recording-") as cache,
        API("inventory") as api,
        Application(
            assets_root=str(ROOT / "web/dist"),
            cache_path=cache,
            force_cpu_renderer=True,
            app_name="AshenReliquary",
        ) as app,
    ):
        api.register_object("backend", bridge, members=GameBridge.MEMBERS)
        window = app.create_window(1440, 1000, title="Ashen Reliquary")
        api.attach(window.view)
        bridge.connect(window.view)
        window.view.load_url("file:///index.html")

        async def run() -> None:
            """Pump AppCore while recording, then release both event lifecycles."""
            pump = asyncio.create_task(app.run_async(update_interval=1 / 120))
            try:
                await record(app, window.view, game)
            finally:
                bridge.close()
                app.close()
                await pump

        asyncio.run(run())


if __name__ == "__main__":
    main()
