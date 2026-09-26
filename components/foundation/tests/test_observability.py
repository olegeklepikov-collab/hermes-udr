from __future__ import annotations

import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_foundation_bridge.errors import BridgeError
from hermes_foundation_bridge.observability import ObservabilityService


def trace_request(**changes: object) -> dict:
    value = {
        "schema_version": 1,
        "trace_id": "TRACE-240",
        "project_id": "PROJECT-240",
        "run_id": "RUN-240",
        "bead_id": "BEAD-240",
        "profile_id": "research",
        "session_hash": "a" * 64,
        "operation_id": "OP-240",
        "attempt": 1,
        "model_ref": "MODEL-240",
        "tool_ref": "TOOL-240",
        "context_refs": ["CTX-240"],
        "evidence_link_refs": ["EVIDENCE-240"],
        "commit_refs": ["COMMIT-240"],
        "latency_ms": 25,
        "cost_microunits": 10,
        "outcome_status": "success",
        "priority": "P1",
        "collector_available": True,
        "sampling_decision": "keep",
        "ttl_seconds": 300,
        "attributes": {"phase": "test"},
    }
    value.update(changes)
    return value


class ObservabilityTests(unittest.TestCase):
    def test_reconciliation_does_not_retarget_modified_spool_identity(self):
        self.service.record(trace_request(collector_available=False))
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            value = json.loads(
                connection.execute("SELECT envelope_json FROM trace_spool").fetchone()[
                    0
                ]
            )
            value["trace_id"] = "HIJACKED"
            connection.execute(
                "UPDATE trace_spool SET envelope_json=?", (json.dumps(value),)
            )
        result = self.service.reconcile(
            {"schema_version": 1, "collector_available": True}
        )
        self.assertEqual(result["conflicting_trace_ids"], ["TRACE-240"])
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM traces").fetchone()[0], 0
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM trace_spool").fetchone()[0], 1
            )

    def test_trace_id_conflict_is_rejected_without_overwriting_prior_trace(self):
        self.service.record(trace_request())
        with self.assertRaises(BridgeError) as caught:
            self.service.record(trace_request(run_id="DIFFERENT-RUN"))
        self.assertEqual(caught.exception.code, "trace_id_conflict")
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            self.assertEqual(
                connection.execute("SELECT run_id FROM traces").fetchall(),
                [("RUN-240",)],
            )
        repeated = self.service.record(trace_request())
        self.assertTrue(repeated["idempotent_existing"])

    def test_sampling_does_not_hide_existing_identity_conflict(self):
        self.service.record(trace_request())
        with self.assertRaises(BridgeError) as caught:
            self.service.record(
                trace_request(run_id="DIFFERENT", sampling_decision="drop")
            )
        self.assertEqual(caught.exception.code, "trace_id_conflict")

    def test_expiry_does_not_discard_conflicting_spool(self):
        self.service.record(trace_request(collector_available=False))
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            envelope = json.loads(
                connection.execute("SELECT envelope_json FROM trace_spool").fetchone()[
                    0
                ]
            )
            redacted = envelope.pop("redacted_field_count")
            envelope["run_id"] = "DIFFERENT"
            self.service._insert_trace(connection, envelope, redacted)
            connection.execute(
                "UPDATE trace_spool SET expires_at='2000-01-01T00:00:00Z'"
            )
        result = self.service.reconcile(
            {"schema_version": 1, "collector_available": True}
        )
        self.assertEqual(result["expired_count"], 0)
        self.assertEqual(result["conflicting_trace_ids"], ["TRACE-240"])
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM trace_spool").fetchone()[0], 1
            )

        self.service.record(trace_request(trace_id="NEW", collector_available=False))
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            self.assertEqual(
                connection.execute(
                    "SELECT trace_id FROM trace_spool ORDER BY trace_id"
                ).fetchall(),
                [("NEW",), ("TRACE-240",)],
            )

    def test_spool_identity_conflict_and_full_queue_duplicate(self):
        request = trace_request(collector_available=False)
        self.service.record(request)
        with patch("hermes_foundation_bridge.observability.SPOOL_LIMIT", 1):
            self.assertTrue(self.service.record(request)["idempotent_existing"])
            with self.assertRaises(BridgeError) as caught:
                self.service.record(
                    trace_request(collector_available=False, trace_id="NEW")
                )
            self.assertEqual(caught.exception.code, "trace_spool_full")
        for available in (False, True):
            with self.assertRaises(BridgeError) as caught:
                self.service.record(
                    trace_request(collector_available=available, run_id="DIFFERENT-RUN")
                )
            self.assertEqual(caught.exception.code, "trace_id_conflict")

    def test_reconciliation_retains_conflict_and_continues_valid_records(self):
        request = trace_request(collector_available=False)
        self.service.record(request)
        self.service.record(trace_request(trace_id="OTHER", collector_available=False))
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            envelope = json.loads(
                connection.execute(
                    "SELECT envelope_json FROM trace_spool WHERE trace_id=?",
                    (request["trace_id"],),
                ).fetchone()[0]
            )
            envelope["run_id"] = "DIFFERENT-RUN"
            redacted = envelope.pop("redacted_field_count")
            self.service._insert_trace(connection, envelope, redacted)
        result = self.service.reconcile(
            {"schema_version": 1, "collector_available": True}
        )
        self.assertEqual(result["conflicting_trace_ids"], [request["trace_id"]])
        self.assertEqual(result["moved_count"], 1)
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            self.assertEqual(
                connection.execute("SELECT trace_id FROM trace_spool").fetchall(),
                [(request["trace_id"],)],
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM traces").fetchone()[0], 2
            )
        self.assertEqual(
            self.service.health({"schema_version": 1})["status"], "degraded"
        )

    def test_recovery_to_available_removes_identical_spool_entry(self):
        self.service.record(trace_request(collector_available=False))
        self.service.record(trace_request())
        repeated = self.service.record(trace_request(collector_available=False))
        self.assertTrue(repeated["idempotent_existing"])
        self.assertEqual(repeated["status"], "recorded")
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM trace_spool").fetchone()[0], 0
            )

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "foundation"
        self.service = ObservabilityService(self.root)
        self.service.migrate({"schema_version": 1, "apply": True})

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_upgrade_adds_hook_queue_without_changing_traces_or_spool(self):
        self.service.record(trace_request(trace_id="KEPT-TRACE"))
        self.service.record(
            trace_request(trace_id="KEPT-SPOOL", collector_available=False)
        )
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            connection.execute("DROP TABLE hook_queue")
            before = {
                table: connection.execute(
                    f"SELECT * FROM {table} ORDER BY trace_id"
                ).fetchall()
                for table in ("traces", "trace_spool")
            }
        self.assertEqual(
            self.service.health({"schema_version": 1})["status"], "blocked"
        )
        self.service.migrate({"schema_version": 1, "apply": True})
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            after = {
                table: connection.execute(
                    f"SELECT * FROM {table} ORDER BY trace_id"
                ).fetchall()
                for table in ("traces", "trace_spool")
            }
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM hook_queue").fetchone()[0], 0
            )
        self.assertEqual(before, after)
        self.assertEqual(
            self.service.health({"schema_version": 1})["status"], "degraded"
        )

    def test_tc240_complete_trace_without_content_payload(self) -> None:
        result = self.service.record(trace_request())
        self.assertEqual(result["status"], "recorded")
        self.assertFalse(result["content_payload_persisted"])
        self.assertTrue(result["evidence_eligible"])
        health = self.service.health({"schema_version": 1})
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["published_endpoints"], [])

    def test_tc241_canary_pii_url_and_header_are_never_persisted(self) -> None:
        canaries = [
            "Bearer CANARY-TOKEN",
            "person@example.test",
            "https://example.test/file?signature=CANARY",
            "api_key=CANARY",
        ]
        result = self.service.record(
            trace_request(
                trace_id="TRACE-241",
                attributes={
                    "authorization_header": canaries[0],
                    "owner": canaries[1],
                    "signed_url": canaries[2],
                    "note": canaries[3],
                },
            )
        )
        self.assertEqual(result["redacted_field_count"], 4)
        database_bytes = self.service.database.read_bytes()
        for canary in canaries:
            self.assertNotIn(canary.encode(), database_bytes)

    def test_tc242_collector_down_spools_with_ttl_then_reconciles(self) -> None:
        result = self.service.record(
            trace_request(
                trace_id="TRACE-242",
                collector_available=False,
                evidence_link_refs=[],
            )
        )
        self.assertEqual(result["status"], "observability_degraded")
        self.assertEqual(result["spool_ttl_seconds"], 300)
        reconciled = self.service.reconcile(
            {"schema_version": 1, "collector_available": True}
        )
        self.assertEqual(reconciled["moved_count"], 1)

    def test_tc243_p0_and_unknown_spans_survive_drop_sampling(self) -> None:
        p0 = self.service.record(
            trace_request(
                trace_id="TRACE-243-P0",
                priority="P0",
                sampling_decision="drop",
            )
        )
        unknown = self.service.record(
            trace_request(
                trace_id="TRACE-243-UNKNOWN",
                outcome_status="unknown",
                sampling_decision="drop",
            )
        )
        ordinary = self.service.record(
            trace_request(
                trace_id="TRACE-243-P2",
                priority="P2",
                sampling_decision="drop",
            )
        )
        self.assertTrue(p0["mandatory_span_retained"])
        self.assertTrue(unknown["mandatory_span_retained"])
        self.assertEqual(ordinary["status"], "sampled_out")

    def test_tc244_tool_success_without_evidence_link_is_not_evidence(self) -> None:
        result = self.service.record(
            trace_request(trace_id="TRACE-244", evidence_link_refs=[])
        )
        self.assertFalse(result["evidence_eligible"])
        self.assertFalse(result["tool_success_is_evidence"])
        connection = sqlite3.connect(self.service.database)
        try:
            value = connection.execute(
                "SELECT evidence_eligible FROM traces WHERE trace_id='TRACE-244'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(value, 0)


if __name__ == "__main__":
    unittest.main()
