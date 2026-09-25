"""Evidence-standard, claim-card, and negative-knowledge decision contracts."""

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
_TEXT_ARRAY = {
    "type": "array",
    "maxItems": 1000,
    "uniqueItems": True,
    "items": _TEXT,
}
_LEVELS = ("E0", "E1", "E2", "E3", "E4", "E5")
_ERROR_COSTS = {"low", "medium", "high", "critical"}
_CLAIM_TYPES = {
    "descriptive",
    "comparative",
    "causal",
    "predictive",
    "normative",
    "existence",
}
_DIRECTNESS = {"direct", "proxy", "mixed", "not_applicable"}

_STANDARD_FIELDS = {
    "standard_id",
    "version",
    "purpose",
    "error_cost",
    "claim_types",
    "required_evidence_level",
    "required_source_families",
    "required_source_classes",
    "direct_evidence_required",
    "mechanism_required",
    "independent_support_min",
    "alternatives_required",
    "max_age_days",
    "prohibited_inferences",
    "prohibited_actions",
    "content_hash",
}

_STANDARD_PROPERTIES = {
    "standard_id": _TEXT,
    "version": {"type": "integer", "minimum": 0},
    "purpose": _TEXT,
    "error_cost": {"enum": sorted(_ERROR_COSTS)},
    "claim_types": {
        "type": "array",
        "maxItems": len(_CLAIM_TYPES),
        "minItems": 1,
        "uniqueItems": True,
        "items": {"enum": sorted(_CLAIM_TYPES)},
    },
    "required_evidence_level": {"enum": list(_LEVELS)},
    "required_source_families": _TEXT_ARRAY,
    "required_source_classes": _TEXT_ARRAY,
    "direct_evidence_required": {"type": "boolean"},
    "mechanism_required": {"type": "boolean"},
    "independent_support_min": {"type": "integer", "minimum": 0},
    "alternatives_required": {"type": "boolean"},
    "max_age_days": {"type": "integer", "minimum": 1},
    "prohibited_inferences": _TEXT_ARRAY,
    "prohibited_actions": _TEXT_ARRAY,
    "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
}

EVIDENCE_STANDARD_CREATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "standard_id",
        "purpose",
        "error_cost",
        "claim_types",
        "required_evidence_level",
        "required_source_families",
        "required_source_classes",
        "direct_evidence_required",
        "mechanism_required",
        "independent_support_min",
        "alternatives_required",
        "max_age_days",
        "prohibited_inferences",
        "prohibited_actions",
        "created_before_search",
        "search_receipt_count",
    ],
    "properties": {
        "schema_version": {"const": 1},
        **{
            key: value
            for key, value in _STANDARD_PROPERTIES.items()
            if key not in {"version", "content_hash"}
        },
        "created_before_search": {"type": "boolean"},
        "search_receipt_count": {"type": "integer", "minimum": 0},
    },
}

EVIDENCE_STANDARD_REVISE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "standard",
        "expected_version",
        "reason",
        "new_terms",
        "new_source_families",
        "affected_claim_refs",
        "residual_risk",
        "changes",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "standard": {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(_STANDARD_FIELDS),
            "properties": _STANDARD_PROPERTIES,
        },
        "expected_version": {"type": "integer", "minimum": 0},
        "reason": _TEXT,
        "new_terms": _TEXT_ARRAY,
        "new_source_families": _TEXT_ARRAY,
        "affected_claim_refs": _TEXT_ARRAY,
        "residual_risk": {"enum": ["low", "medium", "high", "critical"]},
        "changes": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                key: value
                for key, value in _STANDARD_PROPERTIES.items()
                if key
                in {
                    "required_evidence_level",
                    "required_source_families",
                    "required_source_classes",
                    "direct_evidence_required",
                    "mechanism_required",
                    "independent_support_min",
                    "alternatives_required",
                    "max_age_days",
                    "prohibited_inferences",
                    "prohibited_actions",
                }
            },
        },
    },
}

