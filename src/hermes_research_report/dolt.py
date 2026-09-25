"""Dolt logical-transaction and history-receipt validation."""

from __future__ import annotations

from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_list,
    require_mapping,
    require_string,
)

_TX_STATES = {"not_started", "committed", "rolled_back"}


def assess_dolt_commit(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "operation_id",
            "run_id",
            "object_refs",
            "logical_change",
            "no_op",
            "sql_transaction_status",
            "dolt_commit_ref",
            "commit_message_refs",
            "contains_secret_or_user_text",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    operation_id = require_string(data["operation_id"], "request.operation_id")
    run_id = require_string(data["run_id"], "request.run_id")
    object_refs = [
        require_string(value, f"request.object_refs[{index}]")
        for index, value in enumerate(
            require_list(data["object_refs"], "request.object_refs")
        )
    ]
    if len(object_refs) != len(set(object_refs)):
        fail(
            "duplicate_object_ref",
            "request.object_refs",
            "Повторная object ref запрещена.",
        )
    logical_change = require_bool(data["logical_change"], "request.logical_change")
    no_op = require_bool(data["no_op"], "request.no_op")
    tx_status = require_string(
        data["sql_transaction_status"], "request.sql_transaction_status"
    )
    if tx_status not in _TX_STATES:
        fail(
            "invalid_transaction_status",
            "request.sql_transaction_status",
            "Неизвестный статус транзакции.",
        )
    commit_ref = data["dolt_commit_ref"]
    if commit_ref is not None:
        commit_ref = require_string(commit_ref, "request.dolt_commit_ref")
    message_refs = [
        require_string(value, f"request.commit_message_refs[{index}]")
        for index, value in enumerate(
            require_list(data["commit_message_refs"], "request.commit_message_refs")
        )
    ]
    contains_sensitive = require_bool(
        data["contains_secret_or_user_text"], "request.contains_secret_or_user_text"
    )

    issues: list[str] = []
    if logical_change == no_op:
        issues.append("logical_change_no_op_conflict")
    if contains_sensitive:
        issues.append("commit_message_sensitive_content")
    required_refs = {operation_id, run_id, *object_refs}
    if logical_change:
        if tx_status != "committed":
            issues.append("logical_transaction_not_committed")
        if not commit_ref:
            issues.append("dolt_commit_missing")
        if not object_refs:
            issues.append("object_refs_missing")
        if not required_refs.issubset(set(message_refs)):
            issues.append("commit_message_refs_incomplete")
    if no_op:
        if commit_ref is not None or message_refs:
            issues.append("no_op_created_history")
        if tx_status == "rolled_back":
            issues.append("no_op_rollback_is_not_success")

    issues = sorted(set(issues))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "DoltCommitReceipt",
        "status": "accepted" if not issues else "blocked",
        "operation_id": operation_id,
        "run_id": run_id,
        "logical_change": logical_change,
        "no_op": no_op,
        "commit_required": logical_change,
        "dolt_commit_ref": commit_ref,
        "object_ref_count": len(object_refs),
        "history_created": commit_ref is not None,
        "issues": issues,
    }
    return with_receipt_hash(payload)
