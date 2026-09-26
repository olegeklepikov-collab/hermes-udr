from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from hermes_foundation_bridge.runtime import RuntimeCoordinator


class RuntimeCoordinatorTests(unittest.TestCase):
    def test_expired_lease_transfers_with_new_revision_and_fences_old_owner(self):
        now = datetime(2026, 9, 22, tzinfo=UTC)
        request = {
            "schema_version": 1,
            "work_id": "WORK-EXPIRE",
            "holder_id": "A",
            "expected_revision": 1,
            "ttl_seconds": 30,
        }
        with patch("hermes_foundation_bridge.runtime._now", return_value=now):
            self.assertEqual(
                self.coordinator.acquire_lease(request)["status"], "acquired"
            )
        with patch(
            "hermes_foundation_bridge.runtime._now",
            return_value=now + timedelta(seconds=31),
        ):
            transferred = self.coordinator.acquire_lease({**request, "holder_id": "B"})
            self.assertEqual(transferred["status"], "acquired")
            self.assertEqual(transferred["current_revision"], 2)
            self.assertEqual(
                self.coordinator.acquire_lease(request)["status"], "stale_revision"
            )

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "foundation"
        self.coordinator = RuntimeCoordinator(self.root)
        result = self.coordinator.migration_receipt(apply=True)
        self.assertEqual(result["status"], "applied")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_dry_run_does_not_create_database(self) -> None:
        other = RuntimeCoordinator(Path(self.directory.name) / "dry")
        result = other.migration_receipt(apply=False)
        self.assertEqual(result["status"], "dry_run_ready")
        self.assertFalse(other.database.exists())

    def test_same_expected_revision_has_one_owner(self) -> None:
        request = {
            "schema_version": 1,
            "work_id": "WORK-1",
            "holder_id": "WORKER-A",
            "expected_revision": 1,
            "ttl_seconds": 30,
        }
        first = self.coordinator.acquire_lease(request)
        request["holder_id"] = "WORKER-B"
        second = self.coordinator.acquire_lease(request)
        self.assertEqual(first["status"], "acquired")
        self.assertEqual(second["status"], "lease_conflict")
        self.assertTrue(first["lease_active"])
        self.assertFalse(second["lease_active"])

    def test_outbox_is_idempotent_and_detects_changed_payload(self) -> None:
        first = self.coordinator.enqueue(
            event_key="EVENT-1", event_type="artifact", payload={"a": 1}
        )
        repeated = self.coordinator.enqueue(
            event_key="EVENT-1", event_type="artifact", payload={"a": 1}
        )
        conflict = self.coordinator.enqueue(
            event_key="EVENT-1", event_type="artifact", payload={"a": 2}
        )
        self.assertEqual(first["status"], "queued")
        self.assertEqual(repeated["status"], "idempotent_existing")
        self.assertEqual(conflict["status"], "idempotency_conflict")

    def test_hook_journal_is_ordered_and_idempotent(self) -> None:
        start = self.coordinator.record_hook("on_session_start", {"session_id": "S-1"})
        pre = self.coordinator.record_hook(
            "pre_llm_call", {"session_id": "S-1", "turn_id": "T-1"}
        )
        repeated = self.coordinator.record_hook(
            "pre_llm_call", {"session_id": "S-1", "turn_id": "T-1"}
        )
        self.assertEqual((start["sequence"], pre["sequence"]), (1, 2))
        self.assertEqual(repeated["status"], "idempotent_existing")
        self.assertEqual(repeated["sequence"], 2)

    def test_health_reports_wal_and_single_writer(self) -> None:
        result = self.coordinator.health()
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["journal_mode"].lower(), "wal")
        self.assertTrue(result["single_writer_interface"])

    def test_local_turn_ids_are_isolated_between_sessions(self) -> None:
        first = self.coordinator.record_hook(
            "pre_llm_call", {"session_id": "A", "turn_id": "T-1"}
        )
        second = self.coordinator.record_hook(
            "pre_llm_call", {"session_id": "B", "turn_id": "T-1"}
        )
        self.assertEqual((first["status"], second["status"]), ("recorded", "recorded"))
        self.assertNotEqual(first["event_id"], second["event_id"])
        self.assertEqual((first["sequence"], second["sequence"]), (1, 1))

    def test_legacy_event_replay_keeps_identity_without_cross_session_conflict(
        self,
    ) -> None:
        payload = {"session_id": "A", "turn_id": "T-1"}
        original = self.coordinator.record_hook("pre_llm_call", payload)
        with closing(sqlite3.connect(self.coordinator.database)) as connection, connection:
            connection.execute(
                "UPDATE hook_events SET event_key=? WHERE event_id=?",
                ("pre_llm_call:T-1", original["event_id"]),
            )
        replay = self.coordinator.record_hook("pre_llm_call", payload)
        self.assertEqual(replay["status"], "idempotent_existing")
        self.assertEqual(replay["event_id"], original["event_id"])
        other = self.coordinator.record_hook(
            "pre_llm_call", {"session_id": "B", "turn_id": "T-1"}
        )
        self.assertEqual(other["status"], "recorded")


if __name__ == "__main__":
    unittest.main()
