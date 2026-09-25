"""Decision-first business research design without unauthorized data collection."""

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

_METHOD_KINDS = {
    "desk_research",
    "internal_observational",
    "external_observational",
    "survey",
    "interview",
    "experiment",
}
_INPUT_STATES = {"available", "requires_collection", "unavailable"}
_TEXT = {"type": "string", "minLength": 1}
_NULLABLE_TEXT = {"type": ["string", "null"]}
_STRING_ARRAY = {
    "type": "array",
    "maxItems": 1000,
    "uniqueItems": True,
    "items": _TEXT,
}
_METHOD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "method_id",
        "method_kind",
        "rank",
        "can_change_decision",
        "allowed",
        "capabilities_sufficient",
        "input_state",
        "requires_contact",
        "requires_intervention",
        "authorization_receipt_ref",
        "expected_output",
        "missing_inputs",
    ],
    "properties": {
        "method_id": _TEXT,
        "method_kind": {"enum": sorted(_METHOD_KINDS)},
        "rank": {"type": "integer", "minimum": 0},
        "can_change_decision": {"type": "boolean"},
        "allowed": {"type": "boolean"},
        "capabilities_sufficient": {"type": "boolean"},
        "input_state": {"enum": sorted(_INPUT_STATES)},
        "requires_contact": {"type": "boolean"},
        "requires_intervention": {"type": "boolean"},
        "authorization_receipt_ref": _NULLABLE_TEXT,
        "expected_output": _TEXT,
        "missing_inputs": _STRING_ARRAY,
    },
}
BUSINESS_DESIGN_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "decision_context",
        "evidence_classes",
        "methods",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "decision_context": {
            "type": "object",
            "additionalProperties": False,
            "required": ["decision", "observable_criterion", "intended_use"],
            "properties": {
                "decision": _TEXT,
                "observable_criterion": _TEXT,
                "intended_use": _TEXT,
            },
        },
        "evidence_classes": {
            "type": "object",
            "additionalProperties": False,
            "required": ["external_signals", "internal_metrics", "causal_effects"],
            "properties": {
                "external_signals": _STRING_ARRAY,
                "internal_metrics": _STRING_ARRAY,
                "causal_effects": _STRING_ARRAY,
            },
        },
        "methods": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": _METHOD_SCHEMA,
        },
    },
}


