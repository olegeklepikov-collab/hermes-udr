"""Research engagement-level selection, revision, and parsing-result contracts."""

from __future__ import annotations

import re
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
_TEXTS = {"type": "array", "maxItems": 1000, "uniqueItems": True, "items": _TEXT}
_LEVELS = (
    "parsing",
    "search",
    "research",
    "deep_research",
    "ultra_deep_research",
)
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_OBLIGATIONS = {
    "parsing": (
        "preserve_original",
        "structure_material",
        "fragment_locators",
        "parse_errors",
        "content_hash",
        "no_external_search",
        "no_claim_promotion",
    ),
    "search": (
        "decomposition_registered",
        "search_ledger",
        "source_selection",
        "evidence_trace",
        "answer_scope",
    ),
    "research": (
        "brief",
        "multi_source_decomposition",
        "construct_operationalization",
        "synthesis",
        "debrief",
    ),
    "deep_research": (
        "challenge",
        "alternative_analysis",
        "independent_review",
        "fact_map",
        "root_cause_map",
    ),
    "ultra_deep_research": (
        "coverage_frame",
        "robustness_review",
        "source_influence",
        "sensitivity_analysis",
        "quality_dashboard",
    ),
}


def _cumulative(level: str) -> list[str]:
    result: list[str] = []
    for current in _LEVELS:
        result.extend(_OBLIGATIONS[current])
        if current == level:
            break
    return result


_LEVEL_RECORD_FIELDS = {
    "task_ref",
    "revision",
    "engagement_level",
    "obligations",
    "depth_compatibility",
    "content_hash",
}
_LEVEL_RECORD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_LEVEL_RECORD_FIELDS),
    "properties": {
        "task_ref": _TEXT,
        "revision": {"type": "integer", "minimum": 1},
        "engagement_level": {"enum": list(_LEVELS)},
        "obligations": _TEXTS,
        "depth_compatibility": {"enum": ["none", "search", "deep", "ultra"]},
        "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}

ENGAGEMENT_LEVEL_SELECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "task_ref",
        "material_supplied",
        "external_facts_needed",
        "multi_source_synthesis_needed",
        "causal_or_mechanism_test_needed",
        "coverage_claim_required",
        "instrument_selection_started",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "task_ref": _TEXT,
        "material_supplied": {"type": "boolean"},
        "external_facts_needed": {"type": "boolean"},
        "multi_source_synthesis_needed": {"type": "boolean"},
        "causal_or_mechanism_test_needed": {"type": "boolean"},
        "coverage_claim_required": {"type": "boolean"},
        "instrument_selection_started": {"type": "boolean"},
    },
}

ENGAGEMENT_LEVEL_REVISE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "current",
        "expected_revision",
        "proposed_level",
        "reason",
        "user_consent",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "current": _LEVEL_RECORD_SCHEMA,
        "expected_revision": {"type": "integer", "minimum": 1},
        "proposed_level": {"enum": list(_LEVELS)},
        "reason": _TEXT,
        "user_consent": {"type": "boolean"},
    },
}

PARSING_RESULT_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "artifact_ref",
        "original_content_hash",
        "parsed_content_hash",
        "structure_refs",
        "fragment_refs",
        "parse_errors",
        "network_call_count",
        "substantive_recommendations",
        "claim_promotions",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "artifact_ref": _TEXT,
        "original_content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "parsed_content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "structure_refs": _TEXTS,
        "fragment_refs": _TEXTS,
        "parse_errors": _TEXTS,
        "network_call_count": {"type": "integer", "minimum": 0},
        "substantive_recommendations": _TEXTS,
        "claim_promotions": _TEXTS,
    },
}


