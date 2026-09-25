"""Search coverage, source-family, origin, and monoculture contracts."""

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
_NULLABLE_TEXT = {"type": ["string", "null"]}

SEARCH_COVERAGE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "frame_version", "cells", "waves", "entries"],
    "properties": {
        "schema_version": {"const": 1},
        "frame_version": {"type": "integer", "minimum": 1},
        "cells": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "cell_id",
                    "question_ref",
                    "family",
                    "language",
                    "geography",
                    "period",
                    "evidence_type",
                    "required",
                    "query_family_ref",
                    "gap_reason",
                ],
                "properties": {
                    "cell_id": _TEXT,
                    "question_ref": _TEXT,
                    "family": _TEXT,
                    "language": _TEXT,
                    "geography": _TEXT,
                    "period": _TEXT,
                    "evidence_type": _TEXT,
                    "required": {"type": "boolean"},
                    "query_family_ref": _NULLABLE_TEXT,
                    "gap_reason": _NULLABLE_TEXT,
                },
            },
        },
        "waves": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["wave", "status", "rationale"],
                "properties": {
                    "wave": {"enum": ["exploratory", "targeted", "contradictory"]},
                    "status": {"enum": ["completed", "not_applicable", "skipped"]},
                    "rationale": _NULLABLE_TEXT,
                },
            },
        },
        "entries": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "entry_id",
                    "environment",
                    "exact_query",
                    "method",
                    "result_ref",
                    "decision",
                    "continuation",
                ],
                "properties": {
                    "entry_id": _TEXT,
                    "environment": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "platform",
                            "index",
                            "access_context",
                            "language",
                            "geography",
                            "time_window",
                        ],
                        "properties": {
                            "platform": _TEXT,
                            "index": _TEXT,
                            "access_context": _TEXT,
                            "language": _TEXT,
                            "geography": _TEXT,
                            "time_window": _TEXT,
                        },
                    },
                    "exact_query": _TEXT,
                    "method": _TEXT,
                    "result_ref": _TEXT,
                    "decision": _TEXT,
                    "continuation": _TEXT,
                },
            },
        },
    },
}

SOURCE_POOL_AUDIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "pool_id",
        "candidates",
        "density_policy",
        "replacement_families",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "pool_id": _TEXT,
        "candidates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_ref",
                    "family",
                    "source_class",
                    "availability",
                    "role",
                    "decision",
                    "limitation",
                    "replacement_requirement",
                    "origin_cluster",
                    "quality_score",
                    "substantive_support_requested",
                    "provider_incentive",
                ],
                "properties": {
                    "candidate_ref": _TEXT,
                    "family": _TEXT,
                    "source_class": _TEXT,
                    "availability": {"enum": ["full_text", "metadata_only", "blocked"]},
                    "role": {
                        "enum": [
                            "primary_support",
                            "secondary_support",
                            "context",
                            "discovery",
                            "challenge",
                            "excluded",
                        ]
                    },
                    "decision": {
                        "enum": [
                            "include",
                            "context_only",
                            "exclude",
                            "replacement_required",
                        ]
                    },
                    "limitation": _NULLABLE_TEXT,
                    "replacement_requirement": _NULLABLE_TEXT,
                    "origin_cluster": _TEXT,
                    "quality_score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "substantive_support_requested": {"type": "boolean"},
                    "provider_incentive": _TEXT,
                },
            },
        },
        "density_policy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["low_max", "high_min", "policy_ref"],
            "properties": {
                "low_max": {"type": "integer", "minimum": 0},
                "high_min": {"type": "integer", "minimum": 1},
                "policy_ref": _TEXT,
            },
        },
        "replacement_families": {
            "type": "array",
            "maxItems": 100,
            "uniqueItems": True,
            "items": _TEXT,
        },
    },
}


