from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from hermes_foundation_bridge.errors import BridgeError
from hermes_foundation_bridge.fragments import promote, record_fragment
from hermes_foundation_bridge.runtime import RuntimeCoordinator
from tests.common import fragment_request, promotion_request


class FragmentBridgeTests(unittest.TestCase):
    def test_promotion_cannot_reuse_id_for_other_registered_version(self):
        record_fragment(fragment_request(), self.coordinator)
        for field, value in (
            ("source_ref", "OTHER"),
            ("source_version", "v2"),
            ("locator", "page:2"),
            ("run_id", "OTHER-RUN"),
        ):
            request = promotion_request()
            request["fragment"][field] = value
            with self.subTest(field=field), self.assertRaises(BridgeError) as caught:
                promote(request, self.coordinator)
            self.assertEqual(caught.exception.code, "found_fragment_version_mismatch")
        with self.assertRaises(BridgeError) as caught:
            promote(promotion_request("changed source"), self.coordinator)
        self.assertEqual(caught.exception.code, "found_fragment_version_mismatch")
        connection = self.coordinator._connect()
        try:
            self.assertEqual(
                connection.execute("SELECT status FROM found_fragments").fetchone()[0],
                "recorded",
            )
        finally:
            connection.close()

    def test_candidate_with_failed_local_boundary_cannot_be_promoted(self):
        request = fragment_request()
        request["fragment"]["source_ref"] = ""
        record_fragment(request, self.coordinator)
        promotion = promotion_request()
        promotion["fragment"] = request["fragment"]
        self.assertEqual(promote(promotion, self.coordinator)["status"], "candidate")

    def test_input_flags_cannot_override_authoritative_candidate_status(self):
        record_fragment(fragment_request(), self.coordinator)
        connection = self.coordinator._connect()
        try:
            connection.execute("UPDATE found_fragments SET status='candidate'")
        finally:
            connection.close()
        with self.assertRaises(BridgeError) as caught:
            promote(promotion_request(), self.coordinator)
        self.assertEqual(caught.exception.code, "found_fragment_unresolved")

    def test_source_text_disguised_as_metadata_is_not_persisted(self):
        for field in ("source_ref", "source_version", "locator"):
            request = fragment_request("SOURCE-CANARY private full paragraph")
            request["event_key"] += "-" + field
            request["fragment"]["fragment_id"] += "-" + field
            request["fragment"][field] = (
                "prefix:" + request["fragment"]["exact_fragment"]
            )
            original = copy.deepcopy(request)
            result = record_fragment(request, self.coordinator)
            self.assertEqual(result["status"], "candidate")
            self.assertFalse(result["secret_scan_pass"])
            self.assertEqual(request, original)
            self.assertNotIn(
                request["fragment"]["exact_fragment"].encode(),
                self.coordinator.database.read_bytes(),
            )

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.coordinator = RuntimeCoordinator(Path(self.directory.name) / "foundation")
        self.coordinator.migration_receipt(apply=True)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_record_does_not_persist_exact_text_or_promote_claim(self) -> None:
        request = fragment_request("unique exact fragment")
        result = record_fragment(request, self.coordinator)
        self.assertEqual(result["status"], "recorded")
        self.assertFalse(result["exact_fragment_persisted"])
        self.assertFalse(result["evidence_record_created"])
        self.assertFalse(result["claim_status_changed"])
        database_bytes = self.coordinator.database.read_bytes()
        self.assertNotIn(b"unique exact fragment", database_bytes)

    def test_promotion_requires_prior_found_fragment(self) -> None:
        with self.assertRaisesRegex(ValueError, "не зарегистрирован"):
            promote(promotion_request(), self.coordinator)

    def test_registered_fragment_can_be_promoted_without_release(self) -> None:
        record_fragment(fragment_request(), self.coordinator)
        result = promote(promotion_request(), self.coordinator)
        self.assertEqual(result["status"], "promoted")
        self.assertTrue(result["evidence_record_created"])
        self.assertFalse(result["claim_status_changed"])
        self.assertFalse(result["acceptance_changed"])
        self.assertFalse(result["release_changed"])

    def test_secret_like_fragment_remains_candidate_and_text_is_not_persisted(
        self,
    ) -> None:
        request = fragment_request("Authorization: Bearer must-not-persist")
        request["event_key"] = "EVENT-SECRET"
        request["fragment"]["fragment_id"] = "FRAG-SECRET"
        result = record_fragment(request, self.coordinator)
        self.assertEqual(result["status"], "candidate")
        self.assertFalse(result["secret_scan_pass"])
        self.assertNotIn(b"must-not-persist", self.coordinator.database.read_bytes())


if __name__ == "__main__":
    unittest.main()
