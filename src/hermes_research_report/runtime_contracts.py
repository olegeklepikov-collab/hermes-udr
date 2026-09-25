"""Integrated R1 contracts for capability, context, liveness, and delivery."""

from __future__ import annotations

from datetime import UTC, datetime
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

_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_TEXT = {"type": "string", "minLength": 1}


def _closed(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


CAPABILITY_MODEL_SCHEMA = _closed(
    ["schema_version", "catalog", "promotion", "model_lane"],
    {
        "schema_version": {"const": 1},
        "catalog": {"type": "object"},
        "promotion": {"type": "object"},
        "model_lane": {"type": "object"},
    },
)
CONTEXT_ASSEMBLY_SCHEMA = _closed(
    [
        "schema_version",
        "run_id",
        "consumer",
        "assembled_at",
        "contributions",
        "injection_stages",
    ],
    {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "consumer": _TEXT,
        "assembled_at": _TEXT,
        "contributions": {
            "type": "array",
            "maxItems": 1000,
            "items": {"type": "object"},
        },
        "injection_stages": {"type": "array", "uniqueItems": True, "items": _TEXT},
    },
)
LIVENESS_RECONCILE_SCHEMA = _closed(
    [
        "schema_version",
        "observed_at",
        "work_state",
        "error_control",
        "scheduled_control",
        "backup",
        "obligation_checkpoint",
    ],
    {
        "schema_version": {"const": 1},
        "observed_at": _TEXT,
        "work_state": {"type": "object"},
        "error_control": {"type": "object"},
        "scheduled_control": {"type": "object"},
        "backup": {"type": "object"},
        "obligation_checkpoint": {"type": "object"},
    },
)
DISTRIBUTION_DELIVERY_SCHEMA = _closed(
    [
        "schema_version",
        "original",
        "sanitizer",
        "transformation",
        "policy",
        "raw_delivery",
        "release",
        "transport",
    ],
    {
        "schema_version": {"const": 1},
        "original": {"type": "object"},
        "sanitizer": {"type": "object"},
        "transformation": {"type": "object"},
        "policy": {"type": "object"},
        "raw_delivery": {"type": ["object", "null"]},
        "release": {"type": "object"},
        "transport": {"type": "object"},
    },
)


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _time(value: object, path: str) -> datetime:
    text = require_string(value, path)
    try:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith("Z") else text
        )
    except ValueError:
        fail("invalid_timestamp", path, "Ожидалась временная метка ISO 8601.")
    if parsed.tzinfo is None:
        fail("timezone_required", path, "Временная зона обязательна.")
    return parsed.astimezone(UTC)


def _enum(value: object, allowed: set[str], path: str) -> str:
    text = require_string(value, path)
    if text not in allowed:
        fail("invalid_enum", path, "Недопустимое значение.")
    return text


def _strings(value: object, path: str) -> list[str]:
    return [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]


