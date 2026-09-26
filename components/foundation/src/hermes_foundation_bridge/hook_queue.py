"""Bounded durable hook metadata queue in the already backed-up collector database."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, sha256_json
from .errors import BridgeError
from .fragments import prepare_fragment, record_prepared_fragment
from .runtime import HOOK_ORDER, RuntimeCoordinator

QUEUE_LIMIT = 1000
BUSY_TIMEOUT_MS = 50
MAX_ENVELOPE_BYTES = 65536
MAX_DRAIN_ITEMS = 2
ADMISSION_BUDGET_SECONDS = 0.2
ADMISSION_RETRY_SECONDS = 0.01
_HOOK_FIELDS = (
    "session_id",
    "turn_id",
    "tool_call_id",
    "model",
    "platform",
    "tool_name",
    "status",
)


class HookQueue:
    def __init__(self, root: Path):
        self.root = root
        self.database = root / "observability" / "collector.sqlite3"
        self.coordinator = RuntimeCoordinator(root, busy_timeout_ms=BUSY_TIMEOUT_MS)

    @contextmanager
    def _connection(self, *, timeout_ms: int = BUSY_TIMEOUT_MS):
        if self.database.is_symlink() or not self.database.is_file():
            raise ValueError("hook_queue_unavailable")
        connection = sqlite3.connect(
            self.database, timeout=timeout_ms / 1000, isolation_level=None
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
        finally:
            connection.close()

    def _envelope(
        self, event_type: str, payload: dict[str, object]
    ) -> tuple[bytes, str, str | None]:
        if event_type not in HOOK_ORDER:
            raise ValueError("hook_type_invalid")
        fields = {key: str(payload.get(key) or "") for key in _HOOK_FIELDS}
        envelope: dict[str, Any] = {
            "schema_version": 1,
            "event_type": event_type,
            "payload": fields,
            "fragment": None,
            "fragment_issue": None,
        }
        if event_type == "post_tool_call":
            result = payload.get("result")
            # This only bounds hook parsing; the original tool result remains with Hermes.
            if isinstance(result, str) and len(result) > 1_048_576:
                envelope["fragment_issue"] = "hook_result_parse_limit"
            elif isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    result = None
            if isinstance(result, dict) and isinstance(
                result.get("foundation_fragment"), dict
            ):
                identity = fields["tool_call_id"] or fields["turn_id"] or "unbound"
                key = "post-tool-v2:" + sha256_json(
                    {"session_id": fields["session_id"], "identity": identity}
                )
                try:
                    envelope["fragment"] = prepare_fragment(
                        {
                            "schema_version": 1,
                            "event_key": key,
                            "fragment": result["foundation_fragment"],
                        }
                    )
                except (BridgeError, ValueError, TypeError):
                    envelope["fragment_issue"] = "hook_fragment_invalid"
        body = canonical_bytes(envelope)
        if len(body) > MAX_ENVELOPE_BYTES:
            raise ValueError("hook_envelope_too_large")
        hashed = sha256_json(envelope)
        return body, hashed, envelope["fragment_issue"]

    def submit(self, event_type: str, payload: dict[str, object]) -> dict[str, Any]:
        return self._store(*self._envelope(event_type, payload))

    def _store(
        self, body: bytes, hashed: str, fragment_issue: str | None,
        *, timeout_ms: int = BUSY_TIMEOUT_MS,
    ) -> dict[str, Any]:
        with self._connection(timeout_ms=timeout_ms) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT status FROM hook_queue WHERE envelope_hash=?", (hashed,)
            ).fetchone()
            if existing is None:
                if (
                    connection.execute("SELECT COUNT(*) FROM hook_queue").fetchone()[0]
                    >= QUEUE_LIMIT
                ):
                    raise ValueError("hook_queue_full")
                connection.execute(
                    "INSERT INTO hook_queue(envelope_hash,envelope_json) VALUES (?,?)",
                    (hashed, body.decode()),
                )
            connection.execute("COMMIT")
        return {
            "status": "queued" if existing is None else existing["status"],
            "envelope_hash": hashed,
            "fragment_issue": fragment_issue,
        }

    def admit(self, event_type: str, payload: dict[str, object]) -> dict[str, Any]:
        """Retry only local idempotent admission after a rolled-back busy transaction."""
        prepared = self._envelope(event_type, payload)
        deadline = time.monotonic() + ADMISSION_BUDGET_SECONDS
        while True:
            try:
                return self._store(*prepared, timeout_ms=0)
            except sqlite3.OperationalError as error:
                code = getattr(error, "sqlite_errorcode", 0) & 0xFF
                remaining = deadline - time.monotonic()
                if code not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or remaining <= 0:
                    raise
                time.sleep(min(ADMISSION_RETRY_SECONDS, remaining))

    def drain(self, *, limit: int = MAX_DRAIN_ITEMS) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= MAX_DRAIN_ITEMS:
            raise ValueError("hook_drain_limit_invalid")
        applied = quarantined = 0
        for _ in range(limit):
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM hook_queue WHERE status='pending' ORDER BY sequence LIMIT 1"
                ).fetchone()
            if row is None:
                break
            try:
                envelope = json.loads(row["envelope_json"])
                if sha256_json(envelope) != row["envelope_hash"]:
                    raise ValueError("hook_envelope_changed")
                hook = self.coordinator.record_hook(
                    envelope["event_type"], envelope["payload"]
                )
                if hook["status"] == "idempotency_conflict":
                    raise ValueError("hook_identity_conflict")
                fragment = envelope["fragment"]
                if fragment is not None:
                    result = record_prepared_fragment(fragment, self.coordinator)
                    if result["status"] == "idempotency_conflict":
                        raise ValueError("fragment_identity_conflict")
            except sqlite3.OperationalError:
                return {
                    "status": "deferred",
                    "applied": applied,
                    "quarantined": quarantined,
                }
            except (
                BridgeError,
                ValueError,
                TypeError,
                KeyError,
                sqlite3.IntegrityError,
            ):
                with self._connection() as connection:
                    connection.execute(
                        "UPDATE hook_queue SET status='quarantined' WHERE envelope_hash=?",
                        (row["envelope_hash"],),
                    )
                quarantined += 1
                continue
            # A crash here replays idempotently; never acknowledge before coordinator commit.
            with self._connection() as connection:
                connection.execute(
                    "DELETE FROM hook_queue WHERE envelope_hash=?",
                    (row["envelope_hash"],),
                )
            applied += 1
        return {"status": "drained", "applied": applied, "quarantined": quarantined}

    def health(self) -> dict[str, Any]:
        with self._connection() as connection:
            counts = {
                row["status"]: row["n"]
                for row in connection.execute(
                    "SELECT status,COUNT(*) AS n FROM hook_queue GROUP BY status"
                )
            }
        return {
            "pending": counts.get("pending", 0),
            "quarantined": counts.get("quarantined", 0),
            "queue_limit": QUEUE_LIMIT,
            "busy_timeout_ms": BUSY_TIMEOUT_MS,
        }