def _strings(value: object, path: str) -> list[str]:
    rows = require_list(value, path)
    if len(rows) > 1000:
        fail("size_limit", path, "Массив превышает 1000 элементов.")
    result = [
        require_string(item, f"{path}[{index}]") for index, item in enumerate(rows)
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повторный элемент запрещён.")
    return result


def assess_business_design(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {"schema_version", "run_id", "decision_context", "evidence_classes", "methods"},
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    context = require_mapping(data["decision_context"], "request.decision_context")
    require_exact_keys(
        context,
        {"decision", "observable_criterion", "intended_use"},
        "request.decision_context",
    )
    normalized_context = {
        key: require_string(context[key], f"request.decision_context.{key}")
        for key in ("decision", "observable_criterion", "intended_use")
    }
    evidence = require_mapping(data["evidence_classes"], "request.evidence_classes")
    class_names = ("external_signals", "internal_metrics", "causal_effects")
    require_exact_keys(evidence, set(class_names), "request.evidence_classes")
    normalized_evidence = {
        name: _strings(evidence[name], f"request.evidence_classes.{name}")
        for name in class_names
    }
    ownership: dict[str, str] = {}
    for class_name, refs in normalized_evidence.items():
        for ref in refs:
            if ref in ownership:
                fail(
                    "evidence_class_overlap",
                    "request.evidence_classes",
                    "Одна опора не может молча считаться внешним сигналом, внутренней метрикой или причинным эффектом.",
                )
            ownership[ref] = class_name

    raw_methods = require_list(data["methods"], "request.methods")
    if not raw_methods or len(raw_methods) > 100:
        fail(
            "invalid_method_count", "request.methods", "Требуется от 1 до 100 методов."
        )
    methods: list[dict[str, Any]] = []
    method_ids: set[str] = set()
    assessments: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_methods):
        path = f"request.methods[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, set(_METHOD_SCHEMA["required"]), path)
        method_id = require_string(row["method_id"], f"{path}.method_id")
        if method_id in method_ids:
            fail("duplicate_method", f"{path}.method_id", "Повторный метод.")
        method_ids.add(method_id)
        method_kind = require_string(row["method_kind"], f"{path}.method_kind")
        input_state = require_string(row["input_state"], f"{path}.input_state")
        if method_kind not in _METHOD_KINDS or input_state not in _INPUT_STATES:
            fail("invalid_method", path, "Неверный вид метода или состояние входа.")
        requires_contact = require_bool(
            row["requires_contact"], f"{path}.requires_contact"
        )
        requires_intervention = require_bool(
            row["requires_intervention"], f"{path}.requires_intervention"
        )
        authorization = row["authorization_receipt_ref"]
        if authorization is not None:
            authorization = require_string(
                authorization, f"{path}.authorization_receipt_ref"
            )
        issues: list[str] = []
        if not require_bool(row["allowed"], f"{path}.allowed"):
            issues.append("method_not_allowed")
        if not require_bool(
            row["capabilities_sufficient"], f"{path}.capabilities_sufficient"
        ):
            issues.append("capabilities_insufficient")
        if not require_bool(row["can_change_decision"], f"{path}.can_change_decision"):
            issues.append("cannot_change_decision")
        if (requires_contact or requires_intervention) and authorization is None:
            issues.append("host_authorization_required")
        if input_state == "unavailable":
            issues.append("inputs_unavailable")
        method = {
            "method_id": method_id,
            "method_kind": method_kind,
            "rank": require_int(row["rank"], f"{path}.rank"),
            "input_state": input_state,
            "requires_contact": requires_contact,
            "requires_intervention": requires_intervention,
            "authorization_receipt_ref": authorization,
            "expected_output": require_string(
                row["expected_output"], f"{path}.expected_output"
            ),
            "missing_inputs": _strings(row["missing_inputs"], f"{path}.missing_inputs"),
            "issues": sorted(issues),
        }
        methods.append(method)
        assessments.append(
            {
                "method_id": method_id,
                "eligible": not issues,
                "input_state": input_state,
                "issues": sorted(issues),
            }
        )
    available = sorted(
        (
            method
            for method in methods
            if not method["issues"] and method["input_state"] == "available"
        ),
        key=lambda method: (method["rank"], method["method_id"]),
    )
    collection = sorted(
        (
            method
            for method in methods
            if not method["issues"] and method["input_state"] == "requires_collection"
        ),
        key=lambda method: (method["rank"], method["method_id"]),
    )
    selected = available[0] if available else None
    if selected:
        status = "design_selected"
    elif collection:
        status = "collection_required"
    elif any("host_authorization_required" in method["issues"] for method in methods):
        status = "authorization_required"
    else:
        status = "blocked"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "BusinessDesignDecisionReceipt",
        "status": status,
        "run_id": run_id,
        "decision_context": normalized_context,
        "evidence_classes": normalized_evidence,
        "selected_method": (
            {
                key: selected[key]
                for key in (
                    "method_id",
                    "method_kind",
                    "rank",
                    "expected_output",
                    "authorization_receipt_ref",
                )
            }
            if selected
            else None
        ),
        "collection_program": [
            {
                "method_id": method["method_id"],
                "method_kind": method["method_kind"],
                "expected_output": method["expected_output"],
                "missing_inputs": method["missing_inputs"],
                "requires_contact": method["requires_contact"],
                "requires_intervention": method["requires_intervention"],
                "authorization_receipt_ref": method["authorization_receipt_ref"],
            }
            for method in collection
        ],
        "method_assessments": sorted(assessments, key=lambda row: row["method_id"]),
        "fabricated_results": [],
        "contact_performed": False,
        "intervention_performed": False,
        "external_action_performed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)
