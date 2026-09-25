from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from hermes_foundation_bridge.canonical import canonical_bytes
from hermes_foundation_bridge.errors import BridgeError
from hermes_foundation_bridge.release import (
    ARCHIVE_NAME,
    PUBLIC_KEY_NAME,
    RELEASE_NAME,
    RELEASE_VERSION,
    SIGNATURE_NAME,
    release_verified,
    trusted_public_key_path,
    verify_release,
)

SOURCE_ROOT = Path(__file__).resolve().parents[1]
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_release(root: Path) -> Path:
    release = root / "releases" / f"{RELEASE_NAME}-{RELEASE_VERSION}"
    release.mkdir(parents=True)
    public_key = trusted_public_key_path().read_bytes()
    files = {
        name: (SOURCE_ROOT / name).read_bytes()
        for name in (
            "LICENSE",
            "LICENSE_STATUS.md",
            "RELEASE.md",
            "RECOVERY.md",
            "DOLT_SQL.md",
            "SBOM.json",
            "bridge-lock.json",
            "plugin.py",
            "plugin.yaml",
        )
    }
    files[PUBLIC_KEY_NAME] = public_key
    manifest = {
        "schema_version": 1,
        "bundle_type": "hermes-plugin",
        "name": RELEASE_NAME,
        "version": RELEASE_VERSION,
        "release_status": "release",
        "signature_scheme": "minisign",
        "trusted_public_key_sha256": digest(public_key),
        "source_commit": COMMIT,
        "source_tree_clean": True,
        "license_status": "Apache-2.0",
        "production_activation_allowed": False,
        "files": [
            {"path": name, "sha256": digest(data), "bytes": len(data)}
            for name, data in sorted(files.items())
        ],
    }
    with zipfile.ZipFile(release / ARCHIVE_NAME, "w") as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
        archive.writestr("bundle-manifest.json", canonical_bytes(manifest))
    (release / SIGNATURE_NAME).write_text("test signature\n", encoding="utf-8")
    (release / PUBLIC_KEY_NAME).write_bytes(public_key)
    return release


class ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "foundation"
        self.release = make_release(self.root)

    def tearDown(self) -> None:
        self.directory.cleanup()

    @patch(
        "hermes_foundation_bridge.release.shutil.which",
        return_value="/usr/bin/minisign",
    )
    @patch("hermes_foundation_bridge.release.subprocess.run")
    def test_verified_release_writes_self_hashing_receipt(
        self, run: MagicMock, _which: MagicMock
    ) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        result = verify_release(
            {
                "schema_version": 1,
                "expected_version": RELEASE_VERSION,
                "expected_commit": COMMIT,
            },
            self.root,
        )
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source_commit"], COMMIT)
        self.assertTrue(result["signature_verified"])
        self.assertFalse(result["production_activation_allowed"])
        verified, persisted = release_verified(self.root)
        self.assertTrue(verified)
        self.assertEqual(persisted, result)
        mode = os.stat(self.root / "runtime" / "release-verification.json").st_mode
        self.assertEqual(mode & 0o777, 0o600)

    def test_invalid_commit_is_rejected_before_signature_check(self) -> None:
        with self.assertRaises(BridgeError) as caught:
            verify_release(
                {
                    "schema_version": 1,
                    "expected_version": RELEASE_VERSION,
                    "expected_commit": "main",
                },
                self.root,
            )
        self.assertEqual(caught.exception.code, "release_commit_invalid")

    @patch(
        "hermes_foundation_bridge.release.shutil.which",
        return_value="/usr/bin/minisign",
    )
    @patch("hermes_foundation_bridge.release.subprocess.run")
    def test_invalid_signature_is_rejected(
        self, run: MagicMock, _which: MagicMock
    ) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, b"", b"invalid")
        with self.assertRaises(BridgeError) as caught:
            verify_release(
                {
                    "schema_version": 1,
                    "expected_version": RELEASE_VERSION,
                    "expected_commit": COMMIT,
                },
                self.root,
            )
        self.assertEqual(caught.exception.code, "release_signature_invalid")

    def test_tampered_receipt_is_not_trusted(self) -> None:
        path = self.root / "runtime" / "release-verification.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "status": "verified",
                    "name": RELEASE_NAME,
                    "version": RELEASE_VERSION,
                    "source_commit": COMMIT,
                    "signature_verified": True,
                    "license_status": "Apache-2.0",
                    "receipt_hash": "0" * 64,
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(release_verified(self.root), (False, None))


if __name__ == "__main__":
    unittest.main()
