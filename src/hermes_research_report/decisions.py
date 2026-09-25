"""Decision, longitudinal delta, incident, and support-independence contracts."""

from __future__ import annotations

from collections import deque
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

_TEXT = {"type": "string", "minLength": 1}
_TEXTS = {"type": "array", "maxItems": 1000, "uniqueItems": True, "items": _TEXT}
_LEVELS = ("E0", "E1", "E2", "E3", "E4", "E5")

DECISION_ENVELOPE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "recommendation_ref",
        "claim_status_before",
        "claim_status_after",
        "recommendation_strength",
        "allow",
        "prohibit",
        "test",
        "monitor",
        "collect_data",
        "action_if_true",
        "action_if_false",
        "risks",
        "owner",
        "threshold",
        "triggers",
        "challenge",
        "human_impact",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "recommendation_ref": _TEXT,
        "claim_status_before": {
            "enum": ["supported", "contested", "weakened", "unresolved"]
        },
        "claim_status_after": {
            "enum": ["supported", "contested", "weakened", "unresolved"]
        },
        "recommendation_strength": {
            "enum": [
                "observation",
                "limited_test",
                "reversible_action",
                "irreversible_action",
            ]
        },
        "allow": _TEXTS,
        "prohibit": _TEXTS,
        "test": _TEXTS,
        "monitor": _TEXTS,
        "collect_data": _TEXTS,
        "action_if_true": _TEXT,
        "action_if_false": _TEXT,
        "risks": _TEXTS,
        "owner": _TEXT,
        "threshold": _TEXT,
        "triggers": _TEXTS,
        "challenge": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "discriminator", "outcome", "safe_wording"],
            "properties": {
                "type": {
                    "enum": [
                        "fact",
                        "method",
                        "definition",
                        "causal",
                        "scope",
                        "authority",
                    ]
                },
                "discriminator": _TEXT,
                "outcome": {
                    "enum": ["survived", "contested", "weakened", "unresolved"]
                },
                "safe_wording": _TEXT,
            },
        },
        "human_impact": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "applies",
                "prediction_unit",
                "decision_unit",
                "automatic_action_requested",
                "gates",
            ],
            "properties": {
                "applies": {"type": "boolean"},
                "prediction_unit": {"enum": ["none", "segment", "individual"]},
                "decision_unit": {"enum": ["none", "segment", "individual"]},
                "automatic_action_requested": {"type": "boolean"},
                "gates": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["harm", "fairness", "privacy", "authority"],
                    "properties": {
                        "harm": {"enum": ["pass", "fail", "not_assessed"]},
                        "fairness": {"enum": ["pass", "fail", "not_assessed"]},
                        "privacy": {"enum": ["pass", "fail", "not_assessed"]},
                        "authority": {"enum": ["pass", "fail", "not_assessed"]},
                    },
                },
            },
        },
    },
}

DELTA_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "baseline_ref",
        "expected_revision",
        "current_revision",
        "materiality_threshold",
        "delta_score",
        "same_version_content_conflict",
        "changed_refs",
        "tracked_refs",
        "dependency_edges",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "baseline_ref": _TEXT,
        "expected_revision": {"type": "integer", "minimum": 1},
        "current_revision": {"type": "integer", "minimum": 1},
        "materiality_threshold": {"type": "integer", "minimum": 0},
        "delta_score": {"type": "integer", "minimum": 0},
        "same_version_content_conflict": {"type": "boolean"},
        "changed_refs": _TEXTS,
        "tracked_refs": _TEXTS,
        "dependency_edges": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["input_ref", "dependent_ref"],
                "properties": {"input_ref": _TEXT, "dependent_ref": _TEXT},
            },
        },
    },
}

