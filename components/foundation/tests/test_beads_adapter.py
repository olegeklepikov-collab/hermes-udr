from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_foundation_bridge.beads_adapter import BeadsAdapter
from hermes_foundation_bridge.errors import BridgeError


class FakeBeadsAdapter(BeadsAdapter):
    def __init__(self, root: Path):
        super().__init__(root)
        self.rows: dict[str, dict] = {}

    def _run(self, arguments: list[str], *, actor: str = "foundation-bridge") -> object:
        command = arguments[0]
        if command == "status":
            statuses = [row["status"] for row in self.rows.values()]
            return {
                "summary": {
                    "total_issues": len(statuses),
                    "open_issues": statuses.count("open"),
                    "in_progress_issues": statuses.count("in_progress"),
                    "closed_issues": statuses.count("closed"),
                }
            }
        if command == "create":
            issue_id = f"KWF-{len(self.rows) + 1}"
            row = {
                "id": issue_id,
                "status": "open",
                "priority": int(arguments[arguments.index("--priority") + 1][1:]),
                "issue_type": arguments[arguments.index("--type") + 1],
                "assignee": None,
            }
            self.rows[issue_id] = row
            return row
        issue_id = arguments[1]
        row = self.rows[issue_id]
        if command == "show":
            return [row]
        if command == "update":
            if row["assignee"] not in {None, actor}:
                raise BridgeError(
                    "beads_operation_failed",
                    "runtime.beads",
                    "Операция Beads отклонена.",
                )
            row["status"] = "in_progress"
            row["assignee"] = actor
            return [row]
        if command == "close":
            row["status"] = "closed"
            return [row]
        raise AssertionError(command)


