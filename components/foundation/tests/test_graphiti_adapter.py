from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from hermes_foundation_bridge.graphiti_adapter import GraphitiAdapter
from tests.common import native_runtime_fixture


class FakeGraphitiAdapter(GraphitiAdapter):
    def __init__(self, root: Path):
        super().__init__(root)
        self.rows: dict[str, dict] = {}

    def _invoke(self, operation: str, payload: dict | None = None) -> dict:
        data = payload or {}
        if operation in {"versions", "health"}:
            return {
                "status": "healthy" if operation == "health" else "available",
                "graphiti_version": "0.30.2",
                "neo4j_version": "5.26.31",
            }
        if operation == "migrate":
            return {"status": "applied"}
        if operation == "put_fact":
            self.rows[data["fact_id"]] = {**data, "active": True}
            return {
                "status": "written",
                "rows": [
                    {
                        "fact_id": data["fact_id"],
                        "text_hash": data["text_hash"],
                        "active": True,
                    }
                ],
            }
        if operation == "search":
            rows = [
                row
                for row in self.rows.values()
                if row["project_id"] == data["project_id"]
                and row["active"]
                and data["query"].lower() in row["text"].lower()
            ]
            return {"status": "queried", "rows": rows[: data["limit"]]}
        if operation == "tombstone":
            count = 0
            for row in self.rows.values():
                if row["artifact_id"] == data["artifact_id"] and row["active"]:
                    row["active"] = False
                    count += 1
            return {"status": "propagated", "deactivated_count": count}
        raise AssertionError(operation)


class GraphitiAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.adapter = FakeGraphitiAdapter(Path(self.directory.name) / "foundation")
        native_runtime_fixture(self.adapter.foundation)
        self.adapter.migrate({"schema_version": 1, "apply": True})

    def tearDown(self) -> None:
        self.directory.cleanup()

    def request(self, text: str = "temporal graph fact") -> dict:
        return {
            "schema_version": 1,
            "project_id": "PROJECT-1",
            "fact_id": "FACT-1",
            "text": text,
            "text_hash": hashlib.sha256(text.encode()).hexdigest(),
            "source_ref": "originals/abc",
            "artifact_id": "ART-1",
        }

    def test_typed_write_search_and_tombstone(self) -> None:
        written = self.adapter.put_fact(self.request())
        found = self.adapter.search(
            {
                "schema_version": 1,
                "project_id": "PROJECT-1",
                "query": "graph fact",
                "limit": 5,
            }
        )
        tombstone = self.adapter.tombstone_request(
            {"schema_version": 1, "artifact_id": "ART-1"}
        )
        hidden = self.adapter.search(
            {
                "schema_version": 1,
                "project_id": "PROJECT-1",
                "query": "graph fact",
                "limit": 5,
            }
        )
        self.assertEqual(written["status"], "written")
        self.assertEqual(found["result_count"], 1)
        self.assertEqual(tombstone["deactivated_count"], 1)
        self.assertEqual(hidden["result_count"], 0)

    def test_secret_like_text_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "секрет"):
            self.adapter.put_fact(self.request("Authorization: Bearer hidden"))

    def test_health_exposes_no_raw_or_admin_operations(self) -> None:
        result = self.adapter.health({"schema_version": 1})
        self.assertEqual(result["status"], "healthy")
        self.assertFalse(result["raw_query_exposed"])
        self.assertFalse(result["admin_operations_exposed"])

    def test_five_failures_open_circuit_and_success_resets_generation(self) -> None:
        for _ in range(5):
            state = self.adapter._record_failure()
        self.assertEqual(state["state"], "open")
        circuit = self.adapter.circuit_status({"schema_version": 1})
        self.assertEqual(circuit["status"], "open")
        self.assertFalse(circuit["routing_allowed"])
        reset = self.adapter._record_success()
        self.assertEqual(reset["state"], "closed")
        self.assertEqual(reset["failure_count"], 0)
        self.assertEqual(reset["generation"], 1)


if __name__ == "__main__":
    unittest.main()
