"""Precommitted academic protocol and comparable-effect synthesis gates."""

from __future__ import annotations

import math
from datetime import datetime
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

_REVIEW_TYPES = {"narrative", "scoping", "systematic", "rapid", "meta_analysis"}
_IDENTITY_TYPES = {"study", "publication", "version", "correction", "retraction"}
_IDENTITY_STATES = {"active", "superseded", "retracted"}
_PROTOCOL_REQUIRED = {"systematic", "rapid", "meta_analysis"}
_TEXT = {"type": "string", "minLength": 1}
_NULLABLE_TEXT = {"type": ["string", "null"]}
_STRING_ARRAY = {
    "type": "array",
    "maxItems": 1000,
    "uniqueItems": True,
    "items": _TEXT,
}
_IDENTITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["identity_id", "identity_type", "parent_id", "status"],
    "properties": {
        "identity_id": _TEXT,
        "identity_type": {"enum": sorted(_IDENTITY_TYPES)},
        "parent_id": _NULLABLE_TEXT,
        "status": {"enum": sorted(_IDENTITY_STATES)},
    },
}
ACADEMIC_PROTOCOL_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "run_id", "protocol", "identities"],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "protocol": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "protocol_id",
                "version",
                "review_type",
                "frozen",
                "frozen_at",
                "eligibility_rules",
                "search_strategy_refs",
                "screening_rules",
                "extraction_schema_ref",
                "screening_started",
                "screening_started_at",
                "results_seen_before_freeze",
                "amendments",
            ],
            "properties": {
                "protocol_id": _TEXT,
                "version": {"type": "integer", "minimum": 1},
                "review_type": {"enum": sorted(_REVIEW_TYPES)},
                "frozen": {"type": "boolean"},
                "frozen_at": _NULLABLE_TEXT,
                "eligibility_rules": _STRING_ARRAY,
                "search_strategy_refs": _STRING_ARRAY,
                "screening_rules": _STRING_ARRAY,
                "extraction_schema_ref": _TEXT,
                "screening_started": {"type": "boolean"},
                "screening_started_at": _NULLABLE_TEXT,
                "results_seen_before_freeze": {"type": "boolean"},
                "amendments": {
                    "type": "array",
                    "maxItems": 100,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "amendment_id",
                            "created_at",
                            "reason",
                            "affected_decisions",
                            "approved",
                        ],
                        "properties": {
                            "amendment_id": _TEXT,
                            "created_at": _TEXT,
                            "reason": _TEXT,
                            "affected_decisions": _STRING_ARRAY,
                            "approved": {"type": "boolean"},
                        },
                    },
                },
            },
        },
        "identities": {
            "type": "array",
            "maxItems": 10000,
            "items": _IDENTITY_SCHEMA,
        },
    },
}

_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "result_id",
        "study_id",
        "publication_id",
        "version_id",
        "status",
        "effect_measure",
        "estimate",
        "standard_error",
        "unit",
        "population",
        "intervention",
        "comparator",
        "outcome",
        "timepoint",
        "estimand",
    ],
    "properties": {
        "result_id": _TEXT,
        "study_id": _TEXT,
        "publication_id": _TEXT,
        "version_id": _TEXT,
        "status": {"enum": sorted(_IDENTITY_STATES)},
        "effect_measure": _TEXT,
        "estimate": {"type": "number"},
        "standard_error": {"type": "number", "exclusiveMinimum": 0},
        "unit": _TEXT,
        "population": _TEXT,
        "intervention": _TEXT,
        "comparator": _TEXT,
        "outcome": _TEXT,
        "timepoint": _TEXT,
        "estimand": _TEXT,
    },
}
META_ANALYSIS_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "pooling_requested",
        "results",
        "required_sensitivity",
        "sensitivity_receipts",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "pooling_requested": {"type": "boolean"},
        "results": {"type": "array", "maxItems": 10000, "items": _RESULT_SCHEMA},
        "required_sensitivity": _STRING_ARRAY,
        "sensitivity_receipts": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "receipt_ref", "status"],
                "properties": {
                    "kind": _TEXT,
                    "receipt_ref": _TEXT,
                    "status": {"enum": ["pass", "fail"]},
                },
            },
        },
    },
}


