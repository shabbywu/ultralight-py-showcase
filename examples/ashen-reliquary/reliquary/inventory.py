"""Typed inventory state, atomic primitives and isolated transaction planning."""

from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from types import MappingProxyType

from reliquary.models import (
    Container,
    ContainerKind,
    Definition,
    ErrorCode,
    Failure,
    Item,
    ItemShortcut,
    Position,
    Result,
    Snapshot,
    Success,
)

Cell = tuple[str] | tuple[str, int, int]


class Rejected(ValueError):
    """Reject a candidate transaction without changing authoritative state."""


def require(condition: object, message: str) -> None:
    """Require a domain invariant without coercing invalid data."""
    if not condition:
        raise Rejected(message)


def integer(value: object) -> bool:
    """Recognize integer values without accepting booleans."""
    return type(value) is int


class Inventory:
    """Own validated state and commit complete, independently planned transactions."""

    def __init__(self, definitions: tuple[Definition, ...], snapshot: Snapshot) -> None:
        """Admit definitions and the complete initial graph."""
        require(
            all(
                integer(d.width)
                and integer(d.height)
                and integer(d.max_stack)
                and d.width > 0
                and d.height > 0
                and d.max_stack > 0
                for d in definitions
            ),
            "Invalid definition dimensions or stack limit",
        )
        self._definitions = {d.id: d for d in definitions}
        require(len(self._definitions) == len(definitions), "Duplicate definition")
        self.validate(snapshot)
        self._state = deepcopy(snapshot)

    @property
    def definitions(self) -> Mapping[str, Definition]:
        """Expose immutable definitions through a read-only mapping interface."""
        return MappingProxyType(self._definitions)

    def snapshot(self) -> Snapshot:
        """Return an independent copy of authoritative state."""
        return deepcopy(self._state)

    def definition(self, definition_id: str) -> Definition:
        """Resolve a definition or reject an unknown identity."""
        try:
            return self._definitions[definition_id]
        except KeyError as error:
            raise Rejected("Unknown definition") from error

    @staticmethod
    def item(state: Snapshot, item_id: str) -> Item:
        """Resolve an item in a specific candidate snapshot."""
        item = next((i for i in state.items if i.id == item_id), None)
        if item is None:
            raise Rejected("Unknown item: " + str(item_id))
        return item

    @staticmethod
    def container(state: Snapshot, container_id: str) -> Container:
        """Resolve a container in a specific candidate snapshot."""
        container = next((c for c in state.containers if c.id == container_id), None)
        if container is None:
            raise Rejected("Unknown container: " + str(container_id))
        return container

    def dimensions(self, item: Item) -> tuple[int, int]:
        """Return logical dimensions after applying quarter-turn orientation."""
        definition = self.definition(item.definition)
        return (
            (definition.height, definition.width)
            if item.position.rotation % 2
            else (definition.width, definition.height)
        )

    def validate(self, state: Snapshot) -> dict[Cell, str]:
        """Validate identities, quantities, references and placement across a complete graph."""
        require(
            integer(state.schema_version)
            and state.schema_version == 1
            and integer(state.revision)
            and state.revision >= 0,
            "Invalid schema or revision",
        )
        containers = {c.id: c for c in state.containers}
        require(len(containers) == len(state.containers), "Duplicate container")
        items = {i.id: i for i in state.items}
        require(len(items) == len(state.items), "Duplicate item ID")
        cells: dict[Cell, str] = {}
        for container in state.containers:
            require(bool(container.id), "Empty container identity")
            require(
                container.kind is ContainerKind.SOCKET or container.owner is None,
                "Invalid owner",
            )
            if container.kind is ContainerKind.GRID:
                require(
                    integer(container.width)
                    and integer(container.height)
                    and container.width > 0
                    and container.height > 0,
                    "Invalid grid dimensions",
                )
            if container.kind is ContainerKind.SOCKET:
                require(container.owner in items, "Missing socket owner")
        for item in state.items:
            require(bool(item.id), "Empty item identity")
            definition = self.definition(item.definition)
            container = self.container(state, item.position.container)
            position = item.position
            require(
                integer(item.quantity) and 1 <= item.quantity <= definition.max_stack,
                "Invalid quantity",
            )
            require(
                integer(position.rotation)
                and 0 <= position.rotation <= 3
                and (definition.rotatable or position.rotation == 0),
                "Invalid rotation",
            )
            require(
                container.accepts is None or item.definition in container.accepts,
                "Container rejected item",
            )
            keys: list[Cell]
            if container.kind is ContainerKind.GRID:
                width, height = self.dimensions(item)
                x, y = position.x, position.y
                require(integer(x) and integer(y), "Grid coordinates must be integers")
                assert x is not None and y is not None
                require(
                    x >= 0
                    and y >= 0
                    and x + width <= container.width
                    and y + height <= container.height,
                    "Out of bounds",
                )
                keys = [
                    (container.id, a, b)
                    for b in range(y, y + height)
                    for a in range(x, x + width)
                ]
            else:
                require(
                    container.kind is not ContainerKind.SLOT
                    or container.slot in definition.slots,
                    "Invalid equipment slot",
                )
                require(
                    container.kind is not ContainerKind.SOCKET or item.quantity == 1,
                    "Socket takes one gem",
                )
                keys = [(container.id,)]
                if definition.two_handed and container.slot == "mainhand":
                    keys.extend(
                        (c.id,) for c in state.containers if c.slot == "offhand"
                    )
            for key in keys:
                require(key not in cells, "Occupied")
                cells[key] = item.id
            owner, seen = container.owner, {item.id}
            while owner is not None:
                require(owner not in seen, "Socket cycle")
                seen.add(owner)
                owner = self.container(
                    state, self.item(state, owner).position.container
                ).owner
        for shortcut_key, reference in state.shortcuts.items():
            require(
                shortcut_key not in ("__proto__", "prototype", "constructor"),
                "Invalid shortcut key",
            )
            if isinstance(reference, ItemShortcut):
                require(reference.item_id in items, "Invalid shortcut reference")
            else:
                require(bool(reference.action), "Empty shortcut action")
        return cells

    def preview(
        self,
        action: Callable[["InventoryTransaction"], None],
        allocate_id: Callable[[], str],
    ) -> Result:
        """Plan typed atomic operations against a detached candidate without committing."""
        transaction = InventoryTransaction(self, self.snapshot(), allocate_id)
        try:
            action(transaction)
            self.validate(transaction.state)
            transaction.state.revision = self._state.revision + 1
            before = {i.id: i for i in self._state.items}
            after = {i.id: i for i in transaction.state.items}
            affected = tuple(
                key
                for key in sorted(before.keys() | after.keys())
                if before.get(key) != after.get(key)
            )
            return Success(self._state.revision, transaction.state, affected)
        except Rejected as error:
            return Failure(ErrorCode.REJECTED, str(error))

    def commit(self, snapshot: Snapshot) -> None:
        """Commit only a fully validated snapshot, retaining no caller-owned objects."""
        self.validate(snapshot)
        self._state = deepcopy(snapshot)


