"""Dependency admission, result ingest, and cancellation controls."""

from __future__ import annotations

from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

_TEXT = {"type": "string", "minLength": 1}
_CONTROL_TYPES = {"dependency_gate", "result_ingest", "cancellation"}

WORK_EXECUTION_ASSESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "control_type", "payload"],
    "properties": {
        "schema_version": {"const": 1},
        "control_type": {"enum": sorted(_CONTROL_TYPES)},
        "payload": {"type": "object"},
    },
}


def _dependency(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {"packet_ref", "expected_inputs", "available_inputs"},
        "request.payload",
    )
    available = {}
    for index, raw in enumerate(
        require_list(payload["available_inputs"], "request.payload.available_inputs")
    ):
        path = f"request.payload.available_inputs[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"input_ref", "version", "content_hash", "status"}, path
        )
        ref = require_string(row["input_ref"], f"{path}.input_ref")
        available[ref] = {
            "version": require_int(row["version"], f"{path}.version", minimum=1),
            "content_hash": require_string(row["content_hash"], f"{path}.content_hash"),
            "status": require_string(row["status"], f"{path}.status"),
        }
    issues = []
    accepted_inputs = []
    for index, raw in enumerate(
        require_list(payload["expected_inputs"], "request.payload.expected_inputs")
    ):
        path = f"request.payload.expected_inputs[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"input_ref", "version", "content_hash"}, path)
        ref = require_string(row["input_ref"], f"{path}.input_ref")
        expected = {
            "version": require_int(row["version"], f"{path}.version", minimum=1),
            "content_hash": require_string(row["content_hash"], f"{path}.content_hash"),
        }
        actual = available.get(ref)
        if (
            actual is None
            or actual["status"] != "accepted"
            or any(actual[key] != expected[key] for key in ("version", "content_hash"))
        ):
            issues.append(f"dependency_version_unaccepted:{ref}")
        else:
            accepted_inputs.append(ref)
    return {
        "packet_ref": require_string(
            payload["packet_ref"], "request.payload.packet_ref"
        ),
        "execution_status": "ready" if not issues else "waiting_dependency",
        "accepted_input_refs": accepted_inputs,
        "dispatch_allowed": not issues,
        "issues": issues,
    }


def _ingest(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload, {"result_ref", "accepted", "incoming"}, "request.payload"
    )
    accepted = require_mapping(payload["accepted"], "request.payload.accepted")
    incoming = require_mapping(payload["incoming"], "request.payload.incoming")
    for path, row in (
        ("request.payload.accepted", accepted),
        ("request.payload.incoming", incoming),
    ):
        require_exact_keys(row, {"version", "content_hash", "covered_scope"}, path)
    accepted_version = require_int(
        accepted["version"], "request.payload.accepted.version", minimum=1
    )
    incoming_version = require_int(
        incoming["version"], "request.payload.incoming.version", minimum=1
    )
    accepted_hash = require_string(
        accepted["content_hash"], "request.payload.accepted.content_hash"
    )
    incoming_hash = require_string(
        incoming["content_hash"], "request.payload.incoming.content_hash"
    )
    duplicate = accepted_version == incoming_version and accepted_hash == incoming_hash
    conflict = accepted_version == incoming_version and accepted_hash != incoming_hash
    status = (
        "duplicate"
        if duplicate
        else "conflict"
        if conflict
        else "new_revision_candidate"
    )
    return {
        "result_ref": require_string(
            payload["result_ref"], "request.payload.result_ref"
        ),
        "status": status,
        "accepted_version_preserved": True,
        "included_in_synthesis": not duplicate and not conflict,
        "duplicate_count_increment": 1 if duplicate else 0,
        "conflict_requires_review": conflict,
        "issues": ["result_version_conflict"] if conflict else [],
    }


def _cancellation(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "cancel_requested",
        "new_dispatch_count",
        "cancelable_workers_stopped",
        "noncancelable_operations",
    }
    require_exact_keys(payload, keys, "request.payload")
    cancelled = require_bool(
        payload["cancel_requested"], "request.payload.cancel_requested"
    )
    new_dispatches = require_int(
        payload["new_dispatch_count"], "request.payload.new_dispatch_count"
    )
    workers_stopped = require_bool(
        payload["cancelable_workers_stopped"],
        "request.payload.cancelable_workers_stopped",
    )
    operations = []
    for index, raw in enumerate(
        require_list(
            payload["noncancelable_operations"],
            "request.payload.noncancelable_operations",
        )
    ):
        path = f"request.payload.noncancelable_operations[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"operation_ref", "state", "reconciliation_required"}, path
        )
        operations.append(
            {
                "operation_ref": require_string(
                    row["operation_ref"], f"{path}.operation_ref"
                ),
                "state": require_string(row["state"], f"{path}.state"),
                "reconciliation_required": require_bool(
                    row["reconciliation_required"], f"{path}.reconciliation_required"
                ),
            }
        )
    issues = []
    if cancelled and new_dispatches:
        issues.append("dispatch_after_cancel")
    if cancelled and not workers_stopped:
        issues.append("cancelable_worker_not_stopped")
    if any(not row["reconciliation_required"] for row in operations):
        issues.append("noncancelable_operation_untracked")
    return {
        "cancel_requested": cancelled,
        "new_dispatch_count": new_dispatches,
        "cancelable_workers_stopped": workers_stopped,
        "noncancelable_operations": operations,
        "resume_requires_reconciliation": bool(operations),
        "issues": issues,
    }


_ASSESSORS = {
    "dependency_gate": _dependency,
    "result_ingest": _ingest,
    "cancellation": _cancellation,
}


def assess_work_execution(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "control_type", "payload"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    control_type = require_string(data["control_type"], "request.control_type")
    if control_type not in _ASSESSORS:
        fail("invalid_control_type", "request.control_type", "Неизвестный контроль.")
    result = _ASSESSORS[control_type](
        require_mapping(data["payload"], "request.payload")
    )
    issues = [str(item) for item in result.get("issues", [])]  # type: ignore[union-attr]
    return with_receipt_hash(
        {
            "contract": "WorkExecutionReceipt",
            "control_type": control_type,
            "status": "accepted" if not issues else "blocked",
            **result,
        }
    )