def assess_capability_model_lane(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "catalog", "promotion", "model_lane"}, "request"
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    catalog = require_mapping(data["catalog"], "request.catalog")
    require_exact_keys(
        catalog,
        {
            "capability_id",
            "immutable_ref",
            "level",
            "qualified_operation",
            "requested_operation",
            "entrypoint_available",
            "dependencies_available",
            "resources_available",
            "update_monitor_status",
            "auto_promotion_attempted",
        },
        "request.catalog",
    )
    capability_id = require_string(
        catalog["capability_id"], "request.catalog.capability_id"
    )
    immutable_ref = require_string(
        catalog["immutable_ref"], "request.catalog.immutable_ref"
    )
    level = _enum(
        catalog["level"],
        {
            "reference_only",
            "preapproved",
            "smoke_verified",
            "resource_gated",
            "qualified",
            "suspended",
        },
        "request.catalog.level",
    )
    qualified_operation = require_string(
        catalog["qualified_operation"], "request.catalog.qualified_operation"
    )
    requested_operation = require_string(
        catalog["requested_operation"], "request.catalog.requested_operation"
    )
    entrypoint = require_bool(
        catalog["entrypoint_available"], "request.catalog.entrypoint_available"
    )
    dependencies = require_bool(
        catalog["dependencies_available"], "request.catalog.dependencies_available"
    )
    resources = require_bool(
        catalog["resources_available"], "request.catalog.resources_available"
    )
    monitor = _enum(
        catalog["update_monitor_status"],
        {"current", "changed", "error"},
        "request.catalog.update_monitor_status",
    )
    auto_promotion = require_bool(
        catalog["auto_promotion_attempted"], "request.catalog.auto_promotion_attempted"
    )

    promotion = require_mapping(data["promotion"], "request.promotion")
    promotion_keys = {
        "pin_verified",
        "license_reviewed",
        "security_reviewed",
        "dependencies_reviewed",
        "isolated_environment",
        "structural_tests",
        "characteristic_probe",
        "data_egress_boundary",
        "reviewer_approved",
        "rollback_verified",
    }
    require_exact_keys(promotion, promotion_keys, "request.promotion")
    promotion_checks = {
        key: require_bool(promotion[key], f"request.promotion.{key}")
        for key in promotion_keys
    }
    promotion_issues: list[str] = []
    if level in {"reference_only", "suspended"}:
        promotion_issues.append(f"catalog_level_not_executable:{level}")
    if qualified_operation != requested_operation:
        promotion_issues.append("operation_not_qualified")
    if not entrypoint:
        promotion_issues.append("entrypoint_missing")
    if not dependencies:
        promotion_issues.append("dependencies_missing")
    if not resources:
        promotion_issues.append("resources_missing")
    promotion_issues.extend(
        f"promotion_check_failed:{key}"
        for key, passed in promotion_checks.items()
        if not passed
    )
    if monitor == "error":
        promotion_issues.append("currentness_unknown")
    if monitor == "changed":
        promotion_issues.append("qualification_stale")
    if auto_promotion:
        promotion_issues.append("automatic_promotion_forbidden")
    promoted = not promotion_issues and level == "qualified"
    if level in {"reference_only", "suspended"}:
        user_status = "dormant"
    elif monitor == "changed":
        user_status = "stale"
    elif monitor == "error" or (entrypoint and (not dependencies or not resources)):
        user_status = "degraded"
    elif not entrypoint:
        user_status = "configured"
    elif promoted:
        user_status = "qualified"
    elif level in {"smoke_verified", "resource_gated"}:
        user_status = "verified"
    else:
        user_status = "available"
    status_labels = {
        "configured": "Настроена: запись и параметры есть, доступная точка вызова не подтверждена.",
        "available": "Доступна: точка вызова и зависимости доступны; предметная квалификация не подтверждена.",
        "verified": "Проверена: выполнена ограниченная техническая проверка; это не предметная квалификация.",
        "qualified": "Квалифицирована: принят заданный вид операции в указанной редакции.",
        "degraded": "Ограниченно работоспособна: недоступны ресурсы или зависимости либо не установлена актуальность.",
        "stale": "Устарела: состояние изменилось после проверки; исполнение запрещено до повторной квалификации.",
        "dormant": "Неактивна: справочная или приостановленная возможность не исполняется.",
    }
    promotion_record = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "CapabilityPromotionRecord",
            "status": "qualified" if promoted else "blocked_pending_promotion",
            "user_status": user_status,
            "user_status_description": status_labels[user_status],
            "status_evidence_scope": "provided_catalog_snapshot_not_live_measurement",
            "capability_id": capability_id,
            "immutable_ref": immutable_ref,
            "qualified_operation": qualified_operation,
            "requested_operation": requested_operation,
            "catalog_level": level,
            "checks": dict(sorted(promotion_checks.items())),
            "currentness": "unknown" if monitor == "error" else monitor,
            "execution_allowed": promoted,
            "issues": sorted(set(promotion_issues)),
        }
    )

    lane = require_mapping(data["model_lane"], "request.model_lane")
    require_exact_keys(
        lane,
        {
            "lane_id",
            "surface",
            "provider",
            "model",
            "effort",
            "tools",
            "budget_tokens",
            "input_hash",
            "output_hash",
            "primary_status",
            "fallback_used",
            "fallback_status",
            "programmatic_gate",
            "source_trace_gate",
            "schema_gate",
            "judge_status",
            "shared_data",
            "shared_model",
            "shared_prompt",
            "shared_method",
        },
        "request.model_lane",
    )
    lane_id = require_string(lane["lane_id"], "request.model_lane.lane_id")
    surface = require_string(lane["surface"], "request.model_lane.surface")
    provider = require_string(lane["provider"], "request.model_lane.provider")
    model = require_string(lane["model"], "request.model_lane.model")
    effort = require_string(lane["effort"], "request.model_lane.effort")
    tools = _strings(lane["tools"], "request.model_lane.tools")
    budget = require_int(
        lane["budget_tokens"], "request.model_lane.budget_tokens", minimum=1
    )
    input_hash = _hash(lane["input_hash"], "request.model_lane.input_hash")
    output_hash = _hash(lane["output_hash"], "request.model_lane.output_hash")
    primary = _enum(
        lane["primary_status"],
        {"success", "failed", "timeout", "unavailable"},
        "request.model_lane.primary_status",
    )
    fallback_used = require_bool(
        lane["fallback_used"], "request.model_lane.fallback_used"
    )
    fallback = _enum(
        lane["fallback_status"],
        {"not_used", "success", "failed"},
        "request.model_lane.fallback_status",
    )
    gates = {
        name: _enum(
            lane[name], {"pass", "fail", "not_run"}, f"request.model_lane.{name}"
        )
        for name in ("programmatic_gate", "source_trace_gate", "schema_gate")
    }
    judge = _enum(
        lane["judge_status"],
        {"pass", "fail", "not_run"},
        "request.model_lane.judge_status",
    )
    independence = {
        name: not require_bool(lane[name], f"request.model_lane.{name}")
        for name in ("shared_data", "shared_model", "shared_prompt", "shared_method")
    }
    hard_gate_failed = any(value == "fail" for value in gates.values())
    lane_allowed = promoted and primary == "success" and not hard_gate_failed
    provisional = (
        promoted
        and primary != "success"
        and fallback_used
        and fallback == "success"
        and not hard_gate_failed
    )
    lane_receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "ModelLaneReceipt",
            "status": "succeeded"
            if lane_allowed
            else "provisional"
            if provisional
            else "blocked",
            "lane_id": lane_id,
            "surface": surface,
            "provider": provider,
            "model": model,
            "effort": effort,
            "tools": tools,
            "budget_tokens": budget,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "primary_status": primary,
            "fallback_used": fallback_used,
            "fallback_status": fallback,
            "primary_gate_open": primary != "success",
            "programmatic_gates": gates,
            "judge_status": judge,
            "judge_overrode_programmatic_failure": False,
            "independence": independence,
            "independent": all(independence.values()),
        }
    )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "CapabilityModelDecisionReceipt",
            "status": lane_receipt["status"],
            "capability_promotion": promotion_record,
            "model_lane": lane_receipt,
            "execution_allowed": lane_allowed,
            "fallback_closed_primary_gate": False,
        }
    )


