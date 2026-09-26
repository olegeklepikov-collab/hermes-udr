from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from hermes_foundation_bridge.errors import BridgeError
from hermes_foundation_bridge.profile_transport import (
    NAMED_PROFILE_IDS,
    ProfileTransportService,
)


def value_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ProfileTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.home = Path(self.directory.name) / "home"
        self.root = self.home / "foundation"
        self.home.mkdir(parents=True)
        self._make_home(self.home)
        for profile_id in NAMED_PROFILE_IDS:
            profile = self.home / "profiles" / profile_id
            profile.mkdir(parents=True)
            self._make_home(profile)
        self.service = ProfileTransportService(self.root)

    def tearDown(self) -> None:
        self.directory.cleanup()

    @staticmethod
    def _make_home(home: Path) -> None:
        for name in ("memories", "sessions", "cron", "plans"):
            (home / name).mkdir(parents=True, exist_ok=True)
        (home / ".env").write_text("# empty profile\n", encoding="utf-8")

    def migrate(self) -> None:
        result = self.service.migrate({"schema_version": 1, "apply": True})
        self.assertEqual(result["status"], "applied")

    def test_default_activity_preserves_initial_contract_and_named_boundaries(self):
        (self.home / "plans").rmdir()
        self.migrate()
        contract = self.service.contract_root / "default.json"
        before = contract.read_bytes()
        (self.home / ".env").write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
        (self.home / "memories" / "new.md").write_text("new local state")
        (self.home / "plans").mkdir()
        self.migrate()
        self.assertEqual(contract.read_bytes(), before)
        observed = self.service.profile_get(
            {"schema_version": 1, "profile_id": "default"}
        )
        self.assertEqual(observed["status"], "verified")
        self.assertEqual(observed["initial_secret_assignment_count"], 0)
        self.assertEqual(observed["initial_state_file_count"], -1)
        self.assertEqual(observed["current_observation"]["state_file_count"], 1)
        self.assertEqual(observed["current_observation"]["assignment_count"], 1)
        self.assertEqual(
            self.service.health({"schema_version": 1})["status"], "healthy"
        )
        altered = json.loads(before)
        altered["role"] = "unexpected"
        contract.write_text(json.dumps(altered))
        self.assertEqual(
            self.service.health({"schema_version": 1})["status"], "blocked"
        )
        with self.assertRaises(BridgeError):
            self.migrate()
        contract.write_bytes(before)
        env = self.home / ".env"
        saved_env = self.home / "saved-env"
        env.rename(saved_env)
        env.symlink_to(saved_env)
        self.assertEqual(self.service.health({"schema_version": 1})["status"], "blocked")
        env.unlink()
        saved_env.rename(env)
        (self.home / "profiles" / "research" / ".env").write_text("FORBIDDEN=1\n")
        self.assertEqual(
            self.service.health({"schema_version": 1})["status"], "blocked"
        )
        with self.assertRaises(BridgeError):
            self.migrate()
        self.assertEqual(contract.read_bytes(), before)

    def test_migration_rejects_symlinked_contract_directory(self):
        self.migrate()
        original = self.service.contract_root
        saved = self.root / "saved-contracts"
        original.rename(saved)
        original.symlink_to(saved, target_is_directory=True)
        before = (saved / "default.json").read_bytes()
        with self.assertRaises(BridgeError):
            self.migrate()
        self.assertEqual((saved / "default.json").read_bytes(), before)
        self.assertEqual(
            self.service.health({"schema_version": 1})["status"], "blocked"
        )

    def test_tc230_blank_profile_and_complete_handoff(self) -> None:
        dry = self.service.migrate({"schema_version": 1, "apply": False})
        self.assertEqual(dry["named_blank_profile_count"], 7)
        self.migrate()
        profile = self.service.profile_get(
            {"schema_version": 1, "profile_id": "engineering"}
        )
        health = self.service.health({"schema_version": 1})
        self.assertEqual(profile["status"], "verified")
        self.assertEqual(health["status"], "healthy")
        self.assertTrue(profile["native_home_isolated"])
        self.assertEqual(profile["initial_secret_assignment_count"], 0)
        handoff = self.service.handoff(
            {
                "schema_version": 1,
                "package_id": "PACKAGE-230",
                "revision": 1,
                "from_profile": "engineering",
                "to_profile": "review",
                "artifact_refs": ["ART-230"],
                "test_refs": ["TEST-230"],
                "computation_refs": [],
                "commit_refs": ["COMMIT-230"],
                "checkpoint_ref": "CHECKPOINT-230",
                "accepted_effect_refs": [],
                "merge_owner": "CONTROLLER",
            }
        )
        self.assertTrue(handoff["complete"])
        self.assertFalse(handoff["merge_changed"])

    def test_nonblank_profile_is_rejected(self) -> None:
        (self.home / "profiles" / "engineering" / ".env").write_text(
            "TOKEN=value\n", encoding="utf-8"
        )
        with self.assertRaises(BridgeError) as caught:
            self.service.migrate({"schema_version": 1, "apply": False})
        self.assertEqual(caught.exception.code, "profile_not_blank")

    def test_tc231_blind_review_first_position(self) -> None:
        self.migrate()
        position = "changes_required"
        result = self.service.review_position(
            {
                "schema_version": 1,
                "package_id": "PACKAGE-231",
                "reviewer_profile": "review",
                "reviewer_id": "REVIEWER-B",
                "artifact_refs": ["ART-231"],
                "author_conclusion_excluded": True,
                "author_acceptance_excluded": True,
                "position": position,
                "position_hash": value_hash(position),
            }
        )
        self.assertFalse(result["author_conclusion_visible"])
        self.assertFalse(result["acceptance_changed"])

    def test_tc232_operator_cannot_change_basis_or_acceptance(self) -> None:
        self.migrate()
        basis = value_hash("basis")
        result = self.service.operator_effect(
            {
                "schema_version": 1,
                "operator_profile": "operator",
                "effect_ref": "EFFECT-232",
                "signed_decision_hash": value_hash("decision"),
                "basis_hash_before": basis,
                "basis_hash_after": basis,
                "acceptance_ref_before": "ACCEPT-232",
                "acceptance_ref_after": "ACCEPT-232",
                "output_hash": value_hash("output"),
                "idempotency_key": "IDEMPOTENCY-232",
            }
        )
        self.assertTrue(result["basis_unchanged"])
        self.assertFalse(result["analysis_created"])

    def test_tc233_resume_does_not_repeat_accepted_effect(self) -> None:
        self.migrate()
        request = {
            "schema_version": 1,
            "package_id": "PACKAGE-233",
            "checkpoint_ref": "CHECKPOINT-233",
            "prior_worker_id": "WORKER-A",
            "new_worker_id": "WORKER-B",
            "new_lease_ref": "LEASE-233",
            "accepted_effect_refs": ["EFFECT-DONE"],
            "requested_effect_refs": ["EFFECT-NEXT"],
        }
        result = self.service.resume(request)
        self.assertFalse(result["accepted_effects_replayed"])
        request["requested_effect_refs"] = ["EFFECT-DONE"]
        with self.assertRaises(BridgeError) as caught:
            self.service.resume(request)
        self.assertEqual(caught.exception.code, "resume_repeats_effect")

    def test_tc234_independent_merge_review(self) -> None:
        self.migrate()
        result = self.service.merge_assess(
            {
                "schema_version": 1,
                "writer_profile": "engineering",
                "writer_id": "WRITER-A",
                "reviewer_profile": "review",
                "reviewer_id": "REVIEWER-B",
                "worktree_ref": "WORKTREE-234",
                "commit_ref": "COMMIT-234",
                "bead_ref": "BEAD-234",
                "review_ref": "REVIEW-234",
                "review_status": "accepted",
            }
        )
        self.assertTrue(result["merge_allowed"])
        self.assertTrue(result["independent_review"])

    def test_tc235_236_dm_binding_and_media_relations(self) -> None:
        self.migrate()
        binding = self.service.telegram_ingress(
            {
                "schema_version": 1,
                "route": "dm_polling",
                "route_qualified": True,
                "user_allowed": True,
                "chat_allowed": True,
                "user_hash": value_hash("user"),
                "chat_hash": value_hash("chat"),
                "project_id": "PROJECT-235",
                "run_id": "RUN-235",
                "bead_id": "BEAD-235",
                "profile_id": "research",
            }
        )
        self.assertFalse(binding["raw_identifiers_persisted"])
        file_receipt = self.service.media_ingest(
            {
                "schema_version": 1,
                "media_ref": "MEDIA-FILE-236",
                "binding_ref": binding["binding_ref"],
                "media_kind": "file",
                "quarantined": True,
                "artifact_hash": value_hash("file"),
                "transcript_hash": None,
                "transformation_ref": None,
            }
        )
        audio_receipt = self.service.media_ingest(
            {
                "schema_version": 1,
                "media_ref": "MEDIA-AUDIO-236",
                "binding_ref": binding["binding_ref"],
                "media_kind": "audio",
                "quarantined": True,
                "artifact_hash": value_hash("audio"),
                "transcript_hash": value_hash("transcript"),
                "transformation_ref": "TRANSFORM-236",
            }
        )
        self.assertEqual(file_receipt["status"], "quarantined")
        self.assertTrue(audio_receipt["separate_hashes"])

    def test_tc237_238_ambiguous_delivery_and_exact_redelivery(self) -> None:
        self.migrate()
        artifact_hash = value_hash("delivery bytes")
        prepared = self.service.delivery_prepare(
            {
                "schema_version": 1,
                "idempotency_key": "DELIVERY-237",
                "artifact_hash": artifact_hash,
                "model_run_id": "MODEL-RUN-237",
                "host_visible_output": True,
                "accepted_artifact": True,
            }
        )
        ambiguous = self.service.delivery_reconcile(
            {
                "schema_version": 1,
                "idempotency_key": prepared["idempotency_key"],
                "provider_status": "timeout",
                "provider_accepted": True,
                "model_run_id": prepared["model_run_id"],
            }
        )
        self.assertEqual(ambiguous["status"], "ambiguous_delivery")
        self.assertFalse(ambiguous["model_rerun"])
        redelivered = self.service.delivery_redeliver(
            {
                "schema_version": 1,
                "idempotency_key": prepared["idempotency_key"],
                "artifact_hash": artifact_hash,
                "user_approved": True,
                "duplicate_visible": True,
                "model_rerun": False,
            }
        )
        self.assertEqual(redelivered["status"], "redelivery_authorized")
        self.assertFalse(redelivered["delivery_observed"])
        self.assertFalse(redelivered["external_effect_performed"])
        self.assertEqual(redelivered["artifact_hash"], artifact_hash)
        with closing(sqlite3.connect(self.service.database)) as connection, connection:
            state, attempts = connection.execute(
                "SELECT state,attempts FROM deliveries WHERE idempotency_key=?",
                (prepared["idempotency_key"],),
            ).fetchone()
        self.assertEqual((state, attempts), ("ambiguous_delivery", 1))
        with self.assertRaises(BridgeError) as caught:
            self.service.delivery_reconcile(
                {
                    "schema_version": 1,
                    "idempotency_key": prepared["idempotency_key"],
                    "provider_status": "delivered",
                    "provider_accepted": False,
                    "model_run_id": prepared["model_run_id"],
                }
            )
        self.assertEqual(caught.exception.code, "delivery_readback_conflict")

    def test_tc239_unqualified_routes_are_blocked(self) -> None:
        self.migrate()
        for route in ("group", "webhook", "local_bot_api"):
            with self.subTest(route=route):
                result = self.service.route_assess(
                    {"schema_version": 1, "route": route, "qualified": False}
                )
                self.assertEqual(result["status"], "blocked")
                self.assertTrue(result["dm_polling_baseline_intact"])


if __name__ == "__main__":
    unittest.main()
