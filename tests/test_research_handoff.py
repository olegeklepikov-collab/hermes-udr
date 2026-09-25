from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hermes_research_report.research_handoff import export_handoff
from hermes_research_report.research_journal import record
from hermes_research_report.research_workspace import finish, note, source, workspace


class ResearchHandoffTests(unittest.TestCase):
    def _finished_run(self):
        started = workspace({"action": "start", "question": "What changed?", "mode": "research"})
        run_id, root = started["run_id"], Path(started["root"])
        saved = source({"run_id": run_id, "url": "https://example.org/document",
                        "text": "Original research passage.", "extent": "excerpt"})
        note({"run_id": run_id, "text": "The source reports a change.",
              "source_ids": [saved["source_id"]]})
        workspace({"action": "plan", "run_id": run_id,
                   "plan": {"steps": [{"id": "step-1", "status": "done",
                                       "question": "What changed?", "method": "read",
                                       "output": "note"}]}})
        record({"run_id": run_id, "event": {"kind": "search", "exact_query": "change",
                                             "results": [saved["source_id"]]}})
        finish({"run_id": run_id, "report": f"A change was observed [{saved['source_id']}].",
                "status": "complete"})
        return run_id, root, saved

    def test_valid_draft_has_only_registered_files_and_verified_manifest(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"HERMES_HOME": directory}):
            run_id, root, saved = self._finished_run()
            (root / "materials" / f"{saved['source_id']}.provenance.json").write_text(json.dumps({
                "source_id": saved["source_id"], "origin_ref": "local-original-ref",
                "parse_receipt_ref": "local-parse-ref", "content_sha256": saved["sha256"],
            }))
            (root / "workspace").mkdir()
            (root / "workspace" / "jolts_method.md").write_text("Registered method output")
            workspace({"action": "plan", "run_id": run_id,
                       "plan": {"steps": [{"id": "step-1",
                                           "result_paths": ["workspace/jolts_method.md", "workspace/jolts_method.md"]}]}})
            raw = b"<html>Original response</html>"
            completed = root / "retrievals" / ("a" * 32)
            completed.mkdir(parents=True)
            (completed / "original.bin").write_bytes(raw)
            (completed / "metadata.json").write_text(json.dumps({
                "status": "full_text_registered", "source_id": saved["source_id"],
                "original_path": str(completed / "original.bin"),
                "original_sha256": hashlib.sha256(raw).hexdigest(),
                "text_sha256": saved["sha256"],
            }))
            inflight = root / "retrievals" / ("b" * 32)
            inflight.mkdir()
            (inflight / "original.bin").write_bytes(b"unfinished")
            (root / "provider-calls").mkdir()
            (root / "provider-calls" / "response.json").write_text("private response")

            exported = export_handoff({"run_id": run_id})
            package = Path(exported["root"])
            manifest_bytes = (package / "manifest.json").read_bytes()
            manifest = json.loads(manifest_bytes)
            self.assertEqual(exported["manifest_sha256"], hashlib.sha256(manifest_bytes).hexdigest())
            self.assertEqual(manifest["submission_status"], "unsubmitted")
            self.assertEqual(manifest["acceptance_status"], "acceptance_not_requested")
            self.assertFalse(manifest["production_qualified"])
            self.assertTrue(exported["host_intake_required"])
            self.assertEqual(manifest["status"], "result_draft")
            self.assertEqual(manifest["contract"], "ResearchHandoffV1")
            self.assertTrue(manifest["host_rehash_required"])
            self.assertEqual(manifest["omitted_unregistered_retrieval_count"], 1)
            names = {row["path"] for row in manifest["files"]}
            self.assertIn("records/journal.json", names)
            self.assertIn("records/plans.json", names)
            self.assertIn("workspace/jolts_method.md", names)
            self.assertEqual(sum(row["path"] == "workspace/jolts_method.md" for row in manifest["files"]), 1)
            self.assertIn(f"materials/{saved['source_id']}.txt", names)
            self.assertIn(f"materials/{saved['source_id']}.provenance.json", names)
            self.assertIn(f"retrievals/{'a' * 32}/original.bin", names)
            self.assertNotIn(f"retrievals/{'b' * 32}/original.bin", names)
            self.assertFalse(any(name.startswith("provider-calls/") for name in names))
            for item in manifest["files"]:
                content = (package / item["path"]).read_bytes()
                self.assertEqual(len(content), item["bytes"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), item["sha256"])

    def test_modified_source_or_report_is_rejected(self):
        for name, expected in (("source", "handoff_source_hash_mismatch"),
                               ("report", "handoff_report_hash_mismatch")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"HERMES_HOME": directory}):
                run_id, root, saved = self._finished_run()
                target = (root / "materials" / f"{saved['source_id']}.txt") if name == "source" else root / "report.md"
                target.write_text("Modified after registration")
                with self.assertRaisesRegex(ValueError, expected):
                    export_handoff({"run_id": run_id})
                self.assertFalse(list((root / "handoffs").iterdir()))

    def test_dispatched_or_running_step_blocks_export(self):
        for active in ("dispatched", "running"):
            with self.subTest(active=active), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"HERMES_HOME": directory}):
                run_id, root, _ = self._finished_run()
                workspace({"action": "plan", "run_id": run_id,
                           "plan": {"steps": [{"id": "step-1", "status": active}]}})
                with self.assertRaisesRegex(ValueError, "handoff_active_worker"):
                    export_handoff({"run_id": run_id})
                self.assertFalse(list((root / "handoffs").iterdir()))

    def test_symlinked_handoff_parent_and_result_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"HERMES_HOME": directory}):
            run_id, root, _ = self._finished_run()
            (root / "handoffs").symlink_to(root / "notes", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "handoff_parent_invalid"):
                export_handoff({"run_id": run_id})
            (root / "handoffs").unlink()
            (root / "method.md").symlink_to(root / "report.md")
            workspace({"action": "plan", "run_id": run_id,
                       "plan": {"steps": [{"id": "step-1", "result_paths": ["method.md"]}]}})
            with self.assertRaisesRegex(ValueError, "handoff_link_not_allowed"):
                export_handoff({"run_id": run_id})
            workspace({"action": "plan", "run_id": run_id,
                       "plan": {"steps": [{"id": "step-1", "result_paths": [str(root / "report.md")]}]}})
            with self.assertRaisesRegex(ValueError, "handoff_path_invalid"):
                export_handoff({"run_id": run_id})


if __name__ == "__main__":
    unittest.main()
