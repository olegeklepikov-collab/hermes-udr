"""Academic design labeling, publication integrity, and reproduction scope."""

from __future__ import annotations

from datetime import datetime
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
_CONTROL_TYPES = {"design_label", "integrity_update", "reproduction_scope"}

ACADEMIC_INTEGRITY_ASSESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "control_type", "payload"],
    "properties": {
        "schema_version": {"const": 1},
        "control_type": {"enum": sorted(_CONTROL_TYPES)},
        "payload": {"type": "object"},
    },
}


def _nullable(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повтор элемента запрещён.")
    return result


def _time(value: object, path: str) -> datetime:
    text = require_string(value, path)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        fail("invalid_time", path, "Ожидалось время ISO-8601.")


def _design(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {"profile_depth", "declared_design", "completed_obligations", "limitations"},
        "request.payload",
    )
    profile_depth = require_string(
        payload["profile_depth"], "request.payload.profile_depth"
    )
    declared = require_string(
        payload["declared_design"], "request.payload.declared_design"
    )
    completed = set(
        _strings(
            payload["completed_obligations"], "request.payload.completed_obligations"
        )
    )
    limitations = _strings(payload["limitations"], "request.payload.limitations")
    systematic_required = {
        "protocol_frozen",
        "dual_independent_screening",
        "risk_of_bias",
        "reproducible_search",
    }
    missing = sorted(systematic_required - completed)
    issues = []
    if declared == "systematic" and missing:
        issues.append("design_obligations_missing")
    effective = declared if declared != "systematic" or not missing else "narrative"
    if effective == "narrative" and not limitations:
        issues.append("design_limitations_missing")
    return {
        "profile_depth": profile_depth,
        "declared_design": declared,
        "effective_design": effective,
        "missing_systematic_obligations": missing,
        "limitations": limitations,
        "issues": issues,
    }


def _integrity(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {"checked_at", "current_at", "max_age_days", "publisher_available", "works"},
        "request.payload",
    )
    checked = _time(payload["checked_at"], "request.payload.checked_at")
    current = _time(payload["current_at"], "request.payload.current_at")
    max_age = require_int(
        payload["max_age_days"], "request.payload.max_age_days", minimum=1
    )
    publisher_available = require_bool(
        payload["publisher_available"], "request.payload.publisher_available"
    )
    issues = []
    if (current - checked).total_seconds() > max_age * 86400:
        issues.append("stale_integrity_check")
    if not publisher_available:
        issues.append("unknown_integrity")
    works = []
    excluded = []
    review_descendants = set()
    for index, raw in enumerate(
        require_list(payload["works"], "request.payload.works")
    ):
        path = f"request.payload.works[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "work_id",
                "status",
                "prior_version_ref",
                "new_version_ref",
                "descendant_refs",
            },
            path,
        )
        work_id = require_string(row["work_id"], f"{path}.work_id")
        status = require_string(row["status"], f"{path}.status")
        if status not in {"active", "corrected", "retracted"}:
            fail("invalid_integrity_status", f"{path}.status", "Неизвестный статус.")
        prior = require_string(row["prior_version_ref"], f"{path}.prior_version_ref")
        new = _nullable(row["new_version_ref"], f"{path}.new_version_ref")
        descendants = _strings(row["descendant_refs"], f"{path}.descendant_refs")
        if status == "corrected" and new is None:
            issues.append(f"correction_version_missing:{work_id}")
        if status in {"corrected", "retracted"}:
            review_descendants.update(descendants)
        if status == "retracted":
            excluded.append(work_id)
        works.append(
            {
                "work_id": work_id,
                "status": status,
                "prior_version_ref": prior,
                "new_version_ref": new,
                "history_preserved": True,
            }
        )
    return {
        "integrity_status": "clean" if not issues else "review_required",
        "works": works,
        "excluded_from_positive_synthesis": sorted(excluded),
        "descendant_review_refs": sorted(review_descendants),
        "issues": issues,
    }


def _reproduction(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {
            "raw_data_access",
            "published_estimates_available",
            "requested_scope",
            "computation_receipt_ref",
            "raw_data_downloaded",
            "code_link",
        },
        "request.payload",
    )
    raw_access = require_string(
        payload["raw_data_access"], "request.payload.raw_data_access"
    )
    if raw_access not in {"open", "restricted", "unavailable"}:
        fail("invalid_access", "request.payload.raw_data_access", "Неизвестный доступ.")
    published = require_bool(
        payload["published_estimates_available"],
        "request.payload.published_estimates_available",
    )
    requested = require_string(
        payload["requested_scope"], "request.payload.requested_scope"
    )
    receipt = _nullable(
        payload["computation_receipt_ref"], "request.payload.computation_receipt_ref"
    )
    raw_downloaded = require_bool(
        payload["raw_data_downloaded"], "request.payload.raw_data_downloaded"
    )
    code_link = require_string(payload["code_link"], "request.payload.code_link")
    limited_available = published and receipt is not None
    issues = []
    if requested == "recompute_published_estimate":
        if not limited_available:
            issues.append("computation_receipt_missing")
    elif requested == "reproduce_from_raw_data":
        if raw_access != "open" or not raw_downloaded or receipt is None:
            issues.append("reproduction_scope_overclaim")
    else:
        fail(
            "invalid_reproduction_scope",
            "request.payload.requested_scope",
            "Неизвестный уровень.",
        )
    if raw_access != "open" and raw_downloaded:
        issues.append("restricted_data_download_claim_invalid")
    effective = (
        "reproduce_from_raw_data"
        if requested == "reproduce_from_raw_data" and not issues
        else "recompute_published_estimate"
        if limited_available
        else "code_and_metadata_only"
    )
    return {
        "requested_scope": requested,
        "effective_scope": effective,
        "raw_data_access": raw_access,
        "raw_data_downloaded": raw_downloaded,
        "published_estimates_available": published,
        "computation_receipt_ref": receipt,
        "code_link": code_link,
        "limited_recomputation_preserved": limited_available,
        "issues": issues,
    }


_ASSESSORS = {
    "design_label": _design,
    "integrity_update": _integrity,
    "reproduction_scope": _reproduction,
}


def assess_academic_integrity(request: object) -> dict[str, Any]:
    """Assess one academic integrity control without changing source records."""

    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "control_type", "payload"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    control_type = require_string(data["control_type"], "request.control_type")
    if control_type not in _ASSESSORS:
        fail("invalid_control_type", "request.control_type", "Неизвестный контроль.")
    result = _ASSESSORS[control_type](
        require_mapping(data["payload"], "request.payload")
    )
    issues = _strings(result.get("issues", []), "result.issues")
    return with_receipt_hash(
        {
            "contract": "AcademicIntegrityReceipt",
            "control_type": control_type,
            "status": "accepted" if not issues else "review_required",
            **result,
        }
    )
