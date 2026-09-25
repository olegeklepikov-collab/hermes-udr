"""Deployment admission and conservative legacy migration contracts."""

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

RESOURCE_ADMISSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["run_ref", "resource_profile", "resource_probe"],
    "properties": {
        "run_ref": {"type": "string", "minLength": 1},
        "resource_profile": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "memory_reserve_bytes",
                "temp_reserve_bytes",
                "disk_reserve_bytes",
                "max_workers",
                "wall_time_seconds",
            ],
            "properties": {
                "memory_reserve_bytes": {"type": "integer", "minimum": 1},
                "temp_reserve_bytes": {"type": "integer", "minimum": 1},
                "disk_reserve_bytes": {"type": "integer", "minimum": 1},
                "max_workers": {"type": "integer", "minimum": 1},
                "wall_time_seconds": {"type": "integer", "minimum": 1},
            },
        },
        "resource_probe": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "memory_available_bytes",
                "temp_available_bytes",
                "disk_available_bytes",
            ],
            "properties": {
                "memory_available_bytes": {"type": "integer", "minimum": 0},
                "temp_available_bytes": {"type": "integer", "minimum": 0},
                "disk_available_bytes": {"type": "integer", "minimum": 0},
            },
        },
    },
}


MIGRATION_MAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["migration_ref", "legacy_objects", "rules"],
    "properties": {
        "migration_ref": {"type": "string", "minLength": 1},
        "legacy_objects": {"type": "array", "minItems": 1},
        "rules": {"type": "array"},
    },
}


_PROFILE_KEYS = {
    "memory_reserve_bytes",
    "temp_reserve_bytes",
    "disk_reserve_bytes",
    "max_workers",
    "wall_time_seconds",
}
_PROBE_KEYS = {
    "memory_available_bytes",
    "temp_available_bytes",
    "disk_available_bytes",
}
_LEGACY_KINDS = {
    "structural_pass",
    "partial_source",
    "resume_state",
    "scoped_review",
}
_ACTIONS = {"copy", "transform", "reference_only", "quarantine", "omit_with_reason"}


def assess_resource_admission(request: object) -> dict[str, object]:
    """Authorize bounded workers only after a complete, passing resource probe."""

    body = require_mapping(request, "request")
    require_exact_keys(
        body, {"run_ref", "resource_profile", "resource_probe"}, "request"
    )
    run_ref = require_string(body["run_ref"], "request.run_ref")
    profile = require_mapping(body["resource_profile"], "request.resource_profile")
    probe = require_mapping(body["resource_probe"], "request.resource_probe")

    missing_limits = sorted(_PROFILE_KEYS - set(profile))
    unknown_limits = sorted(set(profile) - _PROFILE_KEYS)
    missing_probe = sorted(_PROBE_KEYS - set(probe))
    unknown_probe = sorted(set(probe) - _PROBE_KEYS)
    if unknown_limits:
        fail(
            "unknown_field",
            f"request.resource_profile.{unknown_limits[0]}",
            "Неизвестный предел ресурса.",
        )
    if unknown_probe:
        fail(
            "unknown_field",
            f"request.resource_probe.{unknown_probe[0]}",
            "Неизвестное измерение ресурса.",
        )

    blockers: list[str] = []
    if missing_limits:
        blockers.extend(f"missing_resource_limit:{name}" for name in missing_limits)
    if missing_probe:
        blockers.extend(f"missing_resource_probe:{name}" for name in missing_probe)

    normalized_profile: dict[str, int] = {}
    normalized_probe: dict[str, int] = {}
    if not missing_limits:
        normalized_profile = {
            name: require_int(
                profile[name], f"request.resource_profile.{name}", minimum=1
            )
            for name in sorted(_PROFILE_KEYS)
        }
    if not missing_probe:
        normalized_probe = {
            name: require_int(probe[name], f"request.resource_probe.{name}")
            for name in sorted(_PROBE_KEYS)
        }

    if normalized_profile and normalized_probe:
        for resource in ("memory", "temp", "disk"):
            available = normalized_probe[f"{resource}_available_bytes"]
            reserve = normalized_profile[f"{resource}_reserve_bytes"]
            if available < reserve:
                blockers.append(f"insufficient_{resource}:{available}<{reserve}")

    allowed = not blockers
    receipt: dict[str, object] = {
        "contract": "ResourceAdmission",
        "run_ref": run_ref,
        "status": "resource_admission_allowed"
        if allowed
        else "resource_admission_denied",
        "workers_authorized": allowed,
        "worker_launch_count": 0,
        "max_workers": normalized_profile.get("max_workers") if allowed else 0,
        "wall_time_seconds": normalized_profile.get("wall_time_seconds")
        if allowed
        else 0,
        "resource_profile": normalized_profile,
        "resource_probe": normalized_probe,
        "blockers": blockers,
    }
    return with_receipt_hash(receipt)