def assemble_context_package(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "run_id",
            "consumer",
            "assembled_at",
            "contributions",
            "injection_stages",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    consumer = require_string(data["consumer"], "request.consumer")
    assembled_at = _time(data["assembled_at"], "request.assembled_at")
    stages = _strings(data["injection_stages"], "request.injection_stages")
    allowed_stages = {"prefetch", "system_prompt", "pre_compress_reinjection", "manual"}
    if any(stage not in allowed_stages for stage in stages):
        fail(
            "invalid_injection_stage",
            "request.injection_stages",
            "Неизвестный этап внедрения.",
        )
    receipts: list[dict[str, Any]] = []
    origins: dict[tuple[str, str, str], list[str]] = {}
    material_without_evidence: list[str] = []
    graph_overclaims: list[str] = []
    for index, raw in enumerate(
        require_list(data["contributions"], "request.contributions")
    ):
        path = f"request.contributions[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "contribution_id",
                "source_system",
                "query",
                "item_id",
                "item_version",
                "source_ref",
                "locator",
                "rank_or_score",
                "trust_class",
                "expires_at",
                "injected_at",
                "consumer",
                "corpus_id",
                "index_version",
                "retrieval_model",
                "retrieval_mode",
                "top_k",
                "timing_ms",
                "temporal_scope",
                "primary_readback",
                "evidence_link",
                "material_use",
                "poisoning_check",
                "contradiction_check",
            },
            path,
        )
        contribution_id = require_string(
            row["contribution_id"], f"{path}.contribution_id"
        )
        source_system = _enum(
            row["source_system"],
            {"agentmemory", "memora", "zvec", "graphiti", "session"},
            f"{path}.source_system",
        )
        query = require_string(row["query"], f"{path}.query", nonempty=False)
        item_id = require_string(row["item_id"], f"{path}.item_id")
        item_version = require_string(row["item_version"], f"{path}.item_version")
        source_ref = require_string(
            row["source_ref"], f"{path}.source_ref", nonempty=False
        )
        locator = require_string(row["locator"], f"{path}.locator", nonempty=False)
        rank = row["rank_or_score"]
        if rank is not None and (
            isinstance(rank, bool) or not isinstance(rank, (int, float))
        ):
            fail("invalid_rank", f"{path}.rank_or_score", "Ожидалось число либо null.")
        trust = _enum(
            row["trust_class"],
            {"untrusted_candidate", "user_context", "source_backed_candidate"},
            f"{path}.trust_class",
        )
        expires = _time(row["expires_at"], f"{path}.expires_at")
        injected = _time(row["injected_at"], f"{path}.injected_at")
        row_consumer = require_string(row["consumer"], f"{path}.consumer")
        corpus = require_string(row["corpus_id"], f"{path}.corpus_id", nonempty=False)
        index_version = require_string(
            row["index_version"], f"{path}.index_version", nonempty=False
        )
        retrieval_model = require_string(
            row["retrieval_model"], f"{path}.retrieval_model", nonempty=False
        )
        retrieval_mode = _enum(
            row["retrieval_mode"],
            {"exact", "fts", "vector", "hybrid", "rerank", "not_applicable"},
            f"{path}.retrieval_mode",
        )
        top_k = require_int(row["top_k"], f"{path}.top_k")
        timing = require_int(row["timing_ms"], f"{path}.timing_ms")
        temporal_scope = require_string(row["temporal_scope"], f"{path}.temporal_scope")
        primary_readback = require_bool(
            row["primary_readback"], f"{path}.primary_readback"
        )
        evidence_link = require_string(
            row["evidence_link"], f"{path}.evidence_link", nonempty=False
        )
        material = require_bool(row["material_use"], f"{path}.material_use")
        poisoning = require_bool(row["poisoning_check"], f"{path}.poisoning_check")
        contradiction = require_bool(
            row["contradiction_check"], f"{path}.contradiction_check"
        )
        origin_key = (source_ref, item_version, locator)
        origins.setdefault(origin_key, []).append(contribution_id)
        issues = []
        if row_consumer != consumer:
            issues.append("consumer_mismatch")
        if injected > assembled_at or expires < assembled_at:
            issues.append("stale_or_future_contribution")
        if not source_ref or not locator:
            issues.append("source_lineage_incomplete")
        if not poisoning:
            issues.append("poisoning_check_missing")
        if not contradiction:
            issues.append("contradiction_check_missing")
        evidence_eligible = primary_readback and bool(evidence_link) and not issues
        if material and not evidence_eligible:
            material_without_evidence.append(contribution_id)
        if source_system == "graphiti" and material and not evidence_eligible:
            graph_overclaims.append(contribution_id)
        receipts.append(
            with_receipt_hash(
                {
                    "schema_version": 1,
                    "contract": "ContextContributionReceipt",
                    "status": "candidate" if not issues else "excluded",
                    "contribution_id": contribution_id,
                    "source_system": source_system,
                    "query": query,
                    "item_id": item_id,
                    "item_version": item_version,
                    "source_ref": source_ref,
                    "locator": locator,
                    "rank_or_score": rank,
                    "trust_class": trust,
                    "expires_at": expires.isoformat(),
                    "injected_at": injected.isoformat(),
                    "consumer": row_consumer,
                    "retrieval": {
                        "corpus_id": corpus,
                        "index_version": index_version,
                        "model": retrieval_model,
                        "mode": retrieval_mode,
                        "top_k": top_k,
                        "timing_ms": timing,
                    },
                    "temporal_scope": temporal_scope,
                    "authority": "candidate_only",
                    "primary_readback": primary_readback,
                    "evidence_link": evidence_link or None,
                    "automatic_evidence_promotion": False,
                    "material_use_allowed": evidence_eligible,
                    "issues": issues,
                }
            )
        )
    duplicate_groups = [sorted(ids) for ids in origins.values() if len(ids) > 1]
    status = (
        "blocked" if material_without_evidence or graph_overclaims else "context_ready"
    )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "ContextAssemblyReceipt",
            "status": status,
            "run_id": run_id,
            "consumer": consumer,
            "assembled_at": assembled_at.isoformat(),
            "injection_stages": stages,
            "contributions": receipts,
            "contribution_count": len(receipts),
            "automatic_evidence_link_count": 0,
            "duplicate_origin_groups": duplicate_groups,
            "independence_not_increased_by_duplicate_systems": bool(duplicate_groups),
            "material_contributions_without_evidence": sorted(
                material_without_evidence
            ),
            "graph_causal_or_influence_promotions": 0,
        }
    )