class InventoryTransaction:
    """Compose atomic primitives on a private candidate; validation happens before commit."""

    def __init__(
        self, inventory: Inventory, state: Snapshot, allocate_id: Callable[[], str]
    ) -> None:
        """Own one candidate and its backend identity allocator."""
        self.inventory = inventory
        self.state = state
        self._allocate_id = allocate_id

    def item(self, item_id: str) -> Item:
        """Resolve an item in this candidate."""
        return self.inventory.item(self.state, item_id)

    def container(self, container_id: str) -> Container:
        """Resolve a container in this candidate."""
        return self.inventory.container(self.state, container_id)

    def add_item(self, item: Item) -> None:
        """Add an independent item value to the candidate."""
        self.state.items.append(deepcopy(item))

    def move_item(self, item_id: str, destination: Position) -> None:
        """Move an item to an immutable exact position."""
        self.item(item_id).position = destination

    def remove_item(self, item_id: str) -> None:
        """Remove an item, its owned socket subtree and dangling shortcuts."""
        self.item(item_id)
        removed = {item_id}
        while True:
            children = {
                i.id
                for i in self.state.items
                if self.container(i.position.container).owner in removed
            }
            if children <= removed:
                break
            removed |= children
        self.state.items = [i for i in self.state.items if i.id not in removed]
        self.state.containers = [
            c for c in self.state.containers if c.owner not in removed
        ]
        self.state.shortcuts = {
            k: v
            for k, v in self.state.shortcuts.items()
            if not isinstance(v, ItemShortcut) or v.item_id not in removed
        }

    def split_stack(self, item_id: str, quantity: int, destination: Position) -> None:
        """Split a quantity into a newly allocated backend item identity."""
        item = self.item(item_id)
        require(integer(quantity) and 0 < quantity < item.quantity, "Invalid split")
        item.quantity -= quantity
        self.add_item(Item(self._allocate_id(), item.definition, quantity, destination))

    def merge_stacks(self, item_id: str, target_id: str) -> None:
        """Merge stacks and redirect references only when the source disappears."""
        item, target = self.item(item_id), self.item(target_id)
        a, b = (
            self.inventory.definition(item.definition),
            self.inventory.definition(target.definition),
        )
        require(
            item is not target and (a.stack_key or a.id) == (b.stack_key or b.id),
            "Incompatible stack",
        )
        count = min(item.quantity, b.max_stack - target.quantity)
        require(count > 0, "Stack full")
        item.quantity -= count
        target.quantity += count
        if item.quantity == 0:
            self.state.items.remove(item)
            self.state.shortcuts = {
                k: ItemShortcut(target.id)
                if isinstance(v, ItemShortcut) and v.item_id == item.id
                else v
                for k, v in self.state.shortcuts.items()
            }

    def consume_item(self, item_id: str, quantity: int) -> None:
        """Consume a validated quantity as a backend business effect."""
        item = self.item(item_id)
        require(
            integer(quantity) and 0 < quantity <= item.quantity, "Invalid consumption"
        )
        item.quantity -= quantity
        if item.quantity == 0:
            self.remove_item(item_id)

    def bind_item(self, key: str, item_id: str) -> None:
        """Bind an existing identity without copying or consuming its item."""
        self.item(item_id)
        self.state.shortcuts[key] = ItemShortcut(item_id)

    def positions(self, item_id: str, container_id: str) -> Iterator[Position]:
        """Yield deterministic grid positions for search and equipment return planning."""
        item, container = self.item(item_id), self.container(container_id)
        require(container.kind is ContainerKind.GRID, "Destination is not a grid")
        for y in range(container.height):
            for x in range(container.width):
                for rotation in (
                    (0, 1)
                    if self.inventory.definition(item.definition).rotatable
                    else (0,)
                ):
                    yield Position(container_id, x, y, rotation)

    def place_in_grid(self, item_id: str, container_id: str) -> None:
        """Place an item in the first fully valid grid position or reject the candidate."""
        item, previous = self.item(item_id), self.item(item_id).position
        for position in self.positions(item_id, container_id):
            item.position = position
            try:
                self.inventory.validate(self.state)
                return
            except Rejected:
                pass
        item.position = previous
        raise Rejected("No space")
