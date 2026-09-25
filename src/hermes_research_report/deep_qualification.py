"""Deep/Ultra qualification, obligation, independence, and recovery gates."""

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

_TEXT = {"type": "string", "minLength": 1}


def _closed(required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": {
            "schema_version": {"const": 1},
            **{
                field: {"type": "object"}
                for field in required
                if field != "schema_version"
            },
        },
    }


DEEP_QUALIFICATION_ASSESS_SCHEMA = _closed(
    ["schema_version", "suite", "runs", "cross_checks", "scope"]
)
DEEP_QUALIFICATION_ASSESS_SCHEMA["properties"]["runs"] = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "object"},
}
DEEP_QUALIFICATION_ASSESS_SCHEMA["properties"]["cross_checks"] = {
    "type": "array",
    "items": {"type": "object"},
}
OBLIGATION_PRESERVATION_ASSESS_SCHEMA = _closed(
    ["schema_version", "checkpoint_id", "stage", "before", "after"]
)
OBLIGATION_PRESERVATION_ASSESS_SCHEMA["properties"]["checkpoint_id"] = _TEXT
OBLIGATION_PRESERVATION_ASSESS_SCHEMA["properties"]["stage"] = {
    "enum": ["compression", "handoff"]
}
for _field in ("before", "after"):
    OBLIGATION_PRESERVATION_ASSESS_SCHEMA["properties"][_field] = {
        "type": "array",
        "items": {"type": "object"},
    }
MULTIAGENT_INDEPENDENCE_ASSESS_SCHEMA = _closed(
    ["schema_version", "roles", "consensus"]
)
MULTIAGENT_INDEPENDENCE_ASSESS_SCHEMA["properties"]["roles"] = {
    "type": "array",
    "minItems": 2,
    "items": {"type": "object"},
}
RESILIENCE_RECOVERY_ASSESS_SCHEMA = _closed(
    ["schema_version", "baseline", "incidents", "recovery"]
)

_TASK_CLASSES = {"frozen", "live", "multimodal", "dynamic", "ood", "chaos"}
_CROSS_CHECKS = {
    "executability",
    "specification_conformance",
    "domain_validity",
    "evidence_sufficiency",
}
_OBLIGATION_KINDS = {
    "question",
    "constraints",
    "decisions",
    "open_obligations",
    "negative_results",
}


def _version(data: dict[str, object]) -> None:
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )


def _time(value: object, path: str) -> str:
    text = require_string(value, path)
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None or "T" not in text:
            raise ValueError
    except ValueError:
        fail("invalid_timestamp", path, "Требуется ISO 8601 с часовым поясом.")
    return text


