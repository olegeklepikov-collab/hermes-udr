"""Public delivery notices must preserve the bytes and the unknown transport outcome."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import plugin
from hermes_foundation_bridge.errors import BridgeError
from hermes_foundation_bridge.profile_transport import (
    NAMED_PROFILE_IDS,
    ProfileTransportService,
)


class DeliveryPresentationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.home = Path(self.directory.name) / "home"
        self.root = self.home / "foundation"
        for home in [
            self.home,
            *[self.home / "profiles" / x for x in NAMED_PROFILE_IDS],
        ]:
            home.mkdir(parents=True)
            for name in ("memories", "sessions", "cron", "plans"):
                (home / name).mkdir()
            (home / ".env").write_text("# Empty isolated profile\n")
        self.environment = patch.dict(
            os.environ, {"HERMES_FOUNDATION_ROOT": str(self.root)}
        )
        self.environment.start()
        migrated = json.loads(
            plugin.handle_profiles_migrate({"schema_version": 1, "apply": True})
        )
        self.assertEqual(migrated["status"], "applied")
        self.artifact = "Контрольный материал для повторной доставки.\n".encode()
        self.digest = hashlib.sha256(self.artifact).hexdigest()
        self.key = "DELIVERY-PRESENTATION"
        plugin.handle_delivery_prepare(
            {
                "schema_version": 1,
                "idempotency_key": self.key,
                "artifact_hash": self.digest,
                "model_run_id": "NO-MODEL",
                "host_visible_output": True,
                "accepted_artifact": True,
            }
        )
        result = json.loads(
            plugin.handle_delivery_reconcile(
                {
                    "schema_version": 1,
                    "idempotency_key": self.key,
                    "provider_status": "timeout",
                    "provider_accepted": True,
                    "model_run_id": "NO-MODEL",
                }
            )
        )
        self.assertEqual(result["status"], "ambiguous_delivery")

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def request(self, **changes):
        return {
            "schema_version": 1,
            "idempotency_key": self.key,
            "artifact_hash": self.digest,
            "user_approved": True,
            "duplicate_visible": True,
            "model_rerun": False,
            **changes,
        }

    def test_public_notice_is_stable_and_does_not_claim_transport(self):
        first = json.loads(plugin.handle_delivery_redeliver(self.request()))
        second = json.loads(plugin.handle_delivery_redeliver(self.request()))
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "redelivery_authorized")
        self.assertEqual(
            first["artifact_hash"], hashlib.sha256(self.artifact).hexdigest()
        )
        notice = first["user_notice"]
        self.assertIn("Возможен повтор сообщения", notice)
        self.assertIn("SHA-256: " + self.digest, notice)
        self.assertIn("Исход предыдущей отправки не установлен", notice)
        self.assertIn("отправка и получение этой квитанцией не подтверждены", notice)
        self.assertFalse(first["external_effect_performed"])
        self.assertFalse(first["delivery_observed"])
        with closing(sqlite3.connect(self.root / "runtime" / "profile-transport.sqlite3")) as db, db:
            state = db.execute(
                "SELECT state, attempts, artifact_hash FROM deliveries WHERE idempotency_key=?",
                (self.key,),
            ).fetchone()
        self.assertEqual(state, ("ambiguous_delivery", 1, self.digest))

    def test_unsafe_redelivery_never_produces_authorizing_notice(self):
        for change in (
            {"artifact_hash": "0" * 64},
            {"duplicate_visible": False},
            {"user_approved": False},
            {"model_rerun": True},
        ):
            with self.subTest(change=change):
                result = json.loads(
                    plugin.handle_delivery_redeliver(self.request(**change))
                )
                self.assertEqual(result["error"]["code"], "redelivery_blocked")
                self.assertNotIn("user_notice", result)

    def test_lost_transport_response_does_not_repeat_the_send(self):
        calls = []

        def lose(text):
            calls.append(text)
            raise TimeoutError("controlled reply loss")

        first = ProfileTransportService(self.root).present_redelivery(
            self.request(), self.artifact, lose
        )
        second = ProfileTransportService(self.root).present_redelivery(
            self.request(), self.artifact, lose
        )
        self.assertEqual(first["status"], "unknown_outcome")
        self.assertEqual(second["status"], "unknown_outcome")
        self.assertEqual(len(calls), 1)

    def test_notice_and_unchanged_artifact_reach_final_transport(self):
        calls = []
        service = ProfileTransportService(self.root)
        result = service.present_redelivery(
            self.request(),
            self.artifact,
            lambda text: calls.append(text) or {"accepted": True, "provider": "stub"},
        )
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("Возможен повтор сообщения"))
        self.assertIn("SHA-256: " + self.digest, calls[0])
        self.assertTrue(calls[0].endswith(self.artifact.decode()))
        self.assertEqual(result["status"], "transport_invoked")
        self.assertEqual(
            result["transport_receipt"], {"accepted": True, "provider": "stub"}
        )
        self.assertFalse(result["delivery_observed"])
        replay = service.present_redelivery(
            self.request(), self.artifact, lambda text: calls.append(text)
        )
        self.assertEqual(replay["status"], "already_succeeded")
        self.assertEqual(len(calls), 1)
        with self.assertRaises(BridgeError):
            service.present_redelivery(
                self.request(), b"changed", lambda text: calls.append(text)
            )
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
