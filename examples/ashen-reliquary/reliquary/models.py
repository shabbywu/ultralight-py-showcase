"""Concrete domain values; wire dictionaries are confined to the codec boundary."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal, TypeAlias


class ContainerKind(str, Enum):
    """Supported inventory region kinds."""

    GRID = "grid"
    SLOT = "slot"
    SOCKET = "socket"


@dataclass(frozen=True, slots=True)
class Position:
    """An exact location; non-grid locations do not require coordinates."""

    container: str
    x: int | None = None
    y: int | None = None
    rotation: int = 0


@dataclass(frozen=True, slots=True)
class Definition:
    """Backend-owned immutable item definition."""

    id: str
    name: str
    width: int
    height: int
    rarity: str
    power: int
    rotatable: bool = False
    max_stack: int = 1
    stack_key: str | None = None
    slots: tuple[str, ...] = ()
    two_handed: bool = False


@dataclass(frozen=True, slots=True)
class Container:
    """A named grid, equipment slot or owned socket."""

    id: str
    kind: ContainerKind
    width: int = 0
    height: int = 0
    slot: str | None = None
    owner: str | None = None
    accepts: tuple[str, ...] | None = None


@dataclass(slots=True)
class Item:
    """Mutable item data within a detached inventory transaction."""

    id: str
    definition: str
    quantity: int
    position: Position


@dataclass(frozen=True, slots=True)
class ItemShortcut:
    """A shortcut referencing an existing item identity."""

    item_id: str


@dataclass(frozen=True, slots=True)
class ActionShortcut:
    """A shortcut referencing a named backend action."""

    action: str


Shortcut: TypeAlias = ItemShortcut | ActionShortcut


@dataclass(slots=True)
class Snapshot:
    """A complete inventory graph owned by the backend or a detached candidate."""

    revision: int
    containers: list[Container]
    items: list[Item]
    shortcuts: dict[str, Shortcut]
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class Attributes:
    """Calculated character attributes."""

    power: int
    ward: int


class ErrorCode(str, Enum):
    """Stable request rejection codes."""

    REJECTED = "REJECTED"
    STALE = "STALE"
    BUSY = "BUSY"
    INVALID_REVISION = "INVALID_REVISION"
    NO_SPACE = "NO_SPACE"


@dataclass(frozen=True, slots=True)
class Success:
    """An admitted candidate or committed state, including its affected identities."""

    revision: int
    snapshot: Snapshot
    affected: tuple[str, ...]
    attributes: Attributes | None = None
    ok: Literal[True] = True


@dataclass(frozen=True, slots=True)
class Failure:
    """A request rejection that does not change authoritative state."""

    code: ErrorCode
    message: str
    ok: Literal[False] = False


Result: TypeAlias = Success | Failure


class EventKind(str, Enum):
    """Events published after authoritative state or persistence changes."""

    STATE_CHANGED = "stateChanged"
    PERSISTENCE_CHANGED = "persistenceChanged"


@dataclass(frozen=True, slots=True)
class StateEvent:
    """A backend event with a committed revision."""

    kind: EventKind
    revision: int


@dataclass(frozen=True, slots=True)
class ReadModel:
    """An independent projection for frontend rendering."""

    snapshot: Snapshot
    attributes: Attributes
    dirty: bool
    persistence_error: str


@dataclass(frozen=True, slots=True)
class Comparison:
    """An equipment attribute delta or rejection explanation."""

    power: int = 0
    ward: int = 0
    message: str = ""


@dataclass(frozen=True, slots=True)
class Catalog:
    """Backend definitions and initial container configuration."""

    definitions: tuple[Definition, ...]
    containers: tuple[Container, ...]