def _finite(value: object, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        fail("invalid_number", path, "Требуется конечное число.")
    return float(value)


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повтор элемента запрещён.")
    return result


def assess_deep_qualification(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "suite", "runs", "cross_checks", "scope"}, "request"
    )
    _version(data)
    suite = require_mapping(data["suite"], "request.suite")
    require_exact_keys(
        suite,
        {
            "suite_id",
            "profile",
            "sealed_at",
            "versions",
            "task_classes",
            "thresholds",
            "evidence_kind",
        },
        "request.suite",
    )
    evidence_kind = require_string(
        suite["evidence_kind"], "request.suite.evidence_kind"
    )
    if evidence_kind not in {"controlled_fixture", "live_qualification"}:
        fail(
            "invalid_evidence_kind",
            "request.suite.evidence_kind",
            "Неизвестен вид доказательства.",
        )
    sealed_at = _time(suite["sealed_at"], "request.suite.sealed_at")
    versions = require_mapping(suite["versions"], "request.suite.versions")
    version_fields = {"system", "model", "tools", "parsers", "data"}
    require_exact_keys(versions, version_fields, "request.suite.versions")
    version_record = {
        field: require_string(versions[field], f"request.suite.versions.{field}")
        for field in sorted(version_fields)
    }
    class_tasks: dict[str, set[str]] = {}
    task_class_records = []
    for index, raw in enumerate(
        require_list(suite["task_classes"], "request.suite.task_classes")
    ):
        path = f"request.suite.task_classes[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"class", "task_ids"}, path)
        task_class = require_string(item["class"], f"{path}.class")
        if task_class not in _TASK_CLASSES or task_class in class_tasks:
            fail(
                "invalid_or_duplicate_task_class",
                path,
                "Класс неизвестен или повторён.",
            )
        task_ids = set(_strings(item["task_ids"], f"{path}.task_ids"))
        if not task_ids:
            fail(
                "qualification_tasks_missing",
                f"{path}.task_ids",
                "Класс требует задачи.",
            )
        class_tasks[task_class] = task_ids
        task_class_records.append({"class": task_class, "task_ids": sorted(task_ids)})
    missing_classes = sorted(_TASK_CLASSES - set(class_tasks))
    thresholds = {}
    threshold_records = []
    for index, raw in enumerate(
        require_list(suite["thresholds"], "request.suite.thresholds")
    ):
        path = f"request.suite.thresholds[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"metric", "direction", "boundary", "veto"}, path)
        metric = require_string(item["metric"], f"{path}.metric")
        if metric in thresholds:
            fail("duplicate_threshold", path, "Повтор порога запрещён.")
        direction = require_string(item["direction"], f"{path}.direction")
        if direction not in {"minimum", "maximum"}:
            fail(
                "invalid_threshold_direction",
                f"{path}.direction",
                "Неизвестно направление.",
            )
        record = {
            "metric": metric,
            "direction": direction,
            "boundary": _finite(item["boundary"], f"{path}.boundary"),
            "veto": require_bool(item["veto"], f"{path}.veto"),
        }
        thresholds[metric] = record
        threshold_records.append(record)
    if not thresholds:
        fail(
            "qualification_thresholds_missing",
            "request.suite.thresholds",
            "Нужны пороги.",
        )

    runs = []
    observed_classes = set()
    metric_values: dict[str, list[tuple[str, float]]] = {
        metric: [] for metric in thresholds
    }
    veto_failures = []
    for index, raw in enumerate(require_list(data["runs"], "request.runs")):
        path = f"request.runs[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "run_id",
                "task_id",
                "task_class",
                "started_at",
                "seed",
                "metrics",
                "exceptions",
                "worst_case_ref",
                "status",
                "output_hash",
            },
            path,
        )
        run_id = require_string(item["run_id"], f"{path}.run_id")
        task_class = require_string(item["task_class"], f"{path}.task_class")
        task_id = require_string(item["task_id"], f"{path}.task_id")
        if task_class not in class_tasks or task_id not in class_tasks[task_class]:
            fail(
                "qualification_task_not_sealed",
                path,
                "Задача не входит в закрытый набор.",
            )
        started_at = _time(item["started_at"], f"{path}.started_at")
        if datetime.fromisoformat(started_at) <= datetime.fromisoformat(sealed_at):
            fail(
                "qualification_run_before_seal",
                f"{path}.started_at",
                "Порог и набор должны предшествовать запуску.",
            )
        observed_classes.add(task_class)
        metrics = {}
        for metric_index, raw_metric in enumerate(
            require_list(item["metrics"], f"{path}.metrics")
        ):
            metric_path = f"{path}.metrics[{metric_index}]"
            metric_item = require_mapping(raw_metric, metric_path)
            require_exact_keys(metric_item, {"metric", "value"}, metric_path)
            metric = require_string(metric_item["metric"], f"{metric_path}.metric")
            if metric not in thresholds or metric in metrics:
                fail(
                    "invalid_or_duplicate_metric",
                    metric_path,
                    "Метрика неизвестна или повторена.",
                )
            value = _finite(metric_item["value"], f"{metric_path}.value")
            metrics[metric] = value
            metric_values[metric].append((run_id, value))
            threshold = thresholds[metric]
            passed = (
                value >= threshold["boundary"]
                if threshold["direction"] == "minimum"
                else value <= threshold["boundary"]
            )
            if not passed and threshold["veto"]:
                veto_failures.append(f"{run_id}:{metric}")
        missing_metrics = sorted(set(thresholds) - set(metrics))
        if missing_metrics:
            fail(
                "qualification_metric_missing",
                path,
                f"Нет метрики: {missing_metrics[0]}.",
            )
        runs.append(
            {
                "run_id": run_id,
                "task_id": task_id,
                "task_class": task_class,
                "started_at": started_at,
                "seed": require_int(item["seed"], f"{path}.seed"),
                "metrics": metrics,
                "exceptions": _strings(item["exceptions"], f"{path}.exceptions"),
                "worst_case_ref": require_string(
                    item["worst_case_ref"], f"{path}.worst_case_ref"
                ),
                "status": require_string(item["status"], f"{path}.status"),
                "output_hash": require_string(
                    item["output_hash"], f"{path}.output_hash"
                ),
            }
        )
    missing_observed_classes = sorted(_TASK_CLASSES - observed_classes)
    distributions = []
    for metric, values in sorted(metric_values.items()):
        numeric = [value for _, value in values]
        worst_run, worst_value = (
            min(values, key=lambda row: row[1])
            if thresholds[metric]["direction"] == "minimum"
            else max(values, key=lambda row: row[1])
        )
        distributions.append(
            {
                "metric": metric,
                "count": len(numeric),
                "minimum": min(numeric),
                "maximum": max(numeric),
                "mean": sum(numeric) / len(numeric),
                "worst_run_id": worst_run,
                "worst_value": worst_value,
            }
        )
    cross_checks = []
    seen_checks = set()
    premature_consensus = False
    for index, raw in enumerate(
        require_list(data["cross_checks"], "request.cross_checks")
    ):
        path = f"request.cross_checks[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item, {"dimension", "status", "receipt_ref", "premature_consensus"}, path
        )
        dimension = require_string(item["dimension"], f"{path}.dimension")
        if dimension not in _CROSS_CHECKS or dimension in seen_checks:
            fail(
                "invalid_or_duplicate_cross_check",
                path,
                "Проверка неизвестна или повторена.",
            )
        seen_checks.add(dimension)
        status = require_string(item["status"], f"{path}.status")
        if status not in {"pass", "fail"}:
            fail("invalid_cross_check_status", f"{path}.status", "Неизвестен статус.")
        early = require_bool(item["premature_consensus"], f"{path}.premature_consensus")
        premature_consensus = premature_consensus or early
        cross_checks.append(
            {
                "dimension": dimension,
                "status": status,
                "receipt_ref": require_string(
                    item["receipt_ref"], f"{path}.receipt_ref"
                ),
                "premature_consensus": early,
            }
        )
    missing_checks = sorted(_CROSS_CHECKS - seen_checks)
    failed_checks = sorted(
        row["dimension"] for row in cross_checks if row["status"] != "pass"
    )
    scope = require_mapping(data["scope"], "request.scope")
    require_exact_keys(
        scope,
        {"requested_profile", "expires_at", "recheck_triggers"},
        "request.scope",
    )
    blockers = []
    if missing_classes or missing_observed_classes:
        blockers.append("qualification_task_class_missing")
    if veto_failures:
        blockers.append("veto_metric_failed")
    if missing_checks or failed_checks:
        blockers.append("cross_check_incomplete_or_failed")
    if premature_consensus:
        blockers.append("premature_consensus_detected")
    contract_pass = not blockers
    routing_qualified = contract_pass and evidence_kind == "live_qualification"
    return with_receipt_hash(
        {
            "contract": "DeepQualificationReceipt",
            "status": (
                "qualified"
                if routing_qualified
                else "controlled_evidence_pass"
                if contract_pass
                else "not_qualified"
            ),
            "suite": {
                "suite_id": require_string(suite["suite_id"], "request.suite.suite_id"),
                "profile": require_string(suite["profile"], "request.suite.profile"),
                "sealed_at": sealed_at,
                "versions": version_record,
                "task_classes": task_class_records,
                "thresholds": threshold_records,
                "evidence_kind": evidence_kind,
            },
            "runs": runs,
            "run_count": len(runs),
            "observed_task_classes": sorted(observed_classes),
            "missing_task_classes": sorted(
                set(missing_classes) | set(missing_observed_classes)
            ),
            "distributions": distributions,
            "veto_failures": veto_failures,
            "cross_checks": cross_checks,
            "missing_cross_checks": missing_checks,
            "failed_cross_checks": failed_checks,
            "premature_consensus": premature_consensus,
            "requested_profile": require_string(
                scope["requested_profile"], "request.scope.requested_profile"
            ),
            "expires_at": _time(scope["expires_at"], "request.scope.expires_at"),
            "recheck_triggers": _strings(
                scope["recheck_triggers"], "request.scope.recheck_triggers"
            ),
            "blockers": blockers,
            "contract_pass": contract_pass,
            "routing_qualified": routing_qualified,
            "product_status": "not_verified"
            if not routing_qualified
            else "scope_qualified",
            "single_score_used_for_acceptance": False,
        }
    )


