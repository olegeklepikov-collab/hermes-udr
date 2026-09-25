from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.audit_native_bundle import NativeAuditError, audit_native_bundle
from scripts.build_plugin_bundle import build_bundle


class NativeAuditTests(unittest.TestCase):
    def test_clean_native_archive_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "native.zip"
            build_bundle(archive)
            result = audit_native_bundle(archive)
            self.assertEqual(result["status"], "clean_native_candidate")
            self.assertEqual(result["registered_tool_manifest_count"], 9)
            self.assertFalse(result["development_artifacts_present"])

    def test_added_development_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "native.zip"
            build_bundle(archive)
            with zipfile.ZipFile(archive, "a") as output:
                output.writestr("tests/test_debug.py", "print('fixture')")
            with self.assertRaises(NativeAuditError) as error:
                audit_native_bundle(archive)
            self.assertEqual(error.exception.code, "native_member_set_invalid")

    def test_local_path_or_secret_marker_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "native.zip"
            build_bundle(archive)
            with zipfile.ZipFile(archive) as original:
                items = {name: original.read(name) for name in original.namelist()}
            items["README.md"] += b"\n/Users/test/private\n"
            altered = Path(directory) / "altered.zip"
            with zipfile.ZipFile(altered, "w") as output:
                for name, payload in items.items():
                    output.writestr(name, payload)
            with self.assertRaises(NativeAuditError) as error:
                audit_native_bundle(altered)
            self.assertEqual(error.exception.code, "local_identity_or_secret_marker")


if __name__ == "__main__":
    unittest.main()
