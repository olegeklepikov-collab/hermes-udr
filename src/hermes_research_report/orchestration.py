"""Finite WorkPacket DAG validation with separate execution and result states."""

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

_EXECUTION_STATES = {"ready", "running", "succeeded", "failed", "blocked"}
_RESULT_STATES = {"draft", "review_required", "accepted", "rejected"}
_OBJECTIVE_CLASSES = {
    "acquire",
    "parse",
    "search",
    "analyze",
    "synthesize",
    "review",
    "release",
    "migrate",
}
_TEXT = {"type": "string", "minLength": 1}
_STRING_ARRAY = {
    "type": "array",
    "maxItems": 100,
    "uniqueItems": True,
    "items": _TEXT,
}
_LIMITS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["attempts", "wall_seconds", "cost_units"],
    "properties": {
        "attempts": {"type": "integer", "minimum": 1},
        "wall_seconds": {"type": "integer", "minimum": 1},
        "cost_units": {"type": "integer", "minimum": 0},
    },
}
_PACKET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "packet_id",
        "objective",
        "objective_class",
        "output_contract",
        "input_refs",
        "depends_on",
        "required_capabilities",
        "obligations",
        "limits",
        "assignee_role",
        "acceptor_role",
        "active_assignment_count",
        "execution_status",
        "result_status",
    ],
    "properties": {
        "packet_id": _TEXT,
        "objective": _TEXT,
        "objective_class": {"enum": sorted(_OBJECTIVE_CLASSES)},
        "output_contract": _TEXT,
        "input_refs": _STRING_ARRAY,
        "depends_on": _STRING_ARRAY,
        "required_capabilities": _STRING_ARRAY,
        "obligations": _STRING_ARRAY,
        "limits": _LIMITS_SCHEMA,
        "assignee_role": _TEXT,
        "acceptor_role": _TEXT,
        "active_assignment_count": {"type": "integer", "minimum": 0},
        "execution_status": {"enum": sorted(_EXECUTION_STATES)},
        "result_status": {"enum": sorted(_RESULT_STATES)},
    },
}
WORK_PLAN_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "run_ref", "packets"],
    "properties": {
        "schema_version": {"const": 1},
        "run_ref": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "revision", "content_hash"],
            "properties": {
                "id": _TEXT,
                "revision": {"type": "integer", "minimum": 1},
                "content_hash": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
            },
        },
        "packets": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": _PACKET_SCHEMA,
        },
    },
}


