"""Detailed search coverage semantics for language, identity, origin, and gaps."""

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
_NULL_TEXT = {"type": ["string", "null"]}

SEARCH_COVERAGE_DETAILS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "coverage_ref",
        "language_cells",
        "sources",
        "metrics",
        "negative_results",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "coverage_ref": _TEXT,
        "language_cells": {"type": "array", "items": {"type": "object"}},
        "sources": {"type": "array", "items": {"type": "object"}},
        "metrics": {"type": "object"},
        "negative_results": {"type": "array", "items": {"type": "object"}},
    },
}

_LANGUAGE_KEYS = {
    "cell_id",
    "required_language",
    "query_family_ref",
    "query_language",
    "reading_language",
    "gap_reason",
}
_SOURCE_KEYS = {
    "observation_id",
    "source_id",
    "raw_identifier",
    "normalized_identifier",
    "title",
    "discovery_ref",
    "origin_group",
    "origin_verified",
}
_METRIC_KEYS = {
    "reference_universe_known",
    "reference_total",
    "reference_included_ids",
    "reference_ref",
    "frame_numerator",
    "frame_denominator",
}
_NEGATIVE_KEYS = {
    "cell_id",
    "transport_status",
    "classified_as",
    "excluded_as_irrelevant",
    "access_request_target",
}


