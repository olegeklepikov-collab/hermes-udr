"""Deterministic retry-budget and circuit-breaker decisions."""

from __future__ import annotations

from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_int,
    require_mapping,
    require_string,
)

_ERROR_CLASSES = {"none", "transient", "permanent", "configuration", "dependency"}
_STATES = {"closed", "half_open", "open"}


def assess_circuit(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "route_id",
            "error_class",
            "failure_count",
            "retry_budget",
            "current_state",
            "state_change_trigger",
            "manual_probe_pass",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    route_id = require_string(data["route_id"], "request.route_id")
    error_class = require_string(data["error_class"], "request.error_class")
    if error_class not in _ERROR_CLASSES:
        fail("invalid_error_class", "request.error_class", "Неизвестный класс ошибки.")
    failures = require_int(data["failure_count"], "request.failure_count")
    budget = require_int(data["retry_budget"], "request.retry_budget", minimum=1)
    current = require_string(data["current_state"], "request.current_state")
    if current not in _STATES:
        fail(
            "invalid_circuit_state",
            "request.current_state",
            "Неизвестное состояние circuit.",
        )
    trigger = require_bool(data["state_change_trigger"], "request.state_change_trigger")
    probe = require_bool(data["manual_probe_pass"], "request.manual_probe_pass")

    if current == "open":
        next_state = "closed" if trigger and probe else "open"
    elif current == "half_open":
        next_state = "closed" if probe else "open"
    elif error_class == "none":
        next_state = "closed"
    elif failures >= budget:
        next_state = "open"
    else:
        next_state = "closed"

    permanent = error_class in {"permanent", "configuration", "dependency"}
    retry_allowed = next_state != "open" and not (
        permanent and failures > 0 and not trigger
    )
    if permanent and failures > 0 and next_state == "closed" and not trigger:
        retry_reason = "state_change_required"
    elif next_state == "open":
        retry_reason = "circuit_open"
    else:
        retry_reason = "within_budget"

    if next_state == "open":
        status = "open_circuit"
    elif retry_allowed:
        status = "closed_circuit"
    else:
        status = "retry_blocked_state_change_required"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "CircuitDecisionReceipt",
        "status": status,
        "route_id": route_id,
        "error_class": error_class,
        "failure_count": failures,
        "retry_budget": budget,
        "prior_state": current,
        "next_state": next_state,
        "retry_allowed": retry_allowed,
        "retry_reason": retry_reason,
        "reset_applied": current == "open" and next_state == "closed",
    }
    return with_receipt_hash(payload)