INCIDENT_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "incident_ref",
        "as_of",
        "sources",
        "claims",
        "alternatives",
        "action",
        "post_incident_review_ref",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "incident_ref": _TEXT,
        "as_of": _TEXT,
        "sources": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_ref", "reliability_rank"],
                "properties": {
                    "source_ref": _TEXT,
                    "reliability_rank": {"type": "integer", "minimum": 1},
                },
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
                    "knowledge_status",
                    "preliminary",
                    "observed_at",
                ],
                "properties": {
                    "claim_ref": _TEXT,
                    "knowledge_status": {"enum": ["known", "unknown"]},
                    "preliminary": {"type": "boolean"},
                    "observed_at": _TEXT,
                },
            },
        },
        "alternatives": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["alternative_ref", "danger_rank", "test_ref"],
                "properties": {
                    "alternative_ref": _TEXT,
                    "danger_rank": {"type": "integer", "minimum": 1},
                    "test_ref": _TEXT,
                },
            },
        },
        "action": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action_ref", "high_risk", "authorized"],
            "properties": {
                "action_ref": _TEXT,
                "high_risk": {"type": "boolean"},
                "authorized": {"type": "boolean"},
            },
        },
        "post_incident_review_ref": _TEXT,
    },
}

INDEPENDENT_SUPPORT_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "claim_ref",
        "requested_evidence_level",
        "supports",
        "single_source_exception",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "claim_ref": _TEXT,
        "requested_evidence_level": {"enum": list(_LEVELS)},
        "supports": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "support_ref",
                    "origin_cluster",
                    "model_family",
                    "corpus_ref",
                    "method_ref",
                ],
                "properties": {
                    "support_ref": _TEXT,
                    "origin_cluster": _TEXT,
                    "model_family": _TEXT,
                    "corpus_ref": _TEXT,
                    "method_ref": _TEXT,
                },
            },
        },
        "single_source_exception": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["accepted", "owner", "rationale", "expires_at"],
                    "properties": {
                        "accepted": {"type": "boolean"},
                        "owner": _TEXT,
                        "rationale": _TEXT,
                        "expires_at": _TEXT,
                    },
                },
            ]
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
        fail("duplicate_reference", path, "Повтор ссылки запрещён.")
    return result


