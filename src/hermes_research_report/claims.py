"""Atomic claim, challenge, and synthesis decisions without status inflation."""

from __future__ import annotations

import hashlib
import math
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

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_KINDS = {"observation", "inference", "recommendation", "unknown"}
_CLAIM_TYPES = {
    "descriptive",
    "classification",
    "comparative",
    "trend",
    "causal",
    "mechanistic",
    "predictive",
    "normative",
    "recommendation",
    "limitation",
}
_CLAIM_STATES = {"unresolved", "supported", "qualified", "contradicted", "withdrawn"}
_LINK_ROLES = {"support", "contradict", "context"}
_SEMANTIC_STATES = {"unverified", "verified", "rejected", "unable_to_review"}
_CHALLENGE_OUTCOMES = {
    "survived",
    "narrowed",
    "weakened",
    "contested",
    "unresolved",
    "rejected",
    "evidence_required",
    "decision_prohibited",
    "insufficient_material",
}
_TEXT = {"type": "string", "minLength": 1}
_NULLABLE_TEXT = {"type": ["string", "null"]}
_STRING_ARRAY = {
    "type": "array",
    "maxItems": 1000,
    "uniqueItems": True,
    "items": _TEXT,
}
_SCOPE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["population", "geography", "period", "conditions"],
    "properties": {
        "population": _TEXT,
        "geography": _TEXT,
        "period": _TEXT,
        "conditions": _STRING_ARRAY,
    },
}
_EVIDENCE_LINK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "link_id",
        "fragment_ref",
        "fragment_hash",
        "fragment_exact_text",
        "quote",
        "role",
        "semantic_status",
        "semantic_reviewer_ref",
        "current",
        "scope_match",
        "independent",
    ],
    "properties": {
        "link_id": _TEXT,
        "fragment_ref": _TEXT,
        "fragment_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "fragment_exact_text": {"type": "string"},
        "quote": {"type": "string"},
        "role": {"enum": sorted(_LINK_ROLES)},
        "semantic_status": {"enum": sorted(_SEMANTIC_STATES)},
        "semantic_reviewer_ref": _NULLABLE_TEXT,
        "semantic_target_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "current": {"type": "boolean"},
        "scope_match": {"type": "boolean"},
        "independent": {"type": "boolean"},
    },
}
_CALCULATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["operation", "operands", "reported_value", "output_unit", "tolerance"],
    "properties": {
        "operation": {"enum": ["difference", "ratio", "percent_change"]},
        "operands": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value", "unit", "denominator", "locator"],
                "properties": {
                    "value": {"type": ["number", "null"]},
                    "unit": _TEXT,
                    "denominator": _TEXT,
                    "locator": _TEXT,
                },
            },
        },
        "reported_value": {"type": "number"},
        "output_unit": _TEXT,
        "tolerance": {"type": "number", "minimum": 0},
    },
}
CLAIM_EVALUATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "claim",
        "known_fragment_refs",
        "evidence_links",
        "predecessor_claims",
        "qualification_checks",
        "calculation",
        "withdrawn",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "claim": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "claim_id",
                "revision",
                "text",
                "atomic_proposition_count",
                "kind",
                "claim_type",
                "scope",
                "conditions",
                "derivation_refs",
                "alternatives",
                "non_conclusions",
                "limitations",
                "intended_use",
                "reconsider_triggers",
            ],
            "properties": {
                "claim_id": _TEXT,
                "revision": {"type": "integer", "minimum": 1},
                "text": _TEXT,
                "atomic_proposition_count": {"type": "integer", "minimum": 1},
                "kind": {"enum": sorted(_KINDS)},
                "claim_type": {"enum": sorted(_CLAIM_TYPES)},
                "scope": _SCOPE_SCHEMA,
                "conditions": _STRING_ARRAY,
                "derivation_refs": _STRING_ARRAY,
                "alternatives": _STRING_ARRAY,
                "non_conclusions": _STRING_ARRAY,
                "limitations": _STRING_ARRAY,
                "intended_use": _TEXT,
                "reconsider_triggers": _STRING_ARRAY,
            },
        },
        "known_fragment_refs": _STRING_ARRAY,
        "evidence_links": {
            "type": "array",
            "maxItems": 1000,
            "items": _EVIDENCE_LINK_SCHEMA,
        },
        "predecessor_claims": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim_ref", "status", "current"],
                "properties": {
                    "claim_ref": _TEXT,
                    "status": {"enum": sorted(_CLAIM_STATES)},
                    "current": {"type": "boolean"},
                },
            },
        },
        "qualification_checks": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "scope_closed",
                "limitations_closed",
                "derivation_graph_complete",
                "calculation_reproducible",
            ],
            "properties": {
                "scope_closed": {"type": "boolean"},
                "limitations_closed": {"type": "boolean"},
                "derivation_graph_complete": {"type": "boolean"},
                "calculation_reproducible": {"type": "boolean"},
            },
        },
        "calculation": {"anyOf": [_CALCULATION_SCHEMA, {"type": "null"}]},
        "withdrawn": {"type": "boolean"},
    },
}

