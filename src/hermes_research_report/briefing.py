"""Brief, contextualization, role-context, and debrief contracts."""

from __future__ import annotations

from typing import Any

from .canonical import sha256_json, with_receipt_hash
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
_NULLABLE_TEXT = {"type": ["string", "null"]}
_TEXTS = {"type": "array", "maxItems": 1000, "uniqueItems": True, "items": _TEXT}

BRIEF_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "brief_id",
        "original_text",
        "normalized_question",
        "premises",
        "decision",
        "thresholds",
        "scope",
        "audience",
        "definitions",
        "output_contract_ref",
        "freshness_deadline",
        "acceptance_criteria",
        "failure_criteria",
        "profile_ref",
        "budget_ref",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "brief_id": _TEXT,
        "original_text": _TEXT,
        "normalized_question": _TEXT,
        "premises": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["premise_ref", "text", "status", "basis_ref"],
                "properties": {
                    "premise_ref": _TEXT,
                    "text": _TEXT,
                    "status": {
                        "enum": ["confirmed", "assumed", "disputed", "rejected"]
                    },
                    "basis_ref": _NULLABLE_TEXT,
                },
            },
        },
        "decision": _TEXT,
        "thresholds": _TEXTS,
        "scope": _TEXT,
        "audience": _TEXT,
        "definitions": _TEXTS,
        "output_contract_ref": _TEXT,
        "freshness_deadline": _TEXT,
        "acceptance_criteria": _TEXTS,
        "failure_criteria": _TEXTS,
        "profile_ref": _TEXT,
        "budget_ref": _TEXT,
    },
}

CONTEXTUALIZATION_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "context_id",
        "domain",
        "audience",
        "locale",
        "as_of",
        "items",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "context_id": _TEXT,
        "domain": _TEXT,
        "audience": _TEXT,
        "locale": _TEXT,
        "as_of": _TEXT,
        "items": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item_ref", "category", "text", "source_ref"],
                "properties": {
                    "item_ref": _TEXT,
                    "category": {
                        "enum": ["confirmed_context", "assumption", "user_requirement"]
                    },
                    "text": _TEXT,
                    "source_ref": _NULLABLE_TEXT,
                },
            },
        },
    },
}

CONTEXT_PACKAGE_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "package_id",
        "target_project_id",
        "role_ref",
        "purpose",
        "candidates",
        "constraints",
        "permissions",
        "known_gaps",
        "required_schema_refs",
        "gate_refs",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "package_id": _TEXT,
        "target_project_id": _TEXT,
        "role_ref": _TEXT,
        "purpose": _TEXT,
        "candidates": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "object_ref",
                    "project_id",
                    "current",
                    "authorized",
                    "contains_secret",
                    "kind",
                ],
                "properties": {
                    "object_ref": _TEXT,
                    "project_id": _TEXT,
                    "current": {"type": "boolean"},
                    "authorized": {"type": "boolean"},
                    "contains_secret": {"type": "boolean"},
                    "kind": _TEXT,
                },
            },
        },
        "constraints": _TEXTS,
        "permissions": _TEXTS,
        "known_gaps": _TEXTS,
        "required_schema_refs": _TEXTS,
        "gate_refs": _TEXTS,
    },
}

DEBRIEF_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "debrief_id",
        "plan_ref",
        "planned_items",
        "completed_items",
        "failures",
        "residual_risks",
        "triggers",
        "active_config_ref",
        "active_config_version",
        "active_config_hash",
        "improvement_proposals",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "debrief_id": _TEXT,
        "plan_ref": _TEXT,
        "planned_items": _TEXTS,
        "completed_items": _TEXTS,
        "failures": _TEXTS,
        "residual_risks": _TEXTS,
        "triggers": _TEXTS,
        "active_config_ref": _TEXT,
        "active_config_version": {"type": "integer", "minimum": 1},
        "active_config_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "improvement_proposals": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "proposal_ref",
                    "field",
                    "current_value",
                    "proposed_value",
                    "reason",
                    "regression_suite_ref",
                ],
                "properties": {
                    "proposal_ref": _TEXT,
                    "field": _TEXT,
                    "current_value": _TEXT,
                    "proposed_value": _TEXT,
                    "reason": _TEXT,
                    "regression_suite_ref": _TEXT,
                },
            },
        },
    },
}


def _schema(request: object, fields: set[str]) -> dict[str, object]:
    data = require_mapping(request, "request")
    require_exact_keys(data, fields, "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    return data


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{i}]")
        for i, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_value", path, "Повтор значения запрещён.")
    return result


