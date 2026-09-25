from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from hermes_foundation_bridge.canonical import sha256_json
from hermes_foundation_bridge.dolt_state import DoltStateAdapter


@unittest.skipUnless(shutil.which("dolt"), "Dolt CLI is required")
class DoltStateAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "foundation"
        self.adapter = DoltStateAdapter(self.root)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def request(self, operation: str, expected: int, value: int) -> dict:
        body = {"value": value}
        return {
            "schema_version": 1,
            "database": "kw_core",
            "project_id": "PROJECT-1",
            "object_id": "OBJECT-1",
            "expected_revision": expected,
            "content_hash": sha256_json(body),
            "schema_id": "Fixture-v1",
            "object": body,
            "operation_id": operation,
            "run_id": "RUN-1",
        }

    def test_json_control_characters_and_unicode_roundtrip(self) -> None:
        self.adapter.migrate(apply=True)
        body = {"text": "Path C:\\reports\nUnicode: данные; quote ' and \"; color \x1b[33m"}
        request = self.request("OP-JSON", 0, 1)
        request.update(object=body, content_hash=sha256_json(body))
        result = self.adapter.put(request)
        self.assertEqual(result["status"], "committed")
        self.assertRegex(result["commit_ref"], r"^[0-9a-v]{32}$")
        read = self.adapter.get({"schema_version":1,"database":"kw_core",
                                 "project_id":"PROJECT-1","object_id":"OBJECT-1"})
        self.assertEqual(read["object"], body)
        self.adapter._run(self.adapter.root / "kw_core", "sql", "-q",
                          "UPDATE objects SET object_json=JSON_OBJECT('corrupted',true)")
        with self.assertRaises(ValueError):
            self.adapter.get({"schema_version":1,"database":"kw_core",
                              "project_id":"PROJECT-1","object_id":"OBJECT-1"})

    def test_dry_run_then_apply_creates_four_new_databases(self) -> None:
        dry = self.adapter.migrate(apply=False)
        self.assertEqual(dry["status"], "dry_run_ready")
        self.assertFalse(self.adapter.root.exists())
        applied = self.adapter.migrate(apply=True)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(len(applied["applied_database_ids"]), 4)
        for name in applied["database_ids"]:
            self.assertTrue((self.adapter.root / name / ".dolt").is_dir())
        repeated = self.adapter.migrate(apply=True)
        self.assertEqual(repeated["status"], "applied")

    def test_cas_has_one_success_one_stale_and_separate_commit(self) -> None:
        self.adapter.migrate(apply=True)
        first = self.adapter.put(self.request("OP-1", 0, 1))
        stale = self.adapter.put(self.request("OP-2", 0, 2))
        no_op = self.adapter.put(self.request("OP-3", 1, 1))
        read = self.adapter.get(
            {
                "schema_version": 1,
                "database": "kw_core",
                "project_id": "PROJECT-1",
                "object_id": "OBJECT-1",
            }
        )
        self.assertEqual(first["status"], "committed")
        self.assertTrue(first["commit_created"])
        self.assertTrue(first["readback_verified"])
        self.assertEqual(stale["status"], "stale_revision")
        self.assertFalse(stale["commit_created"])
        self.assertFalse(stale["partial_write"])
        self.assertEqual(no_op["status"], "no_op")
        self.assertFalse(no_op["commit_created"])
        self.assertEqual(read["object"], {"value": 1})
        self.assertFalse(read["commit_created"])


if __name__ == "__main__":
    unittest.main()
