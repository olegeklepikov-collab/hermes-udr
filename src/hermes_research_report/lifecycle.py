"""Invalidation, object revision, context isolation, and restore contracts."""

from __future__ import annotations

import re
from collections import deque
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
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

INVALIDATION_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "changed_ref",
        "dependency_edges",
        "active_acceptances",
        "retention_reviews",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "changed_ref": {
            "type": "object",
            "additionalProperties": False,
            "required": ["object_ref", "prior_version", "current_version"],
            "properties": {
                "object_ref": _TEXT,
                "prior_version": _TEXT,
                "current_version": _TEXT,
            },
        },
        "dependency_edges": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["input_ref", "dependent_ref"],
                "properties": {"input_ref": _TEXT, "dependent_ref": _TEXT},
            },
        },
        "active_acceptances": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["object_ref", "acceptance_ref"],
                "properties": {"object_ref": _TEXT, "acceptance_ref": _TEXT},
            },
        },
        "retention_reviews": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "object_ref",
                    "changed_ref",
                    "reviewer_id",
                    "independent",
                    "conclusion_unchanged",
                    "rationale",
                    "reviewed_current_version",
                ],
                "properties": {
                    "object_ref": _TEXT,
                    "changed_ref": _TEXT,
                    "reviewer_id": _TEXT,
                    "independent": {"type": "boolean"},
                    "conclusion_unchanged": {"type": "boolean"},
                    "rationale": _TEXT,
                    "reviewed_current_version": _TEXT,
                },
            },
        },
    },
}

OBJECT_REVISION_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "object_ref",
        "owner_id",
        "actor_id",
        "writer_count",
        "expected_revision",
        "current_revision",
        "current_content_hash",
        "proposed_content_hash",
        "last_journal_sequence",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "object_ref": _TEXT,
        "owner_id": _TEXT,
        "actor_id": _TEXT,
        "writer_count": {"type": "integer", "minimum": 0},
        "expected_revision": {"type": "integer", "minimum": 1},
        "current_revision": {"type": "integer", "minimum": 1},
        "current_content_hash": _HASH,
        "proposed_content_hash": _HASH,
        "last_journal_sequence": {"type": "integer", "minimum": 0},
    },
}

CONTEXT_ASSEMBLY_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "target_project_id", "candidates"],
    "properties": {
        "schema_version": {"const": 1},
        "target_project_id": _TEXT,
        "candidates": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "object_ref",
                    "project_id",
                    "current",
                    "authorized",
                    "provenance_ref",
                    "content_hash",
                ],
                "properties": {
                    "object_ref": _TEXT,
                    "project_id": _TEXT,
                    "current": {"type": "boolean"},
                    "authorized": {"type": "boolean"},
                    "provenance_ref": {"type": ["string", "null"]},
                    "content_hash": _HASH,
                },
            },
        },
    },
}

RESTORE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "snapshot",
        "target_empty",
        "restored",
        "continuation",
        "derived_views",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "snapshot": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "snapshot_ref",
                "consistent",
                "sequence",
                "authority_inventory_hash",
                "object_refs",
                "tombstones",
            ],
            "properties": {
                "snapshot_ref": _TEXT,
                "consistent": {"type": "boolean"},
                "sequence": {"type": "integer", "minimum": 0},
                "authority_inventory_hash": _HASH,
                "object_refs": {
                    "type": "array",
                    "maxItems": 10000,
                    "uniqueItems": True,
                    "items": _TEXT,
                },
                "tombstones": {
                    "type": "array",
                    "maxItems": 10000,
                    "uniqueItems": True,
                    "items": _TEXT,
                },
            },
        },
        "target_empty": {"type": "boolean"},
        "restored": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "sequence",
                "authority_inventory_hash",
                "object_refs",
                "tombstones",
            ],
            "properties": {
                "sequence": {"type": "integer", "minimum": 0},
                "authority_inventory_hash": _HASH,
                "object_refs": {
                    "type": "array",
                    "maxItems": 10000,
                    "uniqueItems": True,
                    "items": _TEXT,
                },
                "tombstones": {
                    "type": "array",
                    "maxItems": 10000,
                    "uniqueItems": True,
                    "items": _TEXT,
                },
            },
        },
        "continuation": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "expected_next_sequence",
                "actual_next_sequence",
                "operation_ready",
            ],
            "properties": {
                "expected_next_sequence": {"type": "integer", "minimum": 1},
                "actual_next_sequence": {"type": "integer", "minimum": 1},
                "operation_ready": {"type": "boolean"},
            },
        },
        "derived_views": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["view_id", "returned_object_refs"],
                "properties": {
                    "view_id": _TEXT,
                    "returned_object_refs": {
                        "type": "array",
                        "maxItems": 10000,
                        "uniqueItems": True,
                        "items": _TEXT,
                    },
                },
            },
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


