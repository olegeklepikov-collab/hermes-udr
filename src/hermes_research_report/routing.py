"""Capability-first route selection from factual route probes and limits."""

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
_STRING_ARRAY = {
    "type": "array",
    "maxItems": 100,
    "uniqueItems": True,
    "items": _TEXT,
}
_CAPABILITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "capability_id",
        "input_schema_ref",
        "output_schema_ref",
        "data_classes",
        "input_bytes",
        "cancellable",
        "idempotent",
        "allowed_recipients",
        "required_obligations",
        "characteristic_probe_id",
    ],
    "properties": {
        "capability_id": _TEXT,
        "input_schema_ref": _TEXT,
        "output_schema_ref": _TEXT,
        "data_classes": _STRING_ARRAY,
        "input_bytes": {"type": "integer", "minimum": 0},
        "cancellable": {"type": "boolean"},
        "idempotent": {"type": "boolean"},
        "allowed_recipients": _STRING_ARRAY,
        "required_obligations": _STRING_ARRAY,
        "characteristic_probe_id": _TEXT,
    },
}
_ROUTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "route_id",
        "priority",
        "provider",
        "executor",
        "version",
        "offered_capability_id",
        "input_schema_ref",
        "output_schema_ref",
        "accepted_data_classes",
        "cancellable",
        "idempotent",
        "allowed",
        "authenticated",
        "entitled",
        "health_status",
        "characteristic_probe_id",
        "characteristic_probe_status",
        "max_input_bytes",
        "chunking_supported",
        "chunk_coverage_verified",
        "cost_upper_bound",
        "supported_obligations",
        "recipient_classes",
        "limitations",
    ],
    "properties": {
        "route_id": _TEXT,
        "priority": {"type": "integer", "minimum": 0},
        "provider": _TEXT,
        "executor": _TEXT,
        "version": _TEXT,
        "offered_capability_id": _TEXT,
        "input_schema_ref": _TEXT,
        "output_schema_ref": _TEXT,
        "accepted_data_classes": _STRING_ARRAY,
        "cancellable": {"type": "boolean"},
        "idempotent": {"type": "boolean"},
        "allowed": {"type": "boolean"},
        "authenticated": {"type": "boolean"},
        "entitled": {"type": "boolean"},
        "health_status": {"enum": ["ok", "degraded", "unavailable", "unknown"]},
        "characteristic_probe_id": _TEXT,
        "characteristic_probe_status": {"enum": ["pass", "fail", "not_run", "stale"]},
        "max_input_bytes": {"type": "integer", "minimum": 0},
        "chunking_supported": {"type": "boolean"},
        "chunk_coverage_verified": {"type": "boolean"},
        "cost_upper_bound": {"type": "integer", "minimum": 0},
        "supported_obligations": _STRING_ARRAY,
        "recipient_classes": _STRING_ARRAY,
        "limitations": _STRING_ARRAY,
    },
}
ROUTE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "project_id",
        "run_id",
        "packet_id",
        "capability_request",
        "budget",
        "routes",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "project_id": _TEXT,
        "run_id": _TEXT,
        "packet_id": _TEXT,
        "capability_request": _CAPABILITY_SCHEMA,
        "budget": {
            "type": "object",
            "additionalProperties": False,
            "required": ["available_units", "reserved_units"],
            "properties": {
                "available_units": {"type": "integer", "minimum": 0},
                "reserved_units": {"type": "integer", "minimum": 0},
            },
        },
        "routes": {
            "type": "array",
            "maxItems": 100,
            "items": _ROUTE_SCHEMA,
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


def _capability(value: object) -> dict[str, Any]:
    path = "request.capability_request"
    data = require_mapping(value, path)
    require_exact_keys(data, set(_CAPABILITY_SCHEMA["required"]), path)
    return {
        "capability_id": require_string(data["capability_id"], f"{path}.capability_id"),
        "input_schema_ref": require_string(
            data["input_schema_ref"], f"{path}.input_schema_ref"
        ),
        "output_schema_ref": require_string(
            data["output_schema_ref"], f"{path}.output_schema_ref"
        ),
        "data_classes": _strings(data["data_classes"], f"{path}.data_classes"),
        "input_bytes": require_int(data["input_bytes"], f"{path}.input_bytes"),
        "cancellable": require_bool(data["cancellable"], f"{path}.cancellable"),
        "idempotent": require_bool(data["idempotent"], f"{path}.idempotent"),
        "allowed_recipients": _strings(
            data["allowed_recipients"], f"{path}.allowed_recipients"
        ),
        "required_obligations": _strings(
            data["required_obligations"], f"{path}.required_obligations"
        ),
        "characteristic_probe_id": require_string(
            data["characteristic_probe_id"], f"{path}.characteristic_probe_id"
        ),
    }


def _route(value: object, index: int) -> dict[str, Any]:
    path = f"request.routes[{index}]"
    data = require_mapping(value, path)
    require_exact_keys(data, set(_ROUTE_SCHEMA["required"]), path)
    health = require_string(data["health_status"], f"{path}.health_status")
    if health not in {"ok", "degraded", "unavailable", "unknown"}:
        fail(
            "invalid_health_status", f"{path}.health_status", "Неверный health status."
        )
    probe = require_string(
        data["characteristic_probe_status"], f"{path}.characteristic_probe_status"
    )
    if probe not in {"pass", "fail", "not_run", "stale"}:
        fail(
            "invalid_probe_status",
            f"{path}.characteristic_probe_status",
            "Неверный probe status.",
        )
    return {
        "route_id": require_string(data["route_id"], f"{path}.route_id"),
        "priority": require_int(data["priority"], f"{path}.priority"),
        "provider": require_string(data["provider"], f"{path}.provider"),
        "executor": require_string(data["executor"], f"{path}.executor"),
        "version": require_string(data["version"], f"{path}.version"),
        "offered_capability_id": require_string(
            data["offered_capability_id"], f"{path}.offered_capability_id"
        ),
        "input_schema_ref": require_string(
            data["input_schema_ref"], f"{path}.input_schema_ref"
        ),
        "output_schema_ref": require_string(
            data["output_schema_ref"], f"{path}.output_schema_ref"
        ),
        "accepted_data_classes": _strings(
            data["accepted_data_classes"], f"{path}.accepted_data_classes"
        ),
        "cancellable": require_bool(data["cancellable"], f"{path}.cancellable"),
        "idempotent": require_bool(data["idempotent"], f"{path}.idempotent"),
        "allowed": require_bool(data["allowed"], f"{path}.allowed"),
        "authenticated": require_bool(data["authenticated"], f"{path}.authenticated"),
        "entitled": require_bool(data["entitled"], f"{path}.entitled"),
        "health_status": health,
        "characteristic_probe_id": require_string(
            data["characteristic_probe_id"], f"{path}.characteristic_probe_id"
        ),
        "characteristic_probe_status": probe,
        "max_input_bytes": require_int(
            data["max_input_bytes"], f"{path}.max_input_bytes"
        ),
        "chunking_supported": require_bool(
            data["chunking_supported"], f"{path}.chunking_supported"
        ),
        "chunk_coverage_verified": require_bool(
            data["chunk_coverage_verified"], f"{path}.chunk_coverage_verified"
        ),
        "cost_upper_bound": require_int(
            data["cost_upper_bound"], f"{path}.cost_upper_bound"
        ),
        "supported_obligations": _strings(
            data["supported_obligations"], f"{path}.supported_obligations"
        ),
        "recipient_classes": _strings(
            data["recipient_classes"], f"{path}.recipient_classes"
        ),
        "limitations": _strings(data["limitations"], f"{path}.limitations"),
    }


def _route_issues(
    route: dict[str, Any], capability: dict[str, Any], remaining_budget: int
) -> list[str]:
    issues: list[str] = []
    if route["offered_capability_id"] != capability["capability_id"]:
        issues.append("capability_mismatch")
    if route["input_schema_ref"] != capability["input_schema_ref"]:
        issues.append("input_schema_mismatch")
    if route["output_schema_ref"] != capability["output_schema_ref"]:
        issues.append("output_schema_mismatch")
    if not set(capability["data_classes"]).issubset(route["accepted_data_classes"]):
        issues.append("data_class_not_allowed")
    if capability["cancellable"] and not route["cancellable"]:
        issues.append("cancellability_weakened")
    if capability["idempotent"] and not route["idempotent"]:
        issues.append("idempotency_weakened")
    if not route["allowed"]:
        issues.append("permission_denied")
    if not route["authenticated"]:
        issues.append("authentication_missing")
    if not route["entitled"]:
        issues.append("entitlement_missing")
    if route["health_status"] != "ok":
        issues.append("health_not_ok")
    if route["version"] == "latest":
        issues.append("floating_version")
    if route["characteristic_probe_id"] != capability["characteristic_probe_id"]:
        issues.append("characteristic_probe_mismatch")
    if route["characteristic_probe_status"] != "pass":
        issues.append("characteristic_probe_not_passed")
    if route["cost_upper_bound"] > remaining_budget:
        issues.append("budget_insufficient")
    if not set(capability["required_obligations"]).issubset(
        route["supported_obligations"]
    ):
        issues.append("required_obligations_weakened")
    if not set(capability["allowed_recipients"]).issubset(route["recipient_classes"]):
        issues.append("recipient_policy_mismatch")
    if capability["input_bytes"] > route["max_input_bytes"] and not (
        route["chunking_supported"] and route["chunk_coverage_verified"]
    ):
        issues.append("input_capacity_exceeded")
    return sorted(set(issues))


def assess_route(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "project_id",
            "run_id",
            "packet_id",
            "capability_request",
            "budget",
            "routes",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    project_id = require_string(data["project_id"], "request.project_id")
    run_id = require_string(data["run_id"], "request.run_id")
    packet_id = require_string(data["packet_id"], "request.packet_id")
    capability = _capability(data["capability_request"])
    budget = require_mapping(data["budget"], "request.budget")
    require_exact_keys(budget, {"available_units", "reserved_units"}, "request.budget")
    available = require_int(budget["available_units"], "request.budget.available_units")
    reserved = require_int(budget["reserved_units"], "request.budget.reserved_units")
    if reserved > available:
        fail(
            "invalid_budget",
            "request.budget.reserved_units",
            "Резерв превышает бюджет.",
        )
    remaining = available - reserved
    raw_routes = require_list(data["routes"], "request.routes")
    if len(raw_routes) > 100:
        fail("size_limit", "request.routes", "Слишком много маршрутов.")
    routes: list[dict[str, Any]] = []
    seen: set[str] = set()
    route_results: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_routes):
        route = _route(raw, index)
        if route["route_id"] in seen:
            fail(
                "duplicate_route",
                f"request.routes[{index}].route_id",
                "Повторный route_id.",
            )
        seen.add(route["route_id"])
        issues = _route_issues(route, capability, remaining)
        routes.append(route)
        route_results.append(
            {"route_id": route["route_id"], "eligible": not issues, "issues": issues}
        )
    eligible = [
        route
        for route, result in zip(routes, route_results, strict=True)
        if result["eligible"]
    ]
    eligible.sort(key=lambda route: (route["priority"], route["route_id"]))
    selected = eligible[0] if eligible else None
    request_hash = sha256_json(capability)
    operation_id = (
        "OP-"
        + sha256_json(
            {
                "project_id": project_id,
                "run_id": run_id,
                "packet_id": packet_id,
                "request_hash": request_hash,
                "route_id": selected["route_id"] if selected else None,
            }
        )[:20]
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "RouteDecisionReceipt",
        "status": "route_ready" if selected else "blocked",
        "project_id": project_id,
        "run_id": run_id,
        "packet_id": packet_id,
        "capability_id": capability["capability_id"],
        "request_hash": request_hash,
        "operation_id": operation_id,
        "selected_route": (
            {
                "route_id": selected["route_id"],
                "provider": selected["provider"],
                "executor": selected["executor"],
                "version": selected["version"],
                "cost_upper_bound": selected["cost_upper_bound"],
                "max_input_bytes": selected["max_input_bytes"],
                "chunking_applied": capability["input_bytes"]
                > selected["max_input_bytes"],
                "limitations": selected["limitations"],
            }
            if selected
            else None
        ),
        "route_assessments": sorted(route_results, key=lambda row: row["route_id"]),
        "budget_available_units": available,
        "budget_reserved_before": reserved,
        "budget_reservation_requested": (
            selected["cost_upper_bound"] if selected else 0
        ),
        "budget_reservation_applied": False,
        "external_call_performed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)
