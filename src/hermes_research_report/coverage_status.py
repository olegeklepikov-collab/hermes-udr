"""Versioned coverage denominator and mutually exclusive status inventory."""

from __future__ import annotations

from collections import Counter
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
_STATUSES = {"completed", "partial", "unavailable", "excluded", "unknown"}

COVERAGE_STATUS_ASSESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "frame_ref",
        "frame_revision",
        "prior_frame_revision",
        "denominator",
        "cells",
        "comparable_claim_requested",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "frame_ref": _TEXT,
        "frame_revision": {"type": "integer", "minimum": 1},
        "prior_frame_revision": {"type": ["integer", "null"], "minimum": 1},
        "denominator": {"type": "integer", "minimum": 1},
        "cells": {"type": "array", "items": {"type": "object"}},
        "comparable_claim_requested": {"type": "boolean"},
    },
}


def assess_coverage_status(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "frame_ref",
            "frame_revision",
            "prior_frame_revision",
            "denominator",
            "cells",
            "comparable_claim_requested",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    frame_ref = require_string(data["frame_ref"], "request.frame_ref")
    revision = require_int(data["frame_revision"], "request.frame_revision", minimum=1)
    prior_raw = data["prior_frame_revision"]
    prior = (
        None
        if prior_raw is None
        else require_int(prior_raw, "request.prior_frame_revision", minimum=1)
    )
    denominator = require_int(data["denominator"], "request.denominator", minimum=1)
    comparable_requested = require_bool(
        data["comparable_claim_requested"], "request.comparable_claim_requested"
    )
    cells = []
    cell_ids = set()
    counts: Counter[str] = Counter()
    for index, raw in enumerate(require_list(data["cells"], "request.cells")):
        path = f"request.cells[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"cell_ref", "status", "reason"}, path)
        cell_ref = require_string(row["cell_ref"], f"{path}.cell_ref")
        if cell_ref in cell_ids:
            fail("duplicate_cell", f"{path}.cell_ref", "Повтор ячейки запрещён.")
        cell_ids.add(cell_ref)
        status = require_string(row["status"], f"{path}.status")
        if status not in _STATUSES:
            fail("invalid_coverage_status", f"{path}.status", "Неизвестный статус.")
        reason = require_string(row["reason"], f"{path}.reason")
        counts[status] += 1
        cells.append({"cell_ref": cell_ref, "status": status, "reason": reason})
    issues = []
    if len(cells) != denominator:
        issues.append("coverage_denominator_mismatch")
    frame_changed = prior is not None and prior != revision
    if frame_changed and comparable_requested:
        issues.append("frame_revision_changed")
    return with_receipt_hash(
        {
            "contract": "CoverageStatusReceipt",
            "status": "accepted" if not issues else "not_comparable",
            "frame_ref": frame_ref,
            "frame_revision": revision,
            "prior_frame_revision": prior,
            "denominator": denominator,
            "counts": {status: counts.get(status, 0) for status in sorted(_STATUSES)},
            "cells": cells,
            "frame_changed": frame_changed,
            "comparable": not frame_changed and not issues,
            "issues": issues,
        }
    )
