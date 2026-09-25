from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hermes_foundation_bridge.canonical import sha256_json
from hermes_foundation_bridge.errors import BridgeError
from hermes_foundation_bridge.recovery import (
    SYSTEM_CLASSES,
    RecoveryService,
    _archive_limit,
)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "foundation"
        self.service = RecoveryService(self.root)
        self.snapshot = "SNAPSHOT-245"
        self.alternate = "ALTERNATE-246"
        self.archive_root = self.service.backups / self.snapshot
        self.restore_root = self.service.drills / self.alternate
        self.archive_root.mkdir(parents=True)
        self.restore_root.mkdir(parents=True)
        self.archive_receipts = []
        self.restore_receipts = []
        self.measurements = []
        for system in SYSTEM_CLASSES:
            encrypted = b"age-encryption.org/v1\n" + system.encode()
            restored = f"restored:{system}".encode()
            (self.archive_root / f"{system}.age").write_bytes(encrypted)
            (self.restore_root / f"{system}.restored").write_bytes(restored)
            self.archive_receipts.append(
                {
                    "system_class": system,
                    "archive_name": f"{system}.age",
                    "archive_sha256": sha(encrypted),
                    "source_quiesced": True,
                    "encrypted": True,
                    "snapshot_readback": True,
                    "source_version_ref": "VERSION-1",
                }
            )
            self.restore_receipts.append(
                {
                    "system_class": system,
                    "snapshot_id": self.snapshot,
                    "restored_ref": f"{system}.restored",
                    "content_hash": sha(restored),
                    "readback_hash": sha(restored),
                    "semantic_probe": True,
                    "secret_boundary_verified": True,
                }
            )
            self.measurements.append(
                {
                    "system_class": system,
                    "rpo_seconds": 60,
                    "rto_seconds": 120,
                    "measured_rpo_seconds": 30,
                    "measured_rto_seconds": 90,
                    "readback_verified": True,
                    "source_sequence_ref": "SEQ-1",
                }
            )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def inventory_request(self) -> dict:
        return {
            "schema_version": 1,
            "snapshot_id": self.snapshot,
            "created_at": datetime.now(UTC).isoformat(),
            "max_age_seconds": 3600,
            "archive_receipts": self.archive_receipts,
        }

    def checkpoint_request(self) -> dict:
        started = datetime.now(UTC) - timedelta(seconds=10)
        released = datetime.now(UTC)
        captured = started + timedelta(seconds=5)
        sequence_hash = sha256_json({system: "SEQ-1" for system in SYSTEM_CLASSES})
        return {
            "schema_version": 1,
            "checkpoint_id": self.snapshot,
            "max_age_seconds": 3600,
            "max_capture_window_seconds": 60,
            "barrier": {
                "owner_id": "OPERATOR-1",
                "gateway_off": True,
                "sql_server_off": True,
                "docker_writers_off": True,
                "active_tool_invocations": 0,
                "write_lease_count": 0,
                "before_sequence_hash": sequence_hash,
                "after_sequence_hash": sequence_hash,
                "started_at": started.isoformat(),
                "released_at": released.isoformat(),
            },
            "systems": [
                {
                    "system_class": row["system_class"],
                    "checkpoint_id": self.snapshot,
                    "archive_sha256": row["archive_sha256"],
                    "captured_at": captured.isoformat(),
                    "source_sequence_ref": "SEQ-1",
                    "restored_sequence_ref": "SEQ-1",
                    "authenticated_decryption": True,
                    "alternate_readback": True,
                    "semantic_probe": True,
                    "secret_boundary": True,
                    "rpo_limit_seconds": 60,
                    "rto_limit_seconds": 120,
                    "measured_rpo_seconds": 10,
                    "measured_rto_seconds": 20,
                }
                for row in self.archive_receipts
            ],
        }

    def test_tc245_inventory_all_twelve_distinct_classes(self) -> None:
        result = self.service.inventory(self.inventory_request())
        self.assertEqual(result["status"], "archive_inventory_candidate")
        self.assertEqual(result["checksum_checked_system_count"], 12)
        self.assertFalse(result["authenticated_decryption_verified"])
        self.assertFalse(result["actual_restore_verified"])
        self.assertFalse(result["production_activation_allowed"])

    def test_missing_or_tampered_archive_blocks_inventory(self) -> None:
        path = self.archive_root / "beads.age"
        path.write_bytes(b"age-encryption.org/v1\ntampered")
        result = self.service.inventory(self.inventory_request())
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["checksum_checked_system_count"], 11)
        self.archive_receipts.pop()
        with self.assertRaises(BridgeError):
            self.service.inventory(self.inventory_request())

    def test_tc246_alternate_root_readback_and_gateway_off(self) -> None:
        result = self.service.restore_assess(
            {
                "schema_version": 1,
                "snapshot_id": self.snapshot,
                "alternate_root_id": self.alternate,
                "gateway_autostart": False,
                "restore_receipts": self.restore_receipts,
            }
        )
        self.assertEqual(result["status"], "fixture_readback_pass")
        self.assertEqual(result["verified_system_count"], 12)
        self.assertFalse(result["production_restore_qualified"])
        (self.restore_root / "gateway.pid").write_text("123", encoding="utf-8")
        with self.assertRaises(BridgeError) as caught:
            self.service.restore_assess(
                {
                    "schema_version": 1,
                    "snapshot_id": self.snapshot,
                    "alternate_root_id": self.alternate,
                    "gateway_autostart": False,
                    "restore_receipts": self.restore_receipts,
                }
            )
        self.assertEqual(caught.exception.code, "restore_gateway_running")

    def test_tc247_one_system_over_rto_blocks_without_averaging(self) -> None:
        self.measurements[0]["measured_rto_seconds"] = 121
        result = self.service.objectives(
            {
                "schema_version": 1,
                "snapshot_id": self.snapshot,
                "measurements": self.measurements,
            }
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["failed_systems"], [SYSTEM_CLASSES[0]])
        self.assertFalse(result["averaging_applied"])
        self.assertFalse(result["production_activation_allowed"])

    def test_complete_checkpoint_is_candidate_not_product_qualification(self) -> None:
        result = self.service.checkpoint_assess(self.checkpoint_request())
        self.assertEqual(result["status"], "checkpoint_candidate")
        self.assertEqual(result["candidate_system_count"], 12)
        self.assertFalse(result["host_observations_independently_attested"])
        self.assertFalse(result["production_restore_qualified"])
        self.assertFalse(result["production_activation_allowed"])

    def test_mixed_checkpoint_or_one_rto_failure_blocks_all(self) -> None:
        request = self.checkpoint_request()
        request["systems"][0]["checkpoint_id"] = "OTHER-SNAPSHOT"
        request["systems"][1]["measured_rto_seconds"] = 121
        request["barrier"]["after_sequence_hash"] = "b" * 64
        result = self.service.checkpoint_assess(request)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("sequence_changed_during_snapshot", result["barrier_issues"])
        self.assertEqual(result["failed_systems"], list(SYSTEM_CLASSES[:2]))
        self.assertFalse(result["averaging_applied"])

    def test_sequence_commitment_must_bind_all_twelve_refs(self) -> None:
        request = self.checkpoint_request()
        request["barrier"]["before_sequence_hash"] = "a" * 64
        request["barrier"]["after_sequence_hash"] = "a" * 64
        result = self.service.checkpoint_assess(request)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("sequence_commitment_mismatch", result["barrier_issues"])
        self.assertEqual(result["candidate_system_count"], 12)

    def test_archive_tamper_and_capture_outside_barrier_block(self) -> None:
        request = self.checkpoint_request()
        (self.archive_root / "beads.age").write_bytes(b"age-encryption.org/v1\nchanged")
        request["systems"][1]["captured_at"] = (
            datetime.now(UTC) - timedelta(minutes=2)
        ).isoformat()
        result = self.service.checkpoint_assess(request)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["failed_systems"], ["beads"])
        self.assertIn("archive_integrity_unverified", result["systems"][1]["issues"])
        self.assertIn("capture_outside_barrier", result["systems"][1]["issues"])

    def test_missing_class_or_future_barrier_blocks(self) -> None:
        request = self.checkpoint_request()
        request["systems"].pop()
        with self.assertRaises(BridgeError) as caught:
            self.service.checkpoint_assess(request)
        self.assertEqual(caught.exception.code, "backup_inventory_incomplete")
        request = self.checkpoint_request()
        request["barrier"]["released_at"] = (
            datetime.now(UTC) + timedelta(minutes=2)
        ).isoformat()
        result = self.service.checkpoint_assess(request)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("checkpoint_stale", result["barrier_issues"])

    def test_only_git_has_larger_archive_limit_and_symlink_still_blocks(self) -> None:
        self.assertEqual(_archive_limit("git_repositories"), 1024**3)
        self.assertTrue(
            all(
                _archive_limit(system) == 512 * 1024**2
                for system in SYSTEM_CLASSES
                if system != "git_repositories"
            )
        )
        path = self.archive_root / "git_repositories.age"
        path.unlink()
        path.symlink_to(self.archive_root / "artifacts.age")
        result = self.service.checkpoint_assess(self.checkpoint_request())
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["failed_systems"], ["git_repositories"])
        self.assertIn(
            "archive_integrity_unverified",
            result["systems"][SYSTEM_CLASSES.index("git_repositories")]["issues"],
        )


if __name__ == "__main__":
    unittest.main()