class BeadsAdapterTests(unittest.TestCase):
    def test_cli_pins_own_database_even_with_foreign_environment(self):
        import os
        from types import SimpleNamespace
        from unittest.mock import patch

        adapter = BeadsAdapter(self.adapter.foundation)
        with (
            patch.dict(os.environ, {"BEADS_DIR": "/unrelated/.beads"}),
            patch(
                "hermes_foundation_bridge.beads_adapter.shutil.which",
                return_value="/bin/bd",
            ),
            patch("hermes_foundation_bridge.beads_adapter.subprocess.run") as command,
        ):
            command.return_value = SimpleNamespace(returncode=0, stdout="{}")
            adapter._run(["status"])
        self.assertEqual(
            command.call_args.kwargs["env"]["BEADS_DIR"], str(adapter.root / ".beads")
        )

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.adapter = FakeBeadsAdapter(Path(self.directory.name) / "foundation")
        self.adapter.root.mkdir(parents=True)
        (self.adapter.root / ".beads").mkdir()
        self.adapter.migrate({"schema_version": 1, "apply": True})

    def tearDown(self) -> None:
        self.directory.cleanup()

    def create(self) -> str:
        result = self.adapter.create(
            {
                "schema_version": 1,
                "title": "Bounded work",
                "description": "New foundation work item.",
                "priority": 1,
                "issue_type": "task",
            }
        )
        return result["issue_id"]

    def test_create_reply_loss_preserves_one_effect_across_adapter_restart(
        self,
    ) -> None:
        request = {
            "schema_version": 1,
            "title": "Control",
            "description": "Known synthetic request",
            "priority": 1,
            "issue_type": "task",
        }
        original = self.adapter._run

        def lose_reply(arguments, **kwargs):
            result = original(arguments, **kwargs)
            if arguments[0] == "create":
                raise BridgeError(
                    "beads_operation_failed",
                    "runtime.beads",
                    "Response lost after acceptance",
                )
            return result

        self.adapter._run = lose_reply
        first = self.adapter.create(request)
        self.assertEqual(first["status"], "unknown_outcome")
        restarted = FakeBeadsAdapter(self.adapter.foundation)
        restarted.rows = self.adapter.rows
        second = restarted.create(request)
        self.assertEqual(second["status"], "unknown_outcome")
        self.assertTrue(second["requires_reconciliation"])
        self.assertEqual(len(restarted.rows), 1)

    def test_claim_and_close_reply_loss_are_not_repeated(self) -> None:
        for method, command in (("claim", "update"), ("close", "close")):
            with self.subTest(method=method):
                request = {
                    "schema_version": 1,
                    "title": method,
                    "description": "Synthetic fault case",
                    "priority": 1,
                    "issue_type": "task",
                }
                issue = self.adapter.create(request)["issue_id"]
                action = {
                    "schema_version": 1,
                    "issue_id": issue,
                    "worker_id": "WORKER-A",
                }
                if method == "close":
                    action["reason_code"] = "COMPLETE"
                original = self.adapter._run
                calls = []

                def lose_reply(
                    arguments, original=original, command=command, calls=calls, **kwargs
                ):
                    result = original(arguments, **kwargs)
                    if arguments[0] == command:
                        calls.append(command)
                        raise BridgeError(
                            "beads_operation_failed", "runtime.beads", "Lost reply"
                        )
                    return result

                self.adapter._run = lose_reply
                try:
                    result = getattr(self.adapter, method)(action)
                    self.assertEqual(result["status"], "unknown_outcome")
                    restarted = FakeBeadsAdapter(self.adapter.foundation)
                    restarted.rows = self.adapter.rows
                    restarted._run = lose_reply
                    retried = getattr(restarted, method)(action)
                    self.assertEqual(retried["status"], "unknown_outcome")
                    self.assertEqual(calls, [command])
                finally:
                    self.adapter._run = original

    def test_explicit_new_operation_can_create_identical_work(self) -> None:
        request = {
            "schema_version": 1,
            "title": "Control",
            "description": "Known synthetic request",
            "priority": 1,
            "issue_type": "task",
        }
        first = self.adapter.create(request)
        replay = self.adapter.create(request)
        self.assertEqual(replay["status"], "already_succeeded")
        self.assertFalse(replay["current_readback_verified"])
        second = self.adapter.create({**request, "operation_key": "NEW-INTENT"})
        self.assertNotEqual(first["issue_id"], second["issue_id"])
        self.assertEqual(len(self.adapter.rows), 2)

    def test_create_claim_single_owner_close_and_read(self) -> None:
        issue_id = self.create()
        claimed = self.adapter.claim(
            {"schema_version": 1, "issue_id": issue_id, "worker_id": "WORKER-A"}
        )
        rejected = self.adapter.claim(
            {"schema_version": 1, "issue_id": issue_id, "worker_id": "WORKER-B"}
        )
        self.assertEqual(rejected["status"], "unknown_outcome")
        self.assertEqual(self.adapter.rows[issue_id]["assignee"], "WORKER-A")
        closed = self.adapter.close(
            {
                "schema_version": 1,
                "issue_id": issue_id,
                "worker_id": "WORKER-A",
                "reason_code": "COMPLETE",
            }
        )
        self.assertEqual(claimed["work_status"], "in_progress")
        self.assertEqual(closed["work_status"], "closed")
        self.assertFalse(closed["acceptance_created"])
        self.assertFalse(closed["release_allowed"])

    def test_real_work_status_drives_reconciliation(self) -> None:
        issue_id = self.create()
        self.adapter.claim(
            {"schema_version": 1, "issue_id": issue_id, "worker_id": "WORKER-A"}
        )
        running = self.adapter.reconcile(
            {
                "schema_version": 1,
                "issue_id": issue_id,
                "lease_status": "active",
                "artifact_status": "draft",
                "review_status": "absent",
                "dolt_commit_ref": None,
                "outbox_status": "pending",
                "writer_count": 1,
                "expected_revision": 1,
                "current_revision": 1,
            }
        )
        self.assertEqual(running["computed_state"], "running")
        self.adapter.close(
            {
                "schema_version": 1,
                "issue_id": issue_id,
                "worker_id": "WORKER-A",
                "reason_code": "COMPLETE",
            }
        )
        inconsistent = self.adapter.reconcile(
            {
                "schema_version": 1,
                "issue_id": issue_id,
                "lease_status": "active",
                "artifact_status": "draft",
                "review_status": "absent",
                "dolt_commit_ref": None,
                "outbox_status": "pending",
                "writer_count": 1,
                "expected_revision": 1,
                "current_revision": 1,
            }
        )
        self.assertIn("inconsistent_lease", inconsistent["issues"])
        self.assertFalse(inconsistent["release_allowed"])

    def test_secret_like_description_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "секрет"):
            self.adapter.create(
                {
                    "schema_version": 1,
                    "title": "Bad work",
                    "description": "api_key=must-not-enter",
                    "priority": 1,
                    "issue_type": "task",
                }
            )


if __name__ == "__main__":
    unittest.main()
