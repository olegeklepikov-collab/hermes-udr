from __future__ import annotations

import unittest

from hermes_foundation_bridge.gates import (
    FAULT_CLASSES,
    GATES,
    assess_failure_suite,
    evaluate_gate_vector,
)


def failure_request() -> dict:
    return {
        "schema_version": 1,
        "suite_id": "FAILURE-248",
        "faults": [
            {
                "fault_class": fault,
                "injected": True,
                "observed_state": "recovered",
                "recovery_verified": True,
                "false_success": False,
                "cross_boundary_corruption": False,
                "receipt_ref": f"RECEIPT-{index}",
            }
            for index, fault in enumerate(FAULT_CLASSES)
        ],
    }


def gate_request() -> dict:
    return {
        "schema_version": 1,
        "evaluated_at": "2026-09-21T08:00:00Z",
        "failure_suite_status": "pass",
        "gates": [
            {
                "gate_id": gate,
                "status": "pass",
                "receipt_ref": f"RECEIPT-{gate}",
                "valid_until": "2026-09-22T08:00:00Z",
                "owner": "FOUNDATION-OWNER",
                "scope": "greenfield-staging",
            }
            for gate in GATES
        ],
        "research_qualification_status": "not_verified",
    }


class FoundationGateTests(unittest.TestCase):
    def test_tc248_all_nine_faults_have_honest_recovery(self) -> None:
        result = assess_failure_suite(failure_request())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["fault_class_count"], 9)
        self.assertTrue(result["honest_state_preserved"])
        self.assertFalse(result["production_activation_allowed"])

    def test_false_success_or_missing_recovery_blocks_suite(self) -> None:
        request = failure_request()
        request["faults"][0]["false_success"] = True
        request["faults"][1]["recovery_verified"] = False
        result = assess_failure_suite(request)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["failed_fault_classes"], list(FAULT_CLASSES[:2]))

    def test_tc249_g7_failure_blocks_activation_without_research_promotion(
        self,
    ) -> None:
        request = gate_request()
        request["gates"][7]["status"] = "fail"
        result = evaluate_gate_vector(request)
        self.assertEqual(result["status"], "production_blocked")
        self.assertEqual(result["failed_gates"], ["G7"])
        self.assertFalse(result["research_qualification_inherited"])
        self.assertEqual(result["research_qualification_after"], "not_verified")

    def test_all_current_gates_make_candidate_not_implicit_research_pass(self) -> None:
        result = evaluate_gate_vector(gate_request())
        self.assertEqual(result["status"], "activation_candidate")
        self.assertTrue(result["foundation_ready"])
        self.assertEqual(result["research_qualification_after"], "not_verified")

    def test_expired_gate_is_failed(self) -> None:
        request = gate_request()
        request["gates"][0]["valid_until"] = "2026-09-20T08:00:00Z"
        self.assertEqual(evaluate_gate_vector(request)["failed_gates"], ["G0"])


if __name__ == "__main__":
    unittest.main()