def assess_obligation_preservation(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "checkpoint_id", "stage", "before", "after"}, "request"
    )
    _version(data)
    checkpoint_id = require_string(data["checkpoint_id"], "request.checkpoint_id")
    stage = require_string(data["stage"], "request.stage")
    if stage not in {"compression", "handoff"}:
        fail("invalid_checkpoint_stage", "request.stage", "Неизвестна стадия.")

    def parse(items: object, path: str) -> dict[str, dict[str, str]]:
        result = {}
        for index, raw in enumerate(require_list(items, path)):
            item_path = f"{path}[{index}]"
            item = require_mapping(raw, item_path)
            require_exact_keys(
                item, {"kind", "ref", "content_hash", "status"}, item_path
            )
            kind = require_string(item["kind"], f"{item_path}.kind")
            if kind not in _OBLIGATION_KINDS or kind in result:
                fail(
                    "invalid_or_duplicate_obligation",
                    item_path,
                    "Обязательство неизвестно или повторено.",
                )
            result[kind] = {
                "kind": kind,
                "ref": require_string(item["ref"], f"{item_path}.ref"),
                "content_hash": require_string(
                    item["content_hash"], f"{item_path}.content_hash"
                ),
                "status": require_string(item["status"], f"{item_path}.status"),
            }
        return result

    before = parse(data["before"], "request.before")
    after = parse(data["after"], "request.after")
    missing_before = sorted(_OBLIGATION_KINDS - set(before))
    if missing_before:
        fail(
            "obligation_kind_missing_before",
            "request.before",
            f"Нет вида: {missing_before[0]}.",
        )
    missing = sorted(set(before) - set(after))
    changed = sorted(
        kind
        for kind in set(before) & set(after)
        if before[kind]["content_hash"] != after[kind]["content_hash"]
        or before[kind]["status"] != after[kind]["status"]
        or before[kind]["ref"] != after[kind]["ref"]
    )
    preserved = not missing and not changed
    return with_receipt_hash(
        {
            "contract": "ObligationPreservationReceipt",
            "status": "preserved" if preserved else "failed",
            "checkpoint_id": checkpoint_id,
            "stage": stage,
            "before": [before[kind] for kind in sorted(before)],
            "after": [after[kind] for kind in sorted(after)],
            "missing_kinds": missing,
            "changed_kinds": changed,
            "preserved": preserved,
            "continuation_allowed": preserved,
            "release_allowed": preserved,
        }
    )


