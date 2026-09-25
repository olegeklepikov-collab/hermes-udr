from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from hermes_foundation_bridge.bridge import post_tool_call
from hermes_foundation_bridge.hook_queue import HookQueue
from hermes_foundation_bridge.observability import ObservabilityService
from hermes_foundation_bridge.runtime import RuntimeCoordinator
from tests.common import fragment_request
from tests.test_observability import trace_request


class HookQueueTests(unittest.TestCase):
    def test_admission_retries_transient_collector_lock_without_losing_event(self):
        locked = threading.Event()

        def hold():
            with closing(sqlite3.connect(self.queue.database)) as db:
                db.execute("BEGIN IMMEDIATE")
                locked.set()
                time.sleep(0.09)
                db.rollback()

        thread = threading.Thread(target=hold)
        thread.start()
        self.assertTrue(locked.wait(2))
        try:
            with patch.dict(os.environ, {"HERMES_FOUNDATION_ROOT": str(self.root)}):
                post_tool_call(**self.payload())
        finally:
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.runtime.health()["counts"]["hook_events"], 1)
        self.assertEqual(self.runtime.health()["counts"]["found_fragments"], 1)
        self.assertEqual(self.queue.health()["pending"], 0)

    def test_additive_queue_migration_preserves_previous_traces(self):
        observer = ObservabilityService(self.root)
        observer.record(trace_request())
        with closing(sqlite3.connect(self.queue.database)) as db:
            db.execute("DROP TABLE hook_queue")
            db.commit()
            before = db.execute("SELECT * FROM traces").fetchall()
        self.assertFalse(observer.health({"schema_version": 1})["hook_queue_ready"])
        observer.migrate({"schema_version": 1, "apply": True})
        observer.migrate({"schema_version": 1, "apply": True})
        with closing(sqlite3.connect(self.queue.database)) as db:
            self.assertEqual(db.execute("SELECT * FROM traces").fetchall(), before)
        self.assertEqual(observer.health({"schema_version": 1})["status"], "healthy")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "foundation"
        self.runtime = RuntimeCoordinator(self.root)
        self.runtime.migration_receipt(apply=True)
        ObservabilityService(self.root).migrate({"schema_version": 1, "apply": True})
        self.queue = HookQueue(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, session="S-1", fragment="F-1"):
        value = fragment_request("source-text-canary")
        value["fragment"]["fragment_id"] = fragment
        return {
            "session_id": session,
            "tool_call_id": "T-1",
            "result": json.dumps(
                {"foundation_fragment": value["fragment"], "other": "secret-canary"}
            ),
        }

    def run_worker(self, code):
        return subprocess.run(
            [sys.executable, "-c", code, str(self.root)],
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            },
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def test_locked_runtime_defers_without_source_text_and_new_process_replays(self):
        lock = sqlite3.connect(self.runtime.database)
        lock.execute("BEGIN IMMEDIATE")
        try:
            with patch.dict(os.environ, {"HERMES_FOUNDATION_ROOT": str(self.root)}):
                started = time.monotonic()
                post_tool_call(**self.payload())
                elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.5)
            self.assertEqual(self.queue.health()["pending"], 1)
            with closing(sqlite3.connect(self.queue.database)) as db:
                payload = db.execute("SELECT envelope_json FROM hook_queue").fetchone()[
                    0
                ]
            self.assertNotIn("source-text-canary", payload)
            self.assertNotIn("secret-canary", payload)
            self.assertNotIn("retrieval_query", payload)
        finally:
            lock.rollback()
            lock.close()
        worker = self.run_worker(
            "from pathlib import Path;import sys;from hermes_foundation_bridge.hook_queue import HookQueue;q=HookQueue(Path(sys.argv[1]));assert q.drain()['applied']==1;assert q.health()['pending']==0"
        )
        self.assertEqual(worker.returncode, 0, worker.stderr)
        self.assertEqual(self.runtime.health()["counts"]["found_fragments"], 1)
        self.assertEqual(self.runtime.health()["counts"]["hook_events"], 1)

    def test_crash_after_hook_commit_keeps_queue_until_idempotent_replay(self):
        self.queue.submit("post_tool_call", self.payload())
        worker = self.run_worker("""
from pathlib import Path
import sys,os
from hermes_foundation_bridge.hook_queue import HookQueue
from hermes_foundation_bridge.runtime import RuntimeCoordinator
original=RuntimeCoordinator.record_hook
def crash(self,*args):
    original(self,*args)
    os._exit(73)
RuntimeCoordinator.record_hook=crash
HookQueue(Path(sys.argv[1])).drain()
""")
        self.assertEqual(worker.returncode, 73)
        self.assertEqual(self.queue.health()["pending"], 1)
        self.assertEqual(self.queue.drain()["applied"], 1)
        self.assertEqual(self.runtime.health()["counts"]["hook_events"], 1)
        self.assertEqual(self.runtime.health()["counts"]["found_fragments"], 1)

    def test_local_tool_identifiers_do_not_collide_across_sessions(self):
        for session, fragment in (("A", "F-A"), ("B", "F-B")):
            self.queue.submit("post_tool_call", self.payload(session, fragment))
            self.queue.drain()
        self.assertEqual(self.runtime.health()["counts"]["found_fragments"], 2)

    def test_crash_after_fragment_commit_does_not_repeat_registration(self):
        self.queue.submit("post_tool_call", self.payload())
        worker = self.run_worker("""
from pathlib import Path
import sys,os
import hermes_foundation_bridge.hook_queue as module
original=module.record_prepared_fragment
def crash(*args):
    original(*args)
    os._exit(73)
module.record_prepared_fragment=crash
module.HookQueue(Path(sys.argv[1])).drain()
""")
        self.assertEqual(worker.returncode, 73)
        self.assertEqual(self.queue.health()["pending"], 1)
        self.assertEqual(self.queue.drain()["applied"], 1)
        self.assertEqual(self.runtime.health()["counts"]["hook_events"], 1)
        self.assertEqual(self.runtime.health()["counts"]["found_fragments"], 1)

    def test_modified_queue_envelope_is_quarantined_without_coordinator_write(self):
        self.queue.submit("post_tool_call", self.payload())
        with closing(sqlite3.connect(self.queue.database)) as db:
            db.execute("UPDATE hook_queue SET envelope_json='{}'")
            db.commit()
        self.assertEqual(self.queue.drain()["quarantined"], 1)
        self.assertEqual(self.runtime.health()["counts"]["hook_events"], 0)

    def test_overflow_explicit_and_duplicate_does_not_consume_capacity(self):
        with patch("hermes_foundation_bridge.hook_queue.QUEUE_LIMIT", 1):
            self.queue.submit("post_tool_call", self.payload())
            self.queue.submit("post_tool_call", self.payload())
            with self.assertRaisesRegex(ValueError, "hook_queue_full"):
                self.queue.submit("post_tool_call", self.payload("S-2", "F-2"))
        self.assertEqual(self.queue.health()["pending"], 1)

    def test_identity_conflict_is_preserved_and_does_not_block_following_event(self):
        self.queue.submit("on_session_start", {"session_id": "S", "status": "first"})
        self.queue.drain()
        self.queue.submit("on_session_start", {"session_id": "S", "status": "changed"})
        self.queue.submit("on_session_start", {"session_id": "NEXT"})
        result = self.queue.drain()
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(result["applied"], 1)
        self.assertEqual(self.queue.health()["quarantined"], 1)

    def test_collector_lock_is_bounded_and_callback_does_not_raise(self):
        lock = sqlite3.connect(self.queue.database)
        lock.execute("BEGIN IMMEDIATE")
        try:
            with patch.dict(os.environ, {"HERMES_FOUNDATION_ROOT": str(self.root)}):
                with self.assertLogs(
                    "hermes_foundation_bridge.bridge", level="WARNING"
                ) as log:
                    started = time.monotonic()
                    post_tool_call(**self.payload())
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertIn("foundation_hook_not_fully_persisted", str(log.output))
                self.assertNotIn("canary", str(log.output))
        finally:
            lock.rollback()
            lock.close()
        self.assertEqual(self.queue.health()["pending"], 0)

    def test_backup_contains_pending_metadata_and_can_replay(self):
        self.queue.submit("post_tool_call", self.payload())
        alternate = Path(self.temp.name) / "alternate"
        for source, target in (
            (self.runtime.database, alternate / "runtime/runtime.sqlite3"),
            (self.queue.database, alternate / "observability/collector.sqlite3"),
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            with (
                closing(sqlite3.connect(source)) as original,
                closing(sqlite3.connect(target)) as copy,
            ):
                original.backup(copy)
        restored = HookQueue(alternate)
        self.assertEqual(restored.health()["pending"], 1)
        self.assertEqual(restored.drain()["applied"], 1)
        self.assertEqual(
            RuntimeCoordinator(alternate).health()["counts"]["found_fragments"], 1
        )

    def test_full_queue_makes_progress_when_coordinator_recovers(self):
        with patch("hermes_foundation_bridge.hook_queue.QUEUE_LIMIT", 1):
            self.queue.submit("post_tool_call", self.payload())
            with patch.dict(os.environ, {"HERMES_FOUNDATION_ROOT": str(self.root)}):
                post_tool_call(**self.payload("S-2", "F-2"))
            self.assertEqual(self.queue.health()["pending"], 1)
            self.assertEqual(self.queue.drain()["applied"], 1)
        self.assertEqual(self.runtime.health()["counts"]["found_fragments"], 2)

    def test_invalid_fragment_retains_hook_and_exposes_registration_gap(self):
        payload = self.payload()
        payload["result"] = {"foundation_fragment": {"invalid": "secret-canary"}}
        with (
            patch.dict(os.environ, {"HERMES_FOUNDATION_ROOT": str(self.root)}),
            self.assertLogs("hermes_foundation_bridge.bridge", level="WARNING") as log,
        ):
            post_tool_call(**payload)
        self.assertIn("foundation_fragment_registration_incomplete", str(log.output))
        self.assertNotIn("canary", str(log.output))
        self.assertEqual(self.runtime.health()["counts"]["hook_events"], 1)
        self.assertEqual(self.runtime.health()["counts"]["found_fragments"], 0)

    def test_public_reconciliation_and_health_show_pending_and_quarantine(self):
        observer = ObservabilityService(self.root)
        self.queue.submit("post_tool_call", self.payload())
        before = observer.health({"schema_version": 1})
        self.assertEqual(before["status"], "degraded")
        self.assertEqual(before["hook_queue_pending"], 1)
        result = observer.reconcile({"schema_version": 1, "collector_available": True})
        self.assertEqual(result["hook_reconciliation"]["applied"], 1)
        self.assertEqual(result["hook_reconciliation"]["pending"], 0)
        self.assertEqual(observer.health({"schema_version": 1})["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
