"""Bridge persistence contracts shared by browser reloads and the Python host."""

import json
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from reliquary.state import LayoutStore


class StateTests(unittest.TestCase):
    def test_content_rotation_and_empty_inventory_survive_restart(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = LayoutStore(path)
            item = {
                "id": "sword",
                "x": 2,
                "y": 1,
                "w": 4,
                "h": 2,
                "rotateDeg": 90,
                "content": '<img src="./reliquary/items/saint-breaker.webp">',
            }
            path.write_text(json.dumps({"__godot_ground": [item], "__godot_bag": []}))
            restored = LayoutStore(path)
            self.assertEqual(json.loads(restored.load_layout("__godot_ground")), [item])
            self.assertEqual(json.loads(restored.load_layout("__godot_bag")), [])
            restored.reset()
            self.assertEqual(LayoutStore(path).load_layout("__godot_bag"), "null")

    def test_invalid_legacy_files_are_not_overwritten(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            for value in [
                {"other": []},
                {"__godot_ground": {}},
                {"__godot_ground": [1]},
            ]:
                encoded = json.dumps(value)
                path.write_text(encoded)
                with self.assertRaises(ValueError):
                    LayoutStore(path)
                self.assertEqual(path.read_text(), encoded)


class SnapshotTests(unittest.TestCase):
    @staticmethod
    def snapshot():
        return dict(
            schemaVersion=1,
            revision=4,
            containers=[dict(id="bag", kind="grid", width=12, height=6)],
            items=[
                dict(
                    id="gem",
                    definition="double-cross",
                    quantity=3,
                    position=dict(container="bag", x=1, y=2, rotation=0),
                )
            ],
            shortcuts={"1": dict(item="gem")},
        )

    def test_complete_snapshot_roundtrip(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = LayoutStore(path)
            store.save_snapshot(json.dumps(self.snapshot()))
            self.assertEqual(
                json.loads(LayoutStore(path).load_snapshot()), self.snapshot()
            )

    def test_invalid_snapshot_does_not_change_memory_or_disk(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = LayoutStore(path)
            store.save_snapshot(json.dumps(self.snapshot()))
            before = path.read_bytes()
            for value in [
                dict(self.snapshot(), schemaVersion=99),
                dict(self.snapshot(), revision=-1),
                dict(self.snapshot(), shortcuts={"1": dict(item="missing")}),
            ]:
                with self.assertRaises(ValueError):
                    store.save_snapshot(json.dumps(value))
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(json.loads(store.load_snapshot()), self.snapshot())

    def test_migration_keeps_legacy_file_backup(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            original = json.dumps({"__godot_bag": []})
            path.write_text(original)
            store = LayoutStore(path)
            store.save_snapshot(json.dumps(self.snapshot()))
            self.assertEqual(path.with_suffix(".json.legacy.bak").read_text(), original)

    def test_disk_failure_rolls_back_and_can_retry(self):
        from unittest.mock import patch

        store = LayoutStore()
        store.save_snapshot(json.dumps(self.snapshot()))
        newer = dict(self.snapshot(), revision=5)
        with patch.object(store, "_flush", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                store.save_snapshot(json.dumps(newer))
        self.assertEqual(json.loads(store.load_snapshot()), self.snapshot())
        store.save_snapshot(json.dumps(newer))
        self.assertEqual(json.loads(store.load_snapshot()), newer)


if __name__ == "__main__":
    unittest.main()
