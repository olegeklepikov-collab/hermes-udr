"""Research-result G0–G8 vector, separate from Hermes foundation gates."""

from __future__ import annotations

from typing import Any

from .canonical import verify_receipt_hash, with_receipt_hash

_GATES = tuple(f"G{number}" for number in range(9))
_STATUSES = {"pass", "partial", "fail", "not_applicable"}


def assess_research_gate_vector(run_id: str, gates: object) -> dict[str, Any]:
    if type(run_id) is not str or not run_id or type(gates) is not list:
        raise ValueError("research_gate_inputs_invalid")
    indexed: dict[str, dict[str, Any]] = {}
    for row in gates:
        if type(row) is not dict or set(row) != {
            "gate",
            "status",
            "receipt_evidence",
            "reason",
        }:
            raise ValueError("research_gate_row_invalid")
        gate, status, receipts, reason = (
            row["gate"],
            row["status"],
            row["receipt_evidence"],
            row["reason"],
        )
        if (
            gate not in _GATES
            or gate in indexed
            or status not in _STATUSES
            or type(receipts) is not list
            or any(
                type(value) is not dict or not verify_receipt_hash(value)
                for value in receipts
            )
            or len({value["receipt_hash"] for value in receipts}) != len(receipts)
            or type(reason) is not str
            or not reason.strip()
            or (status == "pass" and not receipts)
        ):
            raise ValueError("research_gate_row_invalid")
        indexed[gate] = {
            "gate": gate,
            "status": status,
            "receipt_hashes": [receipt["receipt_hash"] for receipt in receipts],
            "reason": reason.strip(),
        }
    if set(indexed) != set(_GATES):
        raise ValueError("research_gate_vector_incomplete")
    ordered = [indexed[gate] for gate in _GATES]
    applicable = [row for row in ordered if row["status"] != "not_applicable"]
    complete = bool(applicable) and all(row["status"] == "pass" for row in applicable)
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaResearchQualificationGateVector",
            "run_id": run_id,
            "namespace": "research_result_not_foundation_runtime",
            "gates": ordered,
            "pass_count": sum(row["status"] == "pass" for row in ordered),
            "partial_count": sum(row["status"] == "partial" for row in ordered),
            "fail_count": sum(row["status"] == "fail" for row in ordered),
            "not_applicable_count": sum(
                row["status"] == "not_applicable" for row in ordered
            ),
            "research_qualification_complete": complete,
            "result_delivery_blocked": False,
            "full_qualification_claim_allowed": complete,
            "release_authorized": False,
        }
    )


def gate_row(
    gate: str, status: str, receipts: list[dict[str, Any]], reason: str
) -> dict[str, Any]:
    if any(not verify_receipt_hash(receipt) for receipt in receipts):
        raise ValueError("research_gate_receipt_invalid")
    return {
        "gate": gate,
        "status": status,
        "receipt_evidence": receipts,
        "reason": reason,
    }
