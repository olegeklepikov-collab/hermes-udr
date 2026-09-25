"""Search preflight, persisted-page, pagination, and import reconciliation."""

from __future__ import annotations

import math
import re
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
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_NULL_TEXT = {"type": ["string", "null"]}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

SEARCH_EXECUTION_TRACE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "dispatch_requested",
        "observed_external_call_count",
        "plan",
        "current_inputs",
        "coverage_snapshot",
        "attempts",
        "imports",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "dispatch_requested": {"type": "boolean"},
        "observed_external_call_count": {"type": "integer", "minimum": 0},
        "plan": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "plan_id",
                "revision",
                "content_hash",
                "required_cell_ids",
                "time_limit_seconds",
                "max_calls",
                "reservation_ref",
            ],
            "properties": {
                "plan_id": _TEXT,
                "revision": {"type": "integer", "minimum": 1},
                "content_hash": _HASH,
                "required_cell_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": _TEXT,
                },
                "time_limit_seconds": {"type": ["integer", "null"], "minimum": 1},
                "max_calls": {"type": ["integer", "null"], "minimum": 1},
                "reservation_ref": _NULL_TEXT,
            },
        },
        "current_inputs": {
            "type": "object",
            "additionalProperties": False,
            "required": ["frame_revision", "frame_hash", "origin_revision"],
            "properties": {
                "frame_revision": {"type": "integer", "minimum": 1},
                "frame_hash": _HASH,
                "origin_revision": {"type": "integer", "minimum": 1},
            },
        },
        "coverage_snapshot": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "snapshot_ref",
                "frame_revision",
                "frame_hash",
                "origin_revision",
                "accepted",
            ],
            "properties": {
                "snapshot_ref": _TEXT,
                "frame_revision": {"type": "integer", "minimum": 1},
                "frame_hash": _HASH,
                "origin_revision": {"type": "integer", "minimum": 1},
                "accepted": {"type": "boolean"},
            },
        },
        "attempts": {"type": "array", "items": {"type": "object"}},
        "imports": {"type": "array", "items": {"type": "object"}},
    },
}

