from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.build_bundle import build, source_commit


class BundleTests(unittest.TestCase):
    # These tests exercise archive mechanics, not a release of the mutable worktree.
    @patch("scripts.build_bundle.source_commit", return_value="a" * 40)
    def test_bundle_is_deterministic_and_self_verifying(self, _commit) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.zip"
            second = Path(directory) / "second.zip"
            a = build(first)
            b = build(second)
            self.assertEqual(a["sha256"], b["sha256"])
            with zipfile.ZipFile(first) as archive:
                manifest = json.loads(archive.read("bundle-manifest.json"))
                self.assertEqual(manifest["version"], "0.14.0b1")
                self.assertEqual(manifest["release_status"], "release")
                self.assertEqual(manifest["signature_scheme"], "minisign")
                self.assertEqual(manifest["license_status"], "Apache-2.0")
                self.assertEqual(manifest["source_commit"], "a" * 40)
                self.assertTrue(manifest["source_tree_clean"])
                self.assertFalse(manifest["production_activation_allowed"])
                self.assertIn("LICENSE", archive.namelist())
                self.assertIn("RECOVERY.md", archive.namelist())
                self.assertIn("DOLT_SQL.md", archive.namelist())
                self.assertIn("scripts/provision_dolt_sql.py", archive.namelist())
                self.assertIn("scripts/manage_dolt_sql.py", archive.namelist())
                self.assertIn("scripts/configure_native_runtime.py", archive.namelist())
                self.assertIn("src/hermes_foundation_bridge/native_runtime.py", archive.namelist())
                self.assertIn("src/hermes_foundation_bridge/graphiti_worker.py", archive.namelist())
                self.assertIn("src/hermes_foundation_bridge/agentmemory_worker.mjs", archive.namelist())
                self.assertFalse(any(name.startswith("docker/") for name in archive.namelist()))
                lock = json.loads(archive.read("bridge-lock.json"))
                self.assertEqual(lock["graphiti"]["graph_backend"], "neo4j")
                self.assertNotIn("falkordb", lock)
                sbom = json.loads(archive.read("SBOM.json"))
                self.assertFalse(any(row["type"] == "container" for row in sbom["components"]))
                self.assertIn("release-signing.pub", archive.namelist())
                self.assertIn("migrations/001_runtime.sql", archive.namelist())
                self.assertIn("migrations/002_dolt.sql", archive.namelist())
                self.assertIn(
                    "migrations/003_profile_transport.sql", archive.namelist()
                )
                self.assertIn("migrations/004_observability.sql", archive.namelist())
                for row in manifest["files"]:
                    content = archive.read(row["path"])
                    self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])
                    self.assertEqual(len(content), row["bytes"])

    @patch("scripts.build_bundle.source_commit", return_value="a" * 40)
    def test_bundle_refuses_overwrite(self, _commit) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.zip"
            build(path)
            with self.assertRaises(FileExistsError):
                build(path)

    def test_real_release_guard_rejects_dirty_source(self) -> None:
        with patch(
            "scripts.build_bundle.subprocess.run",
            side_effect=[
                SimpleNamespace(stdout="a" * 40),
                SimpleNamespace(stdout=" M plugin.py\n"),
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "not clean"):
                source_commit()


if __name__ == "__main__":
    unittest.main()