def _strings(value: object, path: str, *, maximum: int = 1000) -> list[str]:
    rows = require_list(value, path)
    if len(rows) > maximum:
        fail("size_limit", path, "Массив превышает предел.")
    result = [
        require_string(item, f"{path}[{index}]") for index, item in enumerate(rows)
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повторный элемент запрещён.")
    return result


def _nullable_text(value: object, path: str) -> str | None:
    if value is None:
        return None
    return require_string(value, path)


def _timestamp(value: str | None, path: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or "T" not in value:
            raise ValueError
    except ValueError:
        fail(
            "invalid_timestamp",
            path,
            "Требуются дата и время ISO 8601 с часовым поясом.",
        )
    return parsed


def assess_academic_protocol(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "run_id", "protocol", "identities"}, "request"
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    protocol = require_mapping(data["protocol"], "request.protocol")
    required_protocol = set(
        ACADEMIC_PROTOCOL_ASSESS_SCHEMA["properties"]["protocol"]["required"]
    )
    require_exact_keys(protocol, required_protocol, "request.protocol")
    protocol_id = require_string(
        protocol["protocol_id"], "request.protocol.protocol_id"
    )
    version = require_int(protocol["version"], "request.protocol.version", minimum=1)
    review_type = require_string(
        protocol["review_type"], "request.protocol.review_type"
    )
    if review_type not in _REVIEW_TYPES:
        fail(
            "invalid_review_type",
            "request.protocol.review_type",
            "Неверный тип обзора.",
        )
    frozen = require_bool(protocol["frozen"], "request.protocol.frozen")
    frozen_at_text = _nullable_text(protocol["frozen_at"], "request.protocol.frozen_at")
    frozen_at = _timestamp(frozen_at_text, "request.protocol.frozen_at")
    screening_started = require_bool(
        protocol["screening_started"], "request.protocol.screening_started"
    )
    screening_at_text = _nullable_text(
        protocol["screening_started_at"], "request.protocol.screening_started_at"
    )
    screening_at = _timestamp(
        screening_at_text, "request.protocol.screening_started_at"
    )
    if frozen != (frozen_at is not None):
        fail(
            "freeze_timestamp_mismatch",
            "request.protocol.frozen_at",
            "Статус freeze и время не совпадают.",
        )
    if screening_started != (screening_at is not None):
        fail(
            "screening_timestamp_mismatch",
            "request.protocol.screening_started_at",
            "Статус screening и время не совпадают.",
        )

    issues: list[str] = []
    if review_type in _PROTOCOL_REQUIRED and not frozen:
        issues.append("protocol_not_frozen")
    if frozen_at and screening_at and frozen_at > screening_at:
        issues.append("screening_started_before_protocol_freeze")
    if require_bool(
        protocol["results_seen_before_freeze"],
        "request.protocol.results_seen_before_freeze",
    ):
        issues.append("results_seen_before_protocol_freeze")
    eligibility = _strings(
        protocol["eligibility_rules"], "request.protocol.eligibility_rules"
    )
    search_refs = _strings(
        protocol["search_strategy_refs"], "request.protocol.search_strategy_refs"
    )
    screening_rules = _strings(
        protocol["screening_rules"], "request.protocol.screening_rules"
    )
    extraction_ref = require_string(
        protocol["extraction_schema_ref"], "request.protocol.extraction_schema_ref"
    )
    if review_type in _PROTOCOL_REQUIRED and not (
        eligibility and search_refs and screening_rules and extraction_ref
    ):
        issues.append("protocol_content_incomplete")

    amendments_raw = require_list(protocol["amendments"], "request.protocol.amendments")
    if len(amendments_raw) > 100:
        fail("size_limit", "request.protocol.amendments", "Слишком много поправок.")
    amendments: list[dict[str, Any]] = []
    amendment_ids: set[str] = set()
    for index, raw in enumerate(amendments_raw):
        path = f"request.protocol.amendments[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {"amendment_id", "created_at", "reason", "affected_decisions", "approved"},
            path,
        )
        amendment_id = require_string(row["amendment_id"], f"{path}.amendment_id")
        if amendment_id in amendment_ids:
            fail("duplicate_amendment", f"{path}.amendment_id", "Повторная поправка.")
        amendment_ids.add(amendment_id)
        approved = require_bool(row["approved"], f"{path}.approved")
        if not approved:
            issues.append(f"unapproved_amendment:{amendment_id}")
        amendments.append(
            {
                "amendment_id": amendment_id,
                "created_at": require_string(row["created_at"], f"{path}.created_at"),
                "reason": require_string(row["reason"], f"{path}.reason"),
                "affected_decisions": _strings(
                    row["affected_decisions"], f"{path}.affected_decisions"
                ),
                "approved": approved,
            }
        )

    identities_raw = require_list(data["identities"], "request.identities")
    if len(identities_raw) > 10000:
        fail("size_limit", "request.identities", "Слишком много идентичностей.")
    identities: dict[str, dict[str, str | None]] = {}
    for index, raw in enumerate(identities_raw):
        path = f"request.identities[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"identity_id", "identity_type", "parent_id", "status"}, path
        )
        identity_id = require_string(row["identity_id"], f"{path}.identity_id")
        if identity_id in identities:
            fail(
                "duplicate_identity",
                f"{path}.identity_id",
                "Идентичности публикации, исследования, версии, исправления и отзыва должны различаться.",
            )
        identity_type = require_string(row["identity_type"], f"{path}.identity_type")
        status = require_string(row["status"], f"{path}.status")
        if identity_type not in _IDENTITY_TYPES or status not in _IDENTITY_STATES:
            fail("invalid_identity", path, "Неверный тип или статус идентичности.")
        parent_id = _nullable_text(row["parent_id"], f"{path}.parent_id")
        identities[identity_id] = {
            "identity_type": identity_type,
            "parent_id": parent_id,
            "status": status,
        }
    allowed_parents = {
        "study": set(),
        "publication": {"study"},
        "version": {"publication"},
        "correction": {"publication", "version"},
        "retraction": {"publication", "version"},
    }
    for identity_id, identity in identities.items():
        parent_id = identity["parent_id"]
        identity_type = str(identity["identity_type"])
        if identity_type == "study":
            if parent_id is not None:
                issues.append(f"study_has_parent:{identity_id}")
            continue
        if parent_id not in identities:
            issues.append(f"identity_parent_missing:{identity_id}")
        elif (
            identities[str(parent_id)]["identity_type"]
            not in allowed_parents[identity_type]
        ):
            issues.append(f"identity_parent_type_invalid:{identity_id}")
    issues = sorted(set(issues))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "AcademicProtocolDecisionReceipt",
        "status": "protocol_ready" if not issues else "blocked",
        "run_id": run_id,
        "protocol_id": protocol_id,
        "protocol_version": version,
        "review_type": review_type,
        "frozen_at": frozen_at_text,
        "screening_started_at": screening_at_text,
        "screening_allowed": not issues,
        "eligibility_rule_count": len(eligibility),
        "search_strategy_count": len(search_refs),
        "screening_rule_count": len(screening_rules),
        "extraction_schema_ref": extraction_ref,
        "amendments": amendments,
        "identity_count": len(identities),
        "identity_type_counts": {
            identity_type: sum(
                row["identity_type"] == identity_type for row in identities.values()
            )
            for identity_type in sorted(_IDENTITY_TYPES)
        },
        "screening_performed_by_decision": False,
        "persistence_applied": False,
        "blocking_issues": issues,
    }
    return with_receipt_hash(payload)