def _schema(request: object, required: set[str]) -> dict[str, object]:
    data = require_mapping(request, "request")
    require_exact_keys(data, required, "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    return data


def _optional_text(value: object, path: str) -> str | None:
    if value is None:
        return None
    return require_string(value, path)


def _unique_texts(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_value", path, "Повтор значения запрещён.")
    return result


def assess_search_coverage(request: object) -> dict[str, Any]:
    data = _schema(request, set(SEARCH_COVERAGE_ASSESS_SCHEMA["required"]))
    frame_version = require_int(
        data["frame_version"], "request.frame_version", minimum=1
    )
    issues: list[str] = []
    cells: list[dict[str, Any]] = []
    cell_ids: set[str] = set()
    for index, raw in enumerate(require_list(data["cells"], "request.cells")):
        path = f"request.cells[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "cell_id",
                "question_ref",
                "family",
                "language",
                "geography",
                "period",
                "evidence_type",
                "required",
                "query_family_ref",
                "gap_reason",
            },
            path,
        )
        cell_id = require_string(row["cell_id"], f"{path}.cell_id")
        if cell_id in cell_ids:
            fail("duplicate_cell", f"{path}.cell_id", "Повтор ячейки запрещён.")
        cell_ids.add(cell_id)
        query_family = _optional_text(
            row["query_family_ref"], f"{path}.query_family_ref"
        )
        gap_reason = _optional_text(row["gap_reason"], f"{path}.gap_reason")
        required = require_bool(row["required"], f"{path}.required")
        if required and query_family is None and gap_reason is None:
            issues.append(f"required_cell_unplanned:{cell_id}")
        cells.append(
            {
                "cell_id": cell_id,
                "question_ref": require_string(
                    row["question_ref"], f"{path}.question_ref"
                ),
                "family": require_string(row["family"], f"{path}.family"),
                "language": require_string(row["language"], f"{path}.language"),
                "geography": require_string(row["geography"], f"{path}.geography"),
                "period": require_string(row["period"], f"{path}.period"),
                "evidence_type": require_string(
                    row["evidence_type"], f"{path}.evidence_type"
                ),
                "required": required,
                "query_family_ref": query_family,
                "gap_reason": gap_reason,
            }
        )
    if not cells:
        fail("empty_coverage_frame", "request.cells", "Карта покрытия пуста.")

    wave_status: dict[str, str] = {}
    wave_records: list[dict[str, str | None]] = []
    for index, raw in enumerate(require_list(data["waves"], "request.waves")):
        path = f"request.waves[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"wave", "status", "rationale"}, path)
        wave = require_string(row["wave"], f"{path}.wave")
        status = require_string(row["status"], f"{path}.status")
        rationale = _optional_text(row["rationale"], f"{path}.rationale")
        if wave not in {"exploratory", "targeted", "contradictory"}:
            fail("invalid_wave", f"{path}.wave", "Неизвестная волна.")
        if wave in wave_status:
            fail("duplicate_wave", f"{path}.wave", "Повтор волны запрещён.")
        if status not in {"completed", "not_applicable", "skipped"}:
            fail("invalid_wave_status", f"{path}.status", "Неизвестный статус.")
        wave_status[wave] = status
        if status == "skipped":
            issues.append(f"wave_skipped:{wave}")
        if status == "not_applicable" and rationale is None:
            issues.append(f"wave_rationale_missing:{wave}")
        wave_records.append({"wave": wave, "status": status, "rationale": rationale})
    for missing in sorted(
        {"exploratory", "targeted", "contradictory"} - set(wave_status)
    ):
        issues.append(f"wave_missing:{missing}")

    entries: list[dict[str, Any]] = []
    entry_ids: set[str] = set()
    for index, raw in enumerate(require_list(data["entries"], "request.entries")):
        path = f"request.entries[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "entry_id",
                "environment",
                "exact_query",
                "method",
                "result_ref",
                "decision",
                "continuation",
            },
            path,
        )
        entry_id = require_string(row["entry_id"], f"{path}.entry_id")
        if entry_id in entry_ids:
            fail("duplicate_entry", f"{path}.entry_id", "Повтор записи запрещён.")
        entry_ids.add(entry_id)
        environment = require_mapping(row["environment"], f"{path}.environment")
        require_exact_keys(
            environment,
            {
                "platform",
                "index",
                "access_context",
                "language",
                "geography",
                "time_window",
            },
            f"{path}.environment",
        )
        normalized_environment = {
            key: require_string(environment[key], f"{path}.environment.{key}")
            for key in (
                "platform",
                "index",
                "access_context",
                "language",
                "geography",
                "time_window",
            )
        }
        entries.append(
            {
                "entry_id": entry_id,
                "environment": normalized_environment,
                "environment_hash": sha256_json(normalized_environment),
                "exact_query": require_string(
                    row["exact_query"], f"{path}.exact_query"
                ),
                "method": require_string(row["method"], f"{path}.method"),
                "result_ref": require_string(row["result_ref"], f"{path}.result_ref"),
                "decision": require_string(row["decision"], f"{path}.decision"),
                "continuation": require_string(
                    row["continuation"], f"{path}.continuation"
                ),
            }
        )
    payload = {
        "schema_version": 1,
        "contract": "SearchCoverageDecisionReceipt",
        "status": "coverage_ready" if not issues else "blocked",
        "frame_version": frame_version,
        "cells": cells,
        "wave_records": sorted(wave_records, key=lambda item: str(item["wave"])),
        "entries": entries,
        "cell_count": len(cells),
        "entry_count": len(entries),
        "environment_variants_preserved": len(
            {entry["environment_hash"] for entry in entries}
        ),
        "closure_allowed": not issues,
        "search_performed": False,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def audit_source_pool(request: object) -> dict[str, Any]:
    data = _schema(request, set(SOURCE_POOL_AUDIT_SCHEMA["required"]))
    pool_id = require_string(data["pool_id"], "request.pool_id")
    policy = require_mapping(data["density_policy"], "request.density_policy")
    require_exact_keys(
        policy, {"low_max", "high_min", "policy_ref"}, "request.density_policy"
    )
    low_max = require_int(policy["low_max"], "request.density_policy.low_max")
    high_min = require_int(
        policy["high_min"], "request.density_policy.high_min", minimum=1
    )
    policy_ref = require_string(
        policy["policy_ref"], "request.density_policy.policy_ref"
    )
    if low_max >= high_min:
        fail(
            "invalid_density_policy",
            "request.density_policy",
            "low_max должен быть меньше high_min.",
        )
    replacement_families = _unique_texts(
        data["replacement_families"], "request.replacement_families"
    )
    assessments: list[dict[str, Any]] = []
    seen: set[str] = set()
    support_origins: set[str] = set()
    support_families: set[str] = set()
    support_incentives: set[str] = set()
    issues: list[str] = []
    for index, raw in enumerate(require_list(data["candidates"], "request.candidates")):
        path = f"request.candidates[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "candidate_ref",
                "family",
                "source_class",
                "availability",
                "role",
                "decision",
                "limitation",
                "replacement_requirement",
                "origin_cluster",
                "quality_score",
                "substantive_support_requested",
                "provider_incentive",
            },
            path,
        )
        candidate_ref = require_string(row["candidate_ref"], f"{path}.candidate_ref")
        if candidate_ref in seen:
            fail(
                "duplicate_candidate",
                f"{path}.candidate_ref",
                "Повтор кандидата запрещён.",
            )
        seen.add(candidate_ref)
        family = require_string(row["family"], f"{path}.family")
        source_class = require_string(row["source_class"], f"{path}.source_class")
        availability = require_string(row["availability"], f"{path}.availability")
        if availability not in {"full_text", "metadata_only", "blocked"}:
            fail(
                "invalid_availability",
                f"{path}.availability",
                "Неизвестная доступность.",
            )
        role = require_string(row["role"], f"{path}.role")
        if role not in {
            "primary_support",
            "secondary_support",
            "context",
            "discovery",
            "challenge",
            "excluded",
        }:
            fail("invalid_source_role", f"{path}.role", "Неизвестная роль.")
        decision = require_string(row["decision"], f"{path}.decision")
        if decision not in {
            "include",
            "context_only",
            "exclude",
            "replacement_required",
        }:
            fail("invalid_source_decision", f"{path}.decision", "Неизвестное решение.")
        limitation = _optional_text(row["limitation"], f"{path}.limitation")
        replacement = _optional_text(
            row["replacement_requirement"], f"{path}.replacement_requirement"
        )
        origin = require_string(row["origin_cluster"], f"{path}.origin_cluster")
        quality = require_int(row["quality_score"], f"{path}.quality_score")
        if quality > 100:
            fail("invalid_quality", f"{path}.quality_score", "Оценка выше 100.")
        substantive = require_bool(
            row["substantive_support_requested"],
            f"{path}.substantive_support_requested",
        )
        incentive = require_string(
            row["provider_incentive"], f"{path}.provider_incentive"
        )
        content_support_allowed = availability == "full_text" and role in {
            "primary_support",
            "secondary_support",
            "challenge",
        }
        effective_decision = decision
        candidate_issues: list[str] = []
        if substantive and not content_support_allowed:
            candidate_issues.append("content_unavailable_for_substantive_support")
            effective_decision = "replacement_required"
        if effective_decision == "replacement_required" and replacement is None:
            candidate_issues.append("replacement_requirement_missing")
        if (
            effective_decision in {"context_only", "replacement_required"}
            and limitation is None
        ):
            candidate_issues.append("limitation_missing")
        if candidate_issues:
            issues.extend(f"{candidate_ref}:{item}" for item in candidate_issues)
        if content_support_allowed and effective_decision == "include":
            support_origins.add(origin)
            support_families.add(family)
            support_incentives.add(incentive)
        assessments.append(
            {
                "candidate_ref": candidate_ref,
                "family": family,
                "source_class": source_class,
                "availability": availability,
                "role": role,
                "declared_decision": decision,
                "effective_decision": effective_decision,
                "limitation": limitation,
                "replacement_requirement": replacement,
                "origin_cluster": origin,
                "quality_score": quality,
                "content_support_allowed": content_support_allowed,
                "issues": sorted(candidate_issues),
            }
        )
    count = len(assessments)
    if not count:
        fail("empty_source_pool", "request.candidates", "Пул источников пуст.")
    density = "low" if count <= low_max else ("high" if count >= high_min else "medium")
    monoculture = bool(support_origins) and (
        len(support_families) == 1 or len(support_incentives) == 1
    )
    if monoculture and not replacement_families:
        issues.append("monoculture_replacement_missing")
    status = "blocked" if issues else ("limited" if monoculture else "audited")
    payload = {
        "schema_version": 1,
        "contract": "SourcePoolAuditReceipt",
        "status": status,
        "pool_id": pool_id,
        "candidate_count": count,
        "density": density,
        "density_policy_ref": policy_ref,
        "density_raises_quality": False,
        "candidate_assessments": assessments,
        "independent_origin_count": len(support_origins),
        "support_families": sorted(support_families),
        "source_monoculture": monoculture,
        "conclusion_limited": monoculture,
        "replacement_requirements": [
            f"family:{family}" for family in replacement_families
        ]
        if monoculture
        else [],
        "evidence_status_changed": False,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)