_ALTERNATIVE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "alternative_id",
        "explanation",
        "supporting_claim_refs",
        "contradicting_claim_refs",
        "discriminator",
        "test_status",
        "result",
    ],
    "properties": {
        "alternative_id": _TEXT,
        "explanation": _TEXT,
        "supporting_claim_refs": _STRING_ARRAY,
        "contradicting_claim_refs": _STRING_ARRAY,
        "discriminator": _TEXT,
        "test_status": {"enum": ["not_tested", "tested"]},
        "result": {"enum": ["supported", "weakened", "rejected", "unresolved"]},
    },
}
CHALLENGE_EVALUATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "claim_ref",
        "claim_status",
        "evidence_profile_ref",
        "known_claim_refs",
        "known_evidence_refs",
        "checks",
        "alternatives",
        "weakening_evidence_refs",
        "contradiction_types",
        "missing_support",
        "repair",
        "residual_risk",
        "safe_wording",
        "decision_impact",
        "round",
        "max_rounds",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "claim_ref": _TEXT,
        "claim_status": {"enum": sorted(_CLAIM_STATES)},
        "evidence_profile_ref": _TEXT,
        "known_claim_refs": _STRING_ARRAY,
        "known_evidence_refs": _STRING_ARRAY,
        "checks": _STRING_ARRAY,
        "alternatives": {
            "type": "array",
            "maxItems": 100,
            "items": _ALTERNATIVE_SCHEMA,
        },
        "weakening_evidence_refs": _STRING_ARRAY,
        "contradiction_types": _STRING_ARRAY,
        "missing_support": _STRING_ARRAY,
        "repair": _TEXT,
        "residual_risk": _TEXT,
        "safe_wording": _TEXT,
        "decision_impact": _TEXT,
        "round": {"type": "integer", "minimum": 1},
        "max_rounds": {"type": "integer", "minimum": 1},
    },
}

SYNTHESIS_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "profile",
        "claims",
        "challenge_records",
        "coverage",
        "robustness",
        "requested_synthesis",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "profile": {
            "type": "object",
            "additionalProperties": False,
            "required": ["depth", "risk"],
            "properties": {
                "depth": {"enum": ["search", "deep", "ultra"]},
                "risk": {"enum": ["low", "medium", "high"]},
            },
        },
        "claims": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "claim_ref",
                    "status",
                    "central",
                    "current",
                    "basis_signature",
                ],
                "properties": {
                    "claim_ref": _TEXT,
                    "status": {"enum": sorted(_CLAIM_STATES)},
                    "central": {"type": "boolean"},
                    "current": {"type": "boolean"},
                    "basis_signature": _TEXT,
                },
            },
        },
        "challenge_records": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["challenge_ref", "claim_ref", "outcome", "current"],
                "properties": {
                    "challenge_ref": _TEXT,
                    "claim_ref": _TEXT,
                    "outcome": {"enum": sorted(_CHALLENGE_OUTCOMES)},
                    "current": {"type": "boolean"},
                },
            },
        },
        "coverage": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "open_cells"],
            "properties": {
                "status": {"enum": ["complete_for_scope", "partial", "unknown"]},
                "open_cells": _STRING_ARRAY,
            },
        },
        "robustness": {
            "type": "object",
            "additionalProperties": False,
            "required": ["required_checks", "passed_checks"],
            "properties": {
                "required_checks": _STRING_ARRAY,
                "passed_checks": _STRING_ARRAY,
            },
        },
        "requested_synthesis": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "claim_refs", "allow_descriptive_fallback"],
            "properties": {
                "kind": {"enum": ["descriptive", "comparative", "pooled_quantitative"]},
                "claim_refs": _STRING_ARRAY,
                "allow_descriptive_fallback": {"type": "boolean"},
            },
        },
    },
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


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


