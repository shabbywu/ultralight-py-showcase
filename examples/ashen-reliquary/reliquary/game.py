"""Backend gameplay composed from typed inventory transaction primitives."""

import itertools
import json
import logging
import random
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from reliquary.codec import decode_catalog
from reliquary.inventory import Inventory, InventoryTransaction, Rejected, require
from reliquary.models import (
    Attributes,
    Comparison,
    Container,
    ContainerKind,
    Definition,
    ErrorCode,
    EventKind,
    Failure,
    Item,
    ItemShortcut,
    Position,
    ReadModel,
    Result,
    Snapshot,
    StateEvent,
    Success,
)
from reliquary.state import SnapshotStore

CATALOG = decode_catalog(
    json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
)
Action = Callable[[InventoryTransaction], None]


def initial_snapshot() -> Snapshot:
    """Create the backend demo arrangement without relying on a page lifecycle."""
    items = [
        Item(
            f"seed-{n}",
            d.id,
            8 if d.max_stack > 1 else 1,
            Position(
                "ground" if n < 10 else "bag",
                (n % 4) * 3,
                ((n if n < 10 else n - 10) // 4) * 4,
            ),
        )
        for n, d in enumerate(CATALOG.definitions[:18])
    ]
    items += [
        Item("chest", "gothic-breastplate", 1, Position("bag", 0, 1)),
        Item("gem", "double-cross", 6, Position("bag", 11, 0)),
    ]
    return Snapshot(
        0,
        list(CATALOG.containers)
        + [
            Container(
                "saint-socket",
                ContainerKind.SOCKET,
                owner="seed-0",
                accepts=("double-cross",),
            )
        ],
        items,
        {},
    )


class Game:
    """Own authoritative gameplay, persistence status and committed state events."""

    def __init__(
        self,
        store: SnapshotStore,
        *,
        choose: Callable[[tuple[Definition, ...]], Definition] = random.choice,
        next_id: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        """Load and validate typed state or initialize a new backend-owned session."""
        self._store = store
        self._choose = choose
        self._next_id = next_id
        self._listeners: dict[int, Callable[[StateEvent], object]] = {}
        self._tokens = itertools.count(1)
        self._publishing = False
        saved = store.load()
        self._inventory = Inventory(
            CATALOG.definitions, initial_snapshot() if saved is None else saved
        )
        self._dirty = saved is None
        self._persistence_error = ""

    @property
    def definitions(self) -> tuple[Definition, ...]:
        """Return immutable backend definitions."""
        return CATALOG.definitions

    def snapshot(self) -> Snapshot:
        """Return an independent copy of authoritative state."""
        return self._inventory.snapshot()

    def attributes(self, state: Snapshot) -> Attributes:
        """Calculate equipment and owned-gem business effects."""
        equipped = [
            i
            for i in state.items
            if self._inventory.container(state, i.position.container).kind
            is ContainerKind.SLOT
        ]
        owners = {i.id for i in equipped}
        gems = [
            i
            for i in state.items
            if self._inventory.container(state, i.position.container).owner in owners
        ]
        return Attributes(
            10
            + sum(self._inventory.definition(i.definition).power for i in equipped)
            + len(gems) * 5,
            5 + len(equipped) * 3,
        )

    def read(self) -> ReadModel:
        """Return a detached render projection and its persistence status."""
        snapshot = self.snapshot()
        return ReadModel(
            snapshot, self.attributes(snapshot), self._dirty, self._persistence_error
        )

    def subscribe(self, callback: Callable[[StateEvent], object]) -> int:
        """Subscribe to committed backend notifications."""
        token = next(self._tokens)
        self._listeners[token] = callback
        return token

    def unsubscribe(self, token: int) -> None:
        """Release an event subscriber by its token."""
        self._listeners.pop(token, None)

    def _notify(self, kind: EventKind) -> None:
        """Notify after commit, isolating observer failures and reentrant writes."""
        self._publishing = True
        try:
            event = StateEvent(kind, self.snapshot().revision)
            for token, callback in list(self._listeners.items()):
                if token not in self._listeners:
                    continue
                try:
                    callback(event)
                except Exception:
                    logging.getLogger(__name__).exception("Inventory observer failed")
        finally:
            self._publishing = False

    def _persist(self) -> bool:
        """Attempt atomic storage while retaining committed gameplay on failure."""
        try:
            self._store.save(self.snapshot())
            self._dirty, self._persistence_error = False, ""
            return True
        except Exception as error:
            self._dirty, self._persistence_error = True, str(error)
            return False

    def save(self) -> bool:
        """Retry persistence of the current backend state."""
        if self._publishing:
            return False
        result = self._persist()
        self._notify(EventKind.PERSISTENCE_CHANGED)
        return result

    def _preview(self, action: Action) -> Result:
        """Plan gameplay against a detached transaction with temporary identities."""
        ids = itertools.count()
        result = self._inventory.preview(
            action, lambda: f"preview-{self.snapshot().revision}-{next(ids)}"
        )
        return (
            replace(result, attributes=self.attributes(result.snapshot))
            if isinstance(result, Success)
            else result
        )

    def _commit(self, result: Result) -> Result:
        """Commit an admitted transaction, attempt storage and publish exactly once."""
        if isinstance(result, Failure):
            return result
        self._inventory.commit(result.snapshot)
        self._dirty = True
        self._persist()
        self._notify(EventKind.STATE_CHANGED)
        return replace(result, revision=self.snapshot().revision)

    def _execute(self, action: Action, expected_revision: int | None) -> Result:
        """Apply gameplay using backend identities against a checked revision."""
        if self._publishing:
            return Failure(ErrorCode.BUSY, "Cannot mutate during notification")
        if expected_revision is not None and type(expected_revision) is not int:
            return Failure(ErrorCode.INVALID_REVISION, "Revision must be an integer")
        if (
            expected_revision is not None
            and expected_revision != self.snapshot().revision
        ):
            return Failure(ErrorCode.STALE, "State changed")
        admitted = self._preview(action)
        if isinstance(admitted, Failure):
            return admitted
        return self._commit(self._inventory.preview(action, self._next_id))

    def _equip(self, tx: InventoryTransaction, item_id: str, slot_id: str) -> None:
        """Plan the gameplay equipment swap and return only conflicting equipment."""
        item, dest = tx.item(item_id), tx.container(slot_id)
        source = tx.container(item.position.container)
        definition = self._inventory.definition(item.definition)
        require(source.kind is ContainerKind.GRID, "Equip from a grid")
        require(
            dest.kind is ContainerKind.SLOT and dest.slot in definition.slots,
            "Invalid equipment slot",
        )
        conflicts = [
            i
            for i in tx.state.items
            if tx.container(i.position.container).kind is ContainerKind.SLOT
            and (
                i.position.container == slot_id
                or (
                    definition.two_handed
                    and tx.container(i.position.container).slot == "offhand"
                )
                or (
                    dest.slot == "offhand"
                    and self._inventory.definition(i.definition).two_handed
                )
            )
        ]
        conflicts.sort(
            key=lambda i: (
                -self._inventory.definition(i.definition).width
                * self._inventory.definition(i.definition).height,
                i.id,
            )
        )
        tx.move_item(item_id, Position(slot_id))

        def place(index: int) -> bool:
            """Search positions for only the remaining equipment conflicts."""
            if index == len(conflicts):
                self._inventory.validate(tx.state)
                return True
            old = conflicts[index]
            for position in tx.positions(old.id, source.id):
                tx.move_item(old.id, position)
                partial = InventoryTransaction(
                    self._inventory, deepcopy(tx.state), self._next_id
                )
                for pending in conflicts[index + 1 :]:
                    partial.remove_item(pending.id)
                try:
                    self._inventory.validate(partial.state)
                    if place(index + 1):
                        return True
                except Rejected:
                    pass
            return False

        require(place(0), "Cannot return all equipment to source grid")

    def _equip_best(self, tx: InventoryTransaction, item_id: str) -> None:
        """Choose a compatible free slot first or unload already equipped items."""
        item = tx.item(item_id)
        if tx.container(item.position.container).kind is not ContainerKind.GRID:
            tx.place_in_grid(item_id, "bag")
            return
        definition = self._inventory.definition(item.definition)
        slots = [
            c
            for c in tx.state.containers
            if c.kind is ContainerKind.SLOT and c.slot in definition.slots
        ]
        occupied = self._inventory.validate(tx.state)
        slots.sort(key=lambda c: (c.id,) in occupied)
        for slot in slots:
            trial = InventoryTransaction(
                self._inventory, deepcopy(tx.state), self._next_id
            )
            try:
                self._equip(trial, item_id, slot.id)
                tx.state = trial.state
                return
            except Rejected:
                pass
        raise Rejected("No compatible equipment slot with space")

    @staticmethod
    def _transfer(tx: InventoryTransaction, item_id: str) -> None:
        """Choose the destination grid according to game transfer rules."""
        tx.place_in_grid(
            item_id, "ground" if tx.item(item_id).position.container == "bag" else "bag"
        )

    @staticmethod
    def _socket(tx: InventoryTransaction, item_id: str, socket_id: str) -> None:
        """Compose a single-gem split or move using atomic primitives."""
        require(tx.container(socket_id).kind is ContainerKind.SOCKET, "Invalid socket")
        if tx.item(item_id).quantity > 1:
            tx.split_stack(item_id, 1, Position(socket_id))
        else:
            tx.move_item(item_id, Position(socket_id))

    def _unsocket(
        self, tx: InventoryTransaction, item_id: str, container_id: str
    ) -> None:
        """Merge an extracted gem when possible, otherwise find a grid position."""
        item = tx.item(item_id)
        require(
            tx.container(item.position.container).kind is ContainerKind.SOCKET,
            "Item is not socketed",
        )
        require(
            tx.container(container_id).kind is ContainerKind.GRID,
            "Destination is not a grid",
        )
        target = next(
            (
                i
                for i in tx.state.items
                if i.id != item_id
                and i.position.container == container_id
                and i.definition == item.definition
                and i.quantity < self._inventory.definition(i.definition).max_stack
            ),
            None,
        )
        if target is not None:
            tx.merge_stacks(item_id, target.id)
        else:
            tx.place_in_grid(item_id, container_id)

    @staticmethod
    def _activate(tx: InventoryTransaction, key: str) -> None:
        """Resolve a shortcut and apply the backend-owned consumption rule."""
        reference = tx.state.shortcuts.get(key)
        require(isinstance(reference, ItemShortcut), "Shortcut has no item")
        assert isinstance(reference, ItemShortcut)
        require(
            tx.item(reference.item_id).definition == "ember-flask",
            "Item cannot be activated",
        )
        tx.consume_item(reference.item_id, 1)

    def create_relic(self) -> Result:
        """Generate, place and commit a new relic without any frontend-generated data."""
        if self._publishing:
            return Failure(ErrorCode.BUSY, "Cannot mutate during notification")
        definition = self._choose(self.definitions)
        ground = self._inventory.container(self.snapshot(), "ground")
        item_id = self._next_id()
        for y in range(ground.height):
            for x in range(ground.width):
                item = Item(item_id, definition.id, 1, Position("ground", x, y))
                result = self._inventory.preview(
                    lambda tx: tx.add_item(item), self._next_id
                )
                if isinstance(result, Success):
                    return self._commit(result)
        return Failure(ErrorCode.NO_SPACE, "No space on Ground")

    def comparison(self, item_id: str) -> Comparison | None:
        """Calculate an equipment preview delta without modifying state."""
        state = self.snapshot()
        try:
            item = self._inventory.item(state, item_id)
            slots = self._inventory.definition(item.definition).slots
            slot = next(
                (
                    c
                    for c in state.containers
                    if c.kind is ContainerKind.SLOT and c.slot in slots
                ),
                None,
            )
            if slot is None:
                return None
            result = self.preview_equip_item(item_id, slot.id)
            if isinstance(result, Failure):
                return Comparison(message=result.message)
            assert result.attributes is not None
            before, after = self.attributes(state), result.attributes
            return Comparison(after.power - before.power, after.ward - before.ward)
        except Rejected:
            return None

    def move_item(
        self,
        item_id: str,
        container_id: str,
        x: int,
        y: int,
        rotation: int,
        expected_revision: int | None = None,
    ) -> Result:
        """Move an item to an exact grid position."""
        return self._execute(
            lambda tx: tx.move_item(item_id, Position(container_id, x, y, rotation)),
            expected_revision,
        )

    def preview_move_item(
        self, item_id: str, container_id: str, x: int, y: int, rotation: int
    ) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(
            lambda tx: tx.move_item(item_id, Position(container_id, x, y, rotation))
        )

    def remove_item(self, item_id: str, expected_revision: int | None = None) -> Result:
        """Delete an item and its dependent sockets."""
        return self._execute(lambda tx: tx.remove_item(item_id), expected_revision)

    def preview_remove_item(self, item_id: str) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(lambda tx: tx.remove_item(item_id))

    def split_stack(
        self,
        item_id: str,
        quantity: int,
        container_id: str,
        x: int,
        y: int,
        rotation: int,
        expected_revision: int | None = None,
    ) -> Result:
        """Split a stack using a backend-generated identity."""
        return self._execute(
            lambda tx: tx.split_stack(
                item_id, quantity, Position(container_id, x, y, rotation)
            ),
            expected_revision,
        )

    def preview_split_stack(
        self,
        item_id: str,
        quantity: int,
        container_id: str,
        x: int,
        y: int,
        rotation: int,
    ) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(
            lambda tx: tx.split_stack(
                item_id, quantity, Position(container_id, x, y, rotation)
            )
        )

    def merge_stacks(
        self, item_id: str, target_id: str, expected_revision: int | None = None
    ) -> Result:
        """Merge compatible item stacks."""
        return self._execute(
            lambda tx: tx.merge_stacks(item_id, target_id), expected_revision
        )

    def preview_merge_stacks(self, item_id: str, target_id: str) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(lambda tx: tx.merge_stacks(item_id, target_id))

    def equip_item(
        self, item_id: str, slot_id: str, expected_revision: int | None = None
    ) -> Result:
        """Equip an item and return conflicting equipment."""
        return self._execute(
            lambda tx: self._equip(tx, item_id, slot_id), expected_revision
        )

    def preview_equip_item(self, item_id: str, slot_id: str) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(lambda tx: self._equip(tx, item_id, slot_id))

    def equip_best_slot(
        self, item_id: str, expected_revision: int | None = None
    ) -> Result:
        """Select an equipment slot or unload equipped items."""
        return self._execute(
            lambda tx: self._equip_best(tx, item_id), expected_revision
        )

    def preview_equip_best_slot(self, item_id: str) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(lambda tx: self._equip_best(tx, item_id))

    def transfer_item(
        self, item_id: str, expected_revision: int | None = None
    ) -> Result:
        """Transfer an item using backend destination selection."""
        return self._execute(lambda tx: self._transfer(tx, item_id), expected_revision)

    def preview_transfer_item(self, item_id: str) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(lambda tx: self._transfer(tx, item_id))

    def socket_gem(
        self, item_id: str, socket_id: str, expected_revision: int | None = None
    ) -> Result:
        """Place one gem into an owned socket."""
        return self._execute(
            lambda tx: self._socket(tx, item_id, socket_id), expected_revision
        )

    def preview_socket_gem(self, item_id: str, socket_id: str) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(lambda tx: self._socket(tx, item_id, socket_id))

    def unsocket_gem(
        self, item_id: str, container_id: str, expected_revision: int | None = None
    ) -> Result:
        """Extract a gem using backend merge and placement rules."""
        return self._execute(
            lambda tx: self._unsocket(tx, item_id, container_id), expected_revision
        )

    def preview_unsocket_gem(self, item_id: str, container_id: str) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(lambda tx: self._unsocket(tx, item_id, container_id))

    def bind_item(
        self, key: str, item_id: str, expected_revision: int | None = None
    ) -> Result:
        """Bind a shortcut to an existing identity."""
        return self._execute(lambda tx: tx.bind_item(key, item_id), expected_revision)

    def preview_bind_item(self, key: str, item_id: str) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(lambda tx: tx.bind_item(key, item_id))

    def activate_shortcut(
        self, key: str, expected_revision: int | None = None
    ) -> Result:
        """Activate backend shortcut business effects."""
        return self._execute(lambda tx: self._activate(tx, key), expected_revision)

    def preview_activate_shortcut(self, key: str) -> Result:
        """Preview this gameplay operation without committing."""
        return self._preview(lambda tx: self._activate(tx, key))
