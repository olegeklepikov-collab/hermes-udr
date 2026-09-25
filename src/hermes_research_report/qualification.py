"""Operational candidate, profile, depth, and utility qualification decisions."""

from __future__ import annotations

import math
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
_ARR = {"type": "array", "maxItems": 1000, "uniqueItems": True, "items": _TEXT}
DEPLOYMENT_CANDIDATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "candidate_version",
        "on_demand",
        "requires_daemon",
        "requires_cluster",
        "requires_gpu",
        "manifest_ref",
        "lock_ref",
        "root_map_ref",
        "staging",
        "compatibility",
        "rollback",
        "backup_restore",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "candidate_version": _TEXT,
        "on_demand": {"type": "boolean"},
        "requires_daemon": {"type": "boolean"},
        "requires_cluster": {"type": "boolean"},
        "requires_gpu": {"type": "boolean"},
        "manifest_ref": _TEXT,
        "lock_ref": _TEXT,
        "root_map_ref": _TEXT,
        "staging": {
            "type": "object",
            "additionalProperties": False,
            "required": ["installed", "native_tool_results", "required_tool_names"],
            "properties": {
                "installed": {"type": "boolean"},
                "native_tool_results": {
                    "type": "array",
                    "maxItems": 1000,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["tool", "status", "receipt_ref"],
                        "properties": {
                            "tool": _TEXT,
                            "status": {"enum": ["pass", "fail"]},
                            "receipt_ref": _TEXT,
                        },
                    },
                },
                "required_tool_names": _ARR,
            },
        },
        "compatibility": {
            "type": "object",
            "additionalProperties": False,
            "required": ["environment", "schema", "state"],
            "properties": {
                "environment": {"type": "boolean"},
                "schema": {"type": "boolean"},
                "state": {"type": "boolean"},
            },
        },
        "rollback": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "environment_compatible",
                "state_compatible",
                "external_effects_reconciled",
                "smoke_pass",
            ],
            "properties": {
                "environment_compatible": {"type": "boolean"},
                "state_compatible": {"type": "boolean"},
                "external_effects_reconciled": {"type": "boolean"},
                "smoke_pass": {"type": "boolean"},
            },
        },
        "backup_restore": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "consistent_snapshot",
                "empty_target_restore",
                "readback_pass",
            ],
            "properties": {
                "consistent_snapshot": {"type": "boolean"},
                "empty_target_restore": {"type": "boolean"},
                "readback_pass": {"type": "boolean"},
            },
        },
    },
}
PROFILE_QUALIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "profile", "suite", "task_results"],
    "properties": {
        "schema_version": {"const": 1},
        "profile": {
            "type": "object",
            "additionalProperties": False,
            "required": ["domain", "depth", "risk", "version"],
            "properties": {
                "domain": {"enum": ["general", "business", "academic"]},
                "depth": {"enum": ["search", "deep", "ultra"]},
                "risk": {"enum": ["low", "medium", "high"]},
                "version": _TEXT,
            },
        },
        "suite": {
            "type": "object",
            "additionalProperties": False,
            "required": ["suite_id", "sealed_before_run", "thresholds", "task_classes"],
            "properties": {
                "suite_id": _TEXT,
                "sealed_before_run": {"type": "boolean"},
                "thresholds": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["correctness_min", "critical_failure_max"],
                    "properties": {
                        "correctness_min": {"type": "number"},
                        "critical_failure_max": {"type": "integer", "minimum": 0},
                    },
                },
                "task_classes": _ARR,
            },
        },
        "task_results": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "task_id",
                    "task_class",
                    "correctness",
                    "critical_failures",
                    "review_complete",
                ],
                "properties": {
                    "task_id": _TEXT,
                    "task_class": _TEXT,
                    "correctness": {"type": "number"},
                    "critical_failures": {"type": "integer", "minimum": 0},
                    "review_complete": {"type": "boolean"},
                },
            },
        },
    },
}
PROFILE_QUALIFICATION_SCHEMA["properties"]["primary_reviews"] = {
    "type": "array",
    "maxItems": 10000,
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "task_id",
            "generator_ref",
            "reviewer_ref",
            "review_input",
            "materials",
            "judgments",
        ],
        "properties": {
            "task_id": {"type": "string", "minLength": 1},
            "generator_ref": {"type": "string", "minLength": 1},
            "reviewer_ref": {"type": "string", "minLength": 1},
            "review_input": {"type": "string", "minLength": 1},
            "materials": {
                "type": "array",
                "maxItems": 10000,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_ref", "source_author_ref", "text", "sha256"],
                    "properties": {
                        "source_ref": {"type": "string", "minLength": 1},
                        "source_author_ref": {"type": "string", "minLength": 1},
                        "text": {"type": "string", "minLength": 1},
                        "sha256": {"type": "string", "minLength": 1},
                    },
                },
            },
            "judgments": {
                "type": "array",
                "maxItems": 10000,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "claim_id",
                        "claim",
                        "source_ref",
                        "start",
                        "end",
                        "quote",
                        "verdict",
                        "rationale",
                        "disagreement",
                    ],
                    "properties": {
                        "claim_id": {"type": "string", "minLength": 1},
                        "claim": {"type": "string", "minLength": 1},
                        "source_ref": {"type": "string", "minLength": 1},
                        "start": {"type": "integer", "minimum": 0},
                        "end": {"type": "integer", "minimum": 0},
                        "quote": {"type": "string", "minLength": 1},
                        "verdict": {
                            "enum": ["supported", "contradicted", "unresolved"]
                        },
                        "rationale": {"type": "string", "minLength": 1},
                        "disagreement": {"type": ["string", "null"]},
                    },
                },
            },
        },
    },
}