def _schema(request: object, required: set[str]) -> dict[str, object]:
    data = require_mapping(request, "request")
    require_exact_keys(data, required, "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    return data


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_value", path, "Повтор значения запрещён.")
    return result


def _depth(level: str) -> str:
    return {
        "parsing": "none",
        "search": "search",
        "research": "search",
        "deep_research": "deep",
        "ultra_deep_research": "ultra",
    }[level]


def _record(task_ref: str, revision: int, level: str) -> dict[str, Any]:
    record = {
        "task_ref": task_ref,
        "revision": revision,
        "engagement_level": level,
        "obligations": _cumulative(level),
        "depth_compatibility": _depth(level),
    }
    record["content_hash"] = sha256_json(record)
    return record


def _read_record(value: object, path: str) -> dict[str, Any]:
    data = require_mapping(value, path)
    require_exact_keys(data, _LEVEL_RECORD_FIELDS, path)
    task_ref = require_string(data["task_ref"], f"{path}.task_ref")
    revision = require_int(data["revision"], f"{path}.revision", minimum=1)
    level = require_string(data["engagement_level"], f"{path}.engagement_level")
    if level not in _LEVELS:
        fail(
            "invalid_engagement_level",
            f"{path}.engagement_level",
            "Неизвестный уровень.",
        )
    obligations = _strings(data["obligations"], f"{path}.obligations")
    depth = require_string(data["depth_compatibility"], f"{path}.depth_compatibility")
    record = {
        "task_ref": task_ref,
        "revision": revision,
        "engagement_level": level,
        "obligations": obligations,
        "depth_compatibility": depth,
    }
    supplied = require_string(data["content_hash"], f"{path}.content_hash")
    if supplied != sha256_json(record):
        fail("level_hash_mismatch", f"{path}.content_hash", "Хеш уровня не совпадает.")
    if obligations != _cumulative(level) or depth != _depth(level):
        fail("level_obligation_mismatch", path, "Обязательства уровня не совпадают.")
    record["content_hash"] = supplied
    return record


def select_engagement_level(request: object) -> dict[str, Any]:
    data = _schema(request, set(ENGAGEMENT_LEVEL_SELECT_SCHEMA["required"]))
    task_ref = require_string(data["task_ref"], "request.task_ref")
    supplied = require_bool(data["material_supplied"], "request.material_supplied")
    external = require_bool(
        data["external_facts_needed"], "request.external_facts_needed"
    )
    multi = require_bool(
        data["multi_source_synthesis_needed"],
        "request.multi_source_synthesis_needed",
    )
    causal = require_bool(
        data["causal_or_mechanism_test_needed"],
        "request.causal_or_mechanism_test_needed",
    )
    coverage = require_bool(
        data["coverage_claim_required"], "request.coverage_claim_required"
    )
    selection_started = require_bool(
        data["instrument_selection_started"], "request.instrument_selection_started"
    )
    if coverage:
        level = "ultra_deep_research"
        basis = "coverage_claim"
    elif causal:
        level = "deep_research"
        basis = "causal_or_mechanism_test"
    elif multi:
        level = "research"
        basis = "multi_source_synthesis"
    elif external:
        level = "search"
        basis = "external_fact"
    elif supplied:
        level = "parsing"
        basis = "supplied_material_only"
    else:
        level = "search"
        basis = "missing_supplied_material"
    issues = ["instrument_selection_preceded_level"] if selection_started else []
    record = _record(task_ref, 1, level)
    payload = {
        "schema_version": 1,
        "contract": "EngagementLevelDecisionReceipt",
        "status": "level_selected" if not issues else "blocked",
        "level_record": record if not issues else None,
        "selection_basis": basis,
        "minimal_level_selected": True,
        "instrument_selection_allowed": not issues,
        "execution_started": False,
        "persistence_applied": False,
        "issues": issues,
    }
    return with_receipt_hash(payload)


def propose_engagement_level_revision(request: object) -> dict[str, Any]:
    data = _schema(request, set(ENGAGEMENT_LEVEL_REVISE_SCHEMA["required"]))
    current = _read_record(data["current"], "request.current")
    expected = require_int(
        data["expected_revision"], "request.expected_revision", minimum=1
    )
    if expected != current["revision"]:
        fail("stale_revision", "request.expected_revision", "Редакция устарела.")
    proposed = require_string(data["proposed_level"], "request.proposed_level")
    if proposed not in _LEVELS:
        fail(
            "invalid_engagement_level", "request.proposed_level", "Неизвестный уровень."
        )
    reason = require_string(data["reason"], "request.reason")
    consent = require_bool(data["user_consent"], "request.user_consent")
    prior_obligations = set(current["obligations"])
    proposed_obligations = set(_cumulative(proposed))
    added = sorted(proposed_obligations - prior_obligations)
    removed = sorted(prior_obligations - proposed_obligations)
    if proposed == current["engagement_level"]:
        status = "no_change"
        revised = current
    elif not consent:
        status = "consent_required"
        revised = None
    else:
        status = "revision_proposed"
        revised = _record(current["task_ref"], current["revision"] + 1, proposed)
    payload = {
        "schema_version": 1,
        "contract": "EngagementLevelRevisionReceipt",
        "status": status,
        "prior_ref": {
            "task_ref": current["task_ref"],
            "revision": current["revision"],
            "content_hash": current["content_hash"],
        },
        "level_record": revised,
        "proposed_level": proposed,
        "reason": reason,
        "added_obligations": added,
        "removed_obligations": removed,
        "prior_record_mutated": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def assess_parsing_result(request: object) -> dict[str, Any]:
    data = _schema(request, set(PARSING_RESULT_ASSESS_SCHEMA["required"]))
    artifact_ref = require_string(data["artifact_ref"], "request.artifact_ref")
    original_hash = require_string(
        data["original_content_hash"], "request.original_content_hash"
    )
    parsed_hash = require_string(
        data["parsed_content_hash"], "request.parsed_content_hash"
    )
    if not _HASH_PATTERN.fullmatch(original_hash) or not _HASH_PATTERN.fullmatch(
        parsed_hash
    ):
        fail("invalid_hash", "request", "Требуется SHA-256.")
    structures = _strings(data["structure_refs"], "request.structure_refs")
    fragments = _strings(data["fragment_refs"], "request.fragment_refs")
    errors = _strings(data["parse_errors"], "request.parse_errors")
    network_count = require_int(
        data["network_call_count"], "request.network_call_count"
    )
    recommendations = _strings(
        data["substantive_recommendations"],
        "request.substantive_recommendations",
    )
    promotions = _strings(data["claim_promotions"], "request.claim_promotions")
    issues: list[str] = []
    if network_count:
        issues.append("parsing_external_search_forbidden")
    if recommendations:
        issues.append("parsing_recommendation_forbidden")
    if promotions:
        issues.append("parsing_claim_promotion_forbidden")
    if not structures or not fragments:
        issues.append("parsing_output_incomplete")
    payload = {
        "schema_version": 1,
        "contract": "ParsingResultDecisionReceipt",
        "status": "parsing_verified" if not issues else "blocked",
        "artifact_ref": artifact_ref,
        "original_content_hash": original_hash,
        "parsed_content_hash": parsed_hash,
        "structure_refs": structures,
        "fragment_refs": fragments,
        "parse_errors": errors,
        "network_calls_observed": network_count,
        "external_search_performed": network_count > 0,
        "substantive_recommendations": recommendations,
        "claim_promotions": promotions,
        "evidence_status_changed": False,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)
