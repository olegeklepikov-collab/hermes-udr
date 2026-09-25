"""CAS/idempotency, recovery, portable import, and conservative migration gates."""

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

_HASH = re.compile(r"^[0-9a-f]{64}$")
_TEXT = {"type": "string", "minLength": 1}
_ARR = {"type": "array", "maxItems": 10000, "uniqueItems": True, "items": _TEXT}

OPERATION_RECONCILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "operation_id",
        "idempotency_key",
        "request_hash",
        "writer_count",
        "expected_revision",
        "current_revision",
        "attempt",
        "retry_limit",
        "error_class",
        "idempotent",
        "side_effect_state",
        "provider_reconciled",
        "prior_records",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "operation_id": _TEXT,
        "idempotency_key": _TEXT,
        "request_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "writer_count": {"type": "integer", "minimum": 0},
        "expected_revision": {"type": "integer", "minimum": 1},
        "current_revision": {"type": "integer", "minimum": 1},
        "attempt": {"type": "integer", "minimum": 1},
        "retry_limit": {"type": "integer", "minimum": 1},
        "error_class": {"enum": ["none", "transient", "permanent"]},
        "idempotent": {"type": "boolean"},
        "side_effect_state": {
            "enum": ["not_sent", "sent", "confirmed", "failed", "unknown_outcome"]
        },
        "provider_reconciled": {"type": "boolean"},
        "prior_records": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["idempotency_key", "request_hash", "state"],
                "properties": {
                    "idempotency_key": _TEXT,
                    "request_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "state": {"enum": ["confirmed", "failed", "unknown_outcome"]},
                },
            },
        },
    },
}

RECOVERY_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "journal_valid",
        "checkpoint_claims_success",
        "last_confirmed_sequence",
        "events",
        "derived_indexes",
        "context_refs",
        "tombstones",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "journal_valid": {"type": "boolean"},
        "checkpoint_claims_success": {"type": "boolean"},
        "last_confirmed_sequence": {"type": "integer", "minimum": 0},
        "events": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sequence", "state", "accepted_effect"],
                "properties": {
                    "sequence": {"type": "integer", "minimum": 1},
                    "state": {
                        "enum": [
                            "prepared",
                            "sent",
                            "confirmed",
                            "failed",
                            "unknown_outcome",
                        ]
                    },
                    "accepted_effect": {"type": "boolean"},
                },
            },
        },
        "derived_indexes": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index_id", "source_sequence", "rebuild_verified"],
                "properties": {
                    "index_id": _TEXT,
                    "source_sequence": {"type": "integer", "minimum": 0},
                    "rebuild_verified": {"type": "boolean"},
                },
            },
        },
        "context_refs": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "object_ref",
                    "project_id",
                    "target_project_id",
                    "current",
                    "authorized",
                    "provenance_ref",
                ],
                "properties": {
                    "object_ref": _TEXT,
                    "project_id": _TEXT,
                    "target_project_id": _TEXT,
                    "current": {"type": "boolean"},
                    "authorized": {"type": "boolean"},
                    "provenance_ref": _TEXT,
                },
            },
        },
        "tombstones": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["object_ref", "active_views_returning"],
                "properties": {
                    "object_ref": _TEXT,
                    "active_views_returning": {"type": "integer", "minimum": 0},
                },
            },
        },
    },
}

BUNDLE_IMPORT_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "bundle_id",
        "manifest_hash",
        "objects",
        "target_inventory",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "bundle_id": _TEXT,
        "manifest_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "objects": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "revision",
                    "content_hash",
                    "relative_path",
                    "contains_secret",
                ],
                "properties": {
                    "id": _TEXT,
                    "revision": {"type": "integer", "minimum": 1},
                    "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "relative_path": _TEXT,
                    "contains_secret": {"type": "boolean"},
                },
            },
        },
        "target_inventory": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "revision", "content_hash"],
                "properties": {
                    "id": _TEXT,
                    "revision": {"type": "integer", "minimum": 1},
                    "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
            },
        },
    },
}

LEGACY_MIGRATION_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "records"],
    "properties": {
        "schema_version": {"const": 1},
        "records": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "record_id",
                    "legacy_status",
                    "format_supported",
                    "contains_secret",
                    "content_hash",
                ],
                "properties": {
                    "record_id": _TEXT,
                    "legacy_status": _TEXT,
                    "format_supported": {"type": "boolean"},
                    "contains_secret": {"type": "boolean"},
                    "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
            },
        },
    },
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH.fullmatch(text):
        fail("invalid_hash", path, "Неверный SHA-256.")
    return text