_ATTEMPT_KEYS = {
    "attempt_id",
    "plan_id",
    "plan_revision",
    "plan_hash",
    "frame_revision",
    "frame_hash",
    "origin_revision",
    "route_id",
    "page_number",
    "exact_query",
    "filters_json",
    "raw_response_ref",
    "raw_response_hash",
    "response_identity",
    "candidate_ids",
    "cursor_in",
    "cursor_out",
    "terminal",
}
_IMPORT_KEYS = {
    "import_event_id",
    "response_identity",
    "candidate_ids",
    "reported_cost_units",
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _nullable_text(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повтор элемента запрещён.")
    return result


def _cost(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("invalid_number", path, "Ожидалось неотрицательное конечное число.")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        fail("invalid_number", path, "Ожидалось неотрицательное конечное число.")
    return result


def assess_search_execution_trace(request: object) -> dict[str, Any]:
    """Assess one bounded search execution without performing external calls."""

    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "run_id",
            "dispatch_requested",
            "observed_external_call_count",
            "plan",
            "current_inputs",
            "coverage_snapshot",
            "attempts",
            "imports",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    run_id = require_string(data["run_id"], "request.run_id")
    dispatch_requested = require_bool(
        data["dispatch_requested"], "request.dispatch_requested"
    )
    observed_calls = require_int(
        data["observed_external_call_count"],
        "request.observed_external_call_count",
    )

    plan = require_mapping(data["plan"], "request.plan")
    require_exact_keys(
        plan,
        {
            "plan_id",
            "revision",
            "content_hash",
            "required_cell_ids",
            "time_limit_seconds",
            "max_calls",
            "reservation_ref",
        },
        "request.plan",
    )
    plan_id = require_string(plan["plan_id"], "request.plan.plan_id")
    plan_revision = require_int(plan["revision"], "request.plan.revision", minimum=1)
    plan_hash = _hash(plan["content_hash"], "request.plan.content_hash")
    required_cells = _strings(
        plan["required_cell_ids"], "request.plan.required_cell_ids"
    )
    time_limit = plan["time_limit_seconds"]
    max_calls = plan["max_calls"]
    reservation_ref = _nullable_text(
        plan["reservation_ref"], "request.plan.reservation_ref"
    )
    issues: list[str] = []
    if not required_cells:
        issues.append("required_cells_missing")
    if time_limit is None or max_calls is None or reservation_ref is None:
        issues.append("missing_budget")
    else:
        time_limit = require_int(
            time_limit, "request.plan.time_limit_seconds", minimum=1
        )
        max_calls = require_int(max_calls, "request.plan.max_calls", minimum=1)

    current = require_mapping(data["current_inputs"], "request.current_inputs")
    require_exact_keys(
        current,
        {"frame_revision", "frame_hash", "origin_revision"},
        "request.current_inputs",
    )
    current_frame_revision = require_int(
        current["frame_revision"], "request.current_inputs.frame_revision", minimum=1
    )
    current_frame_hash = _hash(
        current["frame_hash"], "request.current_inputs.frame_hash"
    )
    current_origin_revision = require_int(
        current["origin_revision"], "request.current_inputs.origin_revision", minimum=1
    )

    snapshot = require_mapping(data["coverage_snapshot"], "request.coverage_snapshot")
    require_exact_keys(
        snapshot,
        {"snapshot_ref", "frame_revision", "frame_hash", "origin_revision", "accepted"},
        "request.coverage_snapshot",
    )
    snapshot_ref = require_string(
        snapshot["snapshot_ref"], "request.coverage_snapshot.snapshot_ref"
    )
    snapshot_current = (
        require_int(
            snapshot["frame_revision"],
            "request.coverage_snapshot.frame_revision",
            minimum=1,
        )
        == current_frame_revision
        and _hash(snapshot["frame_hash"], "request.coverage_snapshot.frame_hash")
        == current_frame_hash
        and require_int(
            snapshot["origin_revision"],
            "request.coverage_snapshot.origin_revision",
            minimum=1,
        )
        == current_origin_revision
    )
    if not snapshot_current:
        issues.append("stale_coverage_input")

    normalized_attempts: list[dict[str, Any]] = []
    measured_attempts: list[str] = []
    route_pages: dict[str, list[dict[str, Any]]] = {}
    attempt_ids: set[str] = set()
    for index, raw in enumerate(require_list(data["attempts"], "request.attempts")):
        path = f"request.attempts[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, _ATTEMPT_KEYS, path)
        attempt_id = require_string(row["attempt_id"], f"{path}.attempt_id")
        if attempt_id in attempt_ids:
            fail("duplicate_attempt", f"{path}.attempt_id", "Повтор попытки запрещён.")
        attempt_ids.add(attempt_id)
        binding_current = (
            require_string(row["plan_id"], f"{path}.plan_id") == plan_id
            and require_int(row["plan_revision"], f"{path}.plan_revision", minimum=1)
            == plan_revision
            and _hash(row["plan_hash"], f"{path}.plan_hash") == plan_hash
            and require_int(row["frame_revision"], f"{path}.frame_revision", minimum=1)
            == current_frame_revision
            and _hash(row["frame_hash"], f"{path}.frame_hash") == current_frame_hash
            and require_int(
                row["origin_revision"], f"{path}.origin_revision", minimum=1
            )
            == current_origin_revision
        )
        if not binding_current:
            issues.append(f"stale_attempt_binding:{attempt_id}")
        route_id = require_string(row["route_id"], f"{path}.route_id")
        page_number = require_int(row["page_number"], f"{path}.page_number", minimum=1)
        raw_ref = _nullable_text(row["raw_response_ref"], f"{path}.raw_response_ref")
        raw_hash = (
            None
            if row["raw_response_hash"] is None
            else _hash(row["raw_response_hash"], f"{path}.raw_response_hash")
        )
        response_identity = _hash(row["response_identity"], f"{path}.response_identity")
        saved = raw_ref is not None and raw_hash == response_identity
        if not saved:
            issues.append(f"missing_response:{attempt_id}")
        else:
            measured_attempts.append(attempt_id)
        normalized = {
            "attempt_id": attempt_id,
            "plan_id": plan_id,
            "plan_revision": plan_revision,
            "plan_hash": plan_hash,
            "route_id": route_id,
            "page_number": page_number,
            "exact_query": require_string(row["exact_query"], f"{path}.exact_query"),
            "filters_json": require_string(row["filters_json"], f"{path}.filters_json"),
            "raw_response_ref": raw_ref,
            "raw_response_hash": raw_hash,
            "response_identity": response_identity,
            "candidate_ids": _strings(row["candidate_ids"], f"{path}.candidate_ids"),
            "cursor_in": _nullable_text(row["cursor_in"], f"{path}.cursor_in"),
            "cursor_out": _nullable_text(row["cursor_out"], f"{path}.cursor_out"),
            "terminal": require_bool(row["terminal"], f"{path}.terminal"),
            "saved": saved,
            "binding_current": binding_current,
        }
        normalized_attempts.append(normalized)
        route_pages.setdefault(route_id, []).append(normalized)

    if observed_calls > (max_calls if isinstance(max_calls, int) else 0):
        issues.append("call_budget_exceeded")
    budget_ready = "missing_budget" not in issues
    if not budget_ready and observed_calls:
        issues.append("call_without_budget")
    dispatch_allowed = dispatch_requested and budget_ready and snapshot_current

    terminal_routes: list[str] = []
    route_diagnostics: list[dict[str, object]] = []
    for route_id, pages in sorted(route_pages.items()):
        pages.sort(key=lambda row: int(row["page_number"]))
        truncation = None
        seen_cursors: set[str] = set()
        for page in pages:
            cursor_in = page["cursor_in"]
            cursor_out = page["cursor_out"]
            if cursor_in is not None:
                seen_cursors.add(str(cursor_in))
            if cursor_out is not None and str(cursor_out) in seen_cursors:
                truncation = "cursor_cycle"
                break
            if cursor_out is not None:
                seen_cursors.add(str(cursor_out))
        last = pages[-1]
        terminal = bool(last["terminal"] and last["saved"] and truncation is None)
        if terminal:
            terminal_routes.append(route_id)
        route_diagnostics.append(
            {
                "route_id": route_id,
                "page_count": len(pages),
                "terminal": terminal,
                "terminal_response_ref": last["raw_response_ref"] if terminal else None,
                "truncation": truncation,
            }
        )

    import_rows: list[dict[str, object]] = []
    import_ids: set[str] = set()
    first_import: dict[str, tuple[tuple[str, ...], float]] = {}
    corpus_candidates: set[str] = set()
    total_cost = 0.0
    for index, raw in enumerate(require_list(data["imports"], "request.imports")):
        path = f"request.imports[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, _IMPORT_KEYS, path)
        event_id = require_string(row["import_event_id"], f"{path}.import_event_id")
        if event_id in import_ids:
            fail(
                "duplicate_import_event",
                f"{path}.import_event_id",
                "Повтор события импорта.",
            )
        import_ids.add(event_id)
        identity = _hash(row["response_identity"], f"{path}.response_identity")
        candidates = tuple(_strings(row["candidate_ids"], f"{path}.candidate_ids"))
        cost = _cost(row["reported_cost_units"], f"{path}.reported_cost_units")
        duplicate = identity in first_import
        if duplicate:
            prior_candidates, _prior_cost = first_import[identity]
            if candidates != prior_candidates:
                issues.append(f"duplicate_candidate_mismatch:{event_id}")
            if cost != 0:
                issues.append(f"duplicate_cost_inflation:{event_id}")
        else:
            first_import[identity] = (candidates, cost)
            corpus_candidates.update(candidates)
            total_cost += cost
        import_rows.append(
            {
                "import_event_id": event_id,
                "response_identity": identity,
                "candidate_ids": list(candidates),
                "reported_cost_units": cost,
                "duplicate_import": duplicate,
            }
        )

    accepted = not issues
    return with_receipt_hash(
        {
            "contract": "SearchExecutionTraceReceipt",
            "status": "accepted" if accepted else "repair_required",
            "run_id": run_id,
            "plan_ref": {
                "id": plan_id,
                "revision": plan_revision,
                "content_hash": plan_hash,
            },
            "dispatch_allowed": dispatch_allowed,
            "observed_external_call_count": observed_calls,
            "measured_attempt_ids": measured_attempts,
            "attempts": normalized_attempts,
            "terminal_routes": terminal_routes,
            "route_diagnostics": route_diagnostics,
            "coverage_snapshot": {
                "snapshot_ref": snapshot_ref,
                "status": "current" if snapshot_current else "stale",
                "prior_accepted": require_bool(
                    snapshot["accepted"], "request.coverage_snapshot.accepted"
                ),
                "current_origin_revision": current_origin_revision,
            },
            "imports": import_rows,
            "corpus_candidate_ids": sorted(corpus_candidates),
            "unique_external_cost_units": total_cost,
            "issues": sorted(set(issues)),
            "transmission_allowed": accepted and snapshot_current,
        }
    )
