"""Kill real callers around provider effects and prevent unsafe retries across processes."""

import json
import os
import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from hermes_foundation_bridge.canonical import receipt
from hermes_foundation_bridge.errors import BridgeError
from hermes_foundation_bridge.external_operations import guarded_external
from hermes_foundation_bridge.runtime import RuntimeCoordinator
from tests.common import native_runtime_fixture
from tests.test_agentmemory_adapter import FakeAgentMemoryAdapter
from tests.test_graphiti_adapter import FakeGraphitiAdapter

WORKER = r"""
import json,os,sys
from pathlib import Path
from hermes_foundation_bridge.canonical import receipt
from hermes_foundation_bridge.external_operations import guarded_external
from hermes_foundation_bridge.runtime import RuntimeCoordinator
root=Path(sys.argv[1]);point=sys.argv[2]
original=RuntimeCoordinator.finish_external
def finish(self,*args):
 original(self,*args)
 if point=='after_finish':os._exit(73)
RuntimeCoordinator.finish_external=finish
def effect():
 if point=='before_effect':os._exit(73)
 p=root/'provider-effects'
 with p.open('a') as f:f.write('effect\n');f.flush();os.fsync(f.fileno())
 if point=='after_effect':os._exit(73)
 return receipt({'status':'saved','readback_verified':True})
print(json.dumps(guarded_external(root,'memory',{'id':'same'},{'body':'same'},effect,{'saved'})))
"""


class ExternalOperationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        native_runtime_fixture(self.root)
        RuntimeCoordinator(self.root).migration_receipt(apply=True)

    def tearDown(self):
        self.directory.cleanup()

    def worker(self, point):
        return subprocess.run(
            [sys.executable, "-B", "-c", WORKER, str(self.root), point],
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )

    def test_crash_before_effect_blocks_retry_without_assuming_absence(self):
        self.assertEqual(self.worker("before_effect").returncode, 73)
        result = json.loads(self.worker("normal").stdout)
        self.assertEqual(result["status"], "unknown_outcome")
        self.assertTrue(result["requires_reconciliation"])
        self.assertFalse((self.root / "provider-effects").exists())

    def test_crash_after_effect_new_process_does_not_repeat(self):
        self.assertEqual(self.worker("after_effect").returncode, 73)
        result = json.loads(self.worker("normal").stdout)
        self.assertEqual(result["status"], "unknown_outcome")
        self.assertEqual((self.root / "provider-effects").read_text(), "effect\n")
        with closing(sqlite3.connect(self.root / "runtime/runtime.sqlite3")) as db, db:
            self.assertEqual(
                db.execute("SELECT status FROM operations").fetchone()[0], "unknown"
            )

    def test_crash_after_outcome_commit_replays_receipt_reference(self):
        self.assertEqual(self.worker("after_finish").returncode, 73)
        result = json.loads(self.worker("normal").stdout)
        self.assertEqual(result["status"], "already_succeeded")
        self.assertFalse(result["external_call_attempted"])
        self.assertEqual(len(result["previous_result_receipt_hash"]), 64)
        self.assertEqual((self.root / "provider-effects").read_text(), "effect\n")

    def test_unverified_reply_is_unknown_and_raw_response_is_not_persisted(self):
        calls = []

        def effect():
            calls.append(1)
            return receipt(
                {
                    "status": "blocked",
                    "readback_verified": False,
                    "provider_text": "PRIVATE-CONTROL-DO-NOT-PERSIST",
                }
            )

        for _ in range(2):
            result = guarded_external(
                self.root,
                "memory",
                {"id": "same"},
                {"text": "PRIVATE-INPUT-DO-NOT-PERSIST"},
                effect,
                {"saved"},
            )
            self.assertEqual(result["status"], "unknown_outcome")
        self.assertEqual(len(calls), 1)
        for p in (self.root / "runtime").glob("*"):
            if p.is_file():
                self.assertNotIn(b"PRIVATE-CONTROL", p.read_bytes())
                self.assertNotIn(b"PRIVATE-INPUT", p.read_bytes())

    def test_same_identity_changed_payload_is_rejected_before_effect(self):
        calls = []

        def effect():
            calls.append(1)
            return receipt({"status": "saved"})

        guarded_external(
            self.root, "memory", {"id": "same"}, {"value": 1}, effect, {"saved"}
        )
        with self.assertRaises(BridgeError) as error:
            guarded_external(
                self.root, "memory", {"id": "same"}, {"value": 2}, effect, {"saved"}
            )
        self.assertEqual(error.exception.code, "external_operation_conflict")
        self.assertEqual(len(calls), 1)

    def test_observed_success_cannot_be_downgraded_by_lost_commit_ack(self):
        coordinator = RuntimeCoordinator(self.root)
        claim = coordinator.begin_external("memory", "1" * 64, "2" * 64)
        coordinator.finish_external(claim["operation_id"], claim["owner"], "3" * 64)
        coordinator.finish_external(claim["operation_id"], claim["owner"], None)
        repeated = coordinator.begin_external("memory", "1" * 64, "2" * 64)
        self.assertEqual(repeated["status"], "already_succeeded")
        self.assertEqual(repeated["result_receipt_hash"], "3" * 64)
        with self.assertRaises(BridgeError):
            coordinator.finish_external(
                claim["operation_id"], "different-owner", "3" * 64
            )

    def test_malformed_result_is_unknown_without_a_second_effect(self):
        calls = []

        def effect():
            calls.append(1)
            return []

        for _ in range(2):
            result = guarded_external(
                self.root, "memory", "same", "same", effect, {"saved"}
            )
            self.assertEqual(result["status"], "unknown_outcome")
        self.assertEqual(len(calls), 1)

    def test_blocked_provider_echo_is_not_a_memory_success(self):
        class BlockedMemory(FakeAgentMemoryAdapter):
            def _invoke(self, operation, payload=None):
                result = super()._invoke(operation, payload)
                if operation == "save":
                    result["status"] = "blocked"
                return result

        adapter = BlockedMemory(self.root)
        adapter.migrate({"schema_version": 1, "apply": True})
        request = {
            "schema_version": 1,
            "scope": {
                "tenant_id": "T",
                "project_id": "P",
                "profile_id": "F",
                "work_kind": "CONTROL",
            },
            "content": "fact",
            "concepts": [],
        }
        for _ in range(2):
            self.assertEqual(adapter.save(request)["status"], "unknown_outcome")
        self.assertEqual(len(adapter.memories), 1)

    @staticmethod
    def graph_request(fact="F", artifact="A"):
        import hashlib

        return {
            "schema_version": 1,
            "project_id": "P",
            "fact_id": fact,
            "text": "fact",
            "text_hash": hashlib.sha256(b"fact").hexdigest(),
            "source_ref": "originals/control",
            "artifact_id": artifact,
        }

    def test_blocked_provider_echo_is_not_a_graph_success(self):
        class BlockedGraph(FakeGraphitiAdapter):
            calls = 0

            def _invoke(self, operation, payload=None):
                result = super()._invoke(operation, payload)
                if operation == "put_fact":
                    self.calls += 1
                    result["status"] = "blocked"
                return result

        adapter = BlockedGraph(self.root)
        adapter.migrate({"schema_version": 1, "apply": True})
        for _ in range(2):
            self.assertEqual(
                adapter.put_fact(self.graph_request())["status"], "unknown_outcome"
            )
        self.assertEqual(adapter.calls, 1)

    def test_tombstoned_artifact_is_terminal_but_new_artifact_is_writable(self):
        adapter = FakeGraphitiAdapter(self.root)
        adapter.migrate({"schema_version": 1, "apply": True})
        self.assertEqual(adapter.put_fact(self.graph_request())["status"], "written")
        self.assertEqual(adapter.tombstone("A")["status"], "propagated")
        with self.assertRaises(BridgeError) as error:
            adapter.put_fact(self.graph_request("NEW-F", "A"))
        self.assertEqual(error.exception.code, "graphiti_artifact_tombstoned")
        self.assertEqual(adapter.tombstone("A")["status"], "already_succeeded")
        self.assertFalse(adapter.rows["F"]["active"])
        self.assertNotIn("NEW-F", adapter.rows)
        self.assertEqual(
            adapter.put_fact(self.graph_request("NEW-F", "NEW-A"))["status"], "written"
        )

    def test_unknown_tombstone_also_blocks_new_facts(self):
        class LostReply(FakeGraphitiAdapter):
            def _invoke(self, operation, payload=None):
                result = super()._invoke(operation, payload)
                if operation == "tombstone":
                    raise OSError("lost provider response")
                return result

        adapter = LostReply(self.root)
        adapter.migrate({"schema_version": 1, "apply": True})
        adapter.put_fact(self.graph_request())
        self.assertEqual(adapter.tombstone("A")["status"], "unknown_outcome")
        with self.assertRaises(BridgeError) as error:
            adapter.put_fact(self.graph_request("NEW-F", "A"))
        self.assertEqual(error.exception.code, "graphiti_artifact_tombstoned")
        self.assertNotIn("NEW-F", adapter.rows)

    def test_delayed_unknown_put_prevents_false_tombstone_confirmation(self):
        release = threading.Event()
        complete = threading.Event()

        class DelayedGraph(FakeGraphitiAdapter):
            tombstone_calls = 0

            def _invoke(self, operation, payload=None):
                if operation == "put_fact":

                    def later():
                        if release.wait(5):
                            FakeGraphitiAdapter._invoke(self, operation, payload)
                        complete.set()

                    threading.Thread(target=later, daemon=True).start()
                    raise TimeoutError("remote worker continues")
                if operation == "tombstone":
                    self.tombstone_calls += 1
                return super()._invoke(operation, payload)

        adapter = DelayedGraph(self.root)
        adapter.migrate({"schema_version": 1, "apply": True})
        try:
            self.assertEqual(
                adapter.put_fact(self.graph_request())["status"], "unknown_outcome"
            )
            deletion = adapter.tombstone("A")
            self.assertEqual(deletion["status"], "unknown_outcome")
            self.assertIsNone(deletion["deletion_observed"])
            self.assertEqual(adapter.tombstone_calls, 0)
        finally:
            release.set()
            self.assertTrue(complete.wait(5))
        self.assertTrue(adapter.rows["F"]["active"])
        self.assertEqual(adapter.tombstone("A")["status"], "unknown_outcome")
        self.assertEqual(adapter.tombstone_calls, 0)

    def test_provider_control_string_cannot_become_memory_id(self):
        class MaliciousMemory(FakeAgentMemoryAdapter):
            def _invoke(self, operation, payload=None):
                result = super()._invoke(operation, payload)
                if operation == "save":
                    result["result"]["memory"]["id"] = "Bearer secret control text"
                return result

        adapter = MaliciousMemory(self.root)
        adapter.migrate({"schema_version": 1, "apply": True})
        request = {
            "schema_version": 1,
            "scope": {
                "tenant_id": "T",
                "project_id": "P",
                "profile_id": "F",
                "work_kind": "CONTROL",
            },
            "content": "one fact",
            "concepts": [],
        }
        for _ in range(2):
            result = adapter.save(request)
            self.assertEqual(result["status"], "unknown_outcome")
            self.assertNotIn("Bearer", json.dumps(result))
        self.assertEqual(len(adapter.memories), 1)

    def test_graph_wrong_fact_readback_cannot_succeed_or_retry(self):
        class WrongFact(FakeGraphitiAdapter):
            calls = 0

            def _invoke(self, operation, payload=None):
                result = super()._invoke(operation, payload)
                if operation == "put_fact":
                    self.calls += 1
                    result["rows"][0]["fact_id"] = "OTHER"
                return result

        import hashlib

        adapter = WrongFact(self.root)
        adapter.migrate({"schema_version": 1, "apply": True})
        request = {
            "schema_version": 1,
            "project_id": "P",
            "fact_id": "F",
            "text": "fact",
            "text_hash": hashlib.sha256(b"fact").hexdigest(),
            "source_ref": "originals/control",
            "artifact_id": "A",
        }
        for _ in range(2):
            self.assertEqual(adapter.put_fact(request)["status"], "unknown_outcome")
        self.assertEqual(adapter.calls, 1)


if __name__ == "__main__":
    unittest.main()
