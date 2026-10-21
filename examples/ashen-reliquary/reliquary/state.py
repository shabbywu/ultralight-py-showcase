"""JSON layout persistence for the demo; no dependency on the rendering engine."""

from __future__ import annotations

import json
from pathlib import Path

NAMES = ("__godot_ground", "__godot_bag")


class LayoutStore:
    """Keep both inventories across page reloads and optionally across launches."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.layouts = {}
        self.saves = 0
        self.snapshot = None
        if path and path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and "schemaVersion" in value:
                self._validate_snapshot(value)
                self.snapshot = value
                return
            if not isinstance(value, dict) or set(value) - set(NAMES):
                raise ValueError("Invalid inventory state")
            for name, layout in value.items():
                self._validate(name, layout)
            self.layouts = value

    @staticmethod
    def _validate(name, layout):
        if name not in NAMES:
            raise ValueError("Unknown inventory")
        if not isinstance(layout, list) or any(
            not isinstance(item, dict) for item in layout
        ):
            raise ValueError("Layout must be an array of item records")

    def load_layout(self, name: str) -> str:
        """Return a snapshot; null asks the frontend to seed demo items."""
        if name not in NAMES:
            raise ValueError("Unknown inventory")
        return json.dumps(self.layouts.get(name), ensure_ascii=False)

    @staticmethod
    def _validate_snapshot(value):
        if not isinstance(value, dict) or value.get("schemaVersion") != 1:
            raise ValueError("Unsupported snapshot schemaVersion")
        if type(value.get("revision")) is not int or value["revision"] < 0:
            raise ValueError("Invalid snapshot revision")
        if (
            not isinstance(value.get("containers"), list)
            or not isinstance(value.get("items"), list)
            or not isinstance(value.get("shortcuts"), dict)
        ):
            raise ValueError("Snapshot requires containers, items and shortcuts")
        if any(
            not isinstance(c, dict)
            or not isinstance(c.get("id"), str)
            or c.get("kind") not in ("grid", "slot", "socket")
            for c in value["containers"]
        ):
            raise ValueError("Invalid container record")
        containers = {c["id"] for c in value["containers"]}
        if len(containers) != len(value["containers"]):
            raise ValueError("Duplicate container ID")
        ids = set()
        for item in value["items"]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not isinstance(item.get("definition"), str)
                or not isinstance(item.get("position"), dict)
            ):
                raise ValueError("Invalid item record")
            if (
                item["id"] in ids
                or item.get("position", {}).get("container") not in containers
            ):
                raise ValueError("Duplicate item or unknown container")
            ids.add(item["id"])
            if (
                type(item.get("quantity")) is not int
                or item["quantity"] < 1
                or "content" in item
            ):
                raise ValueError("Invalid item quantity or legacy content")
        if any(
            not isinstance(ref, dict)
            or bool(ref.get("item")) == bool(ref.get("action"))
            for ref in value["shortcuts"].values()
        ):
            raise ValueError("Invalid shortcut record")
        if any(
            ref.get("item") not in ids
            for ref in value["shortcuts"].values()
            if "item" in ref
        ):
            raise ValueError("Invalid shortcut reference")

    def load_snapshot(self):
        return json.dumps(self.snapshot, ensure_ascii=False)

    def save_snapshot(self, encoded):
        value = json.loads(encoded)
        self._validate_snapshot(value)
        if self.path and self.path.exists() and self.snapshot is None:
            backup = self.path.with_suffix(self.path.suffix + ".legacy.bak")
            if not backup.exists():
                backup.write_bytes(self.path.read_bytes())
        previous = self.snapshot
        self.snapshot = value
        try:
            self._flush()
        except Exception:
            self.snapshot = previous
            raise
        self.saves += 1

    def reset(self) -> None:
        """Return to the frontend's demo arrangement on next reload."""
        self.layouts = {}
        self.snapshot = None
        self._flush()

    def _flush(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(
                    self.snapshot if self.snapshot is not None else self.layouts,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            temporary.replace(self.path)
