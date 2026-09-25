"""Search ledger and factual coverage assessment without executing search."""

from __future__ import annotations

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

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_READ_STATES = {"not_acquired", "acquired", "partial", "read_in_scope"}
_NEGATIVE_STATES = {
    "not_found_in_scope",
    "low_density",
    "blocked_by_access",
    "metadata_only",
    "method_incapable",
    "out_of_scope",
    "deferred",
}
_DECISIONS = {
    "continue",
    "stop_saturated",
    "stop_low_yield",
    "defer",
    "blocked",
    "reroute",
    "escalate",
}
_STOP_DECISIONS = _DECISIONS - {"continue"}
_TEXT = {"type": "string", "minLength": 1}
_STRING_ARRAY = {
    "type": "array",
    "maxItems": 1000,
    "uniqueItems": True,
    "items": _TEXT,
}
_CELL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "cell_id",
        "question_id",
        "source_family",
        "geography_language",
        "time_window",
        "evidence_type",
        "required",
        "planned",
        "execution_receipt_ref",
        "candidate_count",
        "acquired_count",
        "read_status",
        "origin_verified_count",
        "negative_status",
    ],
    "properties": {
        "cell_id": _TEXT,
        "question_id": _TEXT,
        "source_family": _TEXT,
        "geography_language": _TEXT,
        "time_window": _TEXT,
        "evidence_type": _TEXT,
        "required": {"type": "boolean"},
        "planned": {"type": "boolean"},
        "execution_receipt_ref": {"type": ["string", "null"]},
        "candidate_count": {"type": "integer", "minimum": 0},
        "acquired_count": {"type": "integer", "minimum": 0},
        "read_status": {"enum": sorted(_READ_STATES)},
        "origin_verified_count": {"type": "integer", "minimum": 0},
        "negative_status": {
            "anyOf": [{"enum": sorted(_NEGATIVE_STATES)}, {"type": "null"}]
        },
    },
}
_ENTRY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "entry_id",
        "branch_id",
        "iteration",
        "occurred_at",
        "route_receipt_ref",
        "raw_response_ref",
        "raw_response_hash",
        "language",
        "geography",
        "time_window",
        "exact_query",
        "access_context",
        "ranking_limitations",
        "question_ids",
        "source_family",
        "purpose",
        "expected_signal",
        "candidate_refs",
        "origin_refs",
        "claim_refs",
        "factual_outcome",
        "decision",
        "next_step",
    ],
    "properties": {
        "entry_id": _TEXT,
        "branch_id": _TEXT,
        "iteration": {"type": "integer", "minimum": 1},
        "occurred_at": _TEXT,
        "route_receipt_ref": _TEXT,
        "raw_response_ref": _TEXT,
        "raw_response_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "language": _TEXT,
        "geography": _TEXT,
        "time_window": _TEXT,
        "exact_query": _TEXT,
        "access_context": _TEXT,
        "ranking_limitations": _STRING_ARRAY,
        "question_ids": _STRING_ARRAY,
        "source_family": _TEXT,
        "purpose": _TEXT,
        "expected_signal": _TEXT,
        "candidate_refs": _STRING_ARRAY,
        "origin_refs": _STRING_ARRAY,
        "claim_refs": _STRING_ARRAY,
        "factual_outcome": _TEXT,
        "decision": {"enum": sorted(_DECISIONS)},
        "next_step": _TEXT,
    },
}
SEARCH_LEDGER_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "coverage_frame",
        "cells",
        "entries",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "coverage_frame": {
            "type": "object",
            "additionalProperties": False,
            "required": ["version", "content_hash", "universe_status"],
            "properties": {
                "version": _TEXT,
                "content_hash": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "universe_status": {
                    "enum": ["bounded_frame", "known_reference", "unknown"]
                },
            },
        },
        "cells": {"type": "array", "maxItems": 10000, "items": _CELL_SCHEMA},
        "entries": {"type": "array", "maxItems": 10000, "items": _ENTRY_SCHEMA},
    },
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _strings(value: object, path: str) -> list[str]:
    rows = require_list(value, path)
    if len(rows) > 1000:
        fail("size_limit", path, "Массив превышает 1000 элементов.")
    result = [
        require_string(item, f"{path}[{index}]") for index, item in enumerate(rows)
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повторный элемент запрещён.")
    return result


def assess_search_ledger(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {"schema_version", "run_id", "coverage_frame", "cells", "entries"},
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    frame = require_mapping(data["coverage_frame"], "request.coverage_frame")
    require_exact_keys(
        frame, {"version", "content_hash", "universe_status"}, "request.coverage_frame"
    )
    frame_version = require_string(frame["version"], "request.coverage_frame.version")
    frame_hash = _hash(frame["content_hash"], "request.coverage_frame.content_hash")
    universe = require_string(
        frame["universe_status"], "request.coverage_frame.universe_status"
    )
    if universe not in {"bounded_frame", "known_reference", "unknown"}:
        fail(
            "invalid_universe_status",
            "request.coverage_frame.universe_status",
            "Неверное состояние знаменателя.",
        )

    raw_cells = require_list(data["cells"], "request.cells")
    if len(raw_cells) > 10000:
        fail("size_limit", "request.cells", "Слишком много ячеек покрытия.")
    cells: list[dict[str, Any]] = []
    cell_ids: set[str] = set()
    issues: list[str] = []
    for index, raw in enumerate(raw_cells):
        path = f"request.cells[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, set(_CELL_SCHEMA["required"]), path)
        cell_id = require_string(row["cell_id"], f"{path}.cell_id")
        if cell_id in cell_ids:
            fail("duplicate_cell", f"{path}.cell_id", "Повторная ячейка.")
        cell_ids.add(cell_id)
        execution_ref = row["execution_receipt_ref"]
        if execution_ref is not None:
            execution_ref = require_string(
                execution_ref, f"{path}.execution_receipt_ref"
            )
        candidate_count = require_int(row["candidate_count"], f"{path}.candidate_count")
        acquired_count = require_int(row["acquired_count"], f"{path}.acquired_count")
        origin_count = require_int(
            row["origin_verified_count"], f"{path}.origin_verified_count"
        )
        read_status = require_string(row["read_status"], f"{path}.read_status")
        if read_status not in _READ_STATES:
            fail(
                "invalid_read_status", f"{path}.read_status", "Неверный статус чтения."
            )
        negative = row["negative_status"]
        if negative is not None:
            negative = require_string(negative, f"{path}.negative_status")
            if negative not in _NEGATIVE_STATES:
                fail(
                    "invalid_negative_status",
                    f"{path}.negative_status",
                    "Неверный статус отрицательного знания.",
                )
        planned = require_bool(row["planned"], f"{path}.planned")
        required = require_bool(row["required"], f"{path}.required")
        if not execution_ref and (
            candidate_count or acquired_count or read_status != "not_acquired"
        ):
            issues.append(f"outcome_without_execution:{cell_id}")
        if acquired_count > candidate_count:
            issues.append(f"acquired_exceeds_candidates:{cell_id}")
        if origin_count > acquired_count:
            issues.append(f"origins_exceed_acquired:{cell_id}")
        cells.append(
            {
                "cell_id": cell_id,
                "question_id": require_string(
                    row["question_id"], f"{path}.question_id"
                ),
                "source_family": require_string(
                    row["source_family"], f"{path}.source_family"
                ),
                "geography_language": require_string(
                    row["geography_language"], f"{path}.geography_language"
                ),
                "time_window": require_string(
                    row["time_window"], f"{path}.time_window"
                ),
                "evidence_type": require_string(
                    row["evidence_type"], f"{path}.evidence_type"
                ),
                "required": required,
                "planned": planned,
                "execution_receipt_ref": execution_ref,
                "candidate_count": candidate_count,
                "acquired_count": acquired_count,
                "read_status": read_status,
                "origin_verified_count": origin_count,
                "negative_status": negative,
            }
        )

    raw_entries = require_list(data["entries"], "request.entries")
    if len(raw_entries) > 10000:
        fail("size_limit", "request.entries", "Слишком много записей поиска.")
    entries: list[dict[str, Any]] = []
    entry_ids: set[str] = set()
    branch_iterations: dict[str, set[int]] = {}
    for index, raw in enumerate(raw_entries):
        path = f"request.entries[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, set(_ENTRY_SCHEMA["required"]), path)
        entry_id = require_string(row["entry_id"], f"{path}.entry_id")
        if entry_id in entry_ids:
            fail("duplicate_entry", f"{path}.entry_id", "Повторная запись поиска.")
        entry_ids.add(entry_id)
        branch_id = require_string(row["branch_id"], f"{path}.branch_id")
        iteration = require_int(row["iteration"], f"{path}.iteration", minimum=1)
        if iteration in branch_iterations.setdefault(branch_id, set()):
            fail(
                "duplicate_iteration", f"{path}.iteration", "Повторная итерация ветви."
            )
        branch_iterations[branch_id].add(iteration)
        decision = require_string(row["decision"], f"{path}.decision")
        if decision not in _DECISIONS:
            fail(
                "invalid_search_decision",
                f"{path}.decision",
                "Неверное решение поиска.",
            )
        entries.append(
            {
                "entry_id": entry_id,
                "branch_id": branch_id,
                "iteration": iteration,
                "occurred_at": require_string(
                    row["occurred_at"], f"{path}.occurred_at"
                ),
                "route_receipt_ref": require_string(
                    row["route_receipt_ref"], f"{path}.route_receipt_ref"
                ),
                "raw_response_ref": require_string(
                    row["raw_response_ref"], f"{path}.raw_response_ref"
                ),
                "raw_response_hash": _hash(
                    row["raw_response_hash"], f"{path}.raw_response_hash"
                ),
                "language": require_string(row["language"], f"{path}.language"),
                "geography": require_string(row["geography"], f"{path}.geography"),
                "time_window": require_string(
                    row["time_window"], f"{path}.time_window"
                ),
                "exact_query": require_string(
                    row["exact_query"], f"{path}.exact_query"
                ),
                "access_context": require_string(
                    row["access_context"], f"{path}.access_context"
                ),
                "ranking_limitations": _strings(
                    row["ranking_limitations"], f"{path}.ranking_limitations"
                ),
                "question_ids": _strings(row["question_ids"], f"{path}.question_ids"),
                "source_family": require_string(
                    row["source_family"], f"{path}.source_family"
                ),
                "purpose": require_string(row["purpose"], f"{path}.purpose"),
                "expected_signal": require_string(
                    row["expected_signal"], f"{path}.expected_signal"
                ),
                "candidate_refs": _strings(
                    row["candidate_refs"], f"{path}.candidate_refs"
                ),
                "origin_refs": _strings(row["origin_refs"], f"{path}.origin_refs"),
                "claim_refs": _strings(row["claim_refs"], f"{path}.claim_refs"),
                "factual_outcome": require_string(
                    row["factual_outcome"], f"{path}.factual_outcome"
                ),
                "decision": decision,
                "next_step": require_string(row["next_step"], f"{path}.next_step"),
            }
        )

    stalled: list[str] = []
    for branch_id in sorted(branch_iterations):
        branch = sorted(
            (entry for entry in entries if entry["branch_id"] == branch_id),
            key=lambda entry: entry["iteration"],
        )
        if len(branch) < 2:
            continue
        prior, current = branch[-2:]
        no_delta = set(current["origin_refs"]).issubset(prior["origin_refs"]) and set(
            current["claim_refs"]
        ).issubset(prior["claim_refs"])
        if no_delta:
            stalled.append(branch_id)
            if current["decision"] not in _STOP_DECISIONS:
                issues.append(f"stalled_branch_continues:{branch_id}")

    required_cells = [cell for cell in cells if cell["required"]]
    denominator = len(required_cells)
    counts = {
        "required": denominator,
        "planned": sum(cell["planned"] for cell in required_cells),
        "executed": sum(bool(cell["execution_receipt_ref"]) for cell in required_cells),
        "found": sum(cell["candidate_count"] > 0 for cell in required_cells),
        "acquired": sum(cell["acquired_count"] > 0 for cell in required_cells),
        "read_in_scope": sum(
            cell["read_status"] == "read_in_scope" for cell in required_cells
        ),
        "origin_verified": sum(
            cell["origin_verified_count"] > 0 for cell in required_cells
        ),
    }
    coverage_fraction = (
        counts["read_in_scope"] / denominator
        if denominator and universe != "unknown"
        else None
    )
    issues = sorted(set(issues))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "SearchLedgerAssessmentReceipt",
        "status": "assessed" if not issues else "blocked",
        "run_id": run_id,
        "coverage_frame_version": frame_version,
        "coverage_frame_hash": frame_hash,
        "universe_status": universe,
        "coverage_denominator": denominator,
        "coverage_fraction": coverage_fraction,
        "counts": counts,
        "entry_count": len(entries),
        "stalled_branches": stalled,
        "branches_allowed_to_continue": sorted(set(branch_iterations) - set(stalled)),
        "plan_counts_as_execution": False,
        "execution_counts_as_reading": False,
        "raw_responses_preserved_before_summarization": all(
            entry["raw_response_ref"] and entry["raw_response_hash"]
            for entry in entries
        ),
        "blocking_issues": issues,
    }
    return with_receipt_hash(payload)