def _hash(value: object, path: str) -> str:
    result = require_string(value, path)
    if not _HASH_PATTERN.fullmatch(result):
        fail("invalid_hash", path, "Неверный SHA-256.")
    return result


def _unique_strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_reference", path, "Повтор ссылки запрещён.")
    return result


def assess_invalidation(request: object) -> dict[str, Any]:
    data = _schema(request, set(INVALIDATION_ASSESS_SCHEMA["required"]))
    changed = require_mapping(data["changed_ref"], "request.changed_ref")
    require_exact_keys(
        changed,
        {"object_ref", "prior_version", "current_version"},
        "request.changed_ref",
    )
    changed_ref = require_string(
        changed["object_ref"], "request.changed_ref.object_ref"
    )
    prior_version = require_string(
        changed["prior_version"], "request.changed_ref.prior_version"
    )
    current_version = require_string(
        changed["current_version"], "request.changed_ref.current_version"
    )
    if prior_version == current_version:
        fail(
            "version_unchanged",
            "request.changed_ref.current_version",
            "Для инвалидизации требуется новая версия.",
        )

    adjacency: dict[str, set[str]] = {}
    edge_keys: set[tuple[str, str]] = set()
    for index, raw in enumerate(
        require_list(data["dependency_edges"], "request.dependency_edges")
    ):
        path = f"request.dependency_edges[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"input_ref", "dependent_ref"}, path)
        source = require_string(row["input_ref"], f"{path}.input_ref")
        dependent = require_string(row["dependent_ref"], f"{path}.dependent_ref")
        edge = (source, dependent)
        if edge in edge_keys:
            fail("duplicate_dependency", path, "Повтор зависимости запрещён.")
        edge_keys.add(edge)
        adjacency.setdefault(source, set()).add(dependent)

    acceptance_by_object: dict[str, str] = {}
    for index, raw in enumerate(
        require_list(data["active_acceptances"], "request.active_acceptances")
    ):
        path = f"request.active_acceptances[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"object_ref", "acceptance_ref"}, path)
        object_ref = require_string(row["object_ref"], f"{path}.object_ref")
        acceptance_ref = require_string(row["acceptance_ref"], f"{path}.acceptance_ref")
        if object_ref in acceptance_by_object:
            fail("duplicate_acceptance", path, "Повтор активной приёмки запрещён.")
        acceptance_by_object[object_ref] = acceptance_ref

    affected: set[str] = set()
    pending = deque([changed_ref])
    while pending:
        source = pending.popleft()
        for dependent in sorted(adjacency.get(source, set())):
            if dependent not in affected:
                affected.add(dependent)
                pending.append(dependent)

    retained: dict[str, dict[str, object]] = {}
    review_issues: list[str] = []
    for index, raw in enumerate(
        require_list(data["retention_reviews"], "request.retention_reviews")
    ):
        path = f"request.retention_reviews[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "object_ref",
                "changed_ref",
                "reviewer_id",
                "independent",
                "conclusion_unchanged",
                "rationale",
                "reviewed_current_version",
            },
            path,
        )
        object_ref = require_string(row["object_ref"], f"{path}.object_ref")
        reviewed_change = require_string(row["changed_ref"], f"{path}.changed_ref")
        reviewer_id = require_string(row["reviewer_id"], f"{path}.reviewer_id")
        independent = require_bool(row["independent"], f"{path}.independent")
        unchanged = require_bool(
            row["conclusion_unchanged"], f"{path}.conclusion_unchanged"
        )
        rationale = require_string(row["rationale"], f"{path}.rationale")
        reviewed_version = require_string(
            row["reviewed_current_version"], f"{path}.reviewed_current_version"
        )
        valid = (
            object_ref in affected
            and object_ref in acceptance_by_object
            and reviewed_change == changed_ref
            and independent
            and unchanged
            and reviewed_version == current_version
            and object_ref not in retained
        )
        if not valid:
            review_issues.append(f"retention_review_invalid:{object_ref}")
        else:
            retained[object_ref] = {
                "object_ref": object_ref,
                "acceptance_ref": acceptance_by_object[object_ref],
                "changed_ref": changed_ref,
                "reviewer_id": reviewer_id,
                "rationale": rationale,
                "reviewed_current_version": reviewed_version,
            }

    affected_acceptances = set(affected) & set(acceptance_by_object)
    invalidated = sorted(affected_acceptances - set(retained))
    unaffected = sorted(set(acceptance_by_object) - affected_acceptances)
    payload = {
        "schema_version": 1,
        "contract": "InvalidationDecisionReceipt",
        "status": "blocked" if review_issues else "invalidation_plan_ready",
        "changed_ref": changed_ref,
        "prior_version": prior_version,
        "current_version": current_version,
        "invalidated_refs": invalidated,
        "invalidated_acceptance_refs": [
            acceptance_by_object[object_ref] for object_ref in invalidated
        ],
        "retained_refs": sorted(retained),
        "retention_receipts": [retained[key] for key in sorted(retained)],
        "unaffected_refs": unaffected,
        "repair_packet_refs": [f"repair:{object_ref}" for object_ref in invalidated],
        "history_rewritten": False,
        "late_scope_override_allowed": False,
        "persistence_applied": False,
        "issues": sorted(review_issues),
    }
    return with_receipt_hash(payload)