def dry_run_migration_map(request: object) -> dict[str, object]:
    """Classify legacy objects without writing or strengthening evidence status."""

    body = require_mapping(request, "request")
    require_exact_keys(body, {"migration_ref", "legacy_objects", "rules"}, "request")
    migration_ref = require_string(body["migration_ref"], "request.migration_ref")
    rules = require_list(body["rules"], "request.rules")
    for index, value in enumerate(rules):
        rule = require_mapping(value, f"request.rules[{index}]")
        require_exact_keys(
            rule,
            {"legacy_kind", "target_status", "requires_evidence"},
            f"request.rules[{index}]",
        )
        kind = require_string(
            rule["legacy_kind"], f"request.rules[{index}].legacy_kind"
        )
        target = require_string(
            rule["target_status"], f"request.rules[{index}].target_status"
        )
        requires_evidence = rule["requires_evidence"]
        if type(requires_evidence) is not bool:
            fail(
                "invalid_type",
                f"request.rules[{index}].requires_evidence",
                "Ожидалось логическое значение.",
            )
        if (
            kind == "structural_pass"
            and target == "accepted_for_scope"
            and not requires_evidence
        ):
            fail(
                "status_promotion_without_evidence",
                f"request.rules[{index}]",
                "Старая метка pass не доказывает содержательную приемку.",
            )

    objects = require_list(body["legacy_objects"], "request.legacy_objects")
    mappings: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, value in enumerate(objects):
        path = f"request.legacy_objects[{index}]"
        row = require_mapping(value, path)
        require_exact_keys(
            row, {"object_ref", "legacy_kind", "legacy_status", "evidence_refs"}, path
        )
        object_ref = require_string(row["object_ref"], f"{path}.object_ref")
        if object_ref in seen:
            fail("duplicate_item", f"{path}.object_ref", "Повторный объект запрещен.")
        seen.add(object_ref)
        kind = require_string(row["legacy_kind"], f"{path}.legacy_kind")
        legacy_status = require_string(row["legacy_status"], f"{path}.legacy_status")
        evidence_refs = [
            require_string(item, f"{path}.evidence_refs[{offset}]")
            for offset, item in enumerate(
                require_list(row["evidence_refs"], f"{path}.evidence_refs")
            )
        ]
        if kind not in _LEGACY_KINDS:
            fail(
                "unknown_legacy_kind",
                f"{path}.legacy_kind",
                "Неизвестный тип старого объекта.",
            )

        if kind == "structural_pass":
            action, target_status, reason = (
                "reference_only",
                "review_required",
                "structural_pass_has_no_scope_evidence",
            )
        elif kind == "partial_source":
            action, target_status, reason = (
                "transform",
                "partial",
                "partial_status_preserved",
            )
        elif kind == "resume_state":
            action, target_status, reason = (
                "quarantine",
                "review_required",
                "resume_receipts_missing",
            )
        else:
            if evidence_refs:
                action, target_status, reason = (
                    "copy",
                    "accepted_for_scope",
                    "scoped_review_evidence_preserved",
                )
            else:
                action, target_status, reason = (
                    "quarantine",
                    "review_required",
                    "scoped_review_evidence_missing",
                )
        if action not in _ACTIONS:
            raise AssertionError("unreachable migration action")
        mappings.append(
            {
                "object_ref": object_ref,
                "legacy_kind": kind,
                "legacy_status": legacy_status,
                "action": action,
                "target_status": target_status,
                "evidence_refs": evidence_refs,
                "reason": reason,
            }
        )

    receipt: dict[str, object] = {
        "contract": "MigrationMapDryRun",
        "migration_ref": migration_ref,
        "status": "dry_run_valid",
        "write_applied": False,
        "commit_available": False,
        "object_count": len(mappings),
        "mappings": mappings,
    }
    return with_receipt_hash(receipt)