EVIDENCE_EXCEPTION_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "standard",
        "unavailable_requirement",
        "proxy_basis",
        "narrowed_conclusion",
        "owner",
        "review_by",
        "reopen_condition",
        "requested_evidence_level",
        "prohibited_actions_retained",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "standard": {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(_STANDARD_FIELDS),
            "properties": _STANDARD_PROPERTIES,
        },
        "unavailable_requirement": _TEXT,
        "proxy_basis": _TEXT,
        "narrowed_conclusion": _TEXT,
        "owner": _TEXT,
        "review_by": _TEXT,
        "reopen_condition": _TEXT,
        "requested_evidence_level": {"enum": list(_LEVELS)},
        "prohibited_actions_retained": {"type": "boolean"},
    },
}

CLAIM_CARD_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "claim_ref",
        "central",
        "kind",
        "subject_type",
        "scope",
        "observations",
        "transition_basis",
        "directness",
        "alternatives",
        "standard_ref",
        "requested_evidence_level",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "claim_ref": _TEXT,
        "central": {"type": "boolean"},
        "kind": {"enum": ["fact", "inference", "unknown"]},
        "subject_type": {"enum": sorted(_CLAIM_TYPES)},
        "scope": _TEXT,
        "observations": _TEXT_ARRAY,
        "transition_basis": {"type": ["string", "null"]},
        "directness": {"enum": sorted(_DIRECTNESS)},
        "alternatives": _TEXT_ARRAY,
        "non_inferences": _TEXT_ARRAY,
        "reconsider_if": _TEXT_ARRAY,
        "standard_ref": _TEXT,
        "requested_evidence_level": {"enum": list(_LEVELS)},
    },
}

NEGATIVE_KNOWLEDGE_CLASSIFY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "query_ref",
        "route_outcomes",
        "source_density",
        "absence_claim_requested",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "query_ref": _TEXT,
        "route_outcomes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["route_ref", "observed_outcome", "scope"],
                "properties": {
                    "route_ref": _TEXT,
                    "observed_outcome": {
                        "enum": [
                            "empty_result",
                            "access_denied",
                            "metadata_only",
                            "method_not_capable",
                            "out_of_scope",
                            "deferred",
                        ]
                    },
                    "scope": _TEXT,
                },
            },
        },
        "source_density": {"enum": ["unknown", "low", "medium", "high"]},
        "absence_claim_requested": {"type": "boolean"},
    },
}


def _schema(
    request: object, fields: set[str], *, optional: set[str] | None = None
) -> dict[str, object]:
    data = require_mapping(request, "request")
    optional = optional or set()
    unknown = sorted(set(data) - fields - optional)
    missing = sorted(fields - set(data))
    if missing:
        fail("missing_field", f"request.{missing[0]}", "Отсутствует обязательное поле.")
    if unknown:
        fail("unknown_field", f"request.{unknown[0]}", "Неизвестное поле запрещено.")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    return data


def _strings(value: object, path: str, *, nonempty: bool = False) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if nonempty and not result:
        fail("empty_array", path, "Требуется непустой массив.")
    if len(result) != len(set(result)):
        fail("duplicate_value", path, "Повтор значения запрещён.")
    return result


def _level(value: object, path: str) -> str:
    result = require_string(value, path)
    if result not in _LEVELS:
        fail("invalid_evidence_level", path, "Неизвестный уровень доказательности.")
    return result


