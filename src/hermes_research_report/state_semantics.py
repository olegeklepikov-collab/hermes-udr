"""Authority, blob identity, version coexistence, readback, and memory scope."""

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

_TEXT = {"type": "string", "minLength": 1}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_TYPES = {
    "authority_map",
    "blob_dedup",
    "version_coexistence",
    "evidence_readback",
    "memory_scope",
}

STATE_SEMANTICS_ASSESS_SCHEMA: dict[str, Any] = {
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


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _authority(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {"object_type", "owner_ref", "writer_count", "projection_owner_ref"},
        "request.payload",
    )
    owner = require_string(payload["owner_ref"], "request.payload.owner_ref")
    projection_owner = require_string(
        payload["projection_owner_ref"], "request.payload.projection_owner_ref"
    )
    writers = require_int(payload["writer_count"], "request.payload.writer_count")
    issues = []
    if writers != 1 or owner != projection_owner:
        issues.append("authority_conflict")
    return {
        "object_type": require_string(
            payload["object_type"], "request.payload.object_type"
        ),
        "owner_ref": owner,
        "projection_owner_ref": projection_owner,
        "writer_count": writers,
        "projection_synchronizable": not issues,
        "issues": issues,
    }


def _blob(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(payload, {"objects"}, "request.payload")
    blobs: dict[str, list[dict[str, str]]] = {}
    source_ids: set[str] = set()
    issues = []
    for index, raw in enumerate(
        require_list(payload["objects"], "request.payload.objects")
    ):
        path = f"request.payload.objects[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"source_id", "version", "content_hash", "title"}, path)
        source_id = require_string(row["source_id"], f"{path}.source_id")
        if source_id in source_ids:
            issues.append(f"source_identity_reused:{source_id}")
        source_ids.add(source_id)
        content_hash = _hash(row["content_hash"], f"{path}.content_hash")
        blobs.setdefault(content_hash, []).append(
            {
                "source_id": source_id,
                "version": require_string(row["version"], f"{path}.version"),
                "title": require_string(row["title"], f"{path}.title"),
            }
        )
    blob_rows = [
        {"content_hash": content_hash, "source_aliases": aliases}
        for content_hash, aliases in sorted(blobs.items())
    ]
    return {
        "blob_count": len(blob_rows),
        "source_count": len(source_ids),
        "blobs": blob_rows,
        "source_identity_preserved": not issues,
        "issues": issues,
    }


def _versions(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(payload, {"records", "supersession_basis"}, "request.payload")
    basis = _nullable(
        payload["supersession_basis"], "request.payload.supersession_basis"
    )
    records = []
    for index, raw in enumerate(
        require_list(payload["records"], "request.payload.records")
    ):
        path = f"request.payload.records[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"record_ref", "period", "status", "source_ref"}, path)
        records.append(
            {
                "record_ref": require_string(row["record_ref"], f"{path}.record_ref"),
                "period": require_string(row["period"], f"{path}.period"),
                "status": require_string(row["status"], f"{path}.status"),
                "source_ref": require_string(row["source_ref"], f"{path}.source_ref"),
            }
        )
    issues = []
    if basis is None and any(row["status"] == "withdrawn" for row in records):
        issues.append("supersession_basis_missing")
    return {
        "records": records,
        "supersession_basis": basis,
        "automatic_withdrawal_applied": basis is not None,
        "issues": issues,
    }


def _readback(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "source_ref",
        "candidate_revision",
        "current_revision",
        "readback_available",
        "summary_only",
        "evidence_link_created",
    }
    require_exact_keys(payload, keys, "request.payload")
    candidate = require_int(
        payload["candidate_revision"], "request.payload.candidate_revision", minimum=1
    )
    current = require_int(
        payload["current_revision"], "request.payload.current_revision", minimum=1
    )
    readback = require_bool(
        payload["readback_available"], "request.payload.readback_available"
    )
    summary_only = require_bool(payload["summary_only"], "request.payload.summary_only")
    link = require_bool(
        payload["evidence_link_created"], "request.payload.evidence_link_created"
    )
    issues = []
    if candidate != current:
        issues.append("stale_source_revision")
    if not readback or summary_only:
        issues.append("source_readback_unavailable")
    if not link:
        issues.append("evidence_link_missing")
    return {
        "source_ref": require_string(
            payload["source_ref"], "request.payload.source_ref"
        ),
        "candidate_revision": candidate,
        "current_revision": current,
        "read_in_scope": not issues,
        "supported_claim_allowed": not issues,
        "issues": issues,
    }


def _memory(payload: dict[str, object]) -> dict[str, object]:
    keys = {"record_ref", "target_scope", "provenance_ref", "scope_limit", "authorized"}
    require_exact_keys(payload, keys, "request.payload")
    target = require_string(payload["target_scope"], "request.payload.target_scope")
    limit = require_string(payload["scope_limit"], "request.payload.scope_limit")
    provenance = _nullable(payload["provenance_ref"], "request.payload.provenance_ref")
    authorized = require_bool(payload["authorized"], "request.payload.authorized")
    issues = []
    if target not in {"run", "project"} or limit not in {"run", "project"}:
        fail(
            "invalid_memory_scope",
            "request.payload.target_scope",
            "Неизвестная область.",
        )
    if target == "project" and (
        limit != "project" or provenance is None or not authorized
    ):
        issues.append("memory_scope_violation")
    return {
        "record_ref": require_string(
            payload["record_ref"], "request.payload.record_ref"
        ),
        "target_scope": target,
        "scope_limit": limit,
        "provenance_ref": provenance,
        "persist_allowed": not issues,
        "issues": issues,
    }


_ASSESSORS = {
    "authority_map": _authority,
    "blob_dedup": _blob,
    "version_coexistence": _versions,
    "evidence_readback": _readback,
    "memory_scope": _memory,
}


def assess_state_semantics(request: object) -> dict[str, Any]:
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
    issues = [str(item) for item in result.get("issues", [])]  # type: ignore[union-attr]
    return with_receipt_hash(
        {
            "contract": "StateSemanticsReceipt",
            "control_type": control_type,
            "status": "accepted" if not issues else "blocked",
            **result,
        }
    )