def assess_object_revision(request: object) -> dict[str, Any]:
    data = _schema(request, set(OBJECT_REVISION_ASSESS_SCHEMA["required"]))
    object_ref = require_string(data["object_ref"], "request.object_ref")
    owner_id = require_string(data["owner_id"], "request.owner_id")
    actor_id = require_string(data["actor_id"], "request.actor_id")
    writer_count = require_int(data["writer_count"], "request.writer_count")
    expected = require_int(
        data["expected_revision"], "request.expected_revision", minimum=1
    )
    current = require_int(
        data["current_revision"], "request.current_revision", minimum=1
    )
    current_hash = _hash(data["current_content_hash"], "request.current_content_hash")
    proposed_hash = _hash(
        data["proposed_content_hash"], "request.proposed_content_hash"
    )
    last_sequence = require_int(
        data["last_journal_sequence"], "request.last_journal_sequence"
    )
    issues: list[str] = []
    if writer_count != 1:
        issues.append("writer_count_not_one")
    if actor_id != owner_id:
        issues.append("actor_not_owner")
    if expected != current:
        issues.append("stale_revision")
    if current_hash == proposed_hash:
        issues.append("content_unchanged")
    allowed = not issues
    proposed_revision = current + 1 if allowed else None
    journal_entry = (
        {
            "sequence": last_sequence + 1,
            "object_ref": object_ref,
            "from_revision": current,
            "to_revision": proposed_revision,
            "prior_content_hash": current_hash,
            "proposed_content_hash": proposed_hash,
            "actor_id": actor_id,
        }
        if allowed
        else None
    )
    payload = {
        "schema_version": 1,
        "contract": "ObjectRevisionDecisionReceipt",
        "status": "revision_proposed" if allowed else "blocked",
        "object_ref": object_ref,
        "expected_revision": expected,
        "current_revision": current,
        "proposed_revision": proposed_revision,
        "journal_entry": journal_entry,
        "authoritative_state_changed": False,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def assess_context_assembly(request: object) -> dict[str, Any]:
    data = _schema(request, set(CONTEXT_ASSEMBLY_ASSESS_SCHEMA["required"]))
    target_project = require_string(
        data["target_project_id"], "request.target_project_id"
    )
    included: list[str] = []
    excluded: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(require_list(data["candidates"], "request.candidates")):
        path = f"request.candidates[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "object_ref",
                "project_id",
                "current",
                "authorized",
                "provenance_ref",
                "content_hash",
            },
            path,
        )
        object_ref = require_string(row["object_ref"], f"{path}.object_ref")
        if object_ref in seen:
            fail(
                "duplicate_reference", f"{path}.object_ref", "Повтор объекта запрещён."
            )
        seen.add(object_ref)
        project_id = require_string(row["project_id"], f"{path}.project_id")
        current = require_bool(row["current"], f"{path}.current")
        authorized = require_bool(row["authorized"], f"{path}.authorized")
        provenance = row["provenance_ref"]
        if provenance is not None:
            provenance = require_string(provenance, f"{path}.provenance_ref")
        _hash(row["content_hash"], f"{path}.content_hash")
        reasons: list[str] = []
        if project_id != target_project:
            reasons.append("cross_project_scope")
        if not current:
            reasons.append("stale_reference")
        if not authorized:
            reasons.append("access_not_authorized")
        if provenance is None:
            reasons.append("provenance_missing")
        if reasons:
            decision = {"object_ref": object_ref, "reasons": sorted(reasons)}
            excluded.append(decision)
            events.append(
                {
                    "object_ref": object_ref,
                    "decision": "excluded",
                    "reasons": sorted(reasons),
                    "content_recorded": False,
                }
            )
        else:
            included.append(object_ref)
    payload = {
        "schema_version": 1,
        "contract": "ContextAssemblyDecisionReceipt",
        "status": "context_ready",
        "target_project_id": target_project,
        "included_refs": sorted(included),
        "excluded": sorted(excluded, key=lambda item: str(item["object_ref"])),
        "decision_events": sorted(events, key=lambda item: str(item["object_ref"])),
        "identifier_grants_access": False,
        "content_recorded_in_exclusion_events": False,
        "context_persisted": False,
        "issues": [],
    }
    return with_receipt_hash(payload)