def assess_decision_envelope(request: object) -> dict[str, Any]:
    data = _schema(request, set(DECISION_ENVELOPE_ASSESS_SCHEMA["required"]))
    recommendation_ref = require_string(
        data["recommendation_ref"], "request.recommendation_ref"
    )
    before = require_string(data["claim_status_before"], "request.claim_status_before")
    after = require_string(data["claim_status_after"], "request.claim_status_after")
    strength = require_string(
        data["recommendation_strength"], "request.recommendation_strength"
    )
    actions = {
        key: _strings(data[key], f"request.{key}")
        for key in ("allow", "prohibit", "test", "monitor", "collect_data")
    }
    action_if_true = require_string(data["action_if_true"], "request.action_if_true")
    action_if_false = require_string(data["action_if_false"], "request.action_if_false")
    risks = _strings(data["risks"], "request.risks")
    owner = require_string(data["owner"], "request.owner")
    threshold = require_string(data["threshold"], "request.threshold")
    triggers = _strings(data["triggers"], "request.triggers")
    challenge = require_mapping(data["challenge"], "request.challenge")
    require_exact_keys(
        challenge,
        {"type", "discriminator", "outcome", "safe_wording"},
        "request.challenge",
    )
    challenge_record = {
        key: require_string(challenge[key], f"request.challenge.{key}")
        for key in ("type", "discriminator", "outcome", "safe_wording")
    }
    weakened = after in {
        "contested",
        "weakened",
        "unresolved",
    }
    issues: list[str] = []
    missing = [key for key, values in actions.items() if not values]
    if not risks:
        missing.append("risks")
    if not triggers:
        missing.append("triggers")
    issues.extend(f"decision_field_empty:{field}" for field in missing)
    impact = require_mapping(data["human_impact"], "request.human_impact")
    require_exact_keys(
        impact,
        {
            "applies",
            "prediction_unit",
            "decision_unit",
            "automatic_action_requested",
            "gates",
        },
        "request.human_impact",
    )
    applies = require_bool(impact["applies"], "request.human_impact.applies")
    prediction_unit = require_string(
        impact["prediction_unit"], "request.human_impact.prediction_unit"
    )
    decision_unit = require_string(
        impact["decision_unit"], "request.human_impact.decision_unit"
    )
    automatic = require_bool(
        impact["automatic_action_requested"],
        "request.human_impact.automatic_action_requested",
    )
    gates = require_mapping(impact["gates"], "request.human_impact.gates")
    require_exact_keys(
        gates,
        {"harm", "fairness", "privacy", "authority"},
        "request.human_impact.gates",
    )
    gate_values = {
        key: require_string(gates[key], f"request.human_impact.gates.{key}")
        for key in ("harm", "fairness", "privacy", "authority")
    }
    individual_from_segment = (
        applies and prediction_unit == "segment" and decision_unit == "individual"
    )
    if individual_from_segment and automatic:
        issues.append("segment_prediction_not_individual_authority")
    if applies and any(value != "pass" for value in gate_values.values()):
        issues.append("human_impact_gate_incomplete")
    safe_strength = (
        "limited_test"
        if weakened and strength in {"reversible_action", "irreversible_action"}
        else strength
    )
    payload = {
        "schema_version": 1,
        "contract": "DecisionEnvelopeReceipt",
        "status": "decision_ready" if not issues else "blocked",
        "recommendation_ref": recommendation_ref,
        "claim_status_before": before,
        "claim_status_after": after,
        "recommendation_strength": safe_strength,
        "prior_stronger_recommendation_active": not weakened,
        "recommended_safe_actions": sorted(set(actions["test"] + actions["monitor"]))
        if weakened
        else actions["allow"],
        "allow": actions["allow"],
        "prohibit": actions["prohibit"],
        "test": actions["test"],
        "monitor": actions["monitor"],
        "collect_data": actions["collect_data"],
        "action_if_true": action_if_true,
        "action_if_false": action_if_false,
        "risks": risks,
        "owner": owner,
        "threshold": threshold,
        "triggers": triggers,
        "challenge": challenge_record,
        "human_impact_gates": gate_values,
        "automatic_action_allowed": False,
        "external_action_performed": False,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def assess_delta(request: object) -> dict[str, Any]:
    data = _schema(request, set(DELTA_ASSESS_SCHEMA["required"]))
    baseline_ref = require_string(data["baseline_ref"], "request.baseline_ref")
    expected = require_int(
        data["expected_revision"], "request.expected_revision", minimum=1
    )
    current = require_int(
        data["current_revision"], "request.current_revision", minimum=1
    )
    threshold = require_int(
        data["materiality_threshold"], "request.materiality_threshold"
    )
    score = require_int(data["delta_score"], "request.delta_score")
    conflict = require_bool(
        data["same_version_content_conflict"], "request.same_version_content_conflict"
    )
    changed = _strings(data["changed_refs"], "request.changed_refs")
    tracked = _strings(data["tracked_refs"], "request.tracked_refs")
    adjacency: dict[str, set[str]] = {}
    for index, raw in enumerate(
        require_list(data["dependency_edges"], "request.dependency_edges")
    ):
        path = f"request.dependency_edges[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"input_ref", "dependent_ref"}, path)
        source = require_string(row["input_ref"], f"{path}.input_ref")
        dependent = require_string(row["dependent_ref"], f"{path}.dependent_ref")
        adjacency.setdefault(source, set()).add(dependent)
    issues = []
    if expected != current:
        issues.append("stale_baseline")
    if conflict:
        issues.append("same_version_content_conflict")
    material = score >= threshold and bool(changed)
    affected: set[str] = set()
    pending = deque(changed)
    while pending:
        ref = pending.popleft()
        for dependent in sorted(adjacency.get(ref, set())):
            if dependent not in affected:
                affected.add(dependent)
                pending.append(dependent)
    reassess = sorted(affected & set(tracked)) if material and not issues else []
    status = (
        "blocked"
        if issues
        else ("material_change" if material else "no_material_change")
    )
    payload = {
        "schema_version": 1,
        "contract": "DeltaDecisionReceipt",
        "status": status,
        "baseline_ref": baseline_ref,
        "expected_revision": expected,
        "current_revision": current,
        "delta_score": score,
        "materiality_threshold": threshold,
        "changed_refs": changed,
        "reassess_refs": reassess,
        "unaffected_refs": sorted(set(tracked) - set(reassess)),
        "full_report_proposed": False,
        "receipt_count": 1,
        "authoritative_state_changed": False,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def assess_incident(request: object) -> dict[str, Any]:
    data = _schema(request, set(INCIDENT_ASSESS_SCHEMA["required"]))
    incident_ref = require_string(data["incident_ref"], "request.incident_ref")
    as_of = require_string(data["as_of"], "request.as_of")
    try:
        cutoff = datetime.fromisoformat(as_of)
        if cutoff.tzinfo is None:
            raise ValueError()
    except ValueError:
        fail(
            "invalid_incident_cutoff",
            "request.as_of",
            "Требуется время с часовым поясом.",
        )
    snapshot_issues = []
    source_ranks: list[dict[str, Any]] = []
    for index, raw in enumerate(require_list(data["sources"], "request.sources")):
        path = f"request.sources[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"source_ref", "reliability_rank"}, path)
        source_ranks.append(
            {
                "source_ref": require_string(row["source_ref"], f"{path}.source_ref"),
                "reliability_rank": require_int(
                    row["reliability_rank"], f"{path}.reliability_rank", minimum=1
                ),
            }
        )
    claims: list[dict[str, Any]] = []
    for index, raw in enumerate(require_list(data["claims"], "request.claims")):
        path = f"request.claims[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"claim_ref", "knowledge_status", "preliminary", "observed_at"}, path
        )
        claims.append(
            {
                "claim_ref": require_string(row["claim_ref"], f"{path}.claim_ref"),
                "knowledge_status": require_string(
                    row["knowledge_status"], f"{path}.knowledge_status"
                ),
                "preliminary": require_bool(row["preliminary"], f"{path}.preliminary"),
                "observed_at": require_string(
                    row["observed_at"], f"{path}.observed_at"
                ),
            }
        )
    for row in claims:
        try:
            observed = datetime.fromisoformat(row["observed_at"])
            if observed.tzinfo is None:
                raise ValueError()
        except ValueError:
            fail(
                "invalid_incident_observation",
                "request.claims",
                "Требуется время наблюдения с часовым поясом.",
            )
        if observed > cutoff:
            snapshot_issues.append("incident_observation_after_cutoff")
        if not row["preliminary"]:
            snapshot_issues.append("incident_claim_not_preliminary")
    alternatives: list[dict[str, Any]] = []
    for index, raw in enumerate(
        require_list(data["alternatives"], "request.alternatives")
    ):
        path = f"request.alternatives[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"alternative_ref", "danger_rank", "test_ref"}, path)
        alternatives.append(
            {
                "alternative_ref": require_string(
                    row["alternative_ref"], f"{path}.alternative_ref"
                ),
                "danger_rank": require_int(
                    row["danger_rank"], f"{path}.danger_rank", minimum=1
                ),
                "test_ref": require_string(row["test_ref"], f"{path}.test_ref"),
            }
        )
    evaluation_order = [
        row["alternative_ref"]
        for row in sorted(
            alternatives, key=lambda row: (row["danger_rank"], row["alternative_ref"])
        )
    ]
    action = require_mapping(data["action"], "request.action")
    require_exact_keys(
        action, {"action_ref", "high_risk", "authorized"}, "request.action"
    )
    action_ref = require_string(action["action_ref"], "request.action.action_ref")
    high_risk = require_bool(action["high_risk"], "request.action.high_risk")
    authorized = require_bool(action["authorized"], "request.action.authorized")
    post_review = require_string(
        data["post_incident_review_ref"], "request.post_incident_review_ref"
    )
    issues = snapshot_issues + (
        ["high_risk_action_not_authorized"] if high_risk and not authorized else []
    )
    payload = {
        "schema_version": 1,
        "contract": "IncidentDecisionEnvelopeReceipt",
        "status": "partial_action_blocked" if issues else "incident_snapshot_ready",
        "incident_ref": incident_ref,
        "as_of": as_of,
        "sources_by_reliability": sorted(
            source_ranks, key=lambda row: (row["reliability_rank"], row["source_ref"])
        ),
        "claims": claims,
        "known_claim_refs": sorted(
            row["claim_ref"] for row in claims if row["knowledge_status"] == "known"
        ),
        "unknown_claim_refs": sorted(
            row["claim_ref"] for row in claims if row["knowledge_status"] == "unknown"
        ),
        "all_claims_preliminary_and_timed": all(
            row["preliminary"] and row["observed_at"] for row in claims
        ),
        "alternative_evaluation_order": evaluation_order,
        "dangerous_alternatives_first": evaluation_order
        == [
            row["alternative_ref"]
            for row in sorted(alternatives, key=lambda row: row["danger_rank"])
        ],
        "analysis_separate_from_action": True,
        "action_checkpoint": {
            "action_ref": action_ref,
            "authorized": authorized,
            "execution_allowed": not issues,
        },
        "partial_analysis_retained": True,
        "post_incident_review_ref": post_review,
        "external_action_performed": False,
        "persistence_applied": False,
        "issues": issues,
    }
    return with_receipt_hash(payload)


def assess_independent_support(request: object) -> dict[str, Any]:
    data = _schema(request, set(INDEPENDENT_SUPPORT_ASSESS_SCHEMA["required"]))
    claim_ref = require_string(data["claim_ref"], "request.claim_ref")
    level = require_string(
        data["requested_evidence_level"], "request.requested_evidence_level"
    )
    if level not in _LEVELS:
        fail(
            "invalid_evidence_level",
            "request.requested_evidence_level",
            "Неизвестный E-уровень.",
        )
    supports: list[dict[str, str]] = []
    support_refs: set[str] = set()
    independence_groups: set[tuple[str, str, str, str]] = set()
    origins: set[str] = set()
    for index, raw in enumerate(require_list(data["supports"], "request.supports")):
        path = f"request.supports[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "support_ref",
                "origin_cluster",
                "model_family",
                "corpus_ref",
                "method_ref",
            },
            path,
        )
        record = {
            key: require_string(row[key], f"{path}.{key}")
            for key in (
                "support_ref",
                "origin_cluster",
                "model_family",
                "corpus_ref",
                "method_ref",
            )
        }
        if record["support_ref"] in support_refs:
            fail("duplicate_support", f"{path}.support_ref", "Повтор опоры.")
        support_refs.add(record["support_ref"])
        supports.append(record)
        origins.add(record["origin_cluster"])
        independence_groups.add(
            (
                record["origin_cluster"],
                record["model_family"],
                record["corpus_ref"],
                record["method_ref"],
            )
        )
    exception = data["single_source_exception"]
    exception_record = None
    exception_accepted = False
    if exception is not None:
        row = require_mapping(exception, "request.single_source_exception")
        require_exact_keys(
            row,
            {"accepted", "owner", "rationale", "expires_at"},
            "request.single_source_exception",
        )
        exception_accepted = require_bool(
            row["accepted"], "request.single_source_exception.accepted"
        )
        exception_record = {
            "accepted": exception_accepted,
            "owner": require_string(
                row["owner"], "request.single_source_exception.owner"
            ),
            "rationale": require_string(
                row["rationale"], "request.single_source_exception.rationale"
            ),
            "expires_at": require_string(
                row["expires_at"], "request.single_source_exception.expires_at"
            ),
        }
    high_level = level in {"E3", "E4", "E5"}
    sufficient = len(origins) >= 2 and len(independence_groups) >= 2
    issues = []
    if high_level and not sufficient and not exception_accepted:
        issues.append("independent_support_insufficient")
    effective = level if (not high_level or sufficient) else "E2"
    status = (
        "qualified"
        if not issues and (not high_level or sufficient)
        else ("limited_by_exception" if exception_accepted else "blocked")
    )
    payload = {
        "schema_version": 1,
        "contract": "IndependentSupportDecisionReceipt",
        "status": status,
        "claim_ref": claim_ref,
        "requested_evidence_level": level,
        "effective_evidence_level": effective,
        "support_count": len(supports),
        "independent_origin_count": len(origins),
        "independence_group_count": len(independence_groups),
        "independent_support_sufficient": sufficient,
        "single_source_exception": exception_record,
        "evidence_level_raised_by_exception": False,
        "claim_status_changed": False,
        "persistence_applied": False,
        "issues": issues,
    }
    return with_receipt_hash(payload)
