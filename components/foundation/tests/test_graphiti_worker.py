"""Fixed Neo4j queries and parameter placement against the pinned driver contract."""

from __future__ import annotations

import runpy
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class Result:
    def __init__(self, records):
        self.records = records


class FakeNeo4jDriver:
    calls: list[tuple[str, dict]] = []
    credentials: dict = {}

    def __init__(self, **kwargs):
        self.credentials = kwargs
        FakeNeo4jDriver.credentials = kwargs

    async def health_check(self):
        return None

    async def execute_query(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if "dbms.components" in query:
            return Result([{"version": "5.26.31"}])
        if "RETURN f.fact_id AS fact_id, f.text_hash" in query:
            return Result([{"fact_id": "F", "text_hash": "a" * 64, "active": True}])
        if "deactivated_count" in query:
            return Result([{"deactivated_count": 1}])
        return Result([])

    async def close(self):
        return None


class GraphitiWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.secret = Path(self.temp.name) / "password"
        self.secret.write_text("local-test-password\n")
        self.connection = {
            "neo4j_uri": "bolt://127.0.0.1:7687", "neo4j_user": "neo4j",
            "neo4j_password_file": str(self.secret),
        }
        fake_module = types.ModuleType("graphiti_core.driver.neo4j_driver")
        fake_module.Neo4jDriver = FakeNeo4jDriver
        worker = Path(__file__).resolve().parents[1] / "src/hermes_foundation_bridge/graphiti_worker.py"
        with patch.dict("sys.modules", {
            "graphiti_core": types.ModuleType("graphiti_core"),
            "graphiti_core.driver": types.ModuleType("graphiti_core.driver"),
            "graphiti_core.driver.neo4j_driver": fake_module,
        }):
            self.run = runpy.run_path(str(worker))["run"]
        FakeNeo4jDriver.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def call(self, operation, payload=None):
        return self.run({"operation": operation, "payload": payload or {}, "connection": self.connection})

    def test_health_and_fixed_parameterized_lifecycle(self):
        with patch("importlib.metadata.version", return_value="0.30.2"):
            health = self.call("health")
        self.assertEqual(health["neo4j_version"], "5.26.31")
        self.assertEqual(FakeNeo4jDriver.credentials["password"], "local-test-password")
        self.assertEqual(self.call("migrate")["status"], "applied")
        payload = {
            "project_id": "P", "fact_id": "F", "text": "fact", "text_hash": "a" * 64,
            "source_ref": "originals/ref", "artifact_id": "A",
        }
        self.assertEqual(self.call("put_fact", payload)["rows"][0]["fact_id"], "F")
        self.call("search", {"project_id": "P", "query": "fact", "limit": 5})
        self.assertEqual(self.call("tombstone", {"artifact_id": "A"})["deactivated_count"], 1)
        for query, kwargs in FakeNeo4jDriver.calls:
            if "$" in query:
                self.assertEqual(set(kwargs), {"params"})
        self.assertTrue(any("REQUIRE f.key IS UNIQUE" in query for query, _ in FakeNeo4jDriver.calls))

    def test_rejects_arbitrary_query_operation_before_secret_access(self):
        self.secret.unlink()
        with self.assertRaisesRegex(ValueError, "unsupported_operation"):
            self.call("query", {"cypher": "MATCH (n) RETURN n"})


if __name__ == "__main__":
    unittest.main()
