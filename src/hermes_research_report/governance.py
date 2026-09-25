"""Assurance strictness, BasicLoop, and human-oversight contracts."""

from __future__ import annotations

from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_exact_keys,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

_TEXT = {"type": "string", "minLength": 1}
_TEXTS = {"type": "array", "maxItems": 1000, "uniqueItems": True, "items": _TEXT}
_TIERS = ("mvp", "standard", "high_stakes")
_EPISTEMIC = ("baseline", "strict", "forensic")
_THINKING = ("bounded", "adversarial", "exhaustive")
_OVERSIGHT = ("H0", "H1", "H2", "H3")
_STAGES = (
    "brief",
    "decomposition",
    "plan",
    "execution",
    "parsing",
    "verification",
    "integration",
    "gap_stop",
    "synthesis",
    "challenge",
    "narrative",
    "debrief",
)
_EPISTEMIC_OBLIGATIONS = {
    "baseline": {"claim_type", "scope", "source", "locator", "uncertainty"},
    "strict": {
        "transition_basis",
        "independence",
        "alternatives",
        "non_inferences",
        "freshness",
    },
    "forensic": {
        "provenance_root",
        "independent_recheck",
        "sensitivity",
        "all_contradictions",
        "reproducible_calculation",
    },
}
_THINKING_OBLIGATIONS = {
    "bounded": {"premises", "definitions", "material_alternative"},
    "adversarial": {
        "ranked_hypotheses",
        "falsification_conditions",
        "counterexamples",
        "discriminating_tests",
    },
    "exhaustive": {
        "dangerous_hypotheses_first",
        "source_sensitivity",
        "definition_sensitivity",
        "premise_sensitivity",
        "alternative_space_coverage",
    },
}

ASSURANCE_PROFILE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "profile_ref",
        "risk",
        "evidence_level",
        "action_reversibility",
        "requested_tier",
        "epistemic_strictness",
        "thinking_strictness",
        "requested_oversight",
        "implemented_obligations",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "profile_ref": _TEXT,
        "risk": {"enum": ["low", "medium", "high"]},
        "evidence_level": {"enum": ["E0", "E1", "E2", "E3", "E4", "E5"]},
        "action_reversibility": {"enum": ["none", "reversible", "irreversible"]},
        "requested_tier": {"enum": list(_TIERS)},
        "epistemic_strictness": {"enum": list(_EPISTEMIC)},
        "thinking_strictness": {"enum": list(_THINKING)},
        "requested_oversight": {"enum": list(_OVERSIGHT)},
        "implemented_obligations": _TEXTS,
    },
}

BASIC_LOOP_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "loop_ref",
        "stages",
        "iteration_limit",
        "iteration_delta_ref",
        "exit_condition",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "loop_ref": _TEXT,
        "stages": _TEXTS,
        "iteration_limit": {"type": "integer", "minimum": 1},
        "iteration_delta_ref": {"type": ["string", "null"]},
        "exit_condition": _TEXT,
    },
}

