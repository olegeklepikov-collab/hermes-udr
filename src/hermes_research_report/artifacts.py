"""Pure artifact-operation validation; the host performs all file I/O."""

from __future__ import annotations

import posixpath
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
_OPERATIONS = {"ingest", "derive", "release", "delete"}
_FILE_KINDS = {"regular", "symlink", "fifo", "device"}
_CRASH_POINTS = {
    "none",
    "before_rename",
    "after_rename_before_metadata",
    "after_metadata",
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _path(value: object, path: str) -> str:
    text = require_string(value, path)
    if (
        "\x00" in text
        or not text.startswith("/")
        or posixpath.normpath(text) != text
        or text == "/"
    ):
        fail(
            "invalid_path",
            path,
            "Требуется канонический абсолютный POSIX-путь вне корня.",
        )
    return text


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def assess_artifact(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "operation",
            "artifact_id",
            "file_kind",
            "path",
            "allowed_root",
            "byte_size",
            "max_byte_size",
            "content_hash",
            "original_ref",
            "existing_same_hash_ref",
            "write_receipt",
            "tombstone",
            "propagation",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    operation = require_string(data["operation"], "request.operation")
    if operation not in _OPERATIONS:
        fail(
            "invalid_operation", "request.operation", "Недопустимая файловая операция."
        )
    artifact_id = require_string(data["artifact_id"], "request.artifact_id")
    file_kind = require_string(data["file_kind"], "request.file_kind")
    if file_kind not in _FILE_KINDS:
        fail("invalid_file_kind", "request.file_kind", "Неизвестный вид файла.")
    path = _path(data["path"], "request.path")
    allowed_root = _path(data["allowed_root"], "request.allowed_root")
    byte_size = require_int(data["byte_size"], "request.byte_size")
    max_byte_size = require_int(
        data["max_byte_size"], "request.max_byte_size", minimum=1
    )
    content_hash = _hash(data["content_hash"], "request.content_hash")
    original_ref = data["original_ref"]
    if original_ref is not None:
        original_ref = require_string(original_ref, "request.original_ref")
    existing_ref = data["existing_same_hash_ref"]
    if existing_ref is not None:
        existing_ref = require_string(existing_ref, "request.existing_same_hash_ref")
    tombstone = require_bool(data["tombstone"], "request.tombstone")

    write = require_mapping(data["write_receipt"], "request.write_receipt")
    require_exact_keys(
        write,
        {
            "temporary_write",
            "file_fsync",
            "atomic_rename",
            "directory_fsync",
            "metadata_committed",
            "readback_hash",
            "crash_point",
        },
        "request.write_receipt",
    )
    write_flags = {
        key: require_bool(write[key], f"request.write_receipt.{key}")
        for key in (
            "temporary_write",
            "file_fsync",
            "atomic_rename",
            "directory_fsync",
            "metadata_committed",
        )
    }
    readback_hash = _hash(write["readback_hash"], "request.write_receipt.readback_hash")
    crash_point = require_string(
        write["crash_point"], "request.write_receipt.crash_point"
    )
    if crash_point not in _CRASH_POINTS:
        fail(
            "invalid_crash_point",
            "request.write_receipt.crash_point",
            "Неизвестная точка сбоя.",
        )

    propagation_raw = require_list(data["propagation"], "request.propagation")
    propagation: dict[str, str] = {}
    for index, item in enumerate(propagation_raw):
        item_path = f"request.propagation[{index}]"
        row = require_mapping(item, item_path)
        require_exact_keys(row, {"target", "status"}, item_path)
        target = require_string(row["target"], f"{item_path}.target")
        status = require_string(row["status"], f"{item_path}.status")
        if target in propagation:
            fail(
                "duplicate_propagation_target",
                f"{item_path}.target",
                "Повторная цель запрещена.",
            )
        propagation[target] = status

    issues: list[str] = []
    if file_kind != "regular":
        issues.append(f"file_kind_rejected:{file_kind}")
    if not _within(path, allowed_root):
        issues.append("path_outside_allowed_root")
    if byte_size > max_byte_size:
        issues.append("artifact_size_exceeded")
    if operation in {"derive", "release"} and not original_ref:
        issues.append("original_ref_missing")
    if operation == "ingest" and original_ref:
        issues.append("ingest_original_ref_forbidden")

    idempotent = (
        existing_ref is not None and readback_hash == content_hash and not issues
    )
    if operation == "delete":
        if not tombstone:
            issues.append("tombstone_missing")
        required_targets = {"derived_index", "graph", "restore_view"}
        if set(propagation) != required_targets or any(
            status != "done" for status in propagation.values()
        ):
            issues.append("tombstone_propagation_incomplete")
    elif not idempotent:
        if crash_point != "none":
            issues.append(f"crash_reconciliation_required:{crash_point}")
        for flag, passed in write_flags.items():
            if not passed:
                issues.append(f"write_step_missing:{flag}")
        if readback_hash != content_hash:
            issues.append("readback_hash_mismatch")

    issues = sorted(set(issues))
    if issues:
        disposition = (
            "quarantined_recovery_required"
            if any(item.startswith("crash_") for item in issues)
            else "rejected"
        )
        status = "blocked"
    elif operation == "delete":
        disposition = "tombstoned"
        status = "accepted"
    elif idempotent:
        disposition = "idempotent_existing"
        status = "accepted"
    else:
        disposition = "verified_new_artifact"
        status = "accepted"

    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "ArtifactOperationReceipt",
        "status": status,
        "operation": operation,
        "artifact_id": artifact_id,
        "content_hash": content_hash,
        "byte_size": byte_size,
        "disposition": disposition,
        "original_ref": original_ref,
        "existing_same_hash_ref": existing_ref,
        "issues": issues,
    }
    return with_receipt_hash(payload)
