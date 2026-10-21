"""Typed storage and strict decoding at the disk boundary."""

import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from reliquary.codec import decode_snapshot, encode_snapshot
from reliquary.game import initial_snapshot
from reliquary.state import SnapshotStore


class StateTests(unittest.TestCase):
    """Verify snapshot ownership, strict parsing and atomic persistence."""

    def test_roundtrip_and_detached_memory(self) -> None:
        """Round-trip domain values through JSON and retain no caller-owned items."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            snapshot = initial_snapshot()
            store = SnapshotStore(path)
            store.save(snapshot)
            self.assertEqual(SnapshotStore(path).load(), snapshot)
            snapshot.items.clear()
            stored = store.load()
            assert stored is not None
            self.assertEqual(len(stored.items), 20)
            returned = store.load()
            assert returned is not None
            returned.items.clear()
            stored = store.load()
            assert stored is not None
            self.assertEqual(len(stored.items), 20)

    def test_strict_parser_preserves_invalid_file(self) -> None:
        """Reject malformed transport shapes instead of retaining untyped records."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            for value in [
                {"old-layout": []},
                {"schemaVersion": 99},
                {"schemaVersion": True},
            ]:
                encoded = json.dumps(value)
                path.write_text(encoded)
                with self.assertRaises(ValueError):
                    SnapshotStore(path)
                self.assertEqual(path.read_text(), encoded)
        wire = encode_snapshot(initial_snapshot())
        wire["revision"] = True
        with self.assertRaises(ValueError):
            decode_snapshot(wire)

    def test_disk_failure_retains_previous_memory_and_allows_retry(self) -> None:
        """Update stored memory only after an atomic file write has succeeded."""
        store = SnapshotStore()
        snapshot = initial_snapshot()
        store.save(snapshot)
        newer = replace(snapshot, revision=5)
        with patch.object(store, "_flush", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                store.save(newer)
        self.assertEqual(store.load(), snapshot)
        store.save(newer)
        self.assertEqual(store.load(), newer)


if __name__ == "__main__":
    unittest.main()
