from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from hermes_foundation_bridge.agentmemory_adapter import AgentMemoryAdapter


class FakeAgentMemoryAdapter(AgentMemoryAdapter):
    def __init__(self, root: Path):
        super().__init__(root)
        self.memories: list[dict] = []

    def _invoke(self, operation: str, payload: dict | None = None) -> dict:
        data = payload or {}
        if operation == "version":
            return {
                "status": "available",
                "version": "0.9.29",
                "engine_version": "0.11.2",
            }
        if operation == "health":
            return {"status": "healthy", "result": {}}
        if operation == "save":
            memory = {
                "id": f"MEM-{len(self.memories) + 1}",
                "agentId": data["agentId"],
                "project": data["project"],
                "content": data["content"],
                "createdAt": datetime.now(UTC).isoformat(),
            }
            self.memories.append(memory)
            return {"status": "saved", "result": {"memory": memory}}
        if operation == "search":
            rows = []
            for memory in self.memories:
                if (
                    memory["agentId"] == data["agentId"]
                    and memory["project"] == data["project"]
                    and data["query"].lower() in memory["content"].lower()
                ):
                    rows.append(
                        {
                            "observation": {
                                "id": memory["id"],
                                "agentId": memory["agentId"],
                                "title": memory["content"],
                                "timestamp": memory["createdAt"],
                            },
                            "score": 1.0,
                        }
                    )
            return {"status": "queried", "result": {"results": rows[: data["limit"]]}}
        raise AssertionError(operation)


class AgentMemoryAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.adapter = FakeAgentMemoryAdapter(Path(self.directory.name) / "foundation")
        self.adapter.migrate({"schema_version": 1, "apply": True})
        self.scope = {
            "tenant_id": "TENANT-1",
            "project_id": "PROJECT-1",
            "profile_id": "PROFILE-1",
            "work_kind": "KNOWLEDGE",
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_save_search_context_and_scope_isolation(self) -> None:
        saved = self.adapter.save(
            {
                "schema_version": 1,
                "scope": self.scope,
                "content": "bounded memory fact",
                "concepts": ["fixture"],
            }
        )
        found = self.adapter.search(
            {
                "schema_version": 1,
                "scope": self.scope,
                "query": "memory fact",
                "limit": 5,
            }
        )
        other_scope = {**self.scope, "project_id": "PROJECT-2"}
        hidden = self.adapter.search(
            {
                "schema_version": 1,
                "scope": other_scope,
                "query": "memory fact",
                "limit": 5,
            }
        )
        context = self.adapter.context(
            {
                "schema_version": 1,
                "scope": self.scope,
                "query": "memory fact",
                "limit": 5,
            }
        )
        self.assertEqual(saved["status"], "saved")
        self.assertTrue(saved["readback_verified"])
        self.assertFalse(saved["content_recorded_in_receipt"])
        self.assertEqual(found["result_count"], 1)
        self.assertEqual(hidden["result_count"], 0)
        self.assertEqual(context["contribution_count"], 1)
        self.assertFalse(context["evidence_record_created"])

    def test_default_scope_roundtrip(self) -> None:
        result = self.adapter.set_default_scope(
            {"schema_version": 1, "scope": self.scope}
        )
        self.assertEqual(result["status"], "configured")
        self.assertEqual(self.adapter.default_scope(), self.scope)

    def test_secret_like_content_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "секрет"):
            self.adapter.save(
                {
                    "schema_version": 1,
                    "scope": self.scope,
                    "content": "Authorization: Bearer hidden",
                    "concepts": [],
                }
            )


if __name__ == "__main__":
    unittest.main()
