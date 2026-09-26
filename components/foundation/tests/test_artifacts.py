from __future__ import annotations

import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from hermes_foundation_bridge.artifacts import ArtifactService


class ArtifactServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "foundation"
        self.service = ArtifactService(self.root)
        self.service.prepare(dry_run=False)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def request(self, acquisition_id: str, relative_path: str = "input.bin") -> dict:
        return {
            "schema_version": 1,
            "acquisition_id": acquisition_id,
            "relative_path": relative_path,
            "media_type": "application/octet-stream",
            "max_bytes": 1024,
        }

    def test_ingest_is_atomic_verified_and_deduplicated(self) -> None:
        (self.service.quarantine / "input.bin").write_bytes(b"same bytes")
        first = self.service.ingest(self.request("ACQ-1"))
        second = self.service.ingest(self.request("ACQ-2"))
        self.assertEqual(first["status"], "accepted")
        self.assertEqual(first["disposition"], "verified_new_artifact")
        self.assertTrue(first["readback_verified"])
        self.assertEqual(second["disposition"], "idempotent_existing")
        self.assertEqual(first["artifact_id"], second["artifact_id"])
        self.assertEqual(len(list(self.service.originals.iterdir())), 1)
        self.assertEqual(len(list(self.service.metadata.iterdir())), 2)

    def test_symlink_and_fifo_are_rejected_before_read(self) -> None:
        target = self.service.quarantine / "ordinary"
        target.write_text("data", encoding="utf-8")
        (self.service.quarantine / "link").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "Символическая"):
            self.service.ingest(self.request("ACQ-LINK", "link"))
        fifo = self.service.quarantine / "fifo"
        if hasattr(os, "mkfifo"):
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "обычный файл"):
                self.service.ingest(self.request("ACQ-FIFO", "fifo"))
        outside = Path(self.directory.name) / "outside"
        outside.mkdir()
        (outside / "data").write_text("outside", encoding="utf-8")
        (self.service.quarantine / "linked-parent").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "Символическая"):
            self.service.ingest(self.request("ACQ-PARENT-LINK", "linked-parent/data"))

    def test_recovery_detects_orphan_without_accepting_it(self) -> None:
        (self.service.originals / ("a" * 64)).write_bytes(b"orphan")
        result = self.service.recover()
        self.assertEqual(result["status"], "recovery_required")
        self.assertEqual(result["orphan_count"], 1)
        self.assertFalse(result["orphans_accepted"])

    def test_media_type_runtime_limit_matches_public_schema(self):
        (self.service.quarantine / "input.bin").write_bytes(b"data")
        with self.assertRaises(ValueError):
            self.service.ingest({**self.request("ACQ-LIMIT"), "media_type": "x" * 129})
        self.assertFalse(list(self.service.originals.iterdir()))

    def test_retry_quarantines_only_exact_temporary_duplicates(self):
        payload = b"retained original"
        (self.service.quarantine / "input.bin").write_bytes(payload)
        duplicate = self.service.originals / ".original-interrupted"
        duplicate.write_bytes(payload)
        unique = self.service.originals / ".original-unique"
        unique.write_bytes(b"unrelated information")
        result = self.service.ingest(self.request("ACQ-RETRY"))
        self.assertEqual(len(result["reconciled_temporary_refs"]), 1)
        self.assertEqual(
            (self.service.root / result["reconciled_temporary_refs"][0]).read_bytes(),
            payload,
        )
        self.assertFalse(duplicate.exists())
        self.assertEqual(unique.read_bytes(), b"unrelated information")
        self.assertEqual(self.service.recover()["orphan_count"], 1)

    def test_reconciliation_resumes_after_its_own_link_publication(self):
        payload = b"retained original"
        (self.service.quarantine / "input.bin").write_bytes(payload)
        temporary = self.service.originals / ".original-interrupted"
        temporary.write_bytes(payload)
        target_root = self.service.quarantine / "recovered-temporaries"
        target_root.mkdir()
        target = target_root / "originals-original-interrupted"
        os.link(temporary, target)
        self.service.ingest(self.request("ACQ-RETRY"))
        self.assertFalse(temporary.exists())
        self.assertEqual(target.read_bytes(), payload)
        self.assertEqual(self.service.recover()["status"], "consistent")

    def test_reconciliation_never_overwrites_conflicting_target(self):
        payload = b"retained original"
        (self.service.quarantine / "input.bin").write_bytes(payload)
        temporary = self.service.originals / ".original-interrupted"
        temporary.write_bytes(payload)
        target_root = self.service.quarantine / "recovered-temporaries"
        target_root.mkdir()
        target = target_root / "originals-original-interrupted"
        target.write_bytes(b"other retained information")
        self.service.ingest(self.request("ACQ-RETRY"))
        self.assertEqual(temporary.read_bytes(), payload)
        self.assertEqual(target.read_bytes(), b"other retained information")

    def test_metadata_draft_timestamp_is_preserved_in_quarantine(self):
        (self.service.quarantine / "input.bin").write_bytes(b"data")
        self.service.ingest(self.request("ACQ-DRAFT"))
        draft = json.loads((self.service.metadata / "ACQ-DRAFT.json").read_text())
        draft["created_at"] = "2020-01-01T00:00:00+00:00"
        raw = json.dumps(draft).encode()
        temporary = self.service.metadata / ".artifact-interrupted"
        temporary.write_bytes(raw)
        self.assertEqual(self.service.recover()["temporary_metadata_count"], 1)
        result = self.service.ingest(self.request("ACQ-DRAFT"))
        self.assertEqual(
            (self.service.root / result["reconciled_temporary_refs"][0]).read_bytes(),
            raw,
        )
        self.assertEqual(self.service.recover()["status"], "consistent")

    def test_unknown_metadata_draft_remains_visible(self):
        (self.service.quarantine / "input.bin").write_bytes(b"data")
        (self.service.metadata / ".artifact-unknown").write_bytes(b"unique draft")
        self.service.ingest(self.request("ACQ-DRAFT"))
        self.assertEqual(self.service.recover()["status"], "recovery_required")
        self.assertEqual(
            (self.service.metadata / ".artifact-unknown").read_bytes(), b"unique draft"
        )

    def test_writer_lock_excludes_concurrent_ingest(self):
        (self.service.quarantine / "input.bin").write_bytes(b"data")
        started = Event()

        def ingest():
            started.set()
            return self.service.ingest(self.request("ACQ-CONCURRENT"))

        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.service._writer():
                future = executor.submit(ingest)
                self.assertTrue(started.wait(1))
                self.assertFalse(future.done())
            self.assertEqual(future.result(timeout=2)["status"], "accepted")

    def test_recovery_reports_corrupt_and_special_metadata_without_blocking(self):
        (self.service.metadata / "bad.json").write_text("[]")
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.service.metadata / "fifo.json")
        else:
            (self.service.metadata / "directory.json").mkdir()
        (self.service.metadata / "link.json").symlink_to(
            self.service.metadata / "bad.json"
        )
        result = self.service.recover()
        self.assertEqual(result["corrupt_metadata_count"], 3)
        self.assertEqual(result["status"], "recovery_required")

    def test_tombstone_blocks_restore_before_propagation(self) -> None:
        result = self.service.tombstone(
            {
                "schema_version": 1,
                "artifact_id": "ART-1",
                "reason_code": "RETENTION",
            }
        )
        self.assertEqual(result["status"], "recorded")
        self.assertFalse(result["active"])
        self.assertFalse(result["restore_allowed"])
        self.assertFalse(result["release_allowed"])


if __name__ == "__main__":
    unittest.main()
