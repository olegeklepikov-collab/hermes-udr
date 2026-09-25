"""AgentMemory and Graphiti lifecycle gate for a managed run."""

from __future__ import annotations

from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_list,
    require_mapping,
    require_string,
)


def _service(
    value: object, path: str, check_keys: tuple[str, ...]
) -> tuple[str, dict[str, bool]]:
    data = require_mapping(value, path)
    require_exact_keys(data, {"status", *check_keys}, path)
    status = require_string(data["status"], f"{path}.status")
    checks = {key: require_bool(data[key], f"{path}.{key}") for key in check_keys}
    return status, checks


def assess_context_lifecycle(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "tenant_id",
            "project_id",
            "run_id",
            "profile_id",
            "work_kind",
            "managed_run",
            "requires_agentmemory",
            "requires_graphiti",
            "agentmemory",
            "graphiti",
            "context_receipts_before_llm",
            "degraded_decision",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    tenant_id = require_string(data["tenant_id"], "request.tenant_id")
    project_id = require_string(data["project_id"], "request.project_id")
    run_id = require_string(data["run_id"], "request.run_id")
    profile_id = require_string(data["profile_id"], "request.profile_id")
    work_kind = require_string(data["work_kind"], "request.work_kind")
    managed = require_bool(data["managed_run"], "request.managed_run")
    requires_memory = require_bool(
        data["requires_agentmemory"], "request.requires_agentmemory"
    )
    requires_graph = require_bool(
        data["requires_graphiti"], "request.requires_graphiti"
    )
    receipts_before_llm = require_bool(
        data["context_receipts_before_llm"], "request.context_receipts_before_llm"
    )

    memory_status, memory_checks = _service(
        data["agentmemory"],
        "request.agentmemory",
        (
            "session_start",
            "health_scope",
            "prefetch_receipt",
            "turn_sync",
            "session_close",
            "scope_key_complete",
        ),
    )
    graph_status, graph_checks = _service(
        data["graphiti"],
        "request.graphiti",
        (
            "health_schema",
            "read_receipt",
            "write_receipt",
            "outbox_reconciled",
            "admin_operations_hidden",
        ),
    )

    missing_services: list[str] = []
    if (
        managed
        and requires_memory
        and (
            memory_status not in {"characteristic_verified", "qualified"}
            or not all(memory_checks.values())
        )
    ):
        missing_services.append("agentmemory")
    if (
        managed
        and requires_graph
        and (
            graph_status not in {"characteristic_verified", "qualified"}
            or not all(graph_checks.values())
        )
    ):
        missing_services.append("graphiti")
    hard_issues: list[str] = []
    if managed and not receipts_before_llm:
        hard_issues.append("context receipts were not created before LLM invocation")
    if not graph_checks["admin_operations_hidden"]:
        hard_issues.append("graphiti administrative operations are exposed")

    degraded = data["degraded_decision"]
    degraded_valid = False
    degraded_scope: str | None = None
    acceptance_ceiling: str | None = None
    if degraded is not None:
        decision = require_mapping(degraded, "request.degraded_decision")
        require_exact_keys(
            decision,
            {"approved", "missing_services", "scope", "acceptance_ceiling"},
            "request.degraded_decision",
        )
        approved = require_bool(
            decision["approved"], "request.degraded_decision.approved"
        )
        declared_missing = [
            require_string(
                value, f"request.degraded_decision.missing_services[{index}]"
            )
            for index, value in enumerate(
                require_list(
                    decision["missing_services"],
                    "request.degraded_decision.missing_services",
                )
            )
        ]
        degraded_scope = require_string(
            decision["scope"], "request.degraded_decision.scope"
        )
        acceptance_ceiling = require_string(
            decision["acceptance_ceiling"],
            "request.degraded_decision.acceptance_ceiling",
        )
        degraded_valid = (
            approved
            and set(declared_missing) == set(missing_services)
            and acceptance_ceiling in {"partial", "review_required"}
        )

    missing_services = sorted(set(missing_services))
    if hard_issues:
        status = "blocked"
        blockers = hard_issues
    elif not missing_services:
        status = "context_ready"
        blockers: list[str] = []
    elif degraded_valid:
        status = "degraded_context"
        blockers = []
    else:
        status = "blocked"
        blockers = [
            f"required context service unavailable: {item}" for item in missing_services
        ]

    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "ContextLifecycleReceipt",
        "status": status,
        "run_id": run_id,
        "profile_id": profile_id,
        "scope_key": {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "profile_id": profile_id,
            "work_kind": work_kind,
        },
        "managed_run": managed,
        "context_receipts_before_llm": receipts_before_llm,
        "required_services": sorted(
            [
                name
                for name, required in (
                    ("agentmemory", requires_memory),
                    ("graphiti", requires_graph),
                )
                if managed and required
            ]
        ),
        "missing_services": missing_services,
        "degraded_decision_applied": degraded_valid,
        "degraded_scope": degraded_scope if degraded_valid else None,
        "acceptance_ceiling": acceptance_ceiling if degraded_valid else None,
        "blocking_issues": blockers,
    }
    return with_receipt_hash(payload)
