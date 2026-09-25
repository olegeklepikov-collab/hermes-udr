from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_foundation_bridge.zvec_index import ZvecIndexer
from tests import test_zvec_index as fixtures


@unittest.skipUnless(importlib.util.find_spec("zvec"), "Zvec required")
class ZvecGenerationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.foundation = Path(self.directory.name) / "foundation"
        self.indexer = ZvecIndexer(self.foundation)
        self.indexer.migrate(apply=True)
        self.request = fixtures.ZvecIndexerTests.upsert_request(self)
        self.indexer.upsert(self.request)

    def tearDown(self):
        self.directory.cleanup()

    def change(self, generation="G1", action="replace", documents=1):
        return self.indexer.rebuild_from_sources(
            {
                "schema_version": 1,
                "apply": True,
                "expected_document_count": documents,
                "expected_active_count": documents,
                "generation_action": action,
                "generation_id": generation,
            }
        )

    def query(self):
        return self.indexer.query({"schema_version": 1, "query": "atomic", "limit": 10})

    def test_replace_and_rollback_keep_old_index_and_existing_reader_refreshes(self):
        original = self.query()["collection_ref"]
        selected = self.change()
        self.assertEqual(self.query()["result_count"], 1)
        self.assertEqual(self.query()["collection_ref"], "generations/G1/index")
        self.assertTrue((self.indexer.root / original).is_dir())
        self.change(selected["previous_generation_id"], "rollback")
        self.assertEqual(self.query()["collection_ref"], original)
        self.assertEqual(self.query()["result_count"], 1)

    def test_upsert_after_switch_uses_new_index_and_prevents_stale_rollback(self):
        selected = self.change()
        request = dict(self.request, document_id="DOC-2", content="atomic second")
        request["content_hash"] = hashlib.sha256(
            request["content"].encode()
        ).hexdigest()
        self.indexer.upsert(request)
        self.assertEqual(self.query()["result_count"], 2)
        with self.assertRaisesRegex(ValueError, "rollback_stale"):
            self.change(selected["previous_generation_id"], "rollback", documents=2)
        self.assertEqual(self.query()["result_count"], 2)

    def test_failed_switch_leaves_previous_generation_queryable(self):
        original = self.query()["collection_ref"]
        with (
            patch(
                "hermes_foundation_bridge.zvec_generations._publish",
                side_effect=OSError("simulated switch failure"),
            ),
            self.assertRaises(OSError),
        ):
            self.change()
        self.assertEqual(self.query()["collection_ref"], original)
        self.assertEqual(self.query()["result_count"], 1)
        self.assertTrue((self.indexer.root / "generations/G1/index").is_dir())
        self.change("G2")
        self.assertEqual(self.query()["result_count"], 1)

    def test_read_before_and_after_atomic_switch_never_sees_empty_index(self):
        from hermes_foundation_bridge import zvec_generations as generations

        original_publish = generations._publish
        observations = []

        def observed_switch(root, value):
            observations.append(self.query())
            original_publish(root, value)
            observations.append(self.query())

        with patch.object(generations, "_publish", side_effect=observed_switch):
            self.change()
        self.assertEqual([item["result_count"] for item in observations], [1, 1])
        self.assertNotEqual(
            observations[0]["collection_ref"], observations[1]["collection_ref"]
        )

    def test_replay_is_idempotent_and_bad_manifest_is_not_loaded(self):
        first = self.change()
        repeated = self.change()
        self.assertEqual(repeated["generation_id"], "G1")
        self.assertEqual(
            repeated["previous_generation_id"], first["previous_generation_id"]
        )
        self.assertFalse(repeated["switch_performed"])
        descriptor = self.indexer.root / "generations/G1.json"
        value = json.loads(descriptor.read_text())
        value["manifest_hash"] = "0" * 64
        descriptor.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "manifest_mismatch"):
            self.query()

    def crash_worker(self, after):
        code = """
import os,sys
from pathlib import Path
from hermes_foundation_bridge.zvec_index import ZvecIndexer
from hermes_foundation_bridge import zvec_generations as gen
original=gen._publish
def crash(root,value):
    if sys.argv[2]=='after': original(root,value)
    os._exit(73)
gen._publish=crash
ZvecIndexer(Path(sys.argv[1])).rebuild_from_sources({'schema_version':1,'apply':True,'generation_action':'replace','generation_id':'CRASH','expected_document_count':1,'expected_active_count':1})
"""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
                str(self.foundation),
                "after" if after else "before",
            ],
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 73, result.stderr)

    def test_process_crash_before_selection_keeps_old_readable(self):
        before = self.query()["collection_ref"]
        self.crash_worker(False)
        self.assertEqual(self.query()["collection_ref"], before)
        self.assertEqual(self.query()["result_count"], 1)

    def test_process_crash_after_selection_reads_new_and_replay_is_safe(self):
        self.crash_worker(True)
        self.assertEqual(self.query()["collection_ref"], "generations/CRASH/index")
        self.assertEqual(self.query()["result_count"], 1)
        self.assertEqual(self.change("CRASH")["generation_id"], "CRASH")

    def test_public_handler_selects_generation(self):
        import plugin

        with patch.dict(os.environ, {"HERMES_FOUNDATION_ROOT": str(self.foundation)}):
            result = json.loads(
                plugin.handle_index_rebuild(
                    {
                        "schema_version": 1,
                        "apply": True,
                        "expected_document_count": 1,
                        "expected_active_count": 1,
                        "generation_action": "replace",
                        "generation_id": "PUBLIC",
                    }
                )
            )
        self.assertEqual(result["status"], "selected")
        self.assertEqual(self.query()["collection_ref"], "generations/PUBLIC/index")
        with patch.dict(os.environ, {"HERMES_FOUNDATION_ROOT": str(self.foundation)}):
            rejected = json.loads(
                plugin.handle_index_rebuild(
                    {
                        "schema_version": 1,
                        "apply": True,
                        "expected_document_count": 1,
                        "expected_active_count": 1,
                        "generation_action": "rollback",
                        "generation_id": "WRONG",
                    }
                )
            )
        self.assertEqual(rejected["error"]["code"], "index_generation_not_previous")


if __name__ == "__main__":
    unittest.main()
