"""Typed snapshot persistence with strict decoding and atomic file replacement."""

import json
from copy import deepcopy
from pathlib import Path

from reliquary.codec import decode_snapshot, encode_snapshot
from reliquary.models import Snapshot


class SnapshotStore:
    """Keep a detached snapshot optionally backed by an atomic JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        """Decode persisted values into concrete domain types without overwriting errors."""
        self.path = path
        self.saves = 0
        self._snapshot: Snapshot | None = None
        if path is not None and path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            self._snapshot = None if value is None else decode_snapshot(value)

    def load(self) -> Snapshot | None:
        """Return an independent copy of the last successfully persisted state."""
        return deepcopy(self._snapshot)

    def save(self, snapshot: Snapshot) -> None:
        """Store a typed snapshot, replacing memory only after a successful file write."""
        candidate = deepcopy(snapshot)
        self._flush(candidate)
        self._snapshot = candidate
        self.saves += 1

    def _flush(self, snapshot: Snapshot) -> None:
        """Write JSON only at the disk boundary and atomically replace the state file."""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(encode_snapshot(snapshot), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