DEPTH_COMPARISON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "task_ref", "constraint_hash", "results"],
    "properties": {
        "schema_version": {"const": 1},
        "task_ref": _TEXT,
        "constraint_hash": _TEXT,
        "results": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "depth",
                    "task_ref",
                    "constraint_hash",
                    "correctness",
                    "cost",
                    "review_effort",
                    "repair_effort",
                    "useful_delta",
                    "output_size",
                    "tool_calls",
                    "errors",
                ],
                "properties": {
                    "depth": {"enum": ["search", "deep", "ultra"]},
                    "task_ref": _TEXT,
                    "constraint_hash": _TEXT,
                    "correctness": {"type": "number"},
                    "cost": {"type": "number"},
                    "review_effort": {"type": "number"},
                    "repair_effort": {"type": "number"},
                    "useful_delta": {"type": "number"},
                    "output_size": {"type": "integer", "minimum": 0},
                    "tool_calls": {"type": "integer", "minimum": 0},
                    "errors": {"type": "integer", "minimum": 0},
                },
            },
        },
    },
}
UTILITY_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "result_ref",
        "decision_quality",
        "time_saved",
        "verification_burden",
        "correctness",
        "commercial_effect",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "result_ref": _TEXT,
        "decision_quality": {"type": "number"},
        "time_saved": {"type": "number"},
        "verification_burden": {"type": "number"},
        "correctness": {"type": "number"},
        "commercial_effect": {"type": ["number", "null"]},
    },
}


def _finite(value: object, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        fail("invalid_number", path, "Требуется конечное число.")
    return float(value)


def assess_deployment_candidate(request: object) -> dict[str, Any]:
    d = require_mapping(request, "request")
    require_exact_keys(d, set(DEPLOYMENT_CANDIDATE_SCHEMA["required"]), "request")
    if d["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    version = require_string(d["candidate_version"], "request.candidate_version")
    refs = {
        k: require_string(d[k], f"request.{k}")
        for k in ("manifest_ref", "lock_ref", "root_map_ref")
    }
    issues = []
    if not require_bool(d["on_demand"], "request.on_demand"):
        issues.append("on_demand_baseline_missing")
    for key in ("requires_daemon", "requires_cluster", "requires_gpu"):
        if require_bool(d[key], f"request.{key}"):
            issues.append(f"mandatory_{key}")
    staging = require_mapping(d["staging"], "request.staging")
    require_exact_keys(
        staging,
        {"installed", "native_tool_results", "required_tool_names"},
        "request.staging",
    )
    required = {
        require_string(x, f"request.staging.required_tool_names[{i}]")
        for i, x in enumerate(
            require_list(
                staging["required_tool_names"], "request.staging.required_tool_names"
            )
        )
    }
    passed = set()
    seen = set()
    for i, raw in enumerate(
        require_list(
            staging["native_tool_results"], "request.staging.native_tool_results"
        )
    ):
        p = f"request.staging.native_tool_results[{i}]"
        row = require_mapping(raw, p)
        require_exact_keys(row, {"tool", "status", "receipt_ref"}, p)
        tool = require_string(row["tool"], f"{p}.tool")
        require_string(row["receipt_ref"], f"{p}.receipt_ref")
        if tool in seen:
            fail("duplicate_tool_result", f"{p}.tool", "Повторный результат.")
        seen.add(tool)
        if row["status"] == "pass":
            passed.add(tool)
    if not require_bool(
        staging["installed"], "request.staging.installed"
    ) or not required.issubset(passed):
        issues.append("staging_native_smoke_incomplete")
    compatibility = require_mapping(d["compatibility"], "request.compatibility")
    require_exact_keys(
        compatibility, {"environment", "schema", "state"}, "request.compatibility"
    )
    if not all(
        require_bool(compatibility[k], f"request.compatibility.{k}")
        for k in compatibility
    ):
        issues.append("candidate_incompatible")
    rollback = require_mapping(d["rollback"], "request.rollback")
    require_exact_keys(
        rollback,
        {
            "environment_compatible",
            "state_compatible",
            "external_effects_reconciled",
            "smoke_pass",
        },
        "request.rollback",
    )
    if not all(require_bool(rollback[k], f"request.rollback.{k}") for k in rollback):
        issues.append("rollback_not_verified")
    backup = require_mapping(d["backup_restore"], "request.backup_restore")
    require_exact_keys(
        backup,
        {"consistent_snapshot", "empty_target_restore", "readback_pass"},
        "request.backup_restore",
    )
    if not all(require_bool(backup[k], f"request.backup_restore.{k}") for k in backup):
        issues.append("backup_restore_not_verified")
    issues = sorted(set(issues))
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "DeploymentCandidateDecisionReceipt",
            "status": "switch_ready" if not issues else "blocked",
            "candidate_version": version,
            "artifact_refs": refs,
            "active_version_changed": False,
            "switch_performed": False,
            "rollback_performed": False,
            "issues": issues,
        }
    )