def assess_multiagent_independence(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "roles", "consensus"}, "request")
    _version(data)
    roles = []
    role_ids = set()
    for index, raw in enumerate(require_list(data["roles"], "request.roles")):
        path = f"request.roles[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "role_id",
                "model_signature",
                "data_signature",
                "method_signature",
                "context_signature",
                "first_decision_isolated",
                "error_channels",
            },
            path,
        )
        role_id = require_string(item["role_id"], f"{path}.role_id")
        if role_id in role_ids:
            fail("duplicate_role", path, "Повтор роли запрещён.")
        role_ids.add(role_id)
        roles.append(
            {
                "role_id": role_id,
                "model_signature": require_string(
                    item["model_signature"], f"{path}.model_signature"
                ),
                "data_signature": require_string(
                    item["data_signature"], f"{path}.data_signature"
                ),
                "method_signature": require_string(
                    item["method_signature"], f"{path}.method_signature"
                ),
                "context_signature": require_string(
                    item["context_signature"], f"{path}.context_signature"
                ),
                "first_decision_isolated": require_bool(
                    item["first_decision_isolated"],
                    f"{path}.first_decision_isolated",
                ),
                "error_channels": set(
                    _strings(item["error_channels"], f"{path}.error_channels")
                ),
            }
        )
    pairs = []
    correlated_pairs = []
    for left_index, left in enumerate(roles):
        for right in roles[left_index + 1 :]:
            shared_dimensions = [
                field.removesuffix("_signature")
                for field in (
                    "model_signature",
                    "data_signature",
                    "method_signature",
                    "context_signature",
                )
                if left[field] == right[field]
            ]
            shared_errors = sorted(left["error_channels"] & right["error_channels"])
            isolated = (
                left["first_decision_isolated"] and right["first_decision_isolated"]
            )
            independent = not shared_dimensions and not shared_errors and isolated
            pair = {
                "left_role_id": left["role_id"],
                "right_role_id": right["role_id"],
                "shared_dimensions": shared_dimensions,
                "shared_error_channels": shared_errors,
                "first_decisions_isolated": isolated,
                "independent": independent,
            }
            pairs.append(pair)
            if not independent:
                correlated_pairs.append(f"{left['role_id']}:{right['role_id']}")
    consensus = require_mapping(data["consensus"], "request.consensus")
    require_exact_keys(
        consensus,
        {
            "vote_result",
            "confidence_before",
            "confidence_after_requested",
            "disagreement_refs",
        },
        "request.consensus",
    )
    confidence_before = _finite(
        consensus["confidence_before"], "request.consensus.confidence_before"
    )
    confidence_requested = _finite(
        consensus["confidence_after_requested"],
        "request.consensus.confidence_after_requested",
    )
    correlated = bool(correlated_pairs)
    confidence_after = (
        min(confidence_before, confidence_requested)
        if correlated
        else confidence_requested
    )
    return with_receipt_hash(
        {
            "contract": "MultiAgentIndependenceReceipt",
            "status": "correlated" if correlated else "independent",
            "roles": [
                {**role, "error_channels": sorted(role["error_channels"])}
                for role in roles
            ],
            "pairs": pairs,
            "correlated_pair_refs": correlated_pairs,
            "vote_result": require_string(
                consensus["vote_result"], "request.consensus.vote_result"
            ),
            "disagreement_refs": _strings(
                consensus["disagreement_refs"],
                "request.consensus.disagreement_refs",
            ),
            "confidence_before": confidence_before,
            "confidence_after_requested": confidence_requested,
            "confidence_after_allowed": confidence_after,
            "consensus_increases_confidence": confidence_after > confidence_before,
            "role_count_implies_independence": False,
        }
    )


