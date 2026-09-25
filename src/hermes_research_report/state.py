"""Pure cross-store work-state reconciliation."""

from __future__ import annotations

from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_exact_keys,
    require_int,
    require_mapping,
    require_string,
)

_BEAD = {"open", "claimed", "closed"}
_LEASE = {"absent", "active", "stale"}
_ARTIFACT = {"absent", "draft", "submitted", "accepted"}
_REVIEW = {"absent", "review_required", "changes_required", "accepted"}
_OUTBOX = {"empty", "pending", "done", "failed"}


def _enum(value: object, path: str, allowed: set[str]) -> str:
    text = require_string(value, path)
    if text not in allowed:
        fail("invalid_status", path, f"Недопустимый статус: {text}.")
    return text


def reconcile_state(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "work_id",
            "bead_status",
            "lease_status",
            "artifact_status",
            "review_status",
            "dolt_commit_ref",
            "outbox_status",
            "writer_count",
            "expected_revision",
            "current_revision",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    work_id = require_string(data["work_id"], "request.work_id")
    bead = _enum(data["bead_status"], "request.bead_status", _BEAD)
    lease = _enum(data["lease_status"], "request.lease_status", _LEASE)
    artifact = _enum(data["artifact_status"], "request.artifact_status", _ARTIFACT)
    review = _enum(data["review_status"], "request.review_status", _REVIEW)
    outbox = _enum(data["outbox_status"], "request.outbox_status", _OUTBOX)
    writer_count = require_int(data["writer_count"], "request.writer_count")
    expected_revision = require_int(
        data["expected_revision"], "request.expected_revision", minimum=1
    )
    current_revision = require_int(
        data["current_revision"], "request.current_revision", minimum=1
    )
    commit_ref = data["dolt_commit_ref"]
    if commit_ref is not None:
        commit_ref = require_string(commit_ref, "request.dolt_commit_ref")

    issues: list[str] = []
    if writer_count != 1:
        issues.append("authority_writer_conflict")
    if expected_revision != current_revision:
        issues.append("stale_revision")
    if bead == "closed" and lease == "active":
        issues.append("inconsistent_lease")
    if bead == "open" and artifact == "accepted":
        issues.append("accepted_artifact_with_open_work")
    if review == "accepted" and artifact != "accepted":
        issues.append("accepted_review_without_accepted_artifact")
    if artifact == "accepted" and not commit_ref:
        issues.append("dolt_commit_missing")
    if artifact == "accepted" and outbox != "done":
        issues.append("outbox_unreconciled")

    if issues:
        state = (
            "stale_revision" if issues == ["stale_revision"] else "inconsistent_state"
        )
    elif (
        bead == "open"
        and lease == "absent"
        and artifact == "absent"
        and review == "absent"
    ):
        state = "planned_ready"
    elif (
        bead == "claimed"
        and lease == "active"
        and artifact in {"absent", "draft"}
        and review == "absent"
    ):
        state = "running"
    elif (
        bead == "claimed"
        and lease == "stale"
        and artifact in {"absent", "draft"}
        and review == "absent"
    ):
        state = "stale_pending_reconciliation"
    elif (
        bead == "closed"
        and lease == "absent"
        and artifact == "draft"
        and review == "absent"
    ):
        state = "execution_succeeded_result_draft"
    elif (
        bead == "closed"
        and lease == "absent"
        and artifact == "submitted"
        and review == "review_required"
    ):
        state = "review_required"
    elif (
        bead == "closed"
        and lease == "absent"
        and artifact == "submitted"
        and review == "changes_required"
    ):
        state = "repair_required"
    elif (
        bead == "closed"
        and lease == "absent"
        and artifact == "accepted"
        and review == "accepted"
    ):
        state = "accepted_for_scope"
    else:
        state = "inconsistent_state"
        issues.append("unsupported_state_combination")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "CrossStoreReconciliationReceipt",
        "status": "reconciled" if not issues else "blocked",
        "work_id": work_id,
        "computed_state": state,
        "release_allowed": state == "accepted_for_scope" and not issues,
        "issues": sorted(set(issues)),
    }
    return with_receipt_hash(payload)
