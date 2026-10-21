"""Strict parsing and detached wire encoding at disk and JavaScript boundaries."""

from typing import TypeAlias, cast

from reliquary.models import (
    ActionShortcut,
    Attributes,
    Catalog,
    Comparison,
    Container,
    ContainerKind,
    Definition,
    Failure,
    Item,
    ItemShortcut,
    Position,
    ReadModel,
    Result,
    Shortcut,
    Snapshot,
    StateEvent,
)

WireValue: TypeAlias = (
    None | bool | int | float | str | list["WireValue"] | dict[str, "WireValue"]
)
WireObject: TypeAlias = dict[str, WireValue]


def record(value: object, allowed: set[str]) -> dict[str, object]:
    """Require an object with string keys and reject unrecognized fields."""
    if (
        not isinstance(value, dict)
        or any(not isinstance(k, str) for k in value)
        or set(value) - allowed
    ):
        raise ValueError("Invalid or unexpected record fields")
    return cast(dict[str, object], value)


def text(value: object) -> str:
    """Read a nonempty textual identity or field."""
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a nonempty string")
    return value


def number(value: object) -> int:
    """Read an integer without accepting booleans or truncated floats."""
    if type(value) is not int:
        raise ValueError("Expected an integer")
    return value


def boolean(value: object) -> bool:
    """Read a boolean without coercing other values."""
    if type(value) is not bool:
        raise ValueError("Expected a boolean")
    return value


def array(value: object) -> list[object]:
    """Read a concrete array at the decoding boundary."""
    if not isinstance(value, list):
        raise ValueError("Expected an array")
    return value


def strings(value: object) -> tuple[str, ...]:
    """Read an immutable sequence of nonempty strings."""
    return tuple(text(v) for v in array(value))


def decode_position(value: object) -> Position:
    """Decode an item position without retaining input containers."""
    p = record(value, {"container", "x", "y", "rotation"})
    return Position(
        text(p.get("container")),
        number(p["x"]) if "x" in p else None,
        number(p["y"]) if "y" in p else None,
        number(p.get("rotation", 0)),
    )


def decode_container(value: object) -> Container:
    """Decode a concrete container and its optional kind-specific configuration."""
    c = record(value, {"id", "kind", "width", "height", "slot", "owner", "accepts"})
    return Container(
        text(c.get("id")),
        ContainerKind(text(c.get("kind"))),
        number(c.get("width", 0)),
        number(c.get("height", 0)),
        text(c["slot"]) if "slot" in c else None,
        text(c["owner"]) if "owner" in c else None,
        strings(c["accepts"]) if "accepts" in c else None,
    )


def decode_snapshot(value: object) -> Snapshot:
    """Decode a full snapshot into owned domain instances; validate rules separately."""
    s = record(value, {"schemaVersion", "revision", "containers", "items", "shortcuts"})
    items: list[Item] = []
    for raw in array(s.get("items")):
        i = record(raw, {"id", "definition", "quantity", "position"})
        items.append(
            Item(
                text(i.get("id")),
                text(i.get("definition")),
                number(i.get("quantity")),
                decode_position(i.get("position")),
            )
        )
    raw_shortcuts = s.get("shortcuts")
    if not isinstance(raw_shortcuts, dict) or any(
        not isinstance(k, str) for k in raw_shortcuts
    ):
        raise ValueError("Invalid shortcuts")
    shortcuts: dict[str, Shortcut] = {}
    for key, raw_ref in raw_shortcuts.items():
        ref = record(raw_ref, {"item", "action"})
        if len(ref) != 1:
            raise ValueError("A shortcut requires exactly one reference")
        shortcuts[key] = (
            ItemShortcut(text(ref["item"]))
            if "item" in ref
            else ActionShortcut(text(ref.get("action")))
        )
    snapshot = Snapshot(
        number(s.get("revision")),
        [decode_container(c) for c in array(s.get("containers"))],
        items,
        shortcuts,
        number(s.get("schemaVersion")),
    )
    if snapshot.schema_version != 1 or snapshot.revision < 0:
        raise ValueError("Unsupported schema or revision")
    return snapshot