def _finite_number(value: object, path: str, *, positive: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (positive and value <= 0)
    ):
        fail("invalid_number", path, "Требуется конечное допустимое число.")
    return float(value)


def assess_meta_analysis(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "run_id",
            "pooling_requested",
            "results",
            "required_sensitivity",
            "sensitivity_receipts",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    pooling_requested = require_bool(
        data["pooling_requested"], "request.pooling_requested"
    )
    raw_results = require_list(data["results"], "request.results")
    if len(raw_results) > 10000:
        fail("size_limit", "request.results", "Слишком много результатов.")
    results: list[dict[str, Any]] = []
    result_ids: set[str] = set()
    for index, raw in enumerate(raw_results):
        path = f"request.results[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, set(_RESULT_SCHEMA["required"]), path)
        result_id = require_string(row["result_id"], f"{path}.result_id")
        if result_id in result_ids:
            fail("duplicate_result", f"{path}.result_id", "Повторный результат.")
        result_ids.add(result_id)
        status = require_string(row["status"], f"{path}.status")
        if status not in _IDENTITY_STATES:
            fail(
                "invalid_result_status", f"{path}.status", "Неверный статус результата."
            )
        results.append(
            {
                "result_id": result_id,
                "study_id": require_string(row["study_id"], f"{path}.study_id"),
                "publication_id": require_string(
                    row["publication_id"], f"{path}.publication_id"
                ),
                "version_id": require_string(row["version_id"], f"{path}.version_id"),
                "status": status,
                "effect_measure": require_string(
                    row["effect_measure"], f"{path}.effect_measure"
                ),
                "estimate": _finite_number(row["estimate"], f"{path}.estimate"),
                "standard_error": _finite_number(
                    row["standard_error"], f"{path}.standard_error", positive=True
                ),
                "unit": require_string(row["unit"], f"{path}.unit"),
                "population": require_string(row["population"], f"{path}.population"),
                "intervention": require_string(
                    row["intervention"], f"{path}.intervention"
                ),
                "comparator": require_string(row["comparator"], f"{path}.comparator"),
                "outcome": require_string(row["outcome"], f"{path}.outcome"),
                "timepoint": require_string(row["timepoint"], f"{path}.timepoint"),
                "estimand": require_string(row["estimand"], f"{path}.estimand"),
            }
        )
    active = [row for row in results if row["status"] != "retracted"]
    excluded = [row["result_id"] for row in results if row["status"] == "retracted"]
    signature_fields = (
        "effect_measure",
        "unit",
        "population",
        "intervention",
        "comparator",
        "outcome",
        "timepoint",
        "estimand",
    )
    signatures = {tuple(row[field] for field in signature_fields) for row in active}
    comparable = len(signatures) == 1 and len(active) >= 2
    independent = len({row["study_id"] for row in active}) == len(active)

    required_sensitivity = _strings(
        data["required_sensitivity"], "request.required_sensitivity", maximum=100
    )
    receipt_rows = require_list(
        data["sensitivity_receipts"], "request.sensitivity_receipts"
    )
    if len(receipt_rows) > 100:
        fail(
            "size_limit",
            "request.sensitivity_receipts",
            "Слишком много проверок устойчивости.",
        )
    sensitivity: dict[str, dict[str, str]] = {}
    for index, raw in enumerate(receipt_rows):
        path = f"request.sensitivity_receipts[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"kind", "receipt_ref", "status"}, path)
        kind = require_string(row["kind"], f"{path}.kind")
        if kind in sensitivity:
            fail(
                "duplicate_sensitivity",
                f"{path}.kind",
                "Повторная проверка устойчивости.",
            )
        status = require_string(row["status"], f"{path}.status")
        if status not in {"pass", "fail"}:
            fail(
                "invalid_sensitivity_status",
                f"{path}.status",
                "Неверный статус проверки.",
            )
        sensitivity[kind] = {
            "receipt_ref": require_string(row["receipt_ref"], f"{path}.receipt_ref"),
            "status": status,
        }
    missing_sensitivity = sorted(
        kind
        for kind in required_sensitivity
        if kind not in sensitivity or sensitivity[kind]["status"] != "pass"
    )
    pooled_estimate: float | None = None
    if pooling_requested and comparable and independent:
        weights = [1 / (row["standard_error"] ** 2) for row in active]
        pooled_estimate = sum(
            weight * row["estimate"]
            for weight, row in zip(weights, active, strict=True)
        ) / sum(weights)
    pooled_allowed = (
        pooling_requested
        and comparable
        and independent
        and pooled_estimate is not None
        and not missing_sensitivity
    )
    issues: list[str] = []
    if pooling_requested and not comparable:
        issues.append("effects_not_comparable")
    if pooling_requested and not independent:
        issues.append("studies_not_independent")
    if missing_sensitivity:
        issues.append("sensitivity_incomplete")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "MetaAnalysisDecisionReceipt",
        "status": "pooling_allowed" if pooled_allowed else "descriptive_only",
        "run_id": run_id,
        "pooling_requested": pooling_requested,
        "active_result_ids": [row["result_id"] for row in active],
        "excluded_retracted_result_ids": excluded,
        "active_study_count": len({row["study_id"] for row in active}),
        "effects_comparable": comparable,
        "studies_independent": independent,
        "signature_fields": list(signature_fields),
        "pooled_estimate_proposal": pooled_estimate,
        "pooled_result_allowed": pooled_allowed,
        "required_sensitivity": required_sensitivity,
        "missing_sensitivity": missing_sensitivity,
        "issues": sorted(set(issues)),
        "publication_performed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)