def _finite_number(value: object, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        fail("invalid_number", path, "Требуется конечное число.")
    return float(value)


def _calculation(
    value: object, path: str
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    if value is None:
        return True, None, []
    data = require_mapping(value, path)
    require_exact_keys(
        data,
        {"operation", "operands", "reported_value", "output_unit", "tolerance"},
        path,
    )
    operation = require_string(data["operation"], f"{path}.operation")
    if operation not in {"difference", "ratio", "percent_change"}:
        fail("invalid_calculation", f"{path}.operation", "Неверная операция.")
    operands_raw = require_list(data["operands"], f"{path}.operands")
    if len(operands_raw) != 2:
        fail("invalid_calculation", f"{path}.operands", "Требуются два операнда.")
    operands: list[dict[str, Any]] = []
    issues: list[str] = []
    for index, raw in enumerate(operands_raw):
        operand_path = f"{path}.operands[{index}]"
        row = require_mapping(raw, operand_path)
        require_exact_keys(
            row, {"value", "unit", "denominator", "locator"}, operand_path
        )
        raw_value = row["value"]
        numeric: float | None
        if raw_value is None:
            numeric = None
            issues.append("calculation_operand_missing")
        elif (
            isinstance(raw_value, bool)
            or not isinstance(raw_value, (int, float))
            or not math.isfinite(raw_value)
        ):
            fail(
                "invalid_number",
                f"{operand_path}.value",
                "Требуется конечное число или null.",
            )
        else:
            numeric = float(raw_value)
        operands.append(
            {
                "value": numeric,
                "unit": require_string(row["unit"], f"{operand_path}.unit"),
                "denominator": require_string(
                    row["denominator"], f"{operand_path}.denominator"
                ),
                "locator": require_string(row["locator"], f"{operand_path}.locator"),
            }
        )
    reported_value = _finite_number(data["reported_value"], f"{path}.reported_value")
    tolerance_value = _finite_number(data["tolerance"], f"{path}.tolerance")
    if tolerance_value < 0:
        fail(
            "invalid_tolerance",
            f"{path}.tolerance",
            "Допуск не может быть отрицательным.",
        )
    output_unit = require_string(data["output_unit"], f"{path}.output_unit")
    if (operands[0]["unit"], operands[0]["denominator"]) != (
        operands[1]["unit"],
        operands[1]["denominator"],
    ):
        issues.append("calculation_basis_incompatible")
    computed: float | None = None
    left, right = operands[0]["value"], operands[1]["value"]
    if (
        left is not None
        and right is not None
        and "calculation_basis_incompatible" not in issues
    ):
        if operation == "difference":
            computed = right - left
            if output_unit != operands[0]["unit"]:
                issues.append("calculation_output_unit_mismatch")
        elif operation == "ratio":
            if left == 0:
                issues.append("calculation_zero_denominator")
            else:
                computed = right / left
                if output_unit != "ratio":
                    issues.append("calculation_output_unit_mismatch")
        elif left <= 0:
            issues.append("percent_baseline_nonpositive")
        else:
            computed = (right - left) / left * 100
            if output_unit != "percent":
                issues.append("calculation_output_unit_mismatch")
    if computed is not None and abs(computed - reported_value) > tolerance_value:
        issues.append("calculation_not_reproduced")
    result = {
        "operation": operation,
        "operands": operands,
        "reported_value": reported_value,
        "computed_value": computed,
        "output_unit": output_unit,
        "tolerance": tolerance_value,
    }
    return not issues, result, issues


def semantic_review_target_hash(claim: dict, link: dict) -> str:
    """Bind a review to the exact proposition and supporting source version.

    This identifies the reviewed material; it does not authenticate the reviewer
    or execute the semantic review.
    """
    return sha256_json(
        {
            "claim": claim,
            "evidence": {
                key: link[key]
                for key in (
                    "fragment_ref",
                    "fragment_hash",
                    "quote",
                    "role",
                    "scope_match",
                )
            },
        }
    )


def evaluate_claim(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "run_id",
            "claim",
            "known_fragment_refs",
            "evidence_links",
            "predecessor_claims",
            "qualification_checks",
            "calculation",
            "withdrawn",
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
    claim = require_mapping(data["claim"], "request.claim")
    require_exact_keys(
        claim,
        set(CLAIM_EVALUATE_SCHEMA["properties"]["claim"]["required"]),
        "request.claim",
    )
    claim_id = require_string(claim["claim_id"], "request.claim.claim_id")
    revision = require_int(claim["revision"], "request.claim.revision", minimum=1)
    text = require_string(claim["text"], "request.claim.text")
    proposition_count = require_int(
        claim["atomic_proposition_count"],
        "request.claim.atomic_proposition_count",
        minimum=1,
    )
    kind = require_string(claim["kind"], "request.claim.kind")
    claim_type = require_string(claim["claim_type"], "request.claim.claim_type")
    if kind not in _KINDS:
        fail("invalid_claim_kind", "request.claim.kind", "Неверный вид знания.")
    if claim_type not in _CLAIM_TYPES:
        fail(
            "invalid_claim_type",
            "request.claim.claim_type",
            "Неверный тип утверждения.",
        )
    scope = require_mapping(claim["scope"], "request.claim.scope")
    require_exact_keys(
        scope,
        {"population", "geography", "period", "conditions"},
        "request.claim.scope",
    )
    normalized_scope = {
        "population": require_string(
            scope["population"], "request.claim.scope.population"
        ),
        "geography": require_string(
            scope["geography"], "request.claim.scope.geography"
        ),
        "period": require_string(scope["period"], "request.claim.scope.period"),
        "conditions": _strings(scope["conditions"], "request.claim.scope.conditions"),
    }
    derivation_refs = _strings(
        claim["derivation_refs"], "request.claim.derivation_refs"
    )
    normalized_claim = {
        "claim_id": claim_id,
        "revision": revision,
        "text": text,
        "kind": kind,
        "claim_type": claim_type,
        "scope": normalized_scope,
        "conditions": _strings(claim["conditions"], "request.claim.conditions"),
        "derivation_refs": derivation_refs,
        "alternatives": _strings(claim["alternatives"], "request.claim.alternatives"),
        "non_conclusions": _strings(
            claim["non_conclusions"], "request.claim.non_conclusions"
        ),
        "limitations": _strings(claim["limitations"], "request.claim.limitations"),
        "intended_use": require_string(
            claim["intended_use"], "request.claim.intended_use"
        ),
        "reconsider_triggers": _strings(
            claim["reconsider_triggers"], "request.claim.reconsider_triggers"
        ),
    }
    known_fragments = set(
        _strings(data["known_fragment_refs"], "request.known_fragment_refs")
    )
    predecessor_rows = require_list(
        data["predecessor_claims"], "request.predecessor_claims"
    )
    predecessors: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(predecessor_rows):
        path = f"request.predecessor_claims[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"claim_ref", "status", "current"}, path)
        claim_ref = require_string(row["claim_ref"], f"{path}.claim_ref")
        if claim_ref in predecessors:
            fail(
                "duplicate_predecessor",
                f"{path}.claim_ref",
                "Повторный предшественник.",
            )
        status = require_string(row["status"], f"{path}.status")
        if status not in _CLAIM_STATES:
            fail("invalid_claim_status", f"{path}.status", "Неверный статус тезиса.")
        predecessors[claim_ref] = {
            "status": status,
            "current": require_bool(row["current"], f"{path}.current"),
        }
    unknown_predecessors = sorted(set(derivation_refs) - set(predecessors))
    if unknown_predecessors:
        fail(
            "unknown_predecessor_claim",
            "request.claim.derivation_refs",
            "Производное утверждение ссылается на неизвественный тезис.",
        )

    evidence_rows = require_list(data["evidence_links"], "request.evidence_links")
    links: list[dict[str, Any]] = []
    link_ids: set[str] = set()
    for index, raw in enumerate(evidence_rows):
        path = f"request.evidence_links[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            set(_EVIDENCE_LINK_SCHEMA["required"])
            | ({"semantic_target_hash"} if "semantic_target_hash" in row else set()),
            path,
        )
        link_id = require_string(row["link_id"], f"{path}.link_id")
        if link_id in link_ids:
            fail("duplicate_evidence_link", f"{path}.link_id", "Повторная связь.")
        link_ids.add(link_id)
        fragment_ref = require_string(row["fragment_ref"], f"{path}.fragment_ref")
        if fragment_ref not in known_fragments:
            fail("unknown_fragment", f"{path}.fragment_ref", "Фрагмент отсутствует.")
        fragment_text = require_string(
            row["fragment_exact_text"], f"{path}.fragment_exact_text", nonempty=False
        )
        fragment_hash = _hash(row["fragment_hash"], f"{path}.fragment_hash")
        if hashlib.sha256(fragment_text.encode("utf-8")).hexdigest() != fragment_hash:
            fail(
                "fragment_hash_mismatch",
                f"{path}.fragment_hash",
                "Хеш фрагмента не совпадает.",
            )
        quote = require_string(row["quote"], f"{path}.quote", nonempty=False)
        if not quote or quote not in fragment_text:
            fail(
                "quote_mismatch",
                f"{path}.quote",
                "Цитата не найдена в точном фрагменте.",
            )
        role = require_string(row["role"], f"{path}.role")
        semantic = require_string(row["semantic_status"], f"{path}.semantic_status")
        if role not in _LINK_ROLES or semantic not in _SEMANTIC_STATES:
            fail("invalid_evidence_link", path, "Неверная роль или смысловой статус.")
        reviewer = row["semantic_reviewer_ref"]
        if reviewer is not None:
            reviewer = require_string(reviewer, f"{path}.semantic_reviewer_ref")
        if semantic == "verified" and reviewer is None:
            fail(
                "semantic_reviewer_missing",
                f"{path}.semantic_reviewer_ref",
                "Для смысловой проверки нужен рецензент.",
            )
        target_hash = row.get("semantic_target_hash")
        if target_hash is not None:
            target_hash = _hash(target_hash, f"{path}.semantic_target_hash")
        target_matches = target_hash == semantic_review_target_hash(claim, row)
        links.append(
            {
                "link_id": link_id,
                "fragment_ref": fragment_ref,
                "fragment_hash": fragment_hash,
                "quote": quote,
                "role": role,
                "exact_quote_match": True,
                "semantic_status": semantic,
                "semantic_reviewer_ref": reviewer,
                "semantic_target_hash": target_hash,
                "semantic_target_matches": target_matches,
                "current": require_bool(row["current"], f"{path}.current"),
                "scope_match": require_bool(row["scope_match"], f"{path}.scope_match"),
                "independent": require_bool(row["independent"], f"{path}.independent"),
            }
        )
    checks = require_mapping(
        data["qualification_checks"], "request.qualification_checks"
    )
    check_keys = {
        "scope_closed",
        "limitations_closed",
        "derivation_graph_complete",
        "calculation_reproducible",
    }
    require_exact_keys(checks, check_keys, "request.qualification_checks")
    qualification = {
        key: require_bool(checks[key], f"request.qualification_checks.{key}")
        for key in sorted(check_keys)
    }
    calculation_valid, calculation, calculation_issues = _calculation(
        data["calculation"], "request.calculation"
    )
    if data["calculation"] is not None and not calculation_valid:
        qualification["calculation_reproducible"] = False

    issues = list(calculation_issues)
    if any(
        link["semantic_status"] == "verified" and not link["semantic_target_matches"]
        for link in links
    ):
        issues.append("semantic_review_target_unbound_or_changed")
    if proposition_count != 1:
        issues.append("claim_not_atomic")
    if kind == "inference" and not derivation_refs:
        issues.append("inference_derivation_missing")
    if any(
        not predecessors[ref]["current"]
        or predecessors[ref]["status"] not in {"supported", "qualified"}
        for ref in derivation_refs
    ):
        issues.append("derivation_predecessor_not_supported")
    active_support = [
        link
        for link in links
        if link["role"] == "support"
        and link["current"]
        and link["scope_match"]
        and link["semantic_status"] == "verified"
        and link["semantic_target_matches"]
    ]
    active_contradiction = [
        link
        for link in links
        if link["role"] == "contradict"
        and link["current"]
        and link["scope_match"]
        and link["semantic_status"] == "verified"
        and link["semantic_target_matches"]
    ]
    withdrawn = require_bool(data["withdrawn"], "request.withdrawn")
    if withdrawn:
        claim_status = "withdrawn"
    elif active_contradiction:
        claim_status = "contradicted"
    elif kind == "unknown" or issues or not active_support:
        claim_status = "unresolved"
    elif all(qualification.values()):
        claim_status = "qualified"
    else:
        claim_status = "supported"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "ClaimDecisionReceipt",
        "status": "evaluated" if proposition_count == 1 else "blocked",
        "run_id": run_id,
        "claim": normalized_claim,
        "claim_status": claim_status,
        "evidence_links": links,
        "exact_link_count": len(links),
        "semantically_verified_support_count": len(active_support),
        "verified_contradiction_count": len(active_contradiction),
        "semantic_support_unverified": bool(links) and not bool(active_support),
        "calculation": calculation,
        "qualification_checks": qualification,
        "acceptance_changed": False,
        "release_changed": False,
        "persistence_applied": False,
        "issues": sorted(set(issues)),
    }
    return with_receipt_hash(payload)


def evaluate_challenge(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    required = set(CHALLENGE_EVALUATE_SCHEMA["required"])
    require_exact_keys(data, required, "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    claim_ref = require_string(data["claim_ref"], "request.claim_ref")
    known_claims = set(_strings(data["known_claim_refs"], "request.known_claim_refs"))
    known_evidence = set(
        _strings(data["known_evidence_refs"], "request.known_evidence_refs")
    )
    if claim_ref not in known_claims:
        fail("unknown_claim", "request.claim_ref", "Проверяемый тезис отсутствует.")
    claim_status = require_string(data["claim_status"], "request.claim_status")
    if claim_status not in _CLAIM_STATES:
        fail("invalid_claim_status", "request.claim_status", "Неверный статус тезиса.")
    round_number = require_int(data["round"], "request.round", minimum=1)
    max_rounds = require_int(data["max_rounds"], "request.max_rounds", minimum=1)
    if round_number > max_rounds:
        fail("challenge_round_limit", "request.round", "Превышен предел раундов.")
    alternatives_raw = require_list(data["alternatives"], "request.alternatives")
    if len(alternatives_raw) > 100:
        fail("size_limit", "request.alternatives", "Слишком много альтернатив.")
    alternatives: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(alternatives_raw):
        path = f"request.alternatives[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, set(_ALTERNATIVE_SCHEMA["required"]), path)
        alternative_id = require_string(row["alternative_id"], f"{path}.alternative_id")
        if alternative_id in seen:
            fail(
                "duplicate_alternative",
                f"{path}.alternative_id",
                "Повторная альтернатива.",
            )
        seen.add(alternative_id)
        supporting = _strings(
            row["supporting_claim_refs"], f"{path}.supporting_claim_refs"
        )
        contradicting = _strings(
            row["contradicting_claim_refs"], f"{path}.contradicting_claim_refs"
        )
        unknown = sorted((set(supporting) | set(contradicting)) - known_claims)
        if unknown:
            fail("unknown_claim", path, "Альтернатива ссылается на неизвестный тезис.")
        test_status = require_string(row["test_status"], f"{path}.test_status")
        result = require_string(row["result"], f"{path}.result")
        if test_status not in {"not_tested", "tested"} or result not in {
            "supported",
            "weakened",
            "rejected",
            "unresolved",
        }:
            fail("invalid_alternative_state", path, "Неверное состояние альтернативы.")
        alternatives.append(
            {
                "alternative_id": alternative_id,
                "explanation": require_string(
                    row["explanation"], f"{path}.explanation"
                ),
                "supporting_claim_refs": supporting,
                "contradicting_claim_refs": contradicting,
                "discriminator": require_string(
                    row["discriminator"], f"{path}.discriminator"
                ),
                "test_status": test_status,
                "result": result,
            }
        )
    weakening = _strings(
        data["weakening_evidence_refs"], "request.weakening_evidence_refs"
    )
    if set(weakening) - known_evidence:
        fail(
            "unknown_evidence",
            "request.weakening_evidence_refs",
            "Неизвестная доказательная ссылка.",
        )
    checks = _strings(data["checks"], "request.checks")
    missing_support = _strings(data["missing_support"], "request.missing_support")
    if not alternatives or not checks:
        outcome = "insufficient_material"
    elif any(
        row["test_status"] == "not_tested" or row["result"] == "unresolved"
        for row in alternatives
    ):
        outcome = "evidence_required" if missing_support else "unresolved"
    elif any(row["result"] == "supported" for row in alternatives):
        outcome = "contested"
    elif weakening or any(row["result"] == "weakened" for row in alternatives):
        outcome = "weakened"
    elif all(row["result"] == "rejected" for row in alternatives):
        outcome = "survived"
    else:
        outcome = "unresolved"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "ChallengeRecord",
        "status": "evaluated",
        "run_id": run_id,
        "claim_ref": claim_ref,
        "claim_status_before": claim_status,
        "evidence_profile_ref": require_string(
            data["evidence_profile_ref"], "request.evidence_profile_ref"
        ),
        "checks": checks,
        "alternatives": alternatives,
        "weakening_evidence_refs": weakening,
        "contradiction_types": _strings(
            data["contradiction_types"], "request.contradiction_types"
        ),
        "missing_support": missing_support,
        "outcome": outcome,
        "repair": require_string(data["repair"], "request.repair"),
        "residual_risk": require_string(data["residual_risk"], "request.residual_risk"),
        "safe_wording": require_string(data["safe_wording"], "request.safe_wording"),
        "decision_impact": require_string(
            data["decision_impact"], "request.decision_impact"
        ),
        "round": round_number,
        "max_rounds": max_rounds,
        "claim_status_changed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def assess_synthesis(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(SYNTHESIS_ASSESS_SCHEMA["required"]), "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    profile = require_mapping(data["profile"], "request.profile")
    require_exact_keys(profile, {"depth", "risk"}, "request.profile")
    depth = require_string(profile["depth"], "request.profile.depth")
    risk = require_string(profile["risk"], "request.profile.risk")
    if depth not in {"search", "deep", "ultra"} or risk not in {
        "low",
        "medium",
        "high",
    }:
        fail("invalid_profile", "request.profile", "Неверный профиль.")
    claims_raw = require_list(data["claims"], "request.claims")
    claims: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(claims_raw):
        path = f"request.claims[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"claim_ref", "status", "central", "current", "basis_signature"}, path
        )
        claim_ref = require_string(row["claim_ref"], f"{path}.claim_ref")
        if claim_ref in claims:
            fail("duplicate_claim", f"{path}.claim_ref", "Повторный тезис.")
        status = require_string(row["status"], f"{path}.status")
        if status not in _CLAIM_STATES:
            fail("invalid_claim_status", f"{path}.status", "Неверный статус тезиса.")
        claims[claim_ref] = {
            "status": status,
            "central": require_bool(row["central"], f"{path}.central"),
            "current": require_bool(row["current"], f"{path}.current"),
            "basis_signature": require_string(
                row["basis_signature"], f"{path}.basis_signature"
            ),
        }
    requested = require_mapping(
        data["requested_synthesis"], "request.requested_synthesis"
    )
    require_exact_keys(
        requested,
        {"kind", "claim_refs", "allow_descriptive_fallback"},
        "request.requested_synthesis",
    )
    synthesis_kind = require_string(
        requested["kind"], "request.requested_synthesis.kind"
    )
    if synthesis_kind not in {"descriptive", "comparative", "pooled_quantitative"}:
        fail(
            "invalid_synthesis_kind",
            "request.requested_synthesis.kind",
            "Неверный вид синтеза.",
        )
    claim_refs = _strings(
        requested["claim_refs"], "request.requested_synthesis.claim_refs"
    )
    unknown = sorted(set(claim_refs) - set(claims))
    if unknown:
        fail(
            "unknown_claim",
            "request.requested_synthesis.claim_refs",
            "Синтез ссылается на неизвестный тезис.",
        )
    challenge_rows = require_list(
        data["challenge_records"], "request.challenge_records"
    )
    challenges: list[dict[str, Any]] = []
    for index, raw in enumerate(challenge_rows):
        path = f"request.challenge_records[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"challenge_ref", "claim_ref", "outcome", "current"}, path
        )
        challenged_claim = require_string(row["claim_ref"], f"{path}.claim_ref")
        if challenged_claim not in claims:
            fail(
                "unknown_claim",
                f"{path}.claim_ref",
                "Проверка ссылается на неизвестный тезис.",
            )
        outcome = require_string(row["outcome"], f"{path}.outcome")
        if outcome not in _CHALLENGE_OUTCOMES:
            fail(
                "invalid_challenge_outcome",
                f"{path}.outcome",
                "Неверный исход проверки.",
            )
        challenges.append(
            {
                "challenge_ref": require_string(
                    row["challenge_ref"], f"{path}.challenge_ref"
                ),
                "claim_ref": challenged_claim,
                "outcome": outcome,
                "current": require_bool(row["current"], f"{path}.current"),
            }
        )
    coverage = require_mapping(data["coverage"], "request.coverage")
    require_exact_keys(coverage, {"status", "open_cells"}, "request.coverage")
    coverage_status = require_string(coverage["status"], "request.coverage.status")
    if coverage_status not in {"complete_for_scope", "partial", "unknown"}:
        fail(
            "invalid_coverage_status",
            "request.coverage.status",
            "Неверный статус покрытия.",
        )
    open_cells = _strings(coverage["open_cells"], "request.coverage.open_cells")
    robustness = require_mapping(data["robustness"], "request.robustness")
    require_exact_keys(
        robustness, {"required_checks", "passed_checks"}, "request.robustness"
    )
    required_checks = _strings(
        robustness["required_checks"], "request.robustness.required_checks"
    )
    passed_checks = _strings(
        robustness["passed_checks"], "request.robustness.passed_checks"
    )
    if set(passed_checks) - set(required_checks):
        fail(
            "unknown_robustness_check",
            "request.robustness.passed_checks",
            "Пройдена незапрошенная проверка.",
        )

    missing: list[str] = []
    selected_claims = [claims[ref] for ref in claim_refs]
    if not claim_refs:
        missing.append("claims_missing")
    if any(
        not claim["current"] or claim["status"] not in {"supported", "qualified"}
        for claim in selected_claims
    ):
        missing.append("claim_not_synthesis_ready")
    current_challenges = [row for row in challenges if row["current"]]
    if depth in {"deep", "ultra"} and not current_challenges:
        missing.append("challenge_analysis")
    if any(
        row["outcome"] not in {"survived", "narrowed"} for row in current_challenges
    ):
        missing.append("challenge_unresolved")
    if coverage_status != "complete_for_scope" or open_cells:
        missing.append("coverage_incomplete")
    robustness_missing = sorted(set(required_checks) - set(passed_checks))
    if depth == "ultra" and robustness_missing:
        missing.append("robustness_review")
    bases = {claim["basis_signature"] for claim in selected_claims}
    incompatible_basis = (
        synthesis_kind in {"comparative", "pooled_quantitative"} and len(bases) > 1
    )
    if incompatible_basis:
        missing.append("incompatible_basis")
    allow_fallback = require_bool(
        requested["allow_descriptive_fallback"],
        "request.requested_synthesis.allow_descriptive_fallback",
    )
    effective_kind = (
        "descriptive" if incompatible_basis and allow_fallback else synthesis_kind
    )
    conclusion_allowed = not missing
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "SynthesisDecisionReceipt",
        "status": "draft" if conclusion_allowed else "partial",
        "run_id": run_id,
        "profile": {"depth": depth, "risk": risk},
        "requested_kind": synthesis_kind,
        "effective_kind": effective_kind,
        "claim_refs": claim_refs,
        "challenge_refs": [row["challenge_ref"] for row in current_challenges],
        "coverage_status": coverage_status,
        "open_cells": open_cells,
        "robustness_missing": robustness_missing,
        "incompatible_basis": incompatible_basis,
        "pooled_conclusion_allowed": conclusion_allowed
        and synthesis_kind == "pooled_quantitative",
        "conclusion_allowed": conclusion_allowed,
        "missing_work": list(dict.fromkeys(missing)),
        "acceptance_changed": False,
        "release_changed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)
