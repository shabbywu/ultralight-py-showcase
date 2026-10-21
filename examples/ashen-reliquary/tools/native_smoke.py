"""Check backend authority and rendering in a real, offscreen Ultralight View.

Run from the example directory with ``python -m tools.native_smoke``.
"""

import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from ultralight_py import API, Runtime

from reliquary.bridge import GameBridge
from reliquary.game import Game
from reliquary.state import SnapshotStore

ASSETS = Path(__file__).resolve().parents[1] / "web/dist"


def main() -> None:
    """Exercise host-originated updates, copies, commands and page navigation."""
    game = Game(SnapshotStore())
    bridge = GameBridge(game)
    with (
        tempfile.TemporaryDirectory(prefix="reliquary-check-") as cache,
        Runtime(assets_root=ASSETS, cache_path=cache) as runtime,
        API("inventory") as api,
    ):
        api.register_object("backend", bridge, members=GameBridge.MEMBERS)
        view = runtime.create_view(1440, 1000)
        api.attach(view)
        errors = []
        _console_subscription = view.on(
            "console",
            lambda event: (
                errors.append(str(event))
                if str(event.get("level", "")).lower() in ("error", "2")
                else None
            ),
        )
        bridge.connect(view)

        def wait(predicate: Callable[[], object]) -> None:
            """Pump the renderer until a condition succeeds or a deadline expires."""
            deadline = time.monotonic() + 15
            while not predicate():
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Page did not settle; console errors: {errors}")
                runtime.update()
                runtime.refresh_display()
                runtime.render()
                time.sleep(0.005)

        view.load_url("file:///index.html")
        wait(lambda: view.is_ready and view.evaluate("!!window.Reliquary?.view"))
        assert view.evaluate("Reliquary.snapshot().items.length") == 20
        # No front-end action: Python creates an item and pushes a notification.
        assert game.create_relic().ok
        wait(lambda: view.evaluate("Reliquary.snapshot().items.length") == 21)
        assert view.evaluate("document.querySelectorAll('[data-item]').length") == 21
        view.evaluate(
            "globalThis.copy=Reliquary.snapshot(); copy.items[0].quantity=-2; copy.items.length=0; void 0"
        )
        assert len(game.snapshot().items) == 21
        assert game.snapshot().items[0].quantity == 1
        assert view.evaluate("Reliquary.snapshot().items[0].quantity") == 1
        # Modify the raw bound return value too: it must still be a detached copy.
        view.evaluate("inventory.backend.read().snapshot.items[0].quantity=-99; void 0")
        assert game.snapshot().items[0].quantity == 1
        assert view.evaluate("Reliquary.addRelic().ok")
        assert len(game.snapshot().items) == 22
        assert view.evaluate("Reliquary.snapshot().items.length") == 22
        assert view.evaluate(
            "Reliquary.engine.execute({type:'bind',key:'1',reference:{item:'seed-9'}}).ok"
        )
        assert view.evaluate("Reliquary.activate('1').ok")
        assert next(i for i in game.snapshot().items if i.id == "seed-9").quantity == 7
        assert view.evaluate(
            "Reliquary.engine.execute({type:'equip',id:'seed-12',slot:'ring1'}).ok"
        )
        assert view.evaluate(
            "Reliquary.comparison('seed-0').startsWith('Equip: Power')"
        )
        assert view.evaluate(
            "Reliquary.engine.execute({type:'socket',id:'gem',socket:'saint-socket',newId:'forged'}).ok"
        )
        assert not any(i.id == "forged" for i in game.snapshot().items)
        assert not view.evaluate("Reliquary.engine.execute({type:'add',item:{}}).ok")
        assert not view.evaluate(
            "Reliquary.engine.execute({type:'remove',id:'gem'},0).ok"
        )
        before = game.snapshot()
        view.load_url("file:///index.html")
        wait(lambda: view.is_ready and view.evaluate("!!window.Reliquary?.view"))
        assert game.snapshot() == before
        assert view.evaluate("Reliquary.snapshot().revision") == before.revision
        assert game.create_relic().ok
        assert (
            view.evaluate("Reliquary.snapshot().revision") == game.snapshot().revision
        )
        assert len(game._listeners) == 1
        view.evaluate("Reliquary.dispose(); void 0")
        # Disposed frontends stop rendering; the host keeps its single event channel.
        assert len(game._listeners) == 1
        assert not errors, errors
        bridge.close()
    print(
        "Real Ultralight: backend creation, object copies, notifications, commands and reload passed"
    )


if __name__ == "__main__":
    main()
