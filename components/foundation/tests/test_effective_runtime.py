from __future__ import annotations

import unittest

from hermes_foundation_bridge.effective_runtime import reconcile_effective_runtime
from hermes_foundation_bridge.errors import BridgeError

NOW = "2026-09-21T07:00:00Z"
RECENT = "2026-09-21T06:59:30Z"
OLD = "2026-09-21T05:00:00Z"


def request() -> dict:
    desired = []
    effective = []
    for profile in ("default", "research"):
        desired.append(
            {
                "instance_id": "greenfield",
                "profile_id": profile,
                "operation_id": "web.search",
                "config_hash": "a" * 64,
                "schema_fingerprint": "b" * 64,
                "retry_budget": 2,
                "open_after_failures": 3,
                "observation_ttl_seconds": 300,
            }
        )
        effective.append(
            {
                "instance_id": "greenfield",
                "profile_id": profile,
                "operation_id": "web.search",
                "process_id": f"gateway-{profile}",
                "loaded_config_hash": "a" * 64,
                "loaded_at": RECENT,
                "schema_cache": {
                    "status": "hit",
                    "fingerprint": "b" * 64,
                    "observed_at": RECENT,
                    "ttl_seconds": 300,
                },
                "live_connection": {
                    "status": "connected",
                    "observed_at": RECENT,
                    "ttl_seconds": 120,
                },
                "characteristic_verification": {
                    "status": "pass",
                    "observed_at": RECENT,
                    "ttl_seconds": 300,
                },
                "control": {
                    "consecutive_failures": 0,
                    "failure_class": "none",
                    "retries_used": 0,
                    "circuit_state": "closed",
                    "opened_until": None,
                    "state_change_observed": False,
                },
            }
        )
    return {
        "schema_version": 1,
        "captured_at": NOW,
        "desired_configs": desired,
        "effective_runtimes": effective,
        "schedules": [
            {
                "schedule_id": "research-monitor",
                "configured_enabled": True,
                "next_run_at": "2026-09-21T08:00:00Z",
                "last_run_at": RECENT,
                "last_status": "success",
                "last_success_at": RECENT,
                "freshness_ttl_seconds": 3600,
            }
        ],
        "backups": [
            {
                "backup_id": "research-state",
                "expected_enabled": True,
                "last_attempt_at": RECENT,
                "last_verified_success_at": RECENT,
                "integrity_status": "pass",
                "max_age_seconds": 3600,
            }
        ],
    }


class EffectiveRuntimeTests(unittest.TestCase):
    def test_ready_distinguishes_all_runtime_layers(self) -> None:
        result = reconcile_effective_runtime(request())
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["profile_parity"]["status"], "pass")
        self.assertEqual(result["desired_config_snapshot_count"], 2)
        self.assertEqual(result["effective_runtime_snapshot_count"], 2)
        self.assertTrue(all(row["status"] == "ready" for row in result["capabilities"]))
        self.assertEqual(result["schedules"][0]["computed_status"], "healthy")
        self.assertEqual(result["backups"][0]["computed_status"], "healthy")

    def test_disk_and_loaded_config_are_not_conflated(self) -> None:
        data = request()
        data["effective_runtimes"][0]["loaded_config_hash"] = "c" * 64
        data["effective_runtimes"][0]["control"]["state_change_observed"] = True
        result = reconcile_effective_runtime(data)
        row = result["capabilities"][0]
        self.assertEqual(row["status"], "misconfigured")
        self.assertFalse(row["config_matches"])
        self.assertTrue(row["restart_required"])
        self.assertEqual(row["desired_config_hash"], "a" * 64)
        self.assertEqual(row["loaded_config_hash"], "c" * 64)
        self.assertTrue(row["restart_allowed"])
        self.assertEqual(row["next_action"], "single_restart_after_state_change")

    def test_stale_schema_cache_is_visible_even_when_connection_is_live(self) -> None:
        data = request()
        data["effective_runtimes"][0]["schema_cache"]["observed_at"] = OLD
        result = reconcile_effective_runtime(data)
        row = result["capabilities"][0]
        self.assertEqual(row["status"], "stale")
        self.assertIn("schema_cache", row["stale_controls"])
        self.assertEqual(row["live_connection_status"], "connected")

    def test_cached_schema_without_connection_is_not_a_verified_failure(self) -> None:
        data = request()
        data["effective_runtimes"][0]["live_connection"]["status"] = "unknown"
        data["effective_runtimes"][0]["characteristic_verification"]["status"] = (
            "not_run"
        )
        result = reconcile_effective_runtime(data)
        row = result["capabilities"][0]
        self.assertEqual(row["status"], "cache_only")
        self.assertFalse(row["connected"])
        self.assertFalse(row["restart_allowed"])
        self.assertNotEqual(result["status"], "ready")
        data["effective_runtimes"][0]["live_connection"]["status"] = "error"
        row = reconcile_effective_runtime(data)["capabilities"][0]
        self.assertEqual(row["status"], "failed")
        self.assertFalse(row["connected"])

    def test_permanent_failure_opens_circuit_without_restart_storm(self) -> None:
        data = request()
        control = data["effective_runtimes"][0]["control"]
        control.update({"failure_class": "permanent", "consecutive_failures": 1})
        result = reconcile_effective_runtime(data)
        row = result["capabilities"][0]
        self.assertEqual(row["next_circuit_state"], "open")
        self.assertFalse(row["retry_allowed"])
        self.assertFalse(row["restart_allowed"])
        self.assertTrue(result["restart_storm_prevented"])

    def test_transient_failure_has_bounded_retry_then_opens(self) -> None:
        data = request()
        control = data["effective_runtimes"][0]["control"]
        control.update(
            {"failure_class": "transient", "consecutive_failures": 1, "retries_used": 1}
        )
        first = reconcile_effective_runtime(data)["capabilities"][0]
        self.assertTrue(first["retry_allowed"])
        self.assertEqual(first["retries_remaining"], 1)
        control.update({"consecutive_failures": 3, "retries_used": 2})
        exhausted = reconcile_effective_runtime(data)["capabilities"][0]
        self.assertFalse(exhausted["retry_allowed"])
        self.assertEqual(exhausted["next_circuit_state"], "open")

    def test_profile_contract_mismatch_is_explicit(self) -> None:
        data = request()
        data["desired_configs"][1]["schema_fingerprint"] = "d" * 64
        data["effective_runtimes"][1]["schema_cache"]["fingerprint"] = "d" * 64
        result = reconcile_effective_runtime(data)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["profile_parity"]["status"], "mismatch")

    def test_schedule_and_backup_statuses_are_computed(self) -> None:
        data = request()
        data["schedules"][0]["last_status"] = "failure"
        data["backups"][0]["last_verified_success_at"] = OLD
        result = reconcile_effective_runtime(data)
        self.assertEqual(result["schedules"][0]["computed_status"], "failed")
        self.assertEqual(result["backups"][0]["computed_status"], "stale")
        self.assertEqual(len(result["supporting_control_failures"]), 2)

    def test_capability_sets_must_match_exactly(self) -> None:
        data = request()
        data["effective_runtimes"].pop()
        with self.assertRaisesRegex(BridgeError, "Наблюдения не совпадают"):
            reconcile_effective_runtime(data)


if __name__ == "__main__":
    unittest.main()