def _standard_record(value: object, path: str) -> dict[str, Any]:
    data = require_mapping(value, path)
    require_exact_keys(data, _STANDARD_FIELDS, path)
    record: dict[str, Any] = {
        "standard_id": require_string(data["standard_id"], f"{path}.standard_id"),
        "version": require_int(data["version"], f"{path}.version"),
        "purpose": require_string(data["purpose"], f"{path}.purpose"),
        "error_cost": require_string(data["error_cost"], f"{path}.error_cost"),
        "claim_types": _strings(
            data["claim_types"], f"{path}.claim_types", nonempty=True
        ),
        "required_evidence_level": _level(
            data["required_evidence_level"], f"{path}.required_evidence_level"
        ),
        "required_source_families": _strings(
            data["required_source_families"], f"{path}.required_source_families"
        ),
        "required_source_classes": _strings(
            data["required_source_classes"], f"{path}.required_source_classes"
        ),
        "direct_evidence_required": require_bool(
            data["direct_evidence_required"], f"{path}.direct_evidence_required"
        ),
        "mechanism_required": require_bool(
            data["mechanism_required"], f"{path}.mechanism_required"
        ),
        "independent_support_min": require_int(
            data["independent_support_min"], f"{path}.independent_support_min"
        ),
        "alternatives_required": require_bool(
            data["alternatives_required"], f"{path}.alternatives_required"
        ),
        "max_age_days": require_int(
            data["max_age_days"], f"{path}.max_age_days", minimum=1
        ),
        "prohibited_inferences": _strings(
            data["prohibited_inferences"], f"{path}.prohibited_inferences"
        ),
        "prohibited_actions": _strings(
            data["prohibited_actions"], f"{path}.prohibited_actions"
        ),
    }
    if record["error_cost"] not in _ERROR_COSTS:
        fail("invalid_error_cost", f"{path}.error_cost", "Неизвестная цена ошибки.")
    if not set(record["claim_types"]) <= _CLAIM_TYPES:
        fail(
            "invalid_claim_type", f"{path}.claim_types", "Неизвестный тип утверждения."
        )
    supplied_hash = require_string(data["content_hash"], f"{path}.content_hash")
    if supplied_hash != sha256_json(record):
        fail(
            "standard_hash_mismatch",
            f"{path}.content_hash",
            "Хеш стандарта не совпадает.",
        )
    record["content_hash"] = supplied_hash
    return record