def reconcile_operation(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(OPERATION_RECONCILE_SCHEMA["required"]), "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    operation_id = require_string(data["operation_id"], "request.operation_id")
    key = require_string(data["idempotency_key"], "request.idempotency_key")
    request_hash = _hash(data["request_hash"], "request.request_hash")
    writer_count = require_int(data["writer_count"], "request.writer_count")
    expected = require_int(
        data["expected_revision"], "request.expected_revision", minimum=1
    )
    current = require_int(
        data["current_revision"], "request.current_revision", minimum=1
    )
    attempt = require_int(data["attempt"], "request.attempt", minimum=1)
    limit = require_int(data["retry_limit"], "request.retry_limit", minimum=1)
    idempotent = require_bool(data["idempotent"], "request.idempotent")
    reconciled = require_bool(
        data["provider_reconciled"], "request.provider_reconciled"
    )
    error_class = require_string(data["error_class"], "request.error_class")
    state = require_string(data["side_effect_state"], "request.side_effect_state")
    if error_class not in {"none", "transient", "permanent"} or state not in {
        "not_sent",
        "sent",
        "confirmed",
        "failed",
        "unknown_outcome",
    }:
        fail("invalid_operation_state", "request", "Неверное состояние операции.")
    prior_rows = require_list(data["prior_records"], "request.prior_records")
    duplicate_confirmed = False
    issues: list[str] = []
    for index, raw in enumerate(prior_rows):
        path = f"request.prior_records[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"idempotency_key", "request_hash", "state"}, path)
        prior_key = require_string(row["idempotency_key"], f"{path}.idempotency_key")
        prior_hash = _hash(row["request_hash"], f"{path}.request_hash")
        prior_state = require_string(row["state"], f"{path}.state")
        if prior_key == key and prior_hash != request_hash:
            issues.append("idempotency_key_hash_conflict")
        if (
            prior_key == key
            and prior_hash == request_hash
            and prior_state == "confirmed"
        ):
            duplicate_confirmed = True
    if writer_count != 1:
        issues.append("writer_count_not_one")
    if expected != current:
        issues.append("stale_revision")
    if state == "unknown_outcome" and not reconciled:
        issues.append("provider_reconciliation_required")
    retry_allowed = (
        not issues
        and not duplicate_confirmed
        and error_class == "transient"
        and idempotent
        and attempt < limit
        and state in {"not_sent", "failed"}
    )
    payload = {
        "schema_version": 1,
        "contract": "OperationReconciliationReceipt",
        "status": "no_op_confirmed"
        if duplicate_confirmed and not issues
        else (
            "retry_allowed" if retry_allowed else ("ready" if not issues else "blocked")
        ),
        "operation_id": operation_id,
        "expected_revision": expected,
        "current_revision": current,
        "duplicate_confirmed": duplicate_confirmed,
        "retry_allowed": retry_allowed,
        "next_attempt": attempt + 1 if retry_allowed else None,
        "external_effect_performed": False,
        "persistence_applied": False,
        "issues": sorted(set(issues)),
    }
    return with_receipt_hash(payload)


def assess_recovery(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(RECOVERY_ASSESS_SCHEMA["required"]), "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    journal = require_bool(data["journal_valid"], "request.journal_valid")
    checkpoint = require_bool(
        data["checkpoint_claims_success"], "request.checkpoint_claims_success"
    )
    last = require_int(
        data["last_confirmed_sequence"], "request.last_confirmed_sequence"
    )
    issues = []
    reconcile = []
    repeated = []
    if not journal:
        issues.append("authoritative_journal_invalid")
    for index, raw in enumerate(require_list(data["events"], "request.events")):
        path = f"request.events[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"sequence", "state", "accepted_effect"}, path)
        seq = require_int(row["sequence"], f"{path}.sequence", minimum=1)
        state = require_string(row["state"], f"{path}.state")
        accepted = require_bool(row["accepted_effect"], f"{path}.accepted_effect")
        if state in {"sent", "unknown_outcome"}:
            reconcile.append(seq)
        if state == "confirmed" or accepted:
            repeated.append(seq)
    for index, raw in enumerate(
        require_list(data["derived_indexes"], "request.derived_indexes")
    ):
        path = f"request.derived_indexes[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"index_id", "source_sequence", "rebuild_verified"}, path
        )
        idx = require_string(row["index_id"], f"{path}.index_id")
        seq = require_int(row["source_sequence"], f"{path}.source_sequence")
        verified = require_bool(row["rebuild_verified"], f"{path}.rebuild_verified")
        if seq != last or not verified:
            issues.append(f"derived_index_not_rebuilt:{idx}")
    excluded = []
    for index, raw in enumerate(
        require_list(data["context_refs"], "request.context_refs")
    ):
        path = f"request.context_refs[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "object_ref",
                "project_id",
                "target_project_id",
                "current",
                "authorized",
                "provenance_ref",
            },
            path,
        )
        ref = require_string(row["object_ref"], f"{path}.object_ref")
        require_string(row["provenance_ref"], f"{path}.provenance_ref")
        if (
            row["project_id"] != row["target_project_id"]
            or not require_bool(row["current"], f"{path}.current")
            or not require_bool(row["authorized"], f"{path}.authorized")
        ):
            excluded.append(ref)
    for index, raw in enumerate(require_list(data["tombstones"], "request.tombstones")):
        path = f"request.tombstones[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"object_ref", "active_views_returning"}, path)
        ref = require_string(row["object_ref"], f"{path}.object_ref")
        count = require_int(
            row["active_views_returning"], f"{path}.active_views_returning"
        )
        if count:
            issues.append(f"tombstone_violation:{ref}")
    if checkpoint and not journal:
        issues.append("checkpoint_not_authority")
    payload = {
        "schema_version": 1,
        "contract": "RecoveryDecisionReceipt",
        "status": "resumable" if not issues else "blocked",
        "run_id": run_id,
        "resume_from_sequence": last,
        "sequences_requiring_provider_reconciliation": sorted(reconcile),
        "sequences_forbidden_to_repeat": sorted(set(repeated)),
        "excluded_context_refs": sorted(excluded),
        "checkpoint_accepted_as_authority": False,
        "derived_rebuild_required": True,
        "persistence_applied": False,
        "issues": sorted(set(issues)),
    }
    return with_receipt_hash(payload)