def _strings(value: object, path: str) -> list[str]:
    raw = require_list(value, path)
    if len(raw) > 100:
        fail("size_limit", path, "Массив длиннее 100 элементов.")
    result = [
        require_string(item, f"{path}[{index}]") for index, item in enumerate(raw)
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повторный элемент запрещён.")
    return result


def _topological_order(
    dependencies: dict[str, list[str]], issues: list[str]
) -> list[str]:
    unknown = sorted(
        {
            dependency
            for values in dependencies.values()
            for dependency in values
            if dependency not in dependencies
        }
    )
    issues.extend(f"unknown_dependency:{item}" for item in unknown)
    if unknown:
        return []
    indegree = {packet_id: len(values) for packet_id, values in dependencies.items()}
    dependents: dict[str, list[str]] = {packet_id: [] for packet_id in dependencies}
    for packet_id, values in dependencies.items():
        for dependency in values:
            dependents[dependency].append(packet_id)
    ready = sorted(packet_id for packet_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        packet_id = ready.pop(0)
        order.append(packet_id)
        for dependent in sorted(dependents[packet_id]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort()
    if len(order) != len(dependencies):
        cycle_nodes = sorted(
            packet_id for packet_id, degree in indegree.items() if degree > 0
        )
        issues.append("dependency_cycle:" + ",".join(cycle_nodes))
        return []
    return order


def build_work_plan(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "run_ref", "packets"}, "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_ref = require_mapping(data["run_ref"], "request.run_ref")
    require_exact_keys(run_ref, {"id", "revision", "content_hash"}, "request.run_ref")
    normalized_run_ref = {
        "id": require_string(run_ref["id"], "request.run_ref.id"),
        "revision": require_int(
            run_ref["revision"], "request.run_ref.revision", minimum=1
        ),
        "content_hash": require_string(
            run_ref["content_hash"], "request.run_ref.content_hash"
        ),
    }
    if len(normalized_run_ref["content_hash"]) != 64 or any(
        char not in "0123456789abcdef" for char in normalized_run_ref["content_hash"]
    ):
        fail("invalid_hash", "request.run_ref.content_hash", "Неверный SHA-256.")

    raw_packets = require_list(data["packets"], "request.packets")
    if not raw_packets or len(raw_packets) > 1000:
        fail(
            "invalid_packet_count", "request.packets", "Требуется от 1 до 1000 пакетов."
        )
    packets: dict[str, dict[str, Any]] = {}
    dependencies: dict[str, list[str]] = {}
    issues: list[str] = []
    for index, raw in enumerate(raw_packets):
        path = f"request.packets[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, set(_PACKET_SCHEMA["required"]), path)
        packet_id = require_string(row["packet_id"], f"{path}.packet_id")
        if packet_id in packets:
            fail("duplicate_packet", f"{path}.packet_id", "Повторный packet_id.")
        objective = require_string(row["objective"], f"{path}.objective")
        objective_class = require_string(
            row["objective_class"], f"{path}.objective_class"
        )
        if objective_class not in _OBJECTIVE_CLASSES:
            fail(
                "invalid_objective_class",
                f"{path}.objective_class",
                "Неверный класс выхода.",
            )
        output_contract = require_string(
            row["output_contract"], f"{path}.output_contract"
        )
        input_refs = _strings(row["input_refs"], f"{path}.input_refs")
        depends_on = _strings(row["depends_on"], f"{path}.depends_on")
        capabilities = _strings(
            row["required_capabilities"], f"{path}.required_capabilities"
        )
        obligations = _strings(row["obligations"], f"{path}.obligations")
        limits = require_mapping(row["limits"], f"{path}.limits")
        require_exact_keys(
            limits, {"attempts", "wall_seconds", "cost_units"}, f"{path}.limits"
        )
        normalized_limits = {
            "attempts": require_int(
                limits["attempts"], f"{path}.limits.attempts", minimum=1
            ),
            "wall_seconds": require_int(
                limits["wall_seconds"], f"{path}.limits.wall_seconds", minimum=1
            ),
            "cost_units": require_int(
                limits["cost_units"], f"{path}.limits.cost_units"
            ),
        }
        assignee = require_string(row["assignee_role"], f"{path}.assignee_role")
        acceptor = require_string(row["acceptor_role"], f"{path}.acceptor_role")
        active = require_int(
            row["active_assignment_count"], f"{path}.active_assignment_count"
        )
        execution = require_string(row["execution_status"], f"{path}.execution_status")
        result = require_string(row["result_status"], f"{path}.result_status")
        if execution not in _EXECUTION_STATES:
            fail(
                "invalid_execution_status",
                f"{path}.execution_status",
                "Неверный статус исполнения.",
            )
        if result not in _RESULT_STATES:
            fail(
                "invalid_result_status",
                f"{path}.result_status",
                "Неверный статус результата.",
            )
        if assignee == acceptor:
            issues.append(f"assignee_acceptor_not_separated:{packet_id}")
        if active > 1:
            issues.append(f"multiple_active_assignments:{packet_id}")
        if execution == "running" and active != 1:
            issues.append(f"running_without_one_assignment:{packet_id}")
        if execution != "running" and active != 0:
            issues.append(f"inactive_packet_has_assignment:{packet_id}")
        if execution in {"ready", "running"} and result != "draft":
            issues.append(f"premature_result_status:{packet_id}")
        packets[packet_id] = {
            "packet_id": packet_id,
            "objective": objective,
            "objective_class": objective_class,
            "output_contract": output_contract,
            "input_refs": input_refs,
            "depends_on": depends_on,
            "required_capabilities": capabilities,
            "obligations": obligations,
            "limits": normalized_limits,
            "assignee_role": assignee,
            "acceptor_role": acceptor,
            "active_assignment_count": active,
            "execution_status": execution,
            "result_status": result,
        }
        dependencies[packet_id] = depends_on
    order = _topological_order(dependencies, issues)
    issues = sorted(set(issues))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "WorkPlanDecisionReceipt",
        "status": "plan_ready" if not issues else "blocked",
        "run_ref": normalized_run_ref,
        "packet_count": len(packets),
        "topological_order": order,
        "packets": [packets[packet_id] for packet_id in sorted(packets)],
        "total_attempt_limit": sum(
            packet["limits"]["attempts"] for packet in packets.values()
        ),
        "total_cost_upper_bound": sum(
            packet["limits"]["cost_units"] for packet in packets.values()
        ),
        "execution_started_by_decision": False,
        "persistence_applied": False,
        "blocking_issues": issues,
    }
    return with_receipt_hash(payload)