def evaluate_profile_qualification(request: object) -> dict[str, Any]:
    d = require_mapping(request, "request")
    review_inputs = d.get("primary_reviews", [])
    require_exact_keys(
        {k: v for k, v in d.items() if k != "primary_reviews"},
        set(PROFILE_QUALIFICATION_SCHEMA["required"]),
        "request",
    )
    if d["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    profile = require_mapping(d["profile"], "request.profile")
    require_exact_keys(
        profile, {"domain", "depth", "risk", "version"}, "request.profile"
    )
    normalized = {
        k: require_string(profile[k], f"request.profile.{k}") for k in profile
    }
    suite = require_mapping(d["suite"], "request.suite")
    require_exact_keys(
        suite,
        {"suite_id", "sealed_before_run", "thresholds", "task_classes"},
        "request.suite",
    )
    suite_id = require_string(suite["suite_id"], "request.suite.suite_id")
    sealed = require_bool(suite["sealed_before_run"], "request.suite.sealed_before_run")
    classes = {
        require_string(x, f"request.suite.task_classes[{i}]")
        for i, x in enumerate(
            require_list(suite["task_classes"], "request.suite.task_classes")
        )
    }
    thresholds = require_mapping(suite["thresholds"], "request.suite.thresholds")
    require_exact_keys(
        thresholds,
        {"correctness_min", "critical_failure_max"},
        "request.suite.thresholds",
    )
    minimum = _finite(
        thresholds["correctness_min"], "request.suite.thresholds.correctness_min"
    )
    max_fail = require_int(
        thresholds["critical_failure_max"],
        "request.suite.thresholds.critical_failure_max",
    )
    results = []
    task_ids = set()
    for i, raw in enumerate(require_list(d["task_results"], "request.task_results")):
        p = f"request.task_results[{i}]"
        row = require_mapping(raw, p)
        require_exact_keys(
            row,
            {
                "task_id",
                "task_class",
                "correctness",
                "critical_failures",
                "review_complete",
            }
            | (set(row) & {"answer_sha256"}),
            p,
        )
        task_id = require_string(row["task_id"], f"{p}.task_id")
        if task_id in task_ids:
            fail("duplicate_task_result", f"{p}.task_id", "Повтор результата задачи.")
        task_ids.add(task_id)
        results.append(
            {
                "answer_sha256": require_string(
                    row["answer_sha256"], f"{p}.answer_sha256"
                )
                if "answer_sha256" in row
                else None,
                "task_id": require_string(row["task_id"], f"{p}.task_id"),
                "task_class": require_string(row["task_class"], f"{p}.task_class"),
                "correctness": _finite(row["correctness"], f"{p}.correctness"),
                "critical_failures": require_int(
                    row["critical_failures"], f"{p}.critical_failures"
                ),
                "review_complete": require_bool(
                    row["review_complete"], f"{p}.review_complete"
                ),
            }
        )
    from .security_controls import assess_security_control

    reviews = {}
    for raw in require_list(review_inputs, "request.primary_reviews"):
        review = assess_security_control(
            {"schema_version": 1, "control_type": "primary_review", "payload": raw}
        )
        if review["task_id"] in reviews:
            fail(
                "duplicate_primary_review",
                "request.primary_reviews",
                "Повтор проверки задачи.",
            )
        reviews[review["task_id"]] = review
    review_bound = bool(results) and set(reviews) == {r["task_id"] for r in results}
    review_bound = review_bound and all(
        reviews[r["task_id"]]["independent_metric_eligible"]
        and reviews[r["task_id"]]["answer_sha256"] == r["answer_sha256"]
        and reviews[r["task_id"]]["correctness"] == r["correctness"]
        and reviews[r["task_id"]]["critical_failures"] == r["critical_failures"]
        for r in results
    )
    covered = {r["task_class"] for r in results}
    mean = sum(r["correctness"] for r in results) / len(results) if results else 0
    failures = sum(r["critical_failures"] for r in results)
    qualified = (
        review_bound
        and sealed
        and classes.issubset(covered)
        and mean >= minimum
        and failures <= max_fail
        and all(r["review_complete"] for r in results)
    )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "ProfileQualificationReceipt",
            "status": "qualified" if qualified else "not_qualified",
            "profile": normalized,
            "suite_id": suite_id,
            "tested_task_classes": sorted(covered),
            "qualification_scope": {
                "domain": normalized["domain"],
                "depth": normalized["depth"],
                "risk": normalized["risk"],
            },
            "mean_correctness": mean,
            "primary_review_bound": review_bound,
            "primary_review_receipts": list(reviews.values()),
            "independent_metric_eligible": review_bound,
            "external_product_acceptance": False,
            "critical_failures": failures,
            "other_profiles_qualified": [],
            "persistence_applied": False,
        }
    )


