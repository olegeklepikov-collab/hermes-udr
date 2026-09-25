"""Automatic fragment capture with explicit evidence promotion."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from .canonical import sha256_json, with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_list,
    require_mapping,
    require_string,
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SYSTEMS = {
    "zvec",
    "web",
    "file",
    "agentmemory",
    "graphiti",
    "user",
    "tool",
    "database",
}
_EVIDENCE_CLASSES = {
    "primary_source_evidence",
    "secondary_source_evidence",
    "retrieval_evidence",
    "memory_evidence",
    "graph_evidence",
    "user_provided_evidence",
    "tool_output_evidence",
    "derived_calculation_evidence",
}
_CHECK_KEYS = (
    "source_resolved",
    "version_resolved",
    "locator_verified",
    "exact_hash_verified",
    "within_limits",
    "secret_scan_pass",
    "transformations_resolved",
    "primary_readback",
)


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def promote_fragment(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {"schema_version", "fragment", "checks", "requested_evidence_class"},
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    fragment = require_mapping(data["fragment"], "request.fragment")
    require_exact_keys(
        fragment,
        {
            "fragment_id",
            "run_id",
            "source_system",
            "source_ref",
            "source_version",
            "locator",
            "exact_fragment",
            "content_hash",
            "transformation_refs",
            "retrieval_query",
            "rank_or_score",
        },
        "request.fragment",
    )
    fragment_id = require_string(
        fragment["fragment_id"], "request.fragment.fragment_id"
    )
    run_id = require_string(fragment["run_id"], "request.fragment.run_id")
    source_system = require_string(
        fragment["source_system"], "request.fragment.source_system"
    )
    if source_system not in _SOURCE_SYSTEMS:
        fail(
            "invalid_source_system",
            "request.fragment.source_system",
            "Неизвестная система источника.",
        )
    source_ref = require_string(
        fragment["source_ref"], "request.fragment.source_ref", nonempty=False
    )
    source_version = require_string(
        fragment["source_version"], "request.fragment.source_version", nonempty=False
    )
    locator = require_string(
        fragment["locator"], "request.fragment.locator", nonempty=False
    )
    exact_fragment = require_string(
        fragment["exact_fragment"], "request.fragment.exact_fragment", nonempty=False
    )
    content_hash = _hash(fragment["content_hash"], "request.fragment.content_hash")
    transformation_refs_raw = require_list(
        fragment["transformation_refs"], "request.fragment.transformation_refs"
    )
    transformation_refs = [
        require_string(value, f"request.fragment.transformation_refs[{index}]")
        for index, value in enumerate(transformation_refs_raw)
    ]
    retrieval_query = require_string(
        fragment["retrieval_query"], "request.fragment.retrieval_query", nonempty=False
    )
    rank_or_score = fragment["rank_or_score"]
    if rank_or_score is not None:
        if isinstance(rank_or_score, bool) or not isinstance(
            rank_or_score, (int, float)
        ):
            fail(
                "invalid_rank",
                "request.fragment.rank_or_score",
                "Ранг/оценка должны быть числом либо null.",
            )
        if not math.isfinite(float(rank_or_score)):
            fail(
                "invalid_rank",
                "request.fragment.rank_or_score",
                "Ранг/оценка должны быть конечным числом.",
            )

    checks = require_mapping(data["checks"], "request.checks")
    require_exact_keys(checks, set(_CHECK_KEYS), "request.checks")
    checked = {
        key: require_bool(checks[key], f"request.checks.{key}") for key in _CHECK_KEYS
    }
    evidence_class = require_string(
        data["requested_evidence_class"], "request.requested_evidence_class"
    )
    if evidence_class not in _EVIDENCE_CLASSES:
        fail(
            "invalid_evidence_class",
            "request.requested_evidence_class",
            "Неизвестный класс доказательства.",
        )

    issues: list[str] = []
    computed_hash = hashlib.sha256(exact_fragment.encode("utf-8")).hexdigest()
    if computed_hash != content_hash:
        issues.append("content_hash_mismatch")
    if not exact_fragment:
        issues.append("empty_fragment")
    for key in _CHECK_KEYS[:-1]:
        if not checked[key]:
            issues.append(f"promotion_check_failed:{key}")
    if source_system in {"agentmemory", "graphiti"} and not checked["primary_readback"]:
        issues.append("primary_readback_required")
    if not source_ref:
        issues.append("source_ref_missing")
    if not source_version:
        issues.append("source_version_missing")
    if not locator:
        issues.append("locator_missing")

    issues = sorted(set(issues))
    promoted = not issues
    found_record_hash = sha256_json(
        {
            "fragment_id": fragment_id,
            "run_id": run_id,
            "source_system": source_system,
            "source_ref": source_ref,
            "source_version": source_version,
            "locator": locator,
            "content_hash": content_hash,
            "transformation_refs": transformation_refs,
            "retrieval_query": retrieval_query,
            "rank_or_score": rank_or_score,
        }
    )
    evidence_id = (
        f"EVD-{sha256_json({'found_record_hash': found_record_hash, 'class': evidence_class})[:20]}"
        if promoted
        else None
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "FragmentPromotionReceipt",
        "status": "promoted" if promoted else "candidate",
        "fragment_id": fragment_id,
        "run_id": run_id,
        "found_fragment_status": "recorded",
        "found_record_hash": found_record_hash,
        "source_system": source_system,
        "content_hash": content_hash,
        "evidence_record_created": promoted,
        "evidence_id": evidence_id,
        "evidence_class": evidence_class if promoted else None,
        "evidence_status": "auto_linked_limited" if promoted else None,
        "claim_status_changed": False,
        "acceptance_changed": False,
        "release_changed": False,
        "issues": issues,
    }
    return with_receipt_hash(payload)
