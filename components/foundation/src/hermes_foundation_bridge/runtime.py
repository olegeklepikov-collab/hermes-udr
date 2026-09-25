"""Single-writer SQLite runtime coordinator and idempotent hook journal."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .canonical import receipt, sha256_json
from .config import child
from .errors import fail
from .validation import digest, exact, identifier, integer, mapping

SCHEMA_VERSION = 1
HOOK_ORDER = {
    "on_session_start": 10,
    "pre_llm_call": 20,
    "post_tool_call": 30,
    "post_llm_call": 40,
    "on_session_end": 50,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class RuntimeCoordinator:
    def __init__(self, root: Path, *, busy_timeout_ms: int = 5000):
        if type(busy_timeout_ms) is not int or not 0 <= busy_timeout_ms <= 5000:
            raise ValueError("runtime_timeout_invalid")
        self.root = root
        self.busy_timeout_ms = busy_timeout_ms
        self.database = child(root, "runtime", "runtime.sqlite3")

    @staticmethod
    def migration_path() -> Path:
        return Path(__file__).resolve().parents[2] / "migrations" / "001_runtime.sql"

    def migration_receipt(self, *, apply: bool) -> dict[str, Any]:
        path = self.migration_path()
        if not path.is_file() or path.is_symlink():
            fail("migration_missing", "migrations.001_runtime", "Миграция недоступна.")
        sql = path.read_text(encoding="utf-8")
        mode: int | None = None
        if apply:
            self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            connection = sqlite3.connect(self.database)
            try:
                connection.executescript(sql)
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta(schema_version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _timestamp(_now())),
                )
                connection.commit()
                journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
                version = connection.execute(
                    "SELECT MAX(schema_version) FROM schema_meta"
                ).fetchone()[0]
            finally:
                connection.close()
            mode = self.database.stat().st_mode & 0o777
            if mode & 0o077:
                self.database.chmod(0o600)
                mode = self.database.stat().st_mode & 0o777
            verified = (
                journal.lower() == "wal" and version == SCHEMA_VERSION and mode == 0o600
            )
        else:
            journal = None
            version = None
            verified = False
        return receipt(
            {
                "schema_version": 1,
                "contract": "RuntimeMigrationReceipt",
                "status": "applied"
                if apply and verified
                else "dry_run_ready"
                if not apply
                else "blocked",
                "migration_id": "001_runtime",
                "migration_hash": sha256_json({"sql": sql}),
                "database_ref": "foundation/runtime/runtime.sqlite3",
                "apply_requested": apply,
                "journal_mode": journal,
                "installed_schema_version": version,
                "permission_mode": f"{mode:04o}" if mode is not None else None,
                "readback_verified": verified,
            }
        )

    def _connect(self) -> sqlite3.Connection:
        if not self.database.is_file() or self.database.is_symlink():
            fail(
                "runtime_unavailable", "runtime", "Runtime coordinator не подготовлен."
            )
        connection = sqlite3.connect(
            self.database, timeout=self.busy_timeout_ms / 1000, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return connection

    def begin_external(
        self,
        kind: str,
        identity_hash: str,
        payload_hash: str,
        target_hash: str | None = None,
    ) -> dict[str, Any]:
        """Reserve before crossing a process boundary; a prior start is never a retry permit."""
        identifier(kind, "operation.kind")
        digest(identity_hash, "operation.identity_hash")
        digest(payload_hash, "operation.payload_hash")
        if target_hash is not None:
            digest(target_hash, "operation.target_hash")
        if (
            self.root.is_symlink()
            or self.database.parent.is_symlink()
            or self.database.is_symlink()
        ):
            fail(
                "runtime_path_unsafe",
                "runtime",
                "Небезопасный путь состояния исполнения.",
            )
        if not self.database.exists():
            self.migration_receipt(apply=True)
        key = f"external:{kind}:{identity_hash}"
        operation_id = "EXT-" + sha256_json(key)
        owner = uuid.uuid4().hex
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE idempotency_key=?", (key,)
            ).fetchone()
            if row is None:
                metadata = {
                    "payload_hash": payload_hash,
                    "owner": owner,
                    "result_receipt_hash": None,
                    "target_hash": target_hash,
                }
                now = _timestamp(_now())
                connection.execute(
                    "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?)",
                    (
                        operation_id,
                        key,
                        kind,
                        1,
                        "started",
                        json.dumps(metadata, sort_keys=True),
                        now,
                        now,
                    ),
                )
                state = "owned"
            else:
                metadata = json.loads(row["outcome_ref"])
                if metadata.get("payload_hash") != payload_hash:
                    fail(
                        "external_operation_conflict",
                        "operation",
                        "Идентичность внешней операции уже связана с другим запросом.",
                    )
                if row["status"] == "succeeded":
                    digest(
                        metadata.get("result_receipt_hash"),
                        "operation.result_receipt_hash",
                    )
                    state = "already_succeeded"
                else:
                    connection.execute(
                        "UPDATE operations SET status='unknown',updated_at=? WHERE operation_id=?",
                        (_timestamp(_now()), operation_id),
                    )
                    state = "unknown_outcome"
            connection.execute("COMMIT")
        finally:
            connection.close()
        return {
            "status": state,
            "operation_id": operation_id,
            "owner": owner if state == "owned" else None,
            "result_receipt_hash": metadata.get("result_receipt_hash"),
        }

    def external_status(self, kind: str, identity_hash: str) -> str | None:
        if not self.database.exists():
            return None
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT status FROM operations WHERE idempotency_key=?",
                (f"external:{kind}:{identity_hash}",),
            ).fetchone()
            return str(row["status"]) if row else None
        finally:
            connection.close()

    def unresolved_external_target(self, kind: str, target_hash: str) -> bool:
        """An old record lacking target metadata also blocks until independently reconciled."""
        digest(target_hash, "operation.target_hash")
        if not self.database.exists():
            return False
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT outcome_ref FROM operations WHERE work_id=? AND status IN ('started','unknown')",
                (kind,),
            )
            for row in rows:
                metadata = json.loads(row["outcome_ref"])
                if metadata.get("target_hash") in {None, target_hash}:
                    return True
            return False
        finally:
            connection.close()

    def finish_external(
        self, operation_id: str, owner: str, result_receipt_hash: str | None
    ) -> None:
        """Only the reserving caller can record its observed outcome; raw responses never enter this store."""
        if result_receipt_hash is not None:
            digest(result_receipt_hash, "operation.result_receipt_hash")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT outcome_ref,status FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                fail(
                    "external_operation_missing",
                    "operation",
                    "Внешняя операция не найдена.",
                )
            metadata = json.loads(row["outcome_ref"])
            if metadata.get("owner") != owner:
                fail(
                    "external_operation_owner_mismatch",
                    "operation",
                    "Владелец внешней операции не совпадает.",
                )
            if row["status"] == "succeeded":
                if (
                    result_receipt_hash is not None
                    and metadata.get("result_receipt_hash") != result_receipt_hash
                ):
                    fail(
                        "external_result_conflict",
                        "operation",
                        "Подтвержденный исход внешней операции отличается.",
                    )
                connection.execute("COMMIT")
                return
            metadata["result_receipt_hash"] = result_receipt_hash
            connection.execute(
                "UPDATE operations SET status=?,outcome_ref=?,updated_at=? WHERE operation_id=?",
                (
                    "succeeded" if result_receipt_hash else "unknown",
                    json.dumps(metadata, sort_keys=True),
                    _timestamp(_now()),
                    operation_id,
                ),
            )
            connection.execute("COMMIT")
        finally:
            connection.close()

    def check_lease(self, work_id: str, holder_id: str, revision: int) -> dict[str, Any]:
        """Read current ownership without acquiring or extending the lease."""
        identifier(work_id, "work_id")
        identifier(holder_id, "holder_id")
        integer(revision, "revision", minimum=1)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT holder_id, revision, status, expires_at FROM leases WHERE work_id=?",
                (work_id,),
            ).fetchone()
        finally:
            connection.close()
        active = bool(row and row["holder_id"] == holder_id and row["revision"] == revision
                      and row["status"] == "active" and datetime.fromisoformat(row["expires_at"]) > _now())
        return receipt({"contract": "LeaseReadReceipt", "work_id": work_id,
                        "holder_id": holder_id, "revision": revision, "lease_active": active})

    def acquire_lease(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "work_id",
                "holder_id",
                "expected_revision",
                "ttl_seconds",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        work_id = identifier(data["work_id"], "request.work_id")
        holder_id = identifier(data["holder_id"], "request.holder_id")
        expected = integer(
            data["expected_revision"], "request.expected_revision", minimum=1
        )
        ttl = integer(data["ttl_seconds"], "request.ttl_seconds", minimum=1)
        if ttl > 86400:
            fail("ttl_too_large", "request.ttl_seconds", "TTL превышает сутки.")
        now = _now()
        expires = now + timedelta(seconds=ttl)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT holder_id, revision, status, expires_at FROM leases WHERE work_id=?",
                (work_id,),
            ).fetchone()
            if row is None:
                if expected != 1:
                    status = "stale_revision"
                    current = 0
                else:
                    connection.execute(
                        "INSERT INTO leases VALUES (?, ?, ?, 'active', ?, ?, ?)",
                        (
                            work_id,
                            holder_id,
                            1,
                            _timestamp(now),
                            _timestamp(now),
                            _timestamp(expires),
                        ),
                    )
                    status = "acquired"
                    current = 1
            else:
                current = int(row["revision"])
                active = (
                    row["status"] == "active"
                    and datetime.fromisoformat(row["expires_at"]) > now
                )
                if current != expected:
                    status = "stale_revision"
                elif active and row["holder_id"] != holder_id:
                    status = "lease_conflict"
                elif active:
                    connection.execute(
                        "UPDATE leases SET heartbeat_at=?, expires_at=? WHERE work_id=?",
                        (_timestamp(now), _timestamp(expires), work_id),
                    )
                    status = "idempotent_active"
                else:
                    current += 1
                    connection.execute(
                        "UPDATE leases SET holder_id=?, revision=?, status='active', acquired_at=?, heartbeat_at=?, expires_at=? WHERE work_id=?",
                        (
                            holder_id,
                            current,
                            _timestamp(now),
                            _timestamp(now),
                            _timestamp(expires),
                            work_id,
                        ),
                    )
                    status = "acquired"
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
                "contract": "LeaseDecisionReceipt",
                "status": status,
                "work_id": work_id,
                "holder_id": holder_id,
                "expected_revision": expected,
                "current_revision": current,
                "lease_active": status in {"acquired", "idempotent_active"},
                "partial_write": False,
            }
        )

    def enqueue(
        self, *, event_key: str, event_type: str, payload: object
    ) -> dict[str, Any]:
        key = identifier(event_key, "event_key")
        kind = identifier(event_type, "event_type")
        payload_hash = sha256_json(payload)
        event_id = f"EVT-{sha256_json({'key': key, 'type': kind})[:24]}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT event_id, payload_hash FROM outbox WHERE event_key=?", (key,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO outbox(event_id,event_key,event_type,payload_hash,status,attempts,created_at) VALUES (?, ?, ?, ?, 'pending', 0, ?)",
                    (event_id, key, kind, payload_hash, _timestamp(_now())),
                )
                status = "queued"
            elif existing["payload_hash"] == payload_hash:
                event_id = str(existing["event_id"])
                status = "idempotent_existing"
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
                "contract": "OutboxDecisionReceipt",
                "status": status,
                "event_id": event_id,
                "event_key": key,
                "event_type": kind,
                "payload_hash": payload_hash,
                "external_effect_performed": False,
            }
        )

    def record_hook(
        self, event_type: str, payload: dict[str, object]
    ) -> dict[str, Any]:
        if event_type not in HOOK_ORDER:
            fail("unknown_hook", "event_type", "Неизвестное событие bridge.")
        session_id = str(payload.get("session_id") or "unbound")
        turn_id = str(payload.get("turn_id") or "")
        tool_call_id = str(payload.get("tool_call_id") or "")
        identity = tool_call_id or turn_id or session_id
        legacy_key = f"{event_type}:{identity}"
        event_key = "hook-v2:" + sha256_json(
            {"event_type": event_type, "session_id": session_id, "identity": identity}
        )
        payload_hash = sha256_json(
            {
                "event_type": event_type,
                "session_id": session_id,
                "turn_id": turn_id,
                "tool_call_id": tool_call_id,
                "model": str(payload.get("model") or ""),
                "platform": str(payload.get("platform") or ""),
                "tool_name": str(payload.get("tool_name") or ""),
                "status": str(payload.get("status") or ""),
            }
        )
        event_id = f"HOOK-{sha256_json({'event_key': event_key})[:24]}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            legacy = connection.execute(
                "SELECT event_id,event_key FROM hook_events WHERE event_key=? AND session_id=?",
                (legacy_key, session_id),
            ).fetchone()
            if legacy is not None:
                event_id, event_key = legacy["event_id"], legacy["event_key"]
            existing = connection.execute(
                "SELECT payload_hash FROM hook_events WHERE event_key=?", (event_key,)
            ).fetchone()
            if existing is None:
                prior = connection.execute(
                    "SELECT MAX(sequence) FROM hook_events WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
                sequence = int(prior or 0) + 1
                connection.execute(
                    "INSERT INTO hook_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        event_key,
                        session_id,
                        turn_id,
                        tool_call_id,
                        event_type,
                        sequence,
                        payload_hash,
                        _timestamp(_now()),
                    ),
                )
                status = "recorded"
            elif existing["payload_hash"] == payload_hash:
                sequence = int(
                    connection.execute(
                        "SELECT sequence FROM hook_events WHERE event_key=?",
                        (event_key,),
                    ).fetchone()[0]
                )
                status = "idempotent_existing"
            else:
                sequence = -1
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
                "contract": "FoundationHookReceipt",
                "status": status,
                "event_id": event_id,
                "event_type": event_type,
                "event_key": event_key,
                "sequence": sequence,
                "payload_hash": payload_hash,
                "claim_status_changed": False,
                "acceptance_changed": False,
                "release_changed": False,
            }
        )

    def health(self) -> dict[str, Any]:
        connection = self._connect()
        try:
            version = connection.execute(
                "SELECT MAX(schema_version) FROM schema_meta"
            ).fetchone()[0]
            journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
            counts = {
                name: int(
                    connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                )
                for name in (
                    "leases",
                    "operations",
                    "outbox",
                    "hook_events",
                    "found_fragments",
                )
            }
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "RuntimeHealthReceipt",
                "status": "healthy"
                if version == SCHEMA_VERSION and journal.lower() == "wal"
                else "blocked",
                "installed_schema_version": version,
                "journal_mode": journal,
                "counts": counts,
                "single_writer_interface": True,
            }
        )


def lease_request(raw: object, coordinator: RuntimeCoordinator) -> dict[str, Any]:
    return coordinator.acquire_lease(raw)


def outbox_request(raw: object, coordinator: RuntimeCoordinator) -> dict[str, Any]:
    data = mapping(raw, "request")
    exact(data, {"schema_version", "event_key", "event_type", "payload"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    event_key = identifier(data["event_key"], "request.event_key")
    event_type = identifier(data["event_type"], "request.event_type")
    payload = mapping(data["payload"], "request.payload")
    return coordinator.enqueue(
        event_key=event_key, event_type=event_type, payload=payload
    )