def reconcile_work_liveness(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "observed_at",
            "work_state",
            "error_control",
            "scheduled_control",
            "backup",
            "obligation_checkpoint",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    now = _time(data["observed_at"], "request.observed_at")
    work = require_mapping(data["work_state"], "request.work_state")
    require_exact_keys(
        work,
        {
            "work_id",
            "declared_state",
            "owner",
            "task_ref",
            "process_ref",
            "operation_ref",
            "lease_active",
            "heartbeat_at",
            "deadline_at",
            "process_alive",
            "artifact_refs",
            "accepted_effect_refs",
            "reconciliation_complete",
        },
        "request.work_state",
    )
    work_id = require_string(work["work_id"], "request.work_state.work_id")
    declared = _enum(
        work["declared_state"],
        {"running", "stale", "blocked", "resumable", "complete"},
        "request.work_state.declared_state",
    )
    refs_complete = all(
        require_string(work[key], f"request.work_state.{key}", nonempty=False)
        for key in ("owner", "task_ref", "process_ref", "operation_ref")
    )
    lease = require_bool(work["lease_active"], "request.work_state.lease_active")
    heartbeat = _time(work["heartbeat_at"], "request.work_state.heartbeat_at")
    deadline = _time(work["deadline_at"], "request.work_state.deadline_at")
    alive = require_bool(work["process_alive"], "request.work_state.process_alive")
    artifact_refs = _strings(work["artifact_refs"], "request.work_state.artifact_refs")
    accepted_effects = _strings(
        work["accepted_effect_refs"], "request.work_state.accepted_effect_refs"
    )
    reconciled = require_bool(
        work["reconciliation_complete"], "request.work_state.reconciliation_complete"
    )

    control = require_mapping(data["error_control"], "request.error_control")
    require_exact_keys(
        control,
        {
            "error_class",
            "consecutive_failures",
            "retry_budget",
            "backoff_seconds",
            "state_change_trigger",
            "manual_probe",
            "circuit_state",
        },
        "request.error_control",
    )
    error_class = _enum(
        control["error_class"],
        {"none", "transient", "permanent", "config", "dependency"},
        "request.error_control.error_class",
    )
    failures = require_int(
        control["consecutive_failures"], "request.error_control.consecutive_failures"
    )
    budget = require_int(
        control["retry_budget"], "request.error_control.retry_budget", minimum=1
    )
    backoff = require_int(
        control["backoff_seconds"], "request.error_control.backoff_seconds"
    )
    state_change = require_bool(
        control["state_change_trigger"], "request.error_control.state_change_trigger"
    )
    manual_probe = require_bool(
        control["manual_probe"], "request.error_control.manual_probe"
    )
    reported_circuit = _enum(
        control["circuit_state"],
        {"closed", "open", "half_open"},
        "request.error_control.circuit_state",
    )
    permanent = error_class in {"permanent", "config", "dependency"}
    circuit_open = (
        reported_circuit == "open"
        or failures >= budget
        or (permanent and failures > 0 and not (state_change or manual_probe))
    )
    retry_allowed = (
        error_class == "transient" and failures < budget and not circuit_open
    )

    scheduled = require_mapping(data["scheduled_control"], "request.scheduled_control")
    require_exact_keys(
        scheduled,
        {
            "enabled",
            "last_attempt_at",
            "last_success_at",
            "consecutive_failures",
            "next_due_at",
            "result_ref",
        },
        "request.scheduled_control",
    )
    schedule_enabled = require_bool(
        scheduled["enabled"], "request.scheduled_control.enabled"
    )
    last_attempt = _time(
        scheduled["last_attempt_at"], "request.scheduled_control.last_attempt_at"
    )
    last_success = _time(
        scheduled["last_success_at"], "request.scheduled_control.last_success_at"
    )
    schedule_failures = require_int(
        scheduled["consecutive_failures"],
        "request.scheduled_control.consecutive_failures",
    )
    next_due = _time(scheduled["next_due_at"], "request.scheduled_control.next_due_at")
    result_ref = require_string(
        scheduled["result_ref"], "request.scheduled_control.result_ref", nonempty=False
    )
    scheduled_status = (
        "degraded"
        if schedule_enabled and (schedule_failures or not result_ref)
        else "healthy"
        if schedule_enabled
        else "disabled"
    )

    backup = require_mapping(data["backup"], "request.backup")
    require_exact_keys(
        backup,
        {
            "file_exists",
            "created_at",
            "freshness_slo_seconds",
            "restore_receipt_current",
        },
        "request.backup",
    )
    backup_exists = require_bool(backup["file_exists"], "request.backup.file_exists")
    backup_created = _time(backup["created_at"], "request.backup.created_at")
    backup_slo = require_int(
        backup["freshness_slo_seconds"],
        "request.backup.freshness_slo_seconds",
        minimum=1,
    )
    restore_current = require_bool(
        backup["restore_receipt_current"], "request.backup.restore_receipt_current"
    )
    backup_age = int((now - backup_created).total_seconds())
    backup_status = (
        "qualified"
        if backup_exists and backup_age <= backup_slo and restore_current
        else "stale"
        if backup_exists
        else "failed"
    )

    checkpoint = require_mapping(
        data["obligation_checkpoint"], "request.obligation_checkpoint"
    )
    require_exact_keys(
        checkpoint,
        {
            "required",
            "provider_compatible",
            "question_preserved",
            "constraints_preserved",
            "decisions_preserved",
            "gaps_preserved",
            "negative_results_preserved",
        },
        "request.obligation_checkpoint",
    )
    checkpoint_required = require_bool(
        checkpoint["required"], "request.obligation_checkpoint.required"
    )
    checkpoint_ok = all(
        require_bool(checkpoint[key], f"request.obligation_checkpoint.{key}")
        for key in (
            "provider_compatible",
            "question_preserved",
            "constraints_preserved",
            "decisions_preserved",
            "gaps_preserved",
            "negative_results_preserved",
        )
    )
    compression_allowed = not checkpoint_required or checkpoint_ok

    live = (
        refs_complete
        and lease
        and alive
        and heartbeat <= now <= deadline
        and not circuit_open
    )
    if declared == "complete" and reconciled and not circuit_open:
        computed = "complete"
    elif live:
        computed = "running"
    elif (artifact_refs or accepted_effects) and not reconciled:
        computed = "stale_pending_reconciliation"
    elif reconciled and not circuit_open:
        computed = "resumable"
    else:
        computed = "blocked"
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "LivenessReconciliationReceipt",
            "status": computed,
            "work_id": work_id,
            "declared_state": declared,
            "computed_state": computed,
            "refs_complete": refs_complete,
            "lease_active": lease,
            "heartbeat_age_seconds": int((now - heartbeat).total_seconds()),
            "process_alive": alive,
            "artifact_refs": artifact_refs,
            "accepted_effect_refs": accepted_effects,
            "sequences_or_effects_forbidden_to_repeat": accepted_effects,
            "retry_allowed": retry_allowed,
            "backoff_seconds": backoff if retry_allowed else None,
            "circuit_state": "open" if circuit_open else reported_circuit,
            "restart_storm_prevented": not retry_allowed if permanent else True,
            "scheduled_control": {
                "status": scheduled_status,
                "last_attempt_at": last_attempt.isoformat(),
                "last_success_at": last_success.isoformat(),
                "consecutive_failures": schedule_failures,
                "next_due_at": next_due.isoformat(),
                "result_ref": result_ref or None,
            },
            "backup_qualification": {
                "status": backup_status,
                "age_seconds": backup_age,
                "freshness_slo_seconds": backup_slo,
                "restore_receipt_current": restore_current,
            },
            "obligation_checkpoint": {
                "status": "pass" if checkpoint_ok else "blocked",
                "compression_allowed": compression_allowed,
            },
            "research_stop_decision": "not_inferred_from_runtime_guard",
        }
    )