def _optional(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def build_brief(request: object) -> dict[str, Any]:
    data = _schema(request, set(BRIEF_BUILD_SCHEMA["required"]))
    original = require_string(data["original_text"], "request.original_text")
    premises = []
    premise_refs: set[str] = set()
    for index, raw in enumerate(require_list(data["premises"], "request.premises")):
        path = f"request.premises[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"premise_ref", "text", "status", "basis_ref"}, path)
        ref = require_string(row["premise_ref"], f"{path}.premise_ref")
        if ref in premise_refs:
            fail("duplicate_premise", f"{path}.premise_ref", "Повтор посылки.")
        premise_refs.add(ref)
        status = require_string(row["status"], f"{path}.status")
        if status not in {"confirmed", "assumed", "disputed", "rejected"}:
            fail("invalid_premise_status", f"{path}.status", "Неизвестный статус.")
        premises.append(
            {
                "premise_ref": ref,
                "text": require_string(row["text"], f"{path}.text"),
                "status": status,
                "basis_ref": _optional(row["basis_ref"], f"{path}.basis_ref"),
            }
        )
    acceptance = _strings(data["acceptance_criteria"], "request.acceptance_criteria")
    failures = _strings(data["failure_criteria"], "request.failure_criteria")
    missing = []
    if not acceptance:
        missing.append("request.acceptance_criteria")
    if not failures:
        missing.append("request.failure_criteria")
    brief = {
        "brief_id": require_string(data["brief_id"], "request.brief_id"),
        "original_text": original,
        "normalized_question": require_string(
            data["normalized_question"], "request.normalized_question"
        ),
        "premises": premises,
        "decision": require_string(data["decision"], "request.decision"),
        "thresholds": _strings(data["thresholds"], "request.thresholds"),
        "scope": require_string(data["scope"], "request.scope"),
        "audience": require_string(data["audience"], "request.audience"),
        "definitions": _strings(data["definitions"], "request.definitions"),
        "output_contract_ref": require_string(
            data["output_contract_ref"], "request.output_contract_ref"
        ),
        "freshness_deadline": require_string(
            data["freshness_deadline"], "request.freshness_deadline"
        ),
        "acceptance_criteria": acceptance,
        "failure_criteria": failures,
        "profile_ref": require_string(data["profile_ref"], "request.profile_ref"),
        "budget_ref": require_string(data["budget_ref"], "request.budget_ref"),
    }
    brief["content_hash"] = sha256_json(brief)
    payload = {
        "schema_version": 1,
        "contract": "BriefDecisionReceipt",
        "status": "brief_ready" if not missing else "needs_clarification",
        "brief": brief,
        "disputed_or_rejected_premise_refs": sorted(
            row["premise_ref"]
            for row in premises
            if row["status"] in {"disputed", "rejected"}
        ),
        "missing_details": missing,
        "original_text_changed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def build_contextualization(request: object) -> dict[str, Any]:
    data = _schema(request, set(CONTEXTUALIZATION_BUILD_SCHEMA["required"]))
    grouped: dict[str, list[dict[str, str | None]]] = {
        key: [] for key in ("confirmed_context", "assumption", "user_requirement")
    }
    seen: set[str] = set()
    for index, raw in enumerate(require_list(data["items"], "request.items")):
        path = f"request.items[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"item_ref", "category", "text", "source_ref"}, path)
        ref = require_string(row["item_ref"], f"{path}.item_ref")
        if ref in seen:
            fail("duplicate_context_item", f"{path}.item_ref", "Повтор контекста.")
        seen.add(ref)
        category = require_string(row["category"], f"{path}.category")
        if category not in grouped:
            fail(
                "invalid_context_category", f"{path}.category", "Неизвестная категория."
            )
        grouped[category].append(
            {
                "item_ref": ref,
                "text": require_string(row["text"], f"{path}.text"),
                "source_ref": _optional(row["source_ref"], f"{path}.source_ref"),
            }
        )
    record = {
        "context_id": require_string(data["context_id"], "request.context_id"),
        "domain": require_string(data["domain"], "request.domain"),
        "audience": require_string(data["audience"], "request.audience"),
        "locale": require_string(data["locale"], "request.locale"),
        "as_of": require_string(data["as_of"], "request.as_of"),
        **grouped,
    }
    record["content_hash"] = sha256_json(record)
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "ContextualizationReceipt",
            "status": "contextualized",
            "contextualization": record,
            "categories_merged": False,
            "persistence_applied": False,
        }
    )


