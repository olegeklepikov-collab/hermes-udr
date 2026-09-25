from __future__ import annotations

import hashlib
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from hermes_foundation_bridge.artifacts import ArtifactService
from hermes_foundation_bridge.zvec_index import INDEX_MANIFEST, ZvecIndexer


@unittest.skipUnless(importlib.util.find_spec("zvec"), "Zvec 0.7.0 is required")
class ZvecIndexerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.foundation = Path(self.directory.name) / "foundation"
        self.indexer = ZvecIndexer(self.foundation)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def upsert_request(self, content: str = "atomic research fragment") -> dict:
        artifacts = ArtifactService(self.foundation)
        artifacts.prepare(dry_run=False)
        original = b"zvec fixture original bytes"
        (artifacts.quarantine / "source.txt").write_bytes(original)
        ingested = artifacts.ingest(
            {
                "schema_version": 1,
                "acquisition_id": "ACQ-ZVEC-1",
                "relative_path": "source.txt",
                "media_type": "text/plain",
                "max_bytes": 1024,
            }
        )
        return {
            "schema_version": 1,
            "document_id": "DOC-1",
            "artifact_id": ingested["artifact_id"],
            "source_ref": f"originals/{ingested['content_hash']}",
            "content": content,
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        }

    def test_migrate_upsert_read_only_query_and_tombstone(self) -> None:
        dry = self.indexer.migrate(apply=False)
        self.assertEqual(dry["status"], "dry_run_ready")
        self.assertFalse(self.foundation.exists())
        migrated = self.indexer.migrate(apply=True)
        self.assertEqual(migrated["status"], "applied")
        self.assertEqual(migrated["manifest"], INDEX_MANIFEST)
        upsert_request = self.upsert_request()
        indexed = self.indexer.upsert(upsert_request)
        self.assertEqual(indexed["status"], "indexed")
        self.assertTrue(indexed["rebuildable_from_ledger"])
        self.assertEqual(indexed["evidence_status"], "derived_candidate")
        found = self.indexer.query(
            {"schema_version": 1, "query": "atomic research", "limit": 5}
        )
        self.assertEqual(found["result_count"], 1)
        self.assertEqual(found["reader_mode"], "read_only")
        tombstone = self.indexer.tombstone(
            {"schema_version": 1, "artifact_id": upsert_request["artifact_id"]}
        )
        self.assertEqual(tombstone["status"], "propagated")
        self.assertEqual(tombstone["deactivated_count"], 1)
        hidden = self.indexer.query(
            {"schema_version": 1, "query": "atomic research", "limit": 5}
        )
        self.assertEqual(hidden["result_count"], 0)

    def test_secret_like_content_is_rejected(self) -> None:
        self.indexer.migrate(apply=True)
        request = self.upsert_request("Authorization: Bearer must-not-index")
        with self.assertRaisesRegex(ValueError, "секрет"):
            self.indexer.upsert(request)

    def test_artifact_tombstone_cascades_to_zvec_but_keeps_graph_pending(self) -> None:
        self.indexer.migrate(apply=True)
        request = self.upsert_request()
        self.indexer.upsert(request)
        artifacts = ArtifactService(self.foundation)
        result = artifacts.tombstone(
            {
                "schema_version": 1,
                "artifact_id": request["artifact_id"],
                "reason_code": "RETENTION",
            }
        )
        self.assertTrue(result["zvec_propagated"])
        self.assertFalse(result["graph_propagated"])
        self.assertFalse(result["propagation_complete"])
        hidden = self.indexer.query(
            {"schema_version": 1, "query": "atomic research", "limit": 5}
        )
        self.assertEqual(hidden["result_count"], 0)

    def test_rebuild_from_ledger_without_copying_index(self) -> None:
        self.indexer.migrate(apply=True)
        first = self.upsert_request("recoverable original-anchored fragment")
        self.indexer.upsert(first)
        second = dict(first)
        second["document_id"] = "DOC-2"
        second["content"] = "tombstoned derived fragment"
        second["content_hash"] = hashlib.sha256(second["content"].encode()).hexdigest()
        self.indexer.upsert(second)
        self.indexer.tombstone(
            {"schema_version": 1, "artifact_id": first["artifact_id"]}
        )
        # A third accepted artifact remains active and must reappear after rebuild.
        artifacts = ArtifactService(self.foundation)
        (artifacts.quarantine / "other.txt").write_bytes(b"different original bytes")
        other = artifacts.ingest(
            {
                "schema_version": 1,
                "acquisition_id": "ACQ-ZVEC-2",
                "relative_path": "other.txt",
                "media_type": "text/plain",
                "max_bytes": 1024,
            }
        )
        third = {
            "schema_version": 1,
            "document_id": "DOC-3",
            "artifact_id": other["artifact_id"],
            "source_ref": f"originals/{other['content_hash']}",
            "content": "recoverable active fragment",
            "content_hash": hashlib.sha256(b"recoverable active fragment").hexdigest(),
        }
        self.indexer.upsert(third)
        alternate = Path(self.directory.name) / "alternate-foundation"
        shutil.copytree(
            self.indexer.source_root,
            alternate / "zvec" / INDEX_MANIFEST["source_ledger_id"],
        )
        shutil.copytree(self.foundation / "artifacts", alternate / "artifacts")
        rebuilt = ZvecIndexer(alternate)
        self.assertFalse(rebuilt.collection_path.exists())
        rebuilt.migrate(apply=True)
        result = rebuilt.rebuild_from_sources(
            {
                "schema_version": 1,
                "apply": True,
                "expected_document_count": 3,
                "expected_active_count": 1,
            }
        )
        self.assertEqual(result["status"], "rebuild_verified")
        self.assertFalse(result["index_bytes_used_as_source"])
        self.assertTrue(result["original_hashes_readback"])
        found = rebuilt.query(
            {"schema_version": 1, "query": "recoverable active", "limit": 5}
        )
        self.assertEqual([row["document_id"] for row in found["results"]], ["DOC-3"])
        hidden = rebuilt.query(
            {"schema_version": 1, "query": "tombstoned derived", "limit": 5}
        )
        self.assertEqual(hidden["result_count"], 0)

    def test_prepared_ledger_record_is_not_visible_or_rebuilt(self) -> None:
        self.indexer.migrate(apply=True)
        request = self.upsert_request()
        self.indexer.upsert(request)
        self.indexer._accepted_path("DOC-1").unlink()
        hidden = self.indexer.query(
            {"schema_version": 1, "query": "atomic research", "limit": 5}
        )
        self.assertEqual(hidden["result_count"], 0)
        alternate = Path(self.directory.name) / "alternate-prepared"
        shutil.copytree(
            self.indexer.source_root,
            alternate / "zvec" / INDEX_MANIFEST["source_ledger_id"],
        )
        shutil.copytree(self.foundation / "artifacts", alternate / "artifacts")
        rebuilt = ZvecIndexer(alternate)
        rebuilt.migrate(apply=True)
        with self.assertRaisesRegex(ValueError, "не была принята"):
            rebuilt.rebuild_from_sources(
                {
                    "schema_version": 1,
                    "apply": True,
                    "expected_document_count": 1,
                    "expected_active_count": 1,
                }
            )

    def test_original_identity_and_immutable_document_are_enforced(self) -> None:
        self.indexer.migrate(apply=True)
        request = self.upsert_request()
        wrong_identity = dict(request, artifact_id="ART-WRONG")
        with self.assertRaisesRegex(ValueError, "не совпадает"):
            self.indexer.upsert(wrong_identity)
        self.assertFalse(self.indexer._source_path("DOC-1").exists())
        self.indexer.upsert(request)
        changed = dict(request, content="different derived text")
        changed["content_hash"] = hashlib.sha256(
            changed["content"].encode()
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "другим фрагментом"):
            self.indexer.upsert(changed)
        self.assertEqual(
            self.indexer.query(
                {"schema_version": 1, "query": "atomic research", "limit": 5}
            )["result_count"],
            1,
        )

    def test_rebuild_refuses_nonempty_target(self) -> None:
        self.indexer.migrate(apply=True)
        self.indexer.upsert(self.upsert_request())
        with self.assertRaisesRegex(ValueError, "не пуст"):
            self.indexer.rebuild_from_sources(
                {
                    "schema_version": 1,
                    "apply": True,
                    "expected_document_count": 1,
                    "expected_active_count": 1,
                }
            )


if __name__ == "__main__":
    unittest.main()