def assess_restore(request: object) -> dict[str, Any]:
    data = _schema(request, set(RESTORE_ASSESS_SCHEMA["required"]))
    snapshot = require_mapping(data["snapshot"], "request.snapshot")
    require_exact_keys(
        snapshot,
        {
            "snapshot_ref",
            "consistent",
            "sequence",
            "authority_inventory_hash",
            "object_refs",
            "tombstones",
        },
        "request.snapshot",
    )
    snapshot_ref = require_string(
        snapshot["snapshot_ref"], "request.snapshot.snapshot_ref"
    )
    consistent = require_bool(snapshot["consistent"], "request.snapshot.consistent")
    snapshot_sequence = require_int(snapshot["sequence"], "request.snapshot.sequence")
    snapshot_hash = _hash(
        snapshot["authority_inventory_hash"],
        "request.snapshot.authority_inventory_hash",
    )
    snapshot_objects = _unique_strings(
        snapshot["object_refs"], "request.snapshot.object_refs"
    )
    snapshot_tombstones = _unique_strings(
        snapshot["tombstones"], "request.snapshot.tombstones"
    )
    target_empty = require_bool(data["target_empty"], "request.target_empty")

    restored = require_mapping(data["restored"], "request.restored")
    require_exact_keys(
        restored,
        {"sequence", "authority_inventory_hash", "object_refs", "tombstones"},
        "request.restored",
    )
    restored_sequence = require_int(restored["sequence"], "request.restored.sequence")
    restored_hash = _hash(
        restored["authority_inventory_hash"],
        "request.restored.authority_inventory_hash",
    )
    restored_objects = _unique_strings(
        restored["object_refs"], "request.restored.object_refs"
    )
    restored_tombstones = _unique_strings(
        restored["tombstones"], "request.restored.tombstones"
    )

    continuation = require_mapping(data["continuation"], "request.continuation")
    require_exact_keys(
        continuation,
        {"expected_next_sequence", "actual_next_sequence", "operation_ready"},
        "request.continuation",
    )
    expected_next = require_int(
        continuation["expected_next_sequence"],
        "request.continuation.expected_next_sequence",
        minimum=1,
    )
    actual_next = require_int(
        continuation["actual_next_sequence"],
        "request.continuation.actual_next_sequence",
        minimum=1,
    )
    operation_ready = require_bool(
        continuation["operation_ready"], "request.continuation.operation_ready"
    )

    issues: list[str] = []
    if not consistent:
        issues.append("snapshot_not_consistent")
    if not target_empty:
        issues.append("target_not_empty")
    if restored_sequence != snapshot_sequence:
        issues.append("restore_sequence_mismatch")
    if restored_hash != snapshot_hash:
        issues.append("authority_inventory_hash_mismatch")
    if set(restored_objects) != set(snapshot_objects):
        issues.append("authoritative_object_set_mismatch")
    if set(restored_tombstones) != set(snapshot_tombstones):
        issues.append("tombstone_set_mismatch")
    if expected_next != snapshot_sequence + 1 or actual_next != expected_next:
        issues.append("continuation_sequence_mismatch")
    if not operation_ready:
        issues.append("continuation_not_ready")

    returned_tombstones: set[str] = set()
    for index, raw in enumerate(
        require_list(data["derived_views"], "request.derived_views")
    ):
        path = f"request.derived_views[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"view_id", "returned_object_refs"}, path)
        view_id = require_string(row["view_id"], f"{path}.view_id")
        returned = _unique_strings(
            row["returned_object_refs"], f"{path}.returned_object_refs"
        )
        leaked = set(returned) & set(snapshot_tombstones)
        if leaked:
            returned_tombstones.update(leaked)
            issues.append(f"tombstone_returned:{view_id}")

    authoritative_complete = (
        restored_sequence == snapshot_sequence
        and restored_hash == snapshot_hash
        and set(restored_objects) == set(snapshot_objects)
        and set(restored_tombstones) == set(snapshot_tombstones)
    )
    continuation_verified = (
        expected_next == snapshot_sequence + 1
        and actual_next == expected_next
        and operation_ready
    )
    payload = {
        "schema_version": 1,
        "contract": "RestoreDecisionReceipt",
        "status": "restore_verified" if not issues else "blocked",
        "snapshot_ref": snapshot_ref,
        "restored_sequence": restored_sequence,
        "authoritative_set_complete": authoritative_complete,
        "continuation_verified": continuation_verified,
        "tombstones_enforced": not returned_tombstones,
        "returned_tombstone_refs": sorted(returned_tombstones),
        "production_restore_performed": False,
        "persistence_applied": False,
        "issues": sorted(set(issues)),
    }
    return with_receipt_hash(payload)