def assess_resilience_recovery(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "baseline", "incidents", "recovery"}, "request"
    )
    _version(data)
    baseline = require_mapping(data["baseline"], "request.baseline")
    require_exact_keys(
        baseline,
        {"plan_revision", "work_refs", "accepted_effect_ids", "requested_scope"},
        "request.baseline",
    )
    plan_revision = require_int(
        baseline["plan_revision"], "request.baseline.plan_revision", minimum=1
    )
    work_refs = _strings(baseline["work_refs"], "request.baseline.work_refs")
    effect_ids = _strings(
        baseline["accepted_effect_ids"], "request.baseline.accepted_effect_ids"
    )
    requested_scope = require_string(
        baseline["requested_scope"], "request.baseline.requested_scope"
    )
    incidents = require_mapping(data["incidents"], "request.incidents")
    incident_fields = {"provider_failure", "schema_drift", "restart"}
    require_exact_keys(incidents, incident_fields, "request.incidents")
    incident_record = {
        field: require_bool(incidents[field], f"request.incidents.{field}")
        for field in sorted(incident_fields)
    }
    recovery = require_mapping(data["recovery"], "request.recovery")
    require_exact_keys(
        recovery,
        {
            "replanned_revision",
            "invalidation_refs",
            "recovered_work_refs",
            "effect_executions",
            "provider_reconciled",
            "schema_requalified",
            "restart_checkpoint_loaded",
            "effective_scope",
            "final_status",
        },
        "request.recovery",
    )
    replanned_revision = require_int(
        recovery["replanned_revision"],
        "request.recovery.replanned_revision",
        minimum=1,
    )
    invalidations = _strings(
        recovery["invalidation_refs"], "request.recovery.invalidation_refs"
    )
    recovered = _strings(
        recovery["recovered_work_refs"], "request.recovery.recovered_work_refs"
    )
    executions = []
    execution_counts = {}
    for index, raw in enumerate(
        require_list(
            recovery["effect_executions"], "request.recovery.effect_executions"
        )
    ):
        path = f"request.recovery.effect_executions[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"effect_id", "execution_count", "outcome"}, path)
        effect_id = require_string(item["effect_id"], f"{path}.effect_id")
        count = require_int(item["execution_count"], f"{path}.execution_count")
        execution_counts[effect_id] = count
        executions.append(
            {
                "effect_id": effect_id,
                "execution_count": count,
                "outcome": require_string(item["outcome"], f"{path}.outcome"),
            }
        )
    provider_reconciled = require_bool(
        recovery["provider_reconciled"], "request.recovery.provider_reconciled"
    )
    schema_requalified = require_bool(
        recovery["schema_requalified"], "request.recovery.schema_requalified"
    )
    checkpoint_loaded = require_bool(
        recovery["restart_checkpoint_loaded"],
        "request.recovery.restart_checkpoint_loaded",
    )
    effective_scope = require_string(
        recovery["effective_scope"], "request.recovery.effective_scope"
    )
    final_status = require_string(
        recovery["final_status"], "request.recovery.final_status"
    )
    lost_work = sorted(set(work_refs) - set(recovered))
    missing_effect_receipts = sorted(set(effect_ids) - set(execution_counts))
    double_effects = sorted(
        effect_id for effect_id, count in execution_counts.items() if count > 1
    )
    false_success = final_status == "success" and (
        (incident_record["provider_failure"] and not provider_reconciled)
        or (incident_record["schema_drift"] and not schema_requalified)
        or (incident_record["restart"] and not checkpoint_loaded)
    )
    scope_narrowed = effective_scope != requested_scope
    issues = []
    if replanned_revision <= plan_revision:
        issues.append("versioned_replan_missing")
    if incident_record["schema_drift"] and not invalidations:
        issues.append("schema_invalidation_missing")
    if lost_work:
        issues.append("lost_work")
    if missing_effect_receipts:
        issues.append("effect_receipt_missing")
    if double_effects:
        issues.append("double_effect")
    if false_success:
        issues.append("false_success")
    if incident_record["provider_failure"] and not provider_reconciled:
        issues.append("provider_outcome_unreconciled")
    if incident_record["restart"] and not checkpoint_loaded:
        issues.append("restart_checkpoint_missing")
    if (
        incident_record["schema_drift"]
        and not schema_requalified
        and not scope_narrowed
    ):
        issues.append("schema_scope_not_narrowed")
    accepted = not issues
    return with_receipt_hash(
        {
            "contract": "ResilienceRecoveryReceipt",
            "status": "recovered" if accepted else "blocked",
            "baseline_plan_revision": plan_revision,
            "replanned_revision": replanned_revision,
            "incidents": incident_record,
            "invalidation_refs": invalidations,
            "lost_work_refs": lost_work,
            "missing_effect_receipt_ids": missing_effect_receipts,
            "double_effect_ids": double_effects,
            "false_success": false_success,
            "provider_reconciled": provider_reconciled,
            "schema_requalified": schema_requalified,
            "restart_checkpoint_loaded": checkpoint_loaded,
            "requested_scope": requested_scope,
            "effective_scope": effective_scope,
            "scope_narrowed": scope_narrowed,
            "final_status": final_status,
            "effect_executions": executions,
            "issues": issues,
            "recovery_accepted": accepted,
        }
    )