OVERSIGHT_TRANSITIONS_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "profile_ref", "decisions"],
    "properties": {
        "schema_version": {"const": 1},
        "profile_ref": _TEXT,
        "decisions": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "decision_ref",
                    "actor_ref",
                    "assigned_level",
                    "action",
                    "scope_ref",
                    "profile_version",
                    "decided_at",
                ],
                "properties": {
                    "decision_ref": _TEXT,
                    "actor_ref": _TEXT,
                    "assigned_level": {"enum": list(_OVERSIGHT)},
                    "action": {
                        "enum": [
                            "observe",
                            "stop",
                            "accept_budget",
                            "accept_exception",
                            "authorize_release",
                            "authorize_real_action",
                        ]
                    },
                    "scope_ref": _TEXT,
                    "profile_version": {"type": "integer", "minimum": 1},
                    "decided_at": _TEXT,
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
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_value", path, "Повтор значения запрещён.")
    return result


def _cumulative(
    mapping: dict[str, set[str]], levels: tuple[str, ...], selected: str
) -> set[str]:
    result: set[str] = set()
    for level in levels:
        result.update(mapping[level])
        if level == selected:
            break
    return result


def assess_assurance_profile(request: object) -> dict[str, Any]:
    data = _schema(request, set(ASSURANCE_PROFILE_ASSESS_SCHEMA["required"]))
    profile_ref = require_string(data["profile_ref"], "request.profile_ref")
    risk = require_string(data["risk"], "request.risk")
    evidence = require_string(data["evidence_level"], "request.evidence_level")
    reversibility = require_string(
        data["action_reversibility"], "request.action_reversibility"
    )
    requested_tier = require_string(data["requested_tier"], "request.requested_tier")
    epistemic = require_string(
        data["epistemic_strictness"], "request.epistemic_strictness"
    )
    thinking = require_string(
        data["thinking_strictness"], "request.thinking_strictness"
    )
    requested_oversight = require_string(
        data["requested_oversight"], "request.requested_oversight"
    )
    implemented = set(
        _strings(data["implemented_obligations"], "request.implemented_obligations")
    )
    required_tier = (
        "high_stakes"
        if risk == "high" or evidence in {"E4", "E5"} or reversibility == "irreversible"
        else ("standard" if risk == "medium" or evidence == "E3" else "mvp")
    )
    required_oversight = (
        "H3"
        if risk == "high" or reversibility == "irreversible"
        else ("H2" if risk == "medium" or evidence in {"E3", "E4", "E5"} else "H1")
    )
    required = _cumulative(_EPISTEMIC_OBLIGATIONS, _EPISTEMIC, epistemic)
    required.update(_cumulative(_THINKING_OBLIGATIONS, _THINKING, thinking))
    missing = sorted(required - implemented)
    tier_upgrade = _TIERS.index(requested_tier) < _TIERS.index(required_tier)
    oversight_upgrade = _OVERSIGHT.index(requested_oversight) < _OVERSIGHT.index(
        required_oversight
    )
    issues = [f"obligation_missing:{value}" for value in missing]
    if tier_upgrade:
        issues.append("assurance_tier_too_low")
    if oversight_upgrade:
        issues.append("oversight_level_too_low")
    payload = {
        "schema_version": 1,
        "contract": "AssuranceAndOversightDecisionReceipt",
        "status": "profile_ready" if not issues else "upgrade_required",
        "profile_ref": profile_ref,
        "risk": risk,
        "evidence_level": evidence,
        "requested_tier": requested_tier,
        "required_tier": required_tier,
        "epistemic_strictness": epistemic,
        "thinking_strictness": thinking,
        "requested_oversight": requested_oversight,
        "required_oversight": required_oversight,
        "required_obligations": sorted(required),
        "missing_obligations": missing,
        "risk_lowered": False,
        "evidence_level_lowered": False,
        "external_action_allowed": not issues and required_oversight != "H3",
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def assess_basic_loop(request: object) -> dict[str, Any]:
    data = _schema(request, set(BASIC_LOOP_ASSESS_SCHEMA["required"]))
    loop_ref = require_string(data["loop_ref"], "request.loop_ref")
    stages = _strings(data["stages"], "request.stages")
    require_int(data["iteration_limit"], "request.iteration_limit", minimum=1)
    delta = data["iteration_delta_ref"]
    if delta is not None:
        delta = require_string(delta, "request.iteration_delta_ref")
    exit_condition = require_string(data["exit_condition"], "request.exit_condition")
    missing_stages = [stage for stage in _STAGES if stage not in stages]
    paths = [f"request.stages:{stage}" for stage in missing_stages]
    issues = [f"stage_missing:{stage}" for stage in missing_stages]
    if delta is None:
        paths.append("request.iteration_delta_ref")
        issues.append("iteration_delta_missing")
    payload = {
        "schema_version": 1,
        "contract": "BasicLoopDecisionReceipt",
        "status": "loop_ready" if not issues else "blocked",
        "loop_ref": loop_ref,
        "required_stages": list(_STAGES),
        "provided_stages": stages,
        "missing_stages": missing_stages,
        "iteration_delta_ref": delta,
        "exit_condition": exit_condition,
        "blocking_paths": sorted(paths),
        "execution_started": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def assess_oversight_transitions(request: object) -> dict[str, Any]:
    data = _schema(request, set(OVERSIGHT_TRANSITIONS_ASSESS_SCHEMA["required"]))
    profile_ref = require_string(data["profile_ref"], "request.profile_ref")
    permissions = {
        "H0": {"observe"},
        "H1": {"observe", "stop"},
        "H2": {"observe", "stop", "accept_budget", "accept_exception"},
        "H3": {
            "observe",
            "stop",
            "accept_budget",
            "accept_exception",
            "authorize_release",
            "authorize_real_action",
        },
    }
    records = []
    issues = []
    seen: set[str] = set()
    for index, raw in enumerate(require_list(data["decisions"], "request.decisions")):
        path = f"request.decisions[{index}]"
        row = require_mapping(raw, path)
        fields = {
            "decision_ref",
            "actor_ref",
            "assigned_level",
            "action",
            "scope_ref",
            "profile_version",
            "decided_at",
        }
        require_exact_keys(row, fields, path)
        ref = require_string(row["decision_ref"], f"{path}.decision_ref")
        if ref in seen:
            fail("duplicate_decision", f"{path}.decision_ref", "Повтор решения.")
        seen.add(ref)
        level = require_string(row["assigned_level"], f"{path}.assigned_level")
        action = require_string(row["action"], f"{path}.action")
        allowed = level in permissions and action in permissions[level]
        if not allowed:
            issues.append(f"oversight_scope_exceeded:{ref}")
        records.append(
            {
                "decision_ref": ref,
                "actor_ref": require_string(row["actor_ref"], f"{path}.actor_ref"),
                "assigned_level": level,
                "action": action,
                "scope_ref": require_string(row["scope_ref"], f"{path}.scope_ref"),
                "profile_version": require_int(
                    row["profile_version"], f"{path}.profile_version", minimum=1
                ),
                "decided_at": require_string(row["decided_at"], f"{path}.decided_at"),
                "allowed": allowed,
            }
        )
    payload = {
        "schema_version": 1,
        "contract": "HumanOversightTransitionReceipt",
        "status": "transitions_valid" if not issues else "blocked",
        "profile_ref": profile_ref,
        "decisions": records,
        "external_actions_performed": 0,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)