def _nullable(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def _strings(value: object, path: str) -> list[str]:
    rows = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(rows) != len(set(rows)):
        fail("duplicate_item", path, "Повтор элемента запрещён.")
    return rows


def _fraction(numerator: int, denominator: int, path: str) -> float:
    if denominator <= 0 or numerator > denominator:
        fail("invalid_fraction", path, "Недопустимый числитель или знаменатель.")
    value = numerator / denominator
    if not math.isfinite(value):
        fail("invalid_fraction", path, "Метрика не является конечной.")
    return value


def assess_search_coverage_details(request: object) -> dict[str, Any]:
    """Assess detailed coverage claims without promoting evidence status."""

    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "coverage_ref",
            "language_cells",
            "sources",
            "metrics",
            "negative_results",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    coverage_ref = require_string(data["coverage_ref"], "request.coverage_ref")
    issues: list[str] = []

    language_rows: list[dict[str, object]] = []
    language_ids: set[str] = set()
    for index, raw in enumerate(
        require_list(data["language_cells"], "request.language_cells")
    ):
        path = f"request.language_cells[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, _LANGUAGE_KEYS, path)
        cell_id = require_string(row["cell_id"], f"{path}.cell_id")
        if cell_id in language_ids:
            fail("duplicate_cell", f"{path}.cell_id", "Повтор языковой ячейки.")
        language_ids.add(cell_id)
        required_language = require_string(
            row["required_language"], f"{path}.required_language"
        )
        query_family_ref = _nullable(
            row["query_family_ref"], f"{path}.query_family_ref"
        )
        query_language = _nullable(row["query_language"], f"{path}.query_language")
        reading_language = require_string(
            row["reading_language"], f"{path}.reading_language"
        )
        gap_reason = _nullable(row["gap_reason"], f"{path}.gap_reason")
        matched = query_family_ref is not None and query_language == required_language
        if not matched and gap_reason is None:
            issues.append(f"required_language_unplanned:{cell_id}")
        status = "planned" if matched else "language_gap" if gap_reason else "invalid"
        language_rows.append(
            {
                "cell_id": cell_id,
                "required_language": required_language,
                "query_family_ref": query_family_ref,
                "query_language": query_language,
                "reading_language": reading_language,
                "gap_reason": gap_reason,
                "status": status,
                "reading_language_is_separate": reading_language != query_language,
            }
        )

    sources: list[dict[str, object]] = []
    observation_ids: set[str] = set()
    identity_groups: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(require_list(data["sources"], "request.sources")):
        path = f"request.sources[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, _SOURCE_KEYS, path)
        observation_id = require_string(row["observation_id"], f"{path}.observation_id")
        if observation_id in observation_ids:
            fail(
                "duplicate_observation", f"{path}.observation_id", "Повтор наблюдения."
            )
        observation_ids.add(observation_id)
        source_id = require_string(row["source_id"], f"{path}.source_id")
        raw_identifier = require_string(row["raw_identifier"], f"{path}.raw_identifier")
        normalized = _nullable(
            row["normalized_identifier"], f"{path}.normalized_identifier"
        )
        title = require_string(row["title"], f"{path}.title")
        discovery_ref = require_string(row["discovery_ref"], f"{path}.discovery_ref")
        origin_group = _nullable(row["origin_group"], f"{path}.origin_group")
        origin_verified = require_bool(
            row["origin_verified"], f"{path}.origin_verified"
        )
        identity_key = (
            f"normalized:{normalized}" if normalized else f"source:{source_id}"
        )
        group = identity_groups.setdefault(
            identity_key,
            {
                "canonical_source_id": source_id,
                "normalized_identifier": normalized,
                "title": title,
                "source_ids": [],
                "discovery_refs": [],
                "raw_identifiers": [],
                "invalid_identifier_preserved": normalized is None,
            },
        )
        group["source_ids"].append(source_id)  # type: ignore[union-attr]
        group["discovery_refs"].append(discovery_ref)  # type: ignore[union-attr]
        group["raw_identifiers"].append(raw_identifier)  # type: ignore[union-attr]
        sources.append(
            {
                "observation_id": observation_id,
                "source_id": source_id,
                "identity_key": identity_key,
                "title": title,
                "origin_group": origin_group,
                "origin_verified": origin_verified,
            }
        )
    canonical_sources = []
    for identity_key, group in sorted(identity_groups.items()):
        group["identity_key"] = identity_key
        group["source_ids"] = sorted(set(group["source_ids"]))  # type: ignore[arg-type]
        group["discovery_refs"] = sorted(set(group["discovery_refs"]))  # type: ignore[arg-type]
        group["raw_identifiers"] = list(group["raw_identifiers"])  # type: ignore[arg-type]
        canonical_sources.append(group)

    verified_origin_groups = sorted(
        {
            str(row["origin_group"])
            for row in sources
            if row["origin_verified"] and row["origin_group"] is not None
        }
    )
    unknown_origin_source_ids = sorted(
        str(row["source_id"])
        for row in sources
        if not row["origin_verified"] or row["origin_group"] is None
    )

    metrics = require_mapping(data["metrics"], "request.metrics")
    require_exact_keys(metrics, _METRIC_KEYS, "request.metrics")
    reference_known = require_bool(
        metrics["reference_universe_known"], "request.metrics.reference_universe_known"
    )
    reference_total = require_int(
        metrics["reference_total"], "request.metrics.reference_total"
    )
    reference_ids = _strings(
        metrics["reference_included_ids"], "request.metrics.reference_included_ids"
    )
    reference_ref = _nullable(metrics["reference_ref"], "request.metrics.reference_ref")
    recall = None
    if reference_known:
        if reference_ref is None:
            issues.append("reference_ref_missing")
        elif reference_total <= 0:
            issues.append("reference_universe_empty")
        elif len(reference_ids) > reference_total:
            issues.append("reference_numerator_exceeds_denominator")
        else:
            recall = len(reference_ids) / reference_total
    frame_numerator = require_int(
        metrics["frame_numerator"], "request.metrics.frame_numerator"
    )
    frame_denominator = require_int(
        metrics["frame_denominator"], "request.metrics.frame_denominator", minimum=1
    )
    frame_fraction = _fraction(
        frame_numerator, frame_denominator, "request.metrics.frame_fraction"
    )

    negative_rows: list[dict[str, object]] = []
    access_gaps: list[str] = []
    for index, raw in enumerate(
        require_list(data["negative_results"], "request.negative_results")
    ):
        path = f"request.negative_results[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, _NEGATIVE_KEYS, path)
        cell_id = require_string(row["cell_id"], f"{path}.cell_id")
        transport = require_string(row["transport_status"], f"{path}.transport_status")
        classified = _nullable(row["classified_as"], f"{path}.classified_as")
        excluded = require_bool(
            row["excluded_as_irrelevant"], f"{path}.excluded_as_irrelevant"
        )
        target = _nullable(
            row["access_request_target"], f"{path}.access_request_target"
        )
        expected = {
            "empty": "empty_confirmed",
            "access_denied": "access_denied",
            "server_error": None,
        }.get(transport)
        if transport not in {"empty", "access_denied", "server_error"}:
            fail(
                "invalid_transport_status",
                f"{path}.transport_status",
                "Неизвестный статус.",
            )
        if classified != expected:
            issues.append(f"negative_classification_invalid:{cell_id}")
        if transport == "access_denied":
            access_gaps.append(cell_id)
            if excluded:
                issues.append(f"access_not_relevance:{cell_id}")
            if target is None:
                issues.append(f"access_owner_missing:{cell_id}")
        negative_rows.append(
            {
                "cell_id": cell_id,
                "transport_status": transport,
                "classified_as": classified,
                "excluded_as_irrelevant": excluded,
                "access_request_target": target,
                "read_status": "not_acquired" if transport == "access_denied" else None,
            }
        )

    accepted = not issues
    return with_receipt_hash(
        {
            "contract": "SearchCoverageDetailsReceipt",
            "status": "accepted" if accepted else "repair_required",
            "coverage_ref": coverage_ref,
            "language_cells": language_rows,
            "canonical_sources": canonical_sources,
            "source_count": len(canonical_sources),
            "verified_origin_groups": verified_origin_groups,
            "established_origin_group_count": len(verified_origin_groups),
            "unknown_origin_source_ids": unknown_origin_source_ids,
            "metrics": {
                "reference_recall": recall,
                "reference_numerator": len(reference_ids) if reference_known else None,
                "reference_denominator": reference_total if reference_known else None,
                "reference_ref": reference_ref,
                "frame_coverage": frame_fraction,
                "frame_numerator": frame_numerator,
                "frame_denominator": frame_denominator,
                "metric_names_distinct": True,
            },
            "negative_results": negative_rows,
            "access_gap_cell_ids": sorted(access_gaps),
            "search_completeness_inferred_from_negative_results": False,
            "evidence_status_changed": False,
            "issues": sorted(set(issues)),
        }
    )
