"""Found-fragment registration and explicit evidence promotion."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from .canonical import receipt, sha256_json
from .errors import fail
from .runtime import RuntimeCoordinator
from .validation import digest, exact, identifier, mapping, string

SOURCE_SYSTEMS = {
    "zvec",
    "web",
    "file",
    "agentmemory",
    "graphiti",
    "user",
    "tool",
    "database",
}
_SENSITIVE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|secret|authorization|bearer)[\s:=]"
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sensitive(*values: str) -> bool:
    if any(_SENSITIVE.search(value) for value in values):
        return True
    parsed = urlsplit(values[0])
    return bool(parsed.username or parsed.password or parsed.query)


def prepare_fragment(request: object) -> dict[str, Any]:
    """Validate transient content; return only the existing content-free ledger fields."""
    data = mapping(request, "request")
    exact(data, {"schema_version", "event_key", "fragment"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    event_key = identifier(data["event_key"], "request.event_key")
    fragment = mapping(data["fragment"], "request.fragment")
    exact(
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
    fragment_id = identifier(fragment["fragment_id"], "request.fragment.fragment_id")
    run_id = identifier(fragment["run_id"], "request.fragment.run_id")
    source_system = string(fragment["source_system"], "request.fragment.source_system")
    if source_system not in SOURCE_SYSTEMS:
        fail(
            "unknown_source_system",
            "request.fragment.source_system",
            "Неизвестный источник.",
        )
    source_ref = string(
        fragment["source_ref"], "request.fragment.source_ref", nonempty=False
    )
    source_version = string(
        fragment["source_version"], "request.fragment.source_version", nonempty=False
    )
    locator = string(fragment["locator"], "request.fragment.locator", nonempty=False)
    exact_fragment = string(
        fragment["exact_fragment"], "request.fragment.exact_fragment", nonempty=False
    )
    content_hash = digest(fragment["content_hash"], "request.fragment.content_hash")
    computed = hashlib.sha256(exact_fragment.encode("utf-8")).hexdigest()
    secret_scan_pass = not _sensitive(
        source_ref, source_version, locator, exact_fragment
    ) and not (
        exact_fragment
        and any(
            exact_fragment in value for value in (source_ref, source_version, locator)
        )
    )
    stored_source_ref = source_ref if secret_scan_pass else ""
    stored_source_version = source_version if secret_scan_pass else ""
    stored_locator = locator if secret_scan_pass else ""
    resolvable = bool(
        stored_source_ref
        and stored_source_version
        and stored_locator
        and exact_fragment
        and computed == content_hash
        and secret_scan_pass
    )
    record_hash = sha256_json(
        {
            "fragment_id": fragment_id,
            "run_id": run_id,
            "source_system": source_system,
            "source_ref": stored_source_ref,
            "source_version": stored_source_version,
            "locator": stored_locator,
            "content_hash": content_hash,
            "transformation_refs": fragment["transformation_refs"],
            "retrieval_query": fragment["retrieval_query"],
            "rank_or_score": fragment["rank_or_score"],
        }
    )
    return {
        "fragment_id": fragment_id,
        "event_key": event_key,
        "run_id": run_id,
        "source_system": source_system,
        "source_ref": stored_source_ref,
        "source_version": stored_source_version,
        "locator": stored_locator,
        "content_hash": content_hash,
        "record_hash": record_hash,
        "resolvable": resolvable,
        "secret_scan_pass": secret_scan_pass,
    }


def record_fragment(request: object, coordinator: RuntimeCoordinator) -> dict[str, Any]:
    return record_prepared_fragment(prepare_fragment(request), coordinator)


def record_prepared_fragment(
    prepared: dict[str, Any], coordinator: RuntimeCoordinator
) -> dict[str, Any]:
    """Internal replay of a validated, content-free envelope; never evidence promotion."""
    fragment_id = prepared["fragment_id"]
    event_key = prepared["event_key"]
    record_hash = prepared["record_hash"]
    content_hash = prepared["content_hash"]
    connection = coordinator._connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT fragment_id, record_hash, status FROM found_fragments WHERE event_key=?",
            (event_key,),
        ).fetchone()
        desired = "recorded" if prepared["resolvable"] else "candidate"
        if existing is None:
            connection.execute(
                "INSERT INTO found_fragments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fragment_id,
                    event_key,
                    prepared["run_id"],
                    prepared["source_system"],
                    prepared["source_ref"],
                    prepared["source_version"],
                    prepared["locator"],
                    content_hash,
                    record_hash,
                    desired,
                    _now(),
                ),
            )
            status = desired
        elif existing["record_hash"] == record_hash:
            status = str(existing["status"])
        else:
            status = "idempotency_conflict"
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    return receipt(
        {
            "schema_version": 1,
            "contract": "FoundFragmentRecordReceipt",
            "status": status,
            "fragment_id": fragment_id,
            "event_key": event_key,
            "record_hash": record_hash,
            "content_hash": content_hash,
            "exact_fragment_persisted": False,
            "secret_scan_pass": prepared["secret_scan_pass"],
            "evidence_record_created": False,
            "claim_status_changed": False,
            "acceptance_changed": False,
            "release_changed": False,
        }
    )


def promote(request: object, coordinator: RuntimeCoordinator) -> dict[str, Any]:
    try:
        from hermes_research_report import promote_fragment
    except ImportError as error:
        raise RuntimeError("research contract package unavailable") from error
    result = promote_fragment(request)
    fragment_id = result["fragment_id"]
    connection = coordinator._connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status,record_hash,run_id,content_hash FROM found_fragments WHERE fragment_id=?",
            (fragment_id,),
        ).fetchone()
        if row is None:
            fail(
                "found_fragment_missing",
                "request.fragment.fragment_id",
                "Фрагмент не зарегистрирован.",
            )
        if (
            row["record_hash"] != result["found_record_hash"]
            or row["run_id"] != result["run_id"]
            or row["content_hash"] != result["content_hash"]
        ):
            fail(
                "found_fragment_version_mismatch",
                "request.fragment",
                "Запрос повышения не соответствует зарегистрированному фрагменту.",
            )
        if result["status"] == "promoted":
            if row["status"] not in {"recorded", "promoted"}:
                fail(
                    "found_fragment_unresolved",
                    "request.fragment",
                    "Неразрешённый кандидат не может быть повышен.",
                )
            connection.execute(
                "UPDATE found_fragments SET status='promoted' WHERE fragment_id=?",
                (fragment_id,),
            )
            connection.commit()
    finally:
        connection.close()
    return result