def decode_catalog(value: object) -> Catalog:
    """Decode trusted catalog configuration into immutable definition values."""
    c = record(value, {"definitions", "containers"})
    definitions: list[Definition] = []
    for raw in array(c.get("definitions")):
        d = record(
            raw,
            {
                "id",
                "name",
                "width",
                "height",
                "rarity",
                "power",
                "rotatable",
                "maxStack",
                "stackKey",
                "slots",
                "twoHanded",
            },
        )
        definition = Definition(
            text(d.get("id")),
            text(d.get("name")),
            number(d.get("width")),
            number(d.get("height")),
            text(d.get("rarity")),
            number(d.get("power")),
            boolean(d.get("rotatable", False)),
            number(d.get("maxStack", 1)),
            text(d["stackKey"]) if "stackKey" in d else None,
            strings(d.get("slots", [])),
            boolean(d.get("twoHanded", False)),
        )
        if definition.width < 1 or definition.height < 1 or definition.max_stack < 1:
            raise ValueError("Invalid item dimensions or stack limit")
        definitions.append(definition)
    if len({d.id for d in definitions}) != len(definitions):
        raise ValueError("Duplicate definition")
    return Catalog(
        tuple(definitions),
        tuple(decode_container(v) for v in array(c.get("containers"))),
    )


def encode_position(p: Position) -> WireObject:
    """Encode a location without exposing a domain object to JavaScript."""
    result: WireObject = {"container": p.container, "rotation": p.rotation}
    if p.x is not None:
        result["x"] = p.x
    if p.y is not None:
        result["y"] = p.y
    return result


def encode_container(c: Container) -> WireObject:
    """Encode the fields appropriate to a container kind."""
    result: WireObject = {"id": c.id, "kind": c.kind.value}
    if c.kind is ContainerKind.GRID:
        result.update(width=c.width, height=c.height)
    if c.slot is not None:
        result["slot"] = c.slot
    if c.owner is not None:
        result["owner"] = c.owner
    if c.accepts is not None:
        result["accepts"] = list(c.accepts)
    return result


def encode_snapshot(s: Snapshot) -> WireObject:
    """Create a fully independent wire snapshot from concrete domain values."""
    return {
        "schemaVersion": s.schema_version,
        "revision": s.revision,
        "containers": [encode_container(c) for c in s.containers],
        "items": [
            {
                "id": i.id,
                "definition": i.definition,
                "quantity": i.quantity,
                "position": encode_position(i.position),
            }
            for i in s.items
        ],
        "shortcuts": {
            key: (
                {"item": ref.item_id}
                if isinstance(ref, ItemShortcut)
                else {"action": ref.action}
            )
            for key, ref in s.shortcuts.items()
        },
    }


def encode_definition(d: Definition) -> WireObject:
    """Encode immutable item metadata for rendering."""
    return {
        "id": d.id,
        "name": d.name,
        "width": d.width,
        "height": d.height,
        "rarity": d.rarity,
        "power": d.power,
        "rotatable": d.rotatable,
        "maxStack": d.max_stack,
        "slots": list(d.slots),
        "twoHanded": d.two_handed,
    }


def encode_attributes(a: Attributes) -> WireObject:
    """Encode calculated character attributes."""
    return {"power": a.power, "ward": a.ward}


def encode_result(result: Result) -> WireObject:
    """Encode an admitted transaction or a typed rejection."""
    if isinstance(result, Failure):
        return {"ok": False, "code": result.code.value, "message": result.message}
    value: WireObject = {
        "ok": True,
        "revision": result.revision,
        "snapshot": encode_snapshot(result.snapshot),
        "affected": list(result.affected),
    }
    if result.attributes is not None:
        value["attributes"] = encode_attributes(result.attributes)
    return value


def encode_read_model(value: ReadModel) -> WireObject:
    """Encode the render projection and save status together."""
    return {
        "snapshot": encode_snapshot(value.snapshot),
        "attributes": encode_attributes(value.attributes),
        "dirty": value.dirty,
        "persistenceError": value.persistence_error,
    }


def encode_event(value: StateEvent) -> WireObject:
    """Encode a committed backend notification."""
    return {"type": value.kind.value, "revision": value.revision}


def encode_comparison(value: Comparison | None) -> WireObject | None:
    """Encode an optional equipment comparison."""
    if value is None:
        return None
    return (
        {"message": value.message}
        if value.message
        else {"power": value.power, "ward": value.ward}
    )