def create_evidence_standard(request: object) -> dict[str, Any]:
    fields = set(EVIDENCE_STANDARD_CREATE_SCHEMA["required"])
    data = _schema(request, fields)
    claim_types = _strings(data["claim_types"], "request.claim_types", nonempty=True)
    if not set(claim_types) <= _CLAIM_TYPES:
        fail(
            "invalid_claim_type", "request.claim_types", "Неизвестный тип утверждения."
        )
    error_cost = require_string(data["error_cost"], "request.error_cost")
    if error_cost not in _ERROR_COSTS:
        fail("invalid_error_cost", "request.error_cost", "Неизвестная цена ошибки.")
    record: dict[str, Any] = {
        "standard_id": require_string(data["standard_id"], "request.standard_id"),
        "version": 0,
        "purpose": require_string(data["purpose"], "request.purpose"),
        "error_cost": error_cost,
        "claim_types": claim_types,
        "required_evidence_level": _level(
            data["required_evidence_level"], "request.required_evidence_level"
        ),
        "required_source_families": _strings(
            data["required_source_families"], "request.required_source_families"
        ),
        "required_source_classes": _strings(
            data["required_source_classes"], "request.required_source_classes"
        ),
        "direct_evidence_required": require_bool(
            data["direct_evidence_required"], "request.direct_evidence_required"
        ),
        "mechanism_required": require_bool(
            data["mechanism_required"], "request.mechanism_required"
        ),
        "independent_support_min": require_int(
            data["independent_support_min"], "request.independent_support_min"
        ),
        "alternatives_required": require_bool(
            data["alternatives_required"], "request.alternatives_required"
        ),
        "max_age_days": require_int(
            data["max_age_days"], "request.max_age_days", minimum=1
        ),
        "prohibited_inferences": _strings(
            data["prohibited_inferences"], "request.prohibited_inferences"
        ),
        "prohibited_actions": _strings(
            data["prohibited_actions"], "request.prohibited_actions"
        ),
    }
    created_before_search = require_bool(
        data["created_before_search"], "request.created_before_search"
    )
    search_count = require_int(
        data["search_receipt_count"], "request.search_receipt_count"
    )
    issues: list[str] = []
    if not created_before_search or search_count:
        issues.append("standard_not_precommitted")
    if not record["required_source_families"]:
        issues.append("source_families_missing")
    if not record["required_source_classes"]:
        issues.append("source_classes_missing")
    if not record["prohibited_inferences"]:
        issues.append("prohibited_inferences_missing")
    if "causal" in claim_types and error_cost in {"high", "critical"}:
        if _LEVELS.index(record["required_evidence_level"]) < _LEVELS.index("E4"):
            issues.append("causal_high_cost_requires_e4")
        if not record["direct_evidence_required"]:
            issues.append("direct_evidence_required")
        if not record["mechanism_required"]:
            issues.append("mechanism_required")
        if record["independent_support_min"] < 2:
            issues.append("independent_support_insufficient")
        if not record["alternatives_required"]:
            issues.append("alternatives_required")
        if not record["prohibited_actions"]:
            issues.append("prohibited_actions_missing")
    record["content_hash"] = sha256_json(record)
    payload = {
        "schema_version": 1,
        "contract": "EvidenceStandardDecisionReceipt",
        "status": "standard_ready" if not issues else "blocked",
        "evidence_standard": record if not issues else None,
        "pre_search_verified": created_before_search and search_count == 0,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def propose_evidence_standard_revision(request: object) -> dict[str, Any]:
    fields = set(EVIDENCE_STANDARD_REVISE_SCHEMA["required"])
    data = _schema(request, fields)
    standard = _standard_record(data["standard"], "request.standard")
    expected = require_int(data["expected_version"], "request.expected_version")
    if expected != standard["version"]:
        fail("stale_standard_version", "request.expected_version", "Версия устарела.")
    reason = require_string(data["reason"], "request.reason")
    new_terms = _strings(data["new_terms"], "request.new_terms")
    new_families = _strings(data["new_source_families"], "request.new_source_families")
    affected = _strings(
        data["affected_claim_refs"], "request.affected_claim_refs", nonempty=True
    )
    residual_risk = require_string(data["residual_risk"], "request.residual_risk")
    if residual_risk not in _ERROR_COSTS:
        fail("invalid_residual_risk", "request.residual_risk", "Неизвестный риск.")
    changes = require_mapping(data["changes"], "request.changes")
    allowed_changes = set(
        EVIDENCE_STANDARD_REVISE_SCHEMA["properties"]["changes"]["properties"]
    )
    unknown = sorted(set(changes) - allowed_changes)
    if unknown:
        fail("unknown_field", f"request.changes.{unknown[0]}", "Неизвестное поле.")
    if not changes and not new_terms and not new_families:
        fail("empty_revision", "request.changes", "Редакция не содержит изменения.")

    revised = {key: value for key, value in standard.items() if key != "content_hash"}
    revised["version"] = standard["version"] + 1
    for key, raw in changes.items():
        path = f"request.changes.{key}"
        if key in {
            "required_source_families",
            "required_source_classes",
            "prohibited_inferences",
            "prohibited_actions",
        }:
            revised[key] = _strings(raw, path)
        elif key == "required_evidence_level":
            revised[key] = _level(raw, path)
        elif key in {
            "direct_evidence_required",
            "mechanism_required",
            "alternatives_required",
        }:
            revised[key] = require_bool(raw, path)
        else:
            revised[key] = require_int(
                raw, path, minimum=1 if key == "max_age_days" else 0
            )

    issues: list[str] = []
    if _LEVELS.index(revised["required_evidence_level"]) < _LEVELS.index(
        standard["required_evidence_level"]
    ):
        issues.append("evidence_level_downgrade")
    for key in (
        "direct_evidence_required",
        "mechanism_required",
        "alternatives_required",
    ):
        if standard[key] and not revised[key]:
            issues.append(f"requirement_removed:{key}")
    if revised["independent_support_min"] < standard["independent_support_min"]:
        issues.append("independence_downgrade")
    if revised["max_age_days"] > standard["max_age_days"]:
        issues.append("freshness_downgrade")
    for key in (
        "required_source_families",
        "required_source_classes",
        "prohibited_inferences",
        "prohibited_actions",
    ):
        if not set(standard[key]) <= set(revised[key]):
            issues.append(f"requirement_removed:{key}")
    if not set(new_families) <= set(revised["required_source_families"]):
        issues.append("discovered_family_not_added")

    revised["content_hash"] = sha256_json(revised)
    payload = {
        "schema_version": 1,
        "contract": "EvidenceStandardRevisionReceipt",
        "status": "revision_proposed" if not issues else "blocked",
        "prior_standard_ref": {
            "standard_id": standard["standard_id"],
            "version": standard["version"],
            "content_hash": standard["content_hash"],
        },
        "evidence_standard": revised if not issues else None,
        "reason": reason,
        "new_terms": new_terms,
        "new_source_families": new_families,
        "affected_claim_refs": affected,
        "residual_risk": residual_risk,
        "prior_standard_mutated": False,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def assess_evidence_exception(request: object) -> dict[str, Any]:
    data = _schema(request, set(EVIDENCE_EXCEPTION_ASSESS_SCHEMA["required"]))
    standard = _standard_record(data["standard"], "request.standard")
    unavailable = require_string(
        data["unavailable_requirement"], "request.unavailable_requirement"
    )
    proxy = require_string(data["proxy_basis"], "request.proxy_basis")
    narrowed = require_string(
        data["narrowed_conclusion"], "request.narrowed_conclusion"
    )
    owner = require_string(data["owner"], "request.owner")
    review_by = require_string(data["review_by"], "request.review_by")
    reopen = require_string(data["reopen_condition"], "request.reopen_condition")
    level = _level(data["requested_evidence_level"], "request.requested_evidence_level")
    actions_retained = require_bool(
        data["prohibited_actions_retained"], "request.prohibited_actions_retained"
    )
    issues: list[str] = []
    if _LEVELS.index(level) > _LEVELS.index(standard["required_evidence_level"]):
        issues.append("evidence_inflation")
    if not actions_retained:
        issues.append("prohibited_action_removed")
    payload = {
        "schema_version": 1,
        "contract": "EvidenceExceptionDecisionReceipt",
        "status": "partial_proxy" if not issues else "blocked",
        "standard_ref": {
            "standard_id": standard["standard_id"],
            "version": standard["version"],
            "content_hash": standard["content_hash"],
        },
        "unavailable_requirement": unavailable,
        "proxy_basis": proxy,
        "narrowed_conclusion": narrowed,
        "owner": owner,
        "review_by": review_by,
        "reopen_condition": reopen,
        "evidence_level": level if not issues else None,
        "evidence_strength_raised": False,
        "prohibited_actions_retained": actions_retained,
        "external_action_allowed": False,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def assess_claim_card(request: object) -> dict[str, Any]:
    required = set(CLAIM_CARD_ASSESS_SCHEMA["required"])
    data = _schema(
        request,
        required,
        optional={"non_inferences", "reconsider_if"},
    )
    claim_ref = require_string(data["claim_ref"], "request.claim_ref")
    central = require_bool(data["central"], "request.central")
    kind = require_string(data["kind"], "request.kind")
    if kind not in {"fact", "inference", "unknown"}:
        fail("invalid_kind", "request.kind", "Неизвестный совместимый вид.")
    subject_type = require_string(data["subject_type"], "request.subject_type")
    if subject_type not in _CLAIM_TYPES:
        fail(
            "invalid_claim_type", "request.subject_type", "Неизвестный предметный тип."
        )
    scope = require_string(data["scope"], "request.scope")
    observations = _strings(data["observations"], "request.observations")
    transition = data["transition_basis"]
    if transition is not None:
        transition = require_string(transition, "request.transition_basis")
    directness = require_string(data["directness"], "request.directness")
    if directness not in _DIRECTNESS:
        fail("invalid_directness", "request.directness", "Неизвестная прямота.")
    alternatives = _strings(data["alternatives"], "request.alternatives")
    non_inferences = (
        _strings(data["non_inferences"], "request.non_inferences")
        if "non_inferences" in data
        else []
    )
    reconsider = (
        _strings(data["reconsider_if"], "request.reconsider_if")
        if "reconsider_if" in data
        else []
    )
    standard_ref = require_string(data["standard_ref"], "request.standard_ref")
    level = _level(data["requested_evidence_level"], "request.requested_evidence_level")
    missing: list[str] = []
    if central and not observations:
        missing.append("request.observations")
    if central and not transition:
        missing.append("request.transition_basis")
    if central and not alternatives:
        missing.append("request.alternatives")
    if central and not non_inferences:
        missing.append("request.non_inferences")
    if central and not reconsider:
        missing.append("request.reconsider_if")
    payload = {
        "schema_version": 1,
        "contract": "ClaimCardDecisionReceipt",
        "status": "claim_gate_pass" if not missing else "blocked",
        "claim_ref": claim_ref,
        "kind": kind,
        "subject_type": subject_type,
        "scope": scope,
        "directness": directness,
        "standard_ref": standard_ref,
        "requested_evidence_level": level,
        "transition_basis": transition,
        "non_inferences": non_inferences,
        "reconsider_if": reconsider,
        "missing_fields": sorted(missing),
        "claim_status_changed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def classify_negative_knowledge(request: object) -> dict[str, Any]:
    data = _schema(request, set(NEGATIVE_KNOWLEDGE_CLASSIFY_SCHEMA["required"]))
    query_ref = require_string(data["query_ref"], "request.query_ref")
    density = require_string(data["source_density"], "request.source_density")
    if density not in {"unknown", "low", "medium", "high"}:
        fail("invalid_density", "request.source_density", "Неизвестная плотность.")
    absence_requested = require_bool(
        data["absence_claim_requested"], "request.absence_claim_requested"
    )
    mapping = {
        "empty_result": "not_found_in_scope",
        "access_denied": "blocked_by_access",
        "metadata_only": "metadata_only",
        "method_not_capable": "method_incapable",
        "out_of_scope": "out_of_scope",
        "deferred": "deferred",
    }
    classified: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(
        require_list(data["route_outcomes"], "request.route_outcomes")
    ):
        path = f"request.route_outcomes[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"route_ref", "observed_outcome", "scope"}, path)
        route_ref = require_string(row["route_ref"], f"{path}.route_ref")
        if route_ref in seen:
            fail("duplicate_route", f"{path}.route_ref", "Повтор маршрута запрещён.")
        seen.add(route_ref)
        observed = require_string(row["observed_outcome"], f"{path}.observed_outcome")
        if observed not in mapping:
            fail(
                "invalid_route_outcome",
                f"{path}.observed_outcome",
                "Неизвестный исход.",
            )
        scope = require_string(row["scope"], f"{path}.scope")
        classified.append(
            {
                "route_ref": route_ref,
                "knowledge_type": mapping[observed],
                "scope": scope,
            }
        )
    issues = ["phenomenon_absence_not_supported"] if absence_requested else []
    payload = {
        "schema_version": 1,
        "contract": "NegativeKnowledgeDecisionReceipt",
        "status": "blocked" if issues else "classified",
        "query_ref": query_ref,
        "route_knowledge": classified,
        "source_density": density,
        "density_is_quality": False,
        "phenomenon_absence_inferred": False,
        "prohibited_inferences": ["phenomenon_absent"],
        "persistence_applied": False,
        "issues": issues,
    }
    return with_receipt_hash(payload)
