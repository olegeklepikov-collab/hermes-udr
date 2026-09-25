"""Private content-free trace collector with bounded local degradation."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt
from .config import child
from .errors import BridgeError, fail
from .validation import boolean, digest, exact, identifier, integer, mapping, string

SCHEMA_VERSION = 1
SPOOL_LIMIT = 1000
_SENSITIVE_KEY = re.compile(
    r"(?i)(?:authorization|cookie|header|token|secret|password|api.?key|pii|signed.?url|payload|content|text|prompt|response)"
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:bearer\s+\S+|[A-Za-z0-9_-]*(?:token|secret|key)[A-Za-z0-9_-]*\s*[:=]\s*\S+|https?://\S+[?&]\S+=\S+|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})"
)


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _strings(value: object, path: str) -> list[str]:
    if type(value) is not list:
        fail("invalid_type", path, "Ожидался массив.")
    result = [identifier(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        fail("duplicate_value", path, "Повторы запрещены.")
    return result


def _redaction_count(attributes: object) -> tuple[int, int]:
    data = mapping(attributes, "request.attributes")
    redacted = 0
    for key, value in data.items():
        if type(key) is not str:
            fail(
                "invalid_attribute",
                "request.attributes",
                "Имя атрибута недействительно.",
            )
        if _SENSITIVE_KEY.search(key):
            redacted += 1
            continue
        if (
            isinstance(value, str)
            and _SENSITIVE_VALUE.search(value)
            or type(value) not in {str, int, float, bool, type(None)}
        ):
            redacted += 1
    return len(data), redacted


class ObservabilityService:
    def __init__(self, root: Path):
        self.root = child(root, "observability")
        self.database = child(self.root, "collector.sqlite3")

    @staticmethod
    def migration_path() -> Path:
        return (
            Path(__file__).resolve().parents[2] / "migrations" / "004_observability.sql"
        )

    def migrate(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "apply"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        apply = boolean(data["apply"], "request.apply")
        migration = self.migration_path()
        if migration.is_symlink() or not migration.is_file():
            fail(
                "migration_missing",
                "migrations.004_observability",
                "Миграция отсутствует.",
            )
        if apply:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            connection = sqlite3.connect(self.database)
            try:
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta VALUES (?, ?)",
                    (SCHEMA_VERSION, _timestamp(_now())),
                )
                connection.commit()
            finally:
                connection.close()
            self.database.chmod(0o600)
        return receipt(
            {
                "schema_version": 1,
                "contract": "ObservabilityMigrationReceipt",
                "status": "applied" if apply else "dry_run_ready",
                "migration_id": "004_observability",
                "collector_mode": "private_local",
                "published_endpoints": [],
                "content_payload_allowed": False,
            }
        )

    def _connect(self) -> sqlite3.Connection:
        if self.database.is_symlink() or not self.database.is_file():
            fail(
                "observability_unavailable",
                "runtime.observability",
                "Приёмник не подготовлен.",
            )
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _envelope(self, request: object) -> tuple[dict[str, Any], bool, int, int]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "trace_id",
                "project_id",
                "run_id",
                "bead_id",
                "profile_id",
                "session_hash",
                "operation_id",
                "attempt",
                "model_ref",
                "tool_ref",
                "context_refs",
                "evidence_link_refs",
                "commit_refs",
                "latency_ms",
                "cost_microunits",
                "outcome_status",
                "priority",
                "collector_available",
                "sampling_decision",
                "ttl_seconds",
                "attributes",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        priority = string(data["priority"], "request.priority")
        sampling = string(data["sampling_decision"], "request.sampling_decision")
        outcome = string(data["outcome_status"], "request.outcome_status")
        if priority not in {"P0", "P1", "P2"} or sampling not in {"keep", "drop"}:
            fail(
                "trace_policy_invalid",
                "request.priority",
                "Политика трассы недействительна.",
            )
        if outcome not in {"success", "failed", "unknown", "blocked", "recovered"}:
            fail(
                "trace_status_invalid",
                "request.outcome_status",
                "Статус трассы недействителен.",
            )
        tool_ref = data["tool_ref"]
        normalized = {
            "trace_id": identifier(data["trace_id"], "request.trace_id"),
            "project_id": identifier(data["project_id"], "request.project_id"),
            "run_id": identifier(data["run_id"], "request.run_id"),
            "bead_id": identifier(data["bead_id"], "request.bead_id"),
            "profile_id": identifier(data["profile_id"], "request.profile_id"),
            "session_hash": digest(data["session_hash"], "request.session_hash"),
            "operation_id": identifier(data["operation_id"], "request.operation_id"),
            "attempt": integer(data["attempt"], "request.attempt", minimum=1),
            "model_ref": identifier(data["model_ref"], "request.model_ref"),
            "tool_ref": None
            if tool_ref is None
            else identifier(tool_ref, "request.tool_ref"),
            "context_refs": _strings(data["context_refs"], "request.context_refs"),
            "evidence_link_refs": _strings(
                data["evidence_link_refs"], "request.evidence_link_refs"
            ),
            "commit_refs": _strings(data["commit_refs"], "request.commit_refs"),
            "latency_ms": integer(data["latency_ms"], "request.latency_ms"),
            "cost_microunits": integer(
                data["cost_microunits"], "request.cost_microunits"
            ),
            "outcome_status": outcome,
            "priority": priority,
        }
        available = boolean(data["collector_available"], "request.collector_available")
        ttl = integer(data["ttl_seconds"], "request.ttl_seconds", minimum=1)
        if ttl > 3600:
            fail(
                "trace_ttl_too_large", "request.ttl_seconds", "TTL превышает один час."
            )
        attribute_count, redacted = _redaction_count(data["attributes"])
        mandatory = priority == "P0" or outcome in {"unknown", "blocked"}
        if sampling == "drop" and not mandatory:
            normalized["sampled_out"] = True
        return normalized, available, ttl, redacted if attribute_count else 0

    @staticmethod
    def _trace_values(envelope: dict[str, Any], redacted: int) -> tuple:
        evidence_refs = envelope["evidence_link_refs"]
        return (
            envelope["trace_id"],
            envelope["project_id"],
            envelope["run_id"],
            envelope["bead_id"],
            envelope["profile_id"],
            envelope["session_hash"],
            envelope["operation_id"],
            envelope["attempt"],
            envelope["model_ref"],
            envelope["tool_ref"],
            json.dumps(envelope["context_refs"], separators=(",", ":")),
            json.dumps(evidence_refs, separators=(",", ":")),
            json.dumps(envelope["commit_refs"], separators=(",", ":")),
            envelope["latency_ms"],
            envelope["cost_microunits"],
            envelope["outcome_status"],
            envelope["priority"],
            1 if evidence_refs else 0,
            redacted,
        )

    @classmethod
    def _trace_exists(cls, connection, envelope, redacted) -> bool:
        row = connection.execute(
            "SELECT * FROM traces WHERE trace_id=?", (envelope["trace_id"],)
        ).fetchone()
        if row is None:
            return False
        if tuple(row)[:-1] != cls._trace_values(envelope, redacted):
            fail(
                "trace_id_conflict",
                "request.trace_id",
                "Идентификатор трассы уже связан с другой записью.",
            )
        return True

    @classmethod
    def _insert_trace(cls, connection, envelope, redacted) -> bool:
        if cls._trace_exists(connection, envelope, redacted):
            return False
        connection.execute(
            "INSERT INTO traces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*cls._trace_values(envelope, redacted), _timestamp(_now())),
        )
        return True

    def _read_spool(self, connection, row):
        value = json.loads(row["envelope_json"])
        redacted = integer(
            value.pop("redacted_field_count"),
            "spool.redacted_field_count",
        )
        normalized, _, _, _ = self._envelope(
            {
                **value,
                "schema_version": 1,
                "collector_available": True,
                "sampling_decision": "keep",
                "ttl_seconds": 1,
                "attributes": {},
            }
        )
        if normalized != value or value["trace_id"] != row["trace_id"]:
            raise ValueError("spool_identity_mismatch")
        self._trace_exists(connection, value, redacted)
        return value, redacted

    def record(self, request: object) -> dict[str, Any]:
        envelope, available, ttl, redacted = self._envelope(request)
        sampled_out = envelope.pop("sampled_out", False)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            spool_value = {**envelope, "redacted_field_count": redacted}
            pending = connection.execute(
                "SELECT envelope_json FROM trace_spool WHERE trace_id=?",
                (envelope["trace_id"],),
            ).fetchone()
            if pending is not None and canonical_bytes(
                json.loads(pending[0])
            ) != canonical_bytes(spool_value):
                fail(
                    "trace_id_conflict",
                    "request.trace_id",
                    "Идентификатор очереди уже связан с другой записью.",
                )
            existing = self._trace_exists(connection, envelope, redacted)
            if sampled_out and not existing and pending is None:
                return receipt(
                    {
                        "schema_version": 1,
                        "contract": "TraceReceipt",
                        "status": "sampled_out",
                        "trace_id": envelope["trace_id"],
                        "mandatory_span_retained": False,
                        "content_payload_persisted": False,
                        "evidence_eligible": False,
                    }
                )
            if available or existing:
                inserted = self._insert_trace(connection, envelope, redacted)
                connection.execute(
                    "DELETE FROM trace_spool WHERE trace_id=?", (envelope["trace_id"],)
                )
                status = "recorded"
                idempotent = not inserted
            else:
                now = _now()
                expired_rows = connection.execute(
                    "SELECT * FROM trace_spool WHERE expires_at <= ?",
                    (_timestamp(now),),
                ).fetchall()
                for row in expired_rows:
                    try:
                        self._read_spool(connection, row)
                    except (BridgeError, ValueError, KeyError, TypeError):
                        continue
                    connection.execute(
                        "DELETE FROM trace_spool WHERE trace_id=?", (row["trace_id"],)
                    )
                count = int(
                    connection.execute("SELECT COUNT(*) FROM trace_spool").fetchone()[0]
                )
                pending = connection.execute(
                    "SELECT trace_id FROM trace_spool WHERE trace_id=?",
                    (envelope["trace_id"],),
                ).fetchone()
                if pending is None and count >= SPOOL_LIMIT:
                    fail(
                        "trace_spool_full",
                        "runtime.observability",
                        "Локальный журнал заполнен.",
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO trace_spool VALUES (?,?,?,?)",
                    (
                        envelope["trace_id"],
                        canonical_bytes(spool_value).decode("utf-8"),
                        _timestamp(now + timedelta(seconds=ttl)),
                        _timestamp(now),
                    ),
                )
                status = "observability_degraded"
                idempotent = pending is not None
            connection.commit()
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "TraceReceipt",
                "status": status,
                "idempotent_existing": idempotent,
                "trace_id": envelope["trace_id"],
                "mandatory_span_retained": envelope["priority"] == "P0"
                or envelope["outcome_status"] in {"unknown", "blocked"},
                "redacted_field_count": redacted,
                "content_payload_persisted": False,
                "evidence_eligible": bool(envelope["evidence_link_refs"]),
                "tool_success_is_evidence": False,
                "spool_ttl_seconds": ttl
                if status == "observability_degraded"
                else None,
            }
        )

    def reconcile(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "collector_available"}, "request")
        available = boolean(data["collector_available"], "request.collector_available")
        if not available:
            fail(
                "collector_unavailable",
                "request.collector_available",
                "Приёмник недоступен.",
            )
        connection = self._connect()
        moved = 0
        expired = 0
        conflicts = []
        try:
            connection.execute("BEGIN IMMEDIATE")
            now = _timestamp(_now())
            rows = connection.execute(
                "SELECT * FROM trace_spool ORDER BY created_at"
            ).fetchall()
            for row in rows:
                try:
                    value, redacted = self._read_spool(connection, row)
                except (BridgeError, ValueError, KeyError, TypeError):
                    conflicts.append(row["trace_id"])
                    continue
                if row["expires_at"] <= now:
                    expired += 1
                else:
                    self._insert_trace(connection, value, redacted)
                    moved += 1
                connection.execute(
                    "DELETE FROM trace_spool WHERE trace_id=?", (row["trace_id"],)
                )
            connection.commit()
        finally:
            connection.close()
        from .hook_queue import HookQueue

        hooks = HookQueue(self.root.parent)
        hook_replay = hooks.drain()
        hook_replay.update(hooks.health())
        return receipt(
            {
                "schema_version": 1,
                "contract": "TraceSpoolReconciliationReceipt",
                "hook_reconciliation": hook_replay,
                "status": "observability_degraded" if conflicts else "reconciled",
                "conflicting_trace_ids": conflicts,
                "moved_count": moved,
                "expired_count": expired,
                "content_payload_persisted": False,
            }
        )

    def health(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version"}, "request")
        connection = self._connect()
        try:
            version = connection.execute(
                "SELECT MAX(schema_version) FROM schema_meta"
            ).fetchone()[0]
            trace_count = int(
                connection.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
            )
            spool_count = int(
                connection.execute("SELECT COUNT(*) FROM trace_spool").fetchone()[0]
            )
            queue_ready = bool(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='hook_queue'"
                ).fetchone()
            )
            queue_counts = (
                {
                    row["status"]: row["n"]
                    for row in connection.execute(
                        "SELECT status,COUNT(*) AS n FROM hook_queue GROUP BY status"
                    )
                }
                if queue_ready
                else {}
            )
        finally:
            connection.close()
        healthy = (
            version == SCHEMA_VERSION
            and queue_ready
            and (self.database.stat().st_mode & 0o777) == 0o600
        )
        return receipt(
            {
                "schema_version": 1,
                "contract": "ObservabilityHealthReceipt",
                "status": "blocked"
                if not healthy
                else "degraded"
                if queue_counts or spool_count
                else "healthy",
                "collector_mode": "private_local",
                "published_endpoints": [],
                "trace_count": trace_count,
                "spool_count": spool_count,
                "hook_queue_ready": queue_ready,
                "hook_queue_pending": queue_counts.get("pending", 0),
                "hook_queue_quarantined": queue_counts.get("quarantined", 0),
                "spool_limit": SPOOL_LIMIT,
                "content_payload_allowed": False,
            }
        )
