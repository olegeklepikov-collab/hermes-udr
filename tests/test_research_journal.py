from __future__ import annotations

import json
from contextlib import closing
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from hermes_research_report.research_journal import record
from hermes_research_report.research_workspace import source, workspace


class ResearchJournalTests(unittest.TestCase):
    def test_negative_search_and_budget_stop_remain_factual(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"HERMES_HOME": directory}):
            started = workspace({"action": "start", "question": "Where is the primary record?", "mode": "deep"})
            event = {
                "kind": "search", "planned_vs_executed": {"planned": 3, "executed": 1},
                "exact_query": "primary record missing", "tool": "web_search",
                "family": "official", "time": "2026-09-24", "language": "en",
                "geography": "global", "results": [],
                "deadends": ["No primary document in this route"], "source_ids": [],
                "why_next": "Try the archive", "changed_hypotheses": [],
                "limits": ["one route only"], "declared_stop_reason": "budget",
            }
            result = record({"run_id": started["run_id"], "event": event})
            self.assertEqual(result["seq"], 1)
            self.assertFalse(result["verified_saturation"])
            narrative = json.loads(Path(result["narrative_json"]).read_text())
            saved = narrative["events"][0]
            self.assertEqual(saved["event"], event)
            self.assertEqual(saved["declared_stop_reason"], "budget")
            self.assertFalse(saved["verified_saturation"])
            self.assertIn("No primary document", Path(result["narrative_md"]).read_text())

    def test_same_bytes_at_new_path_do_not_advance_loop_but_new_content_does(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"HERMES_HOME": directory}):
            started = workspace({"action": "start", "question": "What changed?", "mode": "ultra"})
            run_id, root = started["run_id"], Path(started["root"])
            sid = source({"run_id": run_id, "url": "https://example.org/source",
                          "text": "Original material", "extent": "excerpt"})["source_id"]
            (root / "first.txt").write_text("same substantive output")
            first = record({"run_id": run_id, "event": {
                "kind": "loop", "loop_id": "L-1", "source_ids": [sid],
                "output_paths": ["first.txt"],
                "state_delta": {"observations": [{"id": "temporary-1", "text": "finding"}]},
            }})
            (root / "second.txt").write_text("same substantive output")
            second = record({"run_id": run_id, "event": {
                "kind": "loop", "loop_id": "L-1", "source_ids": [sid],
                "output_paths": ["second.txt"],
                "state_delta": {"observations": [{"id": "temporary-2", "text": "finding"}]},
            }})
            self.assertEqual(first["loop_progress"]["fingerprint"], second["loop_progress"]["fingerprint"])
            self.assertEqual(second["loop_progress"]["recommendation"], "change_route_or_stop_this_loop")
            self.assertFalse(second["loop_progress"]["whole_investigation_blocked"])
            (root / "third.txt").write_text("new substantive output")
            third = record({"run_id": run_id, "event": {
                "kind": "loop", "loop_id": "L-1", "source_ids": [sid],
                "output_paths": ["third.txt"],
                "state_delta": {"gap_changes": [{"text": "previous gap resolved"}]},
            }})
            self.assertTrue(third["loop_progress"]["recorded_change"])
            self.assertIsNone(third["loop_progress"]["recommendation"])
            self.assertEqual(len(third["loop_progress"]["output_sha256"]), 2)

    def test_concurrent_sqlite_records_have_unique_order_and_complete_export(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"HERMES_HOME": directory}):
            started = workspace({"action": "start", "question": "What routes exist?", "mode": "deep"})
            run_id = started["run_id"]
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(
                    lambda index: record({"run_id": run_id, "event": {
                        "kind": "search", "exact_query": f"route {index}",
                        "results": [], "deadends": ["not found"],
                    }}),
                    range(8),
                ))
            self.assertEqual(sorted(row["seq"] for row in results), list(range(1, 9)))
            root = Path(started["root"])
            narrative = json.loads((root / "narrative.json").read_text())
            self.assertEqual(len(narrative["events"]), 8)
            self.assertEqual([row["seq"] for row in narrative["events"]], list(range(1, 9)))
            with closing(sqlite3.connect(root / "corpus.sqlite")) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM journal").fetchone()[0], 8)


if __name__ == "__main__":
    unittest.main()