def compare_depths(request: object) -> dict[str, Any]:
    d = require_mapping(request, "request")
    require_exact_keys(
        d, {"schema_version", "task_ref", "constraint_hash", "results"}, "request"
    )
    if d["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    task = require_string(d["task_ref"], "request.task_ref")
    constraint = require_string(d["constraint_hash"], "request.constraint_hash")
    rows = {}
    for i, raw in enumerate(require_list(d["results"], "request.results")):
        p = f"request.results[{i}]"
        row = require_mapping(raw, p)
        require_exact_keys(
            row,
            {
                "depth",
                "task_ref",
                "constraint_hash",
                "correctness",
                "cost",
                "review_effort",
                "repair_effort",
                "useful_delta",
                "output_size",
                "tool_calls",
                "errors",
            },
            p,
        )
        depth = require_string(row["depth"], f"{p}.depth")
        if depth in rows:
            fail("duplicate_depth", f"{p}.depth", "Повторная глубина.")
        rows[depth] = {
            "task_ref": require_string(row["task_ref"], f"{p}.task_ref"),
            "constraint_hash": require_string(
                row["constraint_hash"], f"{p}.constraint_hash"
            ),
            **{
                k: _finite(row[k], f"{p}.{k}")
                for k in (
                    "correctness",
                    "cost",
                    "review_effort",
                    "repair_effort",
                    "useful_delta",
                )
            },
            "output_size": require_int(row["output_size"], f"{p}.output_size"),
            "tool_calls": require_int(row["tool_calls"], f"{p}.tool_calls"),
            "errors": require_int(row["errors"], f"{p}.errors"),
        }
    issues = []
    if set(rows) != {"search", "deep", "ultra"}:
        issues.append("depth_set_incomplete")
    if any(
        r["task_ref"] != task or r["constraint_hash"] != constraint
        for r in rows.values()
    ):
        issues.append("unpaired_task_or_constraints")
    scores = {
        depth: r["correctness"]
        + r["useful_delta"]
        - r["review_effort"]
        - r["repair_effort"]
        - r["errors"]
        for depth, r in rows.items()
    }
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "DepthComparisonReceipt",
            "status": "compared" if not issues else "blocked",
            "task_ref": task,
            "constraint_hash": constraint,
            "metrics": rows,
            "quality_scores": scores,
            "volume_or_calls_used_as_quality": False,
            "issues": issues,
        }
    )


def assess_utility(request: object) -> dict[str, Any]:
    d = require_mapping(request, "request")
    require_exact_keys(d, set(UTILITY_ASSESS_SCHEMA["required"]), "request")
    if d["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    commercial = d["commercial_effect"]
    commercial_value = (
        None if commercial is None else _finite(commercial, "request.commercial_effect")
    )
    decision = _finite(d["decision_quality"], "request.decision_quality")
    saved = _finite(d["time_saved"], "request.time_saved")
    burden = _finite(d["verification_burden"], "request.verification_burden")
    correctness = _finite(d["correctness"], "request.correctness")
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "UtilityAssessmentReceipt",
            "status": "assessed",
            "result_ref": require_string(d["result_ref"], "request.result_ref"),
            "practical_utility": decision + saved - burden,
            "decision_quality": decision,
            "time_saved": saved,
            "verification_burden": burden,
            "correctness": correctness,
            "commercial_effect": commercial_value,
            "correctness_equals_utility": False,
            "commercial_effect_equals_utility": False,
        }
    )


PROFILE_QUALIFICATION_SCHEMA["properties"]["task_results"]["items"]["properties"][
    "answer_sha256"
] = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