def build_context_package(request: object) -> dict[str, Any]:
    data = _schema(request, set(CONTEXT_PACKAGE_BUILD_SCHEMA["required"]))
    target = require_string(data["target_project_id"], "request.target_project_id")
    included: list[str] = []
    excluded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(require_list(data["candidates"], "request.candidates")):
        path = f"request.candidates[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "object_ref",
                "project_id",
                "current",
                "authorized",
                "contains_secret",
                "kind",
            },
            path,
        )
        ref = require_string(row["object_ref"], f"{path}.object_ref")
        if ref in seen:
            fail("duplicate_candidate", f"{path}.object_ref", "Повтор объекта.")
        seen.add(ref)
        reasons = []
        if require_string(row["project_id"], f"{path}.project_id") != target:
            reasons.append("cross_project")
        if not require_bool(row["current"], f"{path}.current"):
            reasons.append("stale")
        if not require_bool(row["authorized"], f"{path}.authorized"):
            reasons.append("unauthorized")
        if require_bool(row["contains_secret"], f"{path}.contains_secret"):
            reasons.append("secret")
        require_string(row["kind"], f"{path}.kind")
        if reasons:
            excluded.append(
                {
                    "object_ref": ref,
                    "reasons": sorted(reasons),
                    "content_recorded": False,
                }
            )
        else:
            included.append(ref)
    package = {
        "package_id": require_string(data["package_id"], "request.package_id"),
        "target_project_id": target,
        "role_ref": require_string(data["role_ref"], "request.role_ref"),
        "purpose": require_string(data["purpose"], "request.purpose"),
        "included_refs": sorted(included),
        "constraints": _strings(data["constraints"], "request.constraints"),
        "permissions": _strings(data["permissions"], "request.permissions"),
        "known_gaps": _strings(data["known_gaps"], "request.known_gaps"),
        "required_schema_refs": _strings(
            data["required_schema_refs"], "request.required_schema_refs"
        ),
        "gate_refs": _strings(data["gate_refs"], "request.gate_refs"),
    }
    package["content_hash"] = sha256_json(package)
    payload = {
        "schema_version": 1,
        "contract": "ContextPackageDecisionReceipt",
        "status": "context_package_ready",
        "context_package": package,
        "excluded": sorted(excluded, key=lambda row: row["object_ref"]),
        "excluded_content_recorded": False,
        "secret_values_recorded": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def assess_debrief(request: object) -> dict[str, Any]:
    data = _schema(request, set(DEBRIEF_ASSESS_SCHEMA["required"]))
    version = require_int(
        data["active_config_version"], "request.active_config_version", minimum=1
    )
    proposals = []
    for index, raw in enumerate(
        require_list(data["improvement_proposals"], "request.improvement_proposals")
    ):
        path = f"request.improvement_proposals[{index}]"
        row = require_mapping(raw, path)
        fields = {
            "proposal_ref",
            "field",
            "current_value",
            "proposed_value",
            "reason",
            "regression_suite_ref",
        }
        require_exact_keys(row, fields, path)
        proposals.append(
            {key: require_string(row[key], f"{path}.{key}") for key in sorted(fields)}
        )
    debrief = {
        "debrief_id": require_string(data["debrief_id"], "request.debrief_id"),
        "plan_ref": require_string(data["plan_ref"], "request.plan_ref"),
        "planned_items": _strings(data["planned_items"], "request.planned_items"),
        "completed_items": _strings(data["completed_items"], "request.completed_items"),
        "failures": _strings(data["failures"], "request.failures"),
        "residual_risks": _strings(data["residual_risks"], "request.residual_risks"),
        "triggers": _strings(data["triggers"], "request.triggers"),
        "active_config_ref": require_string(
            data["active_config_ref"], "request.active_config_ref"
        ),
        "active_config_version": version,
        "active_config_hash": require_string(
            data["active_config_hash"], "request.active_config_hash"
        ),
        "improvement_proposals": proposals,
    }
    debrief["content_hash"] = sha256_json(debrief)
    payload = {
        "schema_version": 1,
        "contract": "DebriefDecisionReceipt",
        "status": "debrief_ready",
        "debrief": debrief,
        "proposed_config_revision": version + 1 if proposals else None,
        "regression_and_acceptance_required": bool(proposals),
        "active_configuration_changed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)