def assess_distribution_delivery(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "original",
            "sanitizer",
            "transformation",
            "policy",
            "raw_delivery",
            "release",
            "transport",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    original = require_mapping(data["original"], "request.original")
    require_exact_keys(
        original,
        {"artifact_id", "content_hash", "byte_size", "evidence_status"},
        "request.original",
    )
    original_id = require_string(
        original["artifact_id"], "request.original.artifact_id"
    )
    original_hash = _hash(original["content_hash"], "request.original.content_hash")
    original_size = require_int(original["byte_size"], "request.original.byte_size")
    evidence_status = require_string(
        original["evidence_status"], "request.original.evidence_status"
    )
    sanitizer = require_mapping(data["sanitizer"], "request.sanitizer")
    require_exact_keys(
        sanitizer,
        {
            "entrypoint",
            "manifest_version",
            "dependencies",
            "output_root",
            "receipt_root",
            "characteristic_probe",
        },
        "request.sanitizer",
    )
    preflight = {
        key: require_bool(sanitizer[key], f"request.sanitizer.{key}")
        for key in sanitizer
    }
    transformation = require_mapping(data["transformation"], "request.transformation")
    require_exact_keys(
        transformation,
        {
            "derived_artifact_id",
            "input_hash",
            "output_hash",
            "output_byte_size",
            "rules",
            "known_losses",
            "signature_decision",
            "orientation_decision",
            "metadata_decision",
            "verify_result",
        },
        "request.transformation",
    )
    derived_id = require_string(
        transformation["derived_artifact_id"],
        "request.transformation.derived_artifact_id",
    )
    input_hash = _hash(
        transformation["input_hash"], "request.transformation.input_hash"
    )
    output_hash = _hash(
        transformation["output_hash"], "request.transformation.output_hash"
    )
    output_size = require_int(
        transformation["output_byte_size"], "request.transformation.output_byte_size"
    )
    rules = _strings(transformation["rules"], "request.transformation.rules")
    losses = _strings(
        transformation["known_losses"], "request.transformation.known_losses"
    )
    decisions = {
        key: require_string(transformation[key], f"request.transformation.{key}")
        for key in ("signature_decision", "orientation_decision", "metadata_decision")
    }
    verified = require_bool(
        transformation["verify_result"], "request.transformation.verify_result"
    )
    policy = require_mapping(data["policy"], "request.policy")
    require_exact_keys(policy, {"channel", "risk", "sanitizer_mode"}, "request.policy")
    channel = require_string(policy["channel"], "request.policy.channel")
    risk = _enum(
        policy["risk"], {"low", "standard", "high_stakes"}, "request.policy.risk"
    )
    sanitizer_mode = _enum(
        policy["sanitizer_mode"],
        {"fail_closed", "soft", "fail_open"},
        "request.policy.sanitizer_mode",
    )
    issues = []
    if not all(preflight.values()):
        issues.append("sanitizer_preflight_failed")
    if input_hash != original_hash:
        issues.append("transformation_input_mismatch")
    if not verified:
        issues.append("transformation_not_verified")
    if risk == "high_stakes" and sanitizer_mode != "fail_closed":
        issues.append("high_stakes_requires_fail_closed")
    if channel in {"text", "file"} and sanitizer_mode == "fail_open":
        issues.append("silent_text_or_file_bypass_forbidden")
    transformation_receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "TransformationReceipt",
            "status": "verified" if not issues else "blocked",
            "original_artifact_id": original_id,
            "derived_artifact_id": derived_id,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "output_byte_size": output_size,
            "rules": rules,
            "known_losses": losses,
            **decisions,
            "verify_result": verified,
            "derivation_edge_created": not issues,
        }
    )
    raw_decision = None
    if data["raw_delivery"] is not None:
        raw = require_mapping(data["raw_delivery"], "request.raw_delivery")
        require_exact_keys(
            raw,
            {
                "explicit_request",
                "authorized",
                "exact_hash",
                "scope",
                "expires_at",
                "warning_acknowledged",
            },
            "request.raw_delivery",
        )
        raw_ok = (
            require_bool(
                raw["explicit_request"], "request.raw_delivery.explicit_request"
            )
            and require_bool(raw["authorized"], "request.raw_delivery.authorized")
            and _hash(raw["exact_hash"], "request.raw_delivery.exact_hash")
            == original_hash
            and bool(require_string(raw["scope"], "request.raw_delivery.scope"))
            and bool(_time(raw["expires_at"], "request.raw_delivery.expires_at"))
            and require_bool(
                raw["warning_acknowledged"], "request.raw_delivery.warning_acknowledged"
            )
        )
        raw_decision = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "RawDeliveryDecision",
                "status": "approved" if raw_ok else "blocked",
                "original_hash": original_hash,
                "evidence_status_unchanged": evidence_status,
            }
        )
        if not raw_ok:
            issues.append("raw_delivery_not_authorized")
    release = require_mapping(data["release"], "request.release")
    require_exact_keys(
        release, {"artifact_id", "content_hash", "approved"}, "request.release"
    )
    release_id = require_string(release["artifact_id"], "request.release.artifact_id")
    release_hash = _hash(release["content_hash"], "request.release.content_hash")
    release_approved = require_bool(release["approved"], "request.release.approved")
    expected_release_hash = (
        original_hash
        if raw_decision and raw_decision["status"] == "approved"
        else output_hash
    )
    if (
        release_id not in {original_id, derived_id}
        or release_hash != expected_release_hash
        or not release_approved
    ):
        issues.append("release_bytes_not_approved")
    transport = require_mapping(data["transport"], "request.transport")
    require_exact_keys(
        transport,
        {
            "channel",
            "recipient",
            "scope",
            "delivered_hash",
            "delivered_at",
            "readback_hash",
        },
        "request.transport",
    )
    transport_channel = require_string(
        transport["channel"], "request.transport.channel"
    )
    recipient = require_string(transport["recipient"], "request.transport.recipient")
    scope = require_string(transport["scope"], "request.transport.scope")
    delivered_hash = _hash(
        transport["delivered_hash"], "request.transport.delivered_hash"
    )
    delivered_at = _time(transport["delivered_at"], "request.transport.delivered_at")
    readback_hash = _hash(transport["readback_hash"], "request.transport.readback_hash")
    delivered = not issues and delivered_hash == release_hash == readback_hash
    if delivered_hash != release_hash or readback_hash != delivered_hash:
        issues.append("transport_readback_hash_mismatch")
        delivered = False
    transport_receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "TransportReceipt",
            "status": "delivered" if delivered else "blocked",
            "channel": transport_channel,
            "recipient": recipient,
            "scope": scope,
            "delivered_hash": delivered_hash,
            "delivered_at": delivered_at.isoformat(),
            "readback_hash": readback_hash,
            "exact_delivered_bytes_verified": delivered,
        }
    )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "DistributionDeliveryReceipt",
            "status": "delivered" if delivered else "blocked",
            "original_artifact": {
                "id": original_id,
                "hash": original_hash,
                "byte_size": original_size,
                "evidence_status": evidence_status,
                "mutated": False,
            },
            "sanitizer_preflight": {
                "status": "pass" if all(preflight.values()) else "degraded",
                "checks": preflight,
            },
            "transformation": transformation_receipt,
            "raw_delivery": raw_decision,
            "release_hash": release_hash,
            "transport": transport_receipt,
            "issues": sorted(set(issues)),
        }
    )
