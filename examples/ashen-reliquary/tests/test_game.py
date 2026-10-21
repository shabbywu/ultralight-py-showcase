"""Typed backend authority, atomic primitives and gameplay orchestration."""

import random
import unittest
from dataclasses import replace
from unittest.mock import patch

from reliquary.bridge import GameBridge
from reliquary.game import Game, initial_snapshot
from reliquary.inventory import InventoryTransaction, Rejected
from reliquary.models import (
    ContainerKind,
    ErrorCode,
    EventKind,
    Failure,
    Item,
    Position,
    Result,
    StateEvent,
    Success,
)
from reliquary.state import SnapshotStore


class GameTests(unittest.TestCase):
    """Verify gameplay through explicit methods and concrete domain values."""

    def setUp(self) -> None:
        """Create deterministic backend identities and observe committed events."""
        self.ids: list[str] = []

        def allocate() -> str:
            """Allocate a deterministic permanent backend identity."""
            value = f"backend-{len(self.ids)}"
            self.ids.append(value)
            return value

        self.store = SnapshotStore()
        self.game = Game(
            self.store, choose=lambda definitions: definitions[-1], next_id=allocate
        )
        self.events: list[StateEvent] = []
        self.game.subscribe(self.events.append)

    def item(self, item_id: str) -> Item:
        """Find an item in an independent projection."""
        return next(i for i in self.game.snapshot().items if i.id == item_id)

    def admitted(self, result: Result) -> Success:
        """Require and narrow a successful gameplay result."""
        self.assertIsInstance(result, Success, result)
        assert isinstance(result, Success)
        return result

    def rejected(self, result: Result) -> Failure:
        """Require and narrow a rejected gameplay result."""
        self.assertIsInstance(result, Failure, result)
        assert isinstance(result, Failure)
        return result

    def test_backend_creation_and_detached_projections(self) -> None:
        """Generate without a view and prevent wire or projection writes to authority."""
        before = self.game.snapshot()
        result = self.admitted(self.game.create_relic())
        self.assertEqual(result.revision, 1)
        self.assertEqual(self.item("backend-0").definition, "double-cross")
        self.assertEqual(self.events, [StateEvent(EventKind.STATE_CHANGED, 1)])
        self.assertEqual(self.store.load(), self.game.snapshot())
        self.assertEqual(self.game.snapshot().items[:20], before.items)
        bridge = GameBridge(self.game)
        returned = bridge.read()
        returned.clear()
        projection = self.game.snapshot()
        projection.items[0].quantity = -2
        projection.items.clear()
        self.assertEqual(len(self.game.snapshot().items), 21)
        self.assertFalse(hasattr(bridge, "dispatch"))
        self.assertFalse(hasattr(bridge, "save_snapshot"))

    def test_split_preview_is_pure_and_backend_allocates_identity(self) -> None:
        """Preview typed operations without consuming IDs or changing state."""
        before = self.game.snapshot()
        self.admitted(self.game.preview_split_stack("gem", 2, "bag", 10, 4, 0))
        self.admitted(self.game.preview_split_stack("gem", 2, "bag", 10, 4, 0))
        self.assertEqual(self.ids, [])
        self.assertEqual(self.game.snapshot(), before)
        self.admitted(self.game.split_stack("gem", 2, "bag", 10, 4, 0))
        self.assertEqual(self.item("backend-0").quantity, 2)
        self.assertEqual(self.item("gem").quantity, 4)
        self.assertEqual(len(self.events), 1)

    def test_invalid_and_stale_operations_are_atomic(self) -> None:
        """Reject bad placement, quantities, revisions and references before commit."""
        before = self.game.snapshot()
        self.assertIsInstance(self.game.move_item("gem", "bag", -1, 0, 0), Failure)
        self.assertIsInstance(
            self.game.split_stack("gem", True, "bag", 10, 4, 0), Failure
        )
        self.assertIsInstance(self.game.bind_item("__proto__", "gem"), Failure)
        self.assertEqual(
            self.game.remove_item("gem", 99), Failure(ErrorCode.STALE, "State changed")
        )
        self.assertEqual(
            self.rejected(self.game.remove_item("gem", False)).code,
            ErrorCode.INVALID_REVISION,
        )
        self.assertEqual(self.game.snapshot(), before)
        self.assertEqual(self.events, [])
        self.assertEqual(self.store.saves, 0)

    def test_gameplay_composes_inventory_primitives(self) -> None:
        """Apply equipment returns, gem extraction, shortcut effects and cascades."""
        self.admitted(self.game.equip_best_slot("seed-12"))
        self.assertEqual(self.item("seed-12").position.container, "ring1")
        self.admitted(self.game.equip_best_slot("seed-12"))
        self.assertEqual(self.item("seed-12").position.container, "bag")
        self.admitted(self.game.equip_item("seed-4", "offhand"))
        self.admitted(self.game.equip_item("seed-0", "mainhand"))
        self.assertEqual(self.item("seed-4").position.container, "ground")
        self.admitted(self.game.socket_gem("gem", "saint-socket"))
        self.assertEqual(self.item("gem").quantity, 5)
        self.admitted(self.game.unsocket_gem("backend-0", "bag"))
        self.assertEqual(self.item("gem").quantity, 6)
        self.admitted(self.game.bind_item("1", "seed-9"))
        self.admitted(self.game.activate_shortcut("1"))
        self.assertEqual(self.item("seed-9").quantity, 7)
        self.admitted(self.game.socket_gem("gem", "saint-socket"))
        self.admitted(self.game.remove_item("seed-0"))
        self.assertFalse(
            any(c.id == "saint-socket" for c in self.game.snapshot().containers)
        )
        self.assertFalse(any(i.id == "backend-1" for i in self.game.snapshot().items))
        self.assertEqual(len(self.events), self.game.snapshot().revision)

    def test_inventory_transaction_rolls_back_composed_failure(self) -> None:
        """Keep all primitive changes isolated until complete candidate validation."""
        inventory = self.game._inventory
        before = inventory.snapshot()

        def action(tx: InventoryTransaction) -> None:
            """Compose a valid deletion followed by an invalid placement."""
            tx.remove_item("gem")
            tx.move_item("seed-15", Position("bag", -1, 0))

        result = inventory.preview(action, lambda: "temporary")
        self.assertIsInstance(result, Failure)
        self.assertEqual(inventory.snapshot(), before)

    def test_equipment_no_space_and_full_ground(self) -> None:
        """Reject return planning and creation without moving unrelated blockers."""
        state = initial_snapshot()
        state.containers = [
            c for c in state.containers if c.kind is not ContainerKind.SOCKET
        ]
        state.items = [
            Item("incoming", "pilgrims-oath", 1, Position("ground", 0, 0)),
            Item("equipped", "saint-breaker", 1, Position("mainhand")),
        ]
        for y in range(12):
            for x in range(12):
                if x == 0 and y < 4:
                    continue
                state.items.append(
                    Item(f"b-{x}-{y}", "enamel-ring", 1, Position("ground", x, y))
                )
        store = SnapshotStore()
        store.save(state)
        game = Game(store)
        self.assertIsInstance(game.equip_item("incoming", "mainhand"), Failure)
        self.assertEqual(game.snapshot(), state)
        state.items = [
            Item(f"b-{x}-{y}", "enamel-ring", 1, Position("ground", x, y))
            for y in range(12)
            for x in range(12)
        ]
        store.save(state)
        game = Game(store)
        self.assertEqual(self.rejected(game.create_relic()).code, ErrorCode.NO_SPACE)
        self.assertEqual(game.snapshot(), state)

    def test_save_failure_retry_and_notification_reentrancy(self) -> None:
        """Retain authority after failed persistence and prevent observer-triggered writes."""
        self.game.save()
        saved = self.store.load()
        with patch.object(self.store, "save", side_effect=OSError("Disk full")):
            self.admitted(self.game.remove_item("gem"))
        self.assertEqual(self.store.load(), saved)
        self.assertTrue(self.game.read().dirty)
        self.assertEqual(self.game.read().persistence_error, "Disk full")
        self.assertTrue(self.game.save())
        self.assertEqual(self.events[-1].kind, EventKind.PERSISTENCE_CHANGED)
        self.assertEqual(self.store.load(), self.game.snapshot())
        observed: list[Result] = []
        token = self.game.subscribe(
            lambda event: observed.append(self.game.create_relic())
        )
        self.game.create_relic()
        self.assertIsInstance(observed[0], Failure)
        self.assertEqual(self.rejected(observed[0]).code, ErrorCode.BUSY)
        self.game.unsubscribe(token)

    def test_random_moves_and_typed_load_admission(self) -> None:
        """Preserve quantities across invalid operations and reject corrupt saved graphs."""
        rng = random.Random(2026)
        for _ in range(300):
            before = self.game.snapshot()
            item = rng.choice(before.items)
            result = self.game.move_item(
                item.id,
                rng.choice(("bag", "ground")),
                rng.randrange(-1, 13),
                rng.randrange(-1, 13),
                rng.randrange(4),
            )
            after = self.game.snapshot()
            if isinstance(result, Failure):
                self.assertEqual(before, after)
            self.game._inventory.validate(after)
            self.assertEqual(
                sum(i.quantity for i in after.items),
                sum(i.quantity for i in before.items),
            )
        state = initial_snapshot()
        state.items[0].position = replace(state.items[0].position, x=100)
        store = SnapshotStore()
        store.save(state)
        with self.assertRaises(Rejected):
            Game(store)
        self.assertEqual(store.load(), state)


if __name__ == "__main__":
    unittest.main()