def assess_bundle_import(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(BUNDLE_IMPORT_ASSESS_SCHEMA["required"]), "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    bundle_id = require_string(data["bundle_id"], "request.bundle_id")
    manifest_hash = _hash(data["manifest_hash"], "request.manifest_hash")
    target = {}
    for index, raw in enumerate(
        require_list(data["target_inventory"], "request.target_inventory")
    ):
        path = f"request.target_inventory[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"id", "revision", "content_hash"}, path)
        key = (
            require_string(row["id"], f"{path}.id"),
            require_int(row["revision"], f"{path}.revision", minimum=1),
        )
        target[key] = _hash(row["content_hash"], f"{path}.content_hash")
    new = []
    skips = []
    conflicts = []
    issues = []
    for index, raw in enumerate(require_list(data["objects"], "request.objects")):
        path = f"request.objects[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {"id", "revision", "content_hash", "relative_path", "contains_secret"},
            path,
        )
        oid = require_string(row["id"], f"{path}.id")
        rev = require_int(row["revision"], f"{path}.revision", minimum=1)
        digest = _hash(row["content_hash"], f"{path}.content_hash")
        rel = require_string(row["relative_path"], f"{path}.relative_path")
        if rel.startswith("/") or ".." in rel.split("/"):
            issues.append(f"nonportable_path:{oid}")
        if require_bool(row["contains_secret"], f"{path}.contains_secret"):
            issues.append(f"secret_in_bundle:{oid}")
        key = (oid, rev)
        if key not in target:
            new.append(f"{oid}@{rev}")
        elif target[key] == digest:
            skips.append(f"{oid}@{rev}")
        else:
            conflicts.append(f"{oid}@{rev}")
    if conflicts:
        issues.append("content_conflict_atomic_abort")
    issues = sorted(set(issues))
    payload = {
        "schema_version": 1,
        "contract": "BundleImportDecisionReceipt",
        "status": "import_plan_ready" if not issues else "blocked",
        "bundle_id": bundle_id,
        "manifest_hash": manifest_hash,
        "new_objects": sorted(new),
        "idempotent_skips": sorted(skips),
        "conflicts": sorted(conflicts),
        "commit_allowed": not issues,
        "partial_writes_allowed": False,
        "persistence_applied": False,
        "issues": issues,
    }
    return with_receipt_hash(payload)


def assess_legacy_migration(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "records"}, "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    decisions = []
    for index, raw in enumerate(require_list(data["records"], "request.records")):
        path = f"request.records[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "record_id",
                "legacy_status",
                "format_supported",
                "contains_secret",
                "content_hash",
            },
            path,
        )
        rid = require_string(row["record_id"], f"{path}.record_id")
        status = require_string(row["legacy_status"], f"{path}.legacy_status")
        _hash(row["content_hash"], f"{path}.content_hash")
        supported = require_bool(row["format_supported"], f"{path}.format_supported")
        secret = require_bool(row["contains_secret"], f"{path}.contains_secret")
        if secret:
            action = "omit_with_reason"
            new_status = None
            reason = "secret"
        elif not supported:
            action = "quarantine"
            new_status = None
            reason = "unsupported_format"
        else:
            action = "transform"
            new_status = (
                "review_required"
                if status in {"pass", "approved", "complete"}
                else "partial"
            )
            reason = "legacy_status_not_evidence"
        decisions.append(
            {
                "record_id": rid,
                "action": action,
                "new_status": new_status,
                "reason": reason,
            }
        )
    payload = {
        "schema_version": 1,
        "contract": "LegacyMigrationDecisionReceipt",
        "status": "dry_run",
        "decisions": decisions,
        "maximum_migrated_status": "review_required",
        "commit_allowed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)
