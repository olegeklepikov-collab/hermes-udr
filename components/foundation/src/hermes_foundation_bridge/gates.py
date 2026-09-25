"""Foundation failure-suite and independent G0-G8 activation decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .canonical import receipt
from .errors import fail
from .validation import boolean, exact, identifier, mapping, string

FAULT_CLASSES = (
    "agentmemory",
    "graphiti",
    "zvec_writer",
    "dolt",
    "telegram",
    "gateway",
    "sqlite_lease",
    "sanitizer",
    "backup",
)
GATES = tuple(f"G{index}" for index in range(9))


def _closed(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


FAILURE_SUITE_SCHEMA = _closed(
    ["schema_version", "suite_id", "faults"],
    {
        "schema_version": {"const": 1},
        "suite_id": {"type": "string", "minLength": 1},
        "faults": {
            "type": "array",
            "minItems": 9,
            "maxItems": 9,
            "items": {"type": "object"},
        },
    },
)
GATE_VECTOR_SCHEMA = _closed(
    [
        "schema_version",
        "evaluated_at",
        "failure_suite_status",
        "gates",
        "research_qualification_status",
    ],
    {
        "schema_version": {"const": 1},
        "evaluated_at": {"type": "string", "format": "date-time"},
        "failure_suite_status": {"enum": ["pass", "fail"]},
        "gates": {
            "type": "array",
            "minItems": 9,
            "maxItems": 9,
            "items": {"type": "object"},
        },
        "research_qualification_status": {"type": "string", "minLength": 1},
    },
)


def _time(value: object, path: str) -> datetime:
    text = string(value, path)
    try:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith("Z") else text
        )
    except ValueError:
        fail("invalid_timestamp", path, "Ожидалась временная метка ISO 8601.")
    if parsed.tzinfo is None:
        fail("timezone_required", path, "Временная зона обязательна.")
    return parsed.astimezone(UTC)


def assess_failure_suite(request: object) -> dict[str, Any]:
    data = mapping(request, "request")
    exact(data, {"schema_version", "suite_id", "faults"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    suite_id = identifier(data["suite_id"], "request.suite_id")
    if type(data["faults"]) is not list:
        fail("invalid_type", "request.faults", "Ожидался список.")
    rows: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(data["faults"]):
        path = f"request.faults[{index}]"
        row = mapping(raw, path)
        exact(
            row,
            {
                "fault_class",
                "injected",
                "observed_state",
                "recovery_verified",
                "false_success",
                "cross_boundary_corruption",
                "receipt_ref",
            },
            path,
        )
        fault = identifier(row["fault_class"], f"{path}.fault_class")
        if fault not in FAULT_CLASSES or fault in rows:
            fail(
                "invalid_fault_class",
                f"{path}.fault_class",
                "Класс отказа неизвестен или повторён.",
            )
        state = string(row["observed_state"], f"{path}.observed_state")
        if state not in {"degraded", "unknown", "blocked", "recovered"}:
            fail(
                "invalid_fault_state",
                f"{path}.observed_state",
                "Недопустимое состояние отказа.",
            )
        injected = boolean(row["injected"], f"{path}.injected")
        recovery = boolean(row["recovery_verified"], f"{path}.recovery_verified")
        false_success = boolean(row["false_success"], f"{path}.false_success")
        corruption = boolean(
            row["cross_boundary_corruption"], f"{path}.cross_boundary_corruption"
        )
        ref = identifier(row["receipt_ref"], f"{path}.receipt_ref")
        issues = []
        if not injected:
            issues.append("fault_not_injected")
        if state == "recovered" and not recovery:
            issues.append("recovery_not_verified")
        if false_success:
            issues.append("false_success")
        if corruption:
            issues.append("cross_boundary_corruption")
        rows[fault] = {
            "fault_class": fault,
            "status": "pass" if not issues else "fail",
            "observed_state": state,
            "recovery_verified": recovery,
            "receipt_ref": ref,
            "issues": issues,
        }
    if set(rows) != set(FAULT_CLASSES):
        fail(
            "failure_suite_incomplete",
            "request.faults",
            "Требуются все девять классов отказов.",
        )
    failed = [fault for fault in FAULT_CLASSES if rows[fault]["status"] == "fail"]
    return receipt(
        {
            "schema_version": 1,
            "contract": "FoundationFailureSuiteReceipt",
            "status": "pass" if not failed else "blocked",
            "suite_id": suite_id,
            "fault_class_count": len(rows),
            "failed_fault_classes": failed,
            "faults": [rows[fault] for fault in FAULT_CLASSES],
            "honest_state_preserved": not any(
                "false_success" in rows[fault]["issues"] for fault in rows
            ),
            "production_activation_allowed": False,
        }
    )


def evaluate_gate_vector(request: object) -> dict[str, Any]:
    data = mapping(request, "request")
    exact(
        data,
        {
            "schema_version",
            "evaluated_at",
            "failure_suite_status",
            "gates",
            "research_qualification_status",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    now = _time(data["evaluated_at"], "request.evaluated_at")
    suite_status = string(data["failure_suite_status"], "request.failure_suite_status")
    if suite_status not in {"pass", "fail"}:
        fail(
            "invalid_failure_suite_status",
            "request.failure_suite_status",
            "Недопустимый статус.",
        )
    if type(data["gates"]) is not list:
        fail("invalid_type", "request.gates", "Ожидался список.")
    rows: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(data["gates"]):
        path = f"request.gates[{index}]"
        row = mapping(raw, path)
        exact(
            row,
            {"gate_id", "status", "receipt_ref", "valid_until", "owner", "scope"},
            path,
        )
        gate = identifier(row["gate_id"], f"{path}.gate_id")
        if gate not in GATES or gate in rows:
            fail("invalid_gate", f"{path}.gate_id", "Gate неизвестен или повторён.")
        declared = string(row["status"], f"{path}.status")
        if declared not in {"pass", "fail"}:
            fail("invalid_gate_status", f"{path}.status", "Недопустимый статус gate.")
        valid_until = _time(row["valid_until"], f"{path}.valid_until")
        current = valid_until >= now
        effective = "pass" if declared == "pass" and current else "fail"
        rows[gate] = {
            "gate_id": gate,
            "status": effective,
            "declared_status": declared,
            "receipt_ref": identifier(row["receipt_ref"], f"{path}.receipt_ref"),
            "valid_until": valid_until.isoformat(),
            "current": current,
            "owner": identifier(row["owner"], f"{path}.owner"),
            "scope": string(row["scope"], f"{path}.scope"),
        }
    if set(rows) != set(GATES):
        fail("gate_vector_incomplete", "request.gates", "Требуются G0-G8.")
    failed = [gate for gate in GATES if rows[gate]["status"] == "fail"]
    if suite_status != "pass":
        failed.append("FAILURE_SUITE")
    research = string(
        data["research_qualification_status"], "request.research_qualification_status"
    )
    allowed = not failed
    return receipt(
        {
            "schema_version": 1,
            "contract": "FoundationGateVector",
            "status": "activation_candidate" if allowed else "production_blocked",
            "evaluated_at": now.isoformat(),
            "gates": [rows[gate] for gate in GATES],
            "failed_gates": failed,
            "foundation_ready": allowed,
            "production_activation_allowed": allowed,
            "research_qualification_before": research,
            "research_qualification_after": research,
            "research_qualification_inherited": False,
        }
    )
