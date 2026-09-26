"""Typed bridge-only Graphiti adapter using a local Neo4j worker."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt, sha256_json
from .config import child
from .errors import BridgeError, fail
from .external_operations import guarded_external
from . import platform_io as fcntl
from .native_runtime import invoke_worker, load_native_runtime
from .runtime import RuntimeCoordinator
from .validation import boolean, digest, exact, identifier, integer, mapping, string

GRAPH_MANIFEST = {
    "schema_version": 1,
    "graph_id": "hermes_foundation",
    "graphiti_core_version": "0.30.2",
    "runtime_kind": "native",
    "graph_backend": "neo4j",
    "neo4j_version": "5.26.31",
    "published_ports": [],
    "write_authority": "hermes-foundation-bridge",
    "raw_query_exposed": False,
    "admin_operations_exposed": False,
}
_SENSITIVE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|secret|authorization|bearer)[\s:=]"
)
ARTIFACT_LOCK_TIMEOUT_SECONDS = 1.0


def graph_manifest(root: Path) -> dict[str, Any]:
    return dict(GRAPH_MANIFEST)


def _circuit_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise BridgeError(
            "graphiti_circuit_corrupt",
            "runtime.graphiti.circuit",
            "Состояние circuit повреждено.",
        )
    return value


class GraphitiAdapter:
    def __init__(self, root: Path):
        self.foundation = root
        self.expected_manifest = graph_manifest(root)
        self.root = child(root, "graphiti")
        self.manifest_path = child(self.root, "graph-manifest.json")
        self.circuit_path = child(self.root, "circuit.json")
        self.circuit_lock = child(self.root, ".circuit.lock")

    @contextmanager
    def _circuit_guard(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.circuit_lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _circuit_state(self) -> dict[str, object]:
        if not self.circuit_path.is_file():
            return {"state": "closed", "failure_count": 0, "generation": 0}
        try:
            value = json.loads(self.circuit_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BridgeError(
                "graphiti_circuit_corrupt",
                "runtime.graphiti.circuit",
                "Состояние circuit повреждено.",
            ) from error
        if not isinstance(value, dict):
            raise BridgeError(
                "graphiti_circuit_corrupt",
                "runtime.graphiti.circuit",
                "Состояние circuit повреждено.",
            )
        if set(value) != {"state", "failure_count", "generation"} or value.get(
            "state"
        ) not in {"closed", "open"}:
            raise BridgeError(
                "graphiti_circuit_corrupt",
                "runtime.graphiti.circuit",
                "Состояние circuit повреждено.",
            )
        _circuit_int(value.get("failure_count"))
        _circuit_int(value.get("generation"))
        return value

    def _write_circuit(self, value: dict[str, object]) -> None:
        temporary = self.circuit_path.with_suffix(".tmp")
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_TRUNC | os.O_WRONLY,
            0o600,
        )
        try:
            payload = canonical_bytes(value) + b"\n"
            written = 0
            while written < len(payload):
                written += os.write(descriptor, payload[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self.circuit_path)
        fcntl.sync_directory(self.root)

    def _record_failure(self) -> dict[str, object]:
        with self._circuit_guard():
            current = self._circuit_state()
            count = _circuit_int(current.get("failure_count", 0)) + 1
            state = "open" if count >= 5 else "closed"
            updated = {
                "state": state,
                "failure_count": count,
                "generation": _circuit_int(current.get("generation", 0)),
            }
            self._write_circuit(updated)
            return updated

    def _record_success(self) -> dict[str, object]:
        with self._circuit_guard():
            current = self._circuit_state()
            generation = _circuit_int(current.get("generation", 0))
            if current.get("state") == "open" or _circuit_int(
                current.get("failure_count", 0)
            ):
                generation += 1
            updated = {
                "state": "closed",
                "failure_count": 0,
                "generation": generation,
            }
            self._write_circuit(updated)
            return updated

    def _invoke(
        self, operation: str, payload: dict[str, object] | None = None
    ) -> dict[str, Any]:
        if operation != "health" and self._circuit_state().get("state") == "open":
            raise BridgeError(
                "graphiti_circuit_open",
                "runtime.graphiti.circuit",
                "Graphiti circuit открыт.",
            )
        config = load_native_runtime(self.foundation)
        try:
            result = invoke_worker(
                str(config["python_path"]), Path(__file__).with_name("graphiti_worker.py"),
                {"connection": {"neo4j_uri": config["neo4j_uri"], "neo4j_user": config["neo4j_user"],
                                "neo4j_password_file": config["neo4j_password_file"]},
                 "operation": operation, "payload": payload or {}},
                failure_code="graphiti_operation_failed", response_code="graphiti_response_invalid",
                error_path="runtime.graphiti",
            )
        except BridgeError:
            self._record_failure()
            raise
        self._record_success()
        return result

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
        health = self._invoke("health")
        if (
            health.get("graphiti_version") != "0.30.2"
            or health.get("neo4j_version") != "5.26.31"
        ):
            fail(
                "graphiti_version_mismatch",
                "runtime.graphiti",
                "Версия Graphiti не совпадает.",
            )
        if apply:
            result = self._invoke("migrate")
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            payload = canonical_bytes(self.expected_manifest) + b"\n"
            if self.manifest_path.exists():
                if (
                    json.loads(self.manifest_path.read_text(encoding="utf-8"))
                    != self.expected_manifest
                ):
                    fail(
                        "graph_manifest_conflict",
                        "graphiti.manifest",
                        "Манифест графа отличается.",
                    )
            else:
                descriptor = os.open(
                    self.manifest_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                try:
                    os.write(descriptor, payload)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            status = result["status"]
        else:
            status = "dry_run_ready"
        return receipt(
            {
                "schema_version": 1,
                "contract": "GraphitiMigrationReceipt",
                "status": status,
                "apply_requested": apply,
                "manifest": self.expected_manifest,
                "manifest_hash": sha256_json(self.expected_manifest),
                "health_verified": True,
            }
        )

    def _ready(self) -> None:
        load_native_runtime(self.foundation)
        if not self.manifest_path.is_file() or self.manifest_path.is_symlink():
            fail("graphiti_unavailable", "runtime.graphiti", "Graphiti не подготовлен.")
        if (
            json.loads(self.manifest_path.read_text(encoding="utf-8"))
            != self.expected_manifest
        ):
            fail(
                "graph_manifest_conflict",
                "graphiti.manifest",
                "Манифест графа отличается.",
            )

    @contextmanager
    def _artifact_guard(self, artifact_id: str):
        """Serialize lifecycle checks and effects for one immutable source artifact."""
        path = child(self.root, ".artifact-" + sha256_json(artifact_id) + ".lock")
        if path.is_symlink():
            fail(
                "graphiti_artifact_lock_unsafe",
                "runtime.graphiti",
                "Небезопасный путь блокировки артефакта.",
            )
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        acquired = False
        try:
            deadline = time.monotonic() + ARTIFACT_LOCK_TIMEOUT_SECONDS
            while not acquired:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        fail(
                            "graphiti_artifact_busy",
                            "runtime.graphiti",
                            "Время ожидания операции над артефактом истекло.",
                        )
                    time.sleep(0.01)
            yield
        finally:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def health(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version"}, "request")
        self._ready()
        result = self._invoke("health")
        circuit = self._circuit_state()
        return receipt(
            {
                "schema_version": 1,
                "contract": "GraphitiHealthReceipt",
                "status": result["status"],
                "manifest_hash": sha256_json(self.expected_manifest),
                "graphiti_version": result["graphiti_version"],
                "neo4j_version": result["neo4j_version"],
                "raw_query_exposed": False,
                "admin_operations_exposed": False,
                "circuit_state": circuit["state"],
                "circuit_failure_count": circuit["failure_count"],
                "circuit_generation": circuit["generation"],
            }
        )

    def circuit_status(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        circuit = self._circuit_state()
        return receipt(
            {
                "schema_version": 1,
                "contract": "GraphitiCircuitReceipt",
                "status": "open" if circuit["state"] == "open" else "closed",
                "failure_count": circuit["failure_count"],
                "generation": circuit["generation"],
                "routing_allowed": circuit["state"] != "open",
            }
        )

    def put_fact(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "project_id",
                "fact_id",
                "text",
                "text_hash",
                "source_ref",
                "artifact_id",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        project_id = identifier(data["project_id"], "request.project_id")
        fact_id = identifier(data["fact_id"], "request.fact_id")
        text = string(data["text"], "request.text")
        text_hash = digest(data["text_hash"], "request.text_hash")
        source_ref = string(data["source_ref"], "request.source_ref")
        artifact_id = identifier(data["artifact_id"], "request.artifact_id")
        if hashlib.sha256(text.encode()).hexdigest() != text_hash:
            fail("text_hash_mismatch", "request.text_hash", "Хеш текста не совпадает.")
        if _SENSITIVE.search(text) or _SENSITIVE.search(source_ref):
            fail("secret_scan_failed", "request.text", "Потенциальный секрет запрещён.")
        self._ready()
        payload = {
            "project_id": project_id,
            "fact_id": fact_id,
            "text": text,
            "text_hash": text_hash,
            "source_ref": source_ref,
            "artifact_id": artifact_id,
        }
        with self._artifact_guard(artifact_id):
            state = RuntimeCoordinator(self.foundation).external_status(
                "graphiti_tombstone", sha256_json({"artifact_id": artifact_id})
            )
            if state is not None:
                fail(
                    "graphiti_artifact_tombstoned",
                    "request.artifact_id",
                    "Артефакт закрыт для новых фактов; новая редакция требует нового идентификатора артефакта.",
                )
            return guarded_external(
                self.foundation,
                "graphiti_put_fact",
                {"project_id": project_id, "fact_id": fact_id},
                data,
                lambda: self._put_prepared(payload),
                {"written"},
                target={"artifact_id": artifact_id},
            )

    def _put_prepared(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id, fact_id = payload["project_id"], payload["fact_id"]
        text_hash, source_ref, artifact_id = (
            payload["text_hash"],
            payload["source_ref"],
            payload["artifact_id"],
        )
        result = self._invoke(
            "put_fact",
            payload,
        )
        rows = result.get("rows", [])
        row = (
            rows[0]
            if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
            else {}
        )
        verified = bool(
            result.get("status") == "written"
            and row.get("fact_id") == fact_id
            and row.get("text_hash") == text_hash
            and row.get("active") is True
        )
        return receipt(
            {
                "schema_version": 1,
                "contract": "GraphitiWriteReceipt",
                "status": "written" if verified else "blocked",
                "project_id": project_id,
                "fact_id": fact_id,
                "text_hash": text_hash,
                "source_ref": source_ref,
                "artifact_id": artifact_id,
                "readback_verified": verified,
                "write_authority": "hermes-foundation-bridge",
            }
        )

    def search(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "project_id", "query", "limit"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        project_id = identifier(data["project_id"], "request.project_id")
        query = string(data["query"], "request.query")
        limit = integer(data["limit"], "request.limit", minimum=1)
        if limit > 100:
            fail("limit_too_large", "request.limit", "Предел превышает 100.")
        self._ready()
        result = self._invoke(
            "search", {"project_id": project_id, "query": query, "limit": limit}
        )
        rows = result.get("rows", [])
        return receipt(
            {
                "schema_version": 1,
                "contract": "GraphitiSearchReceipt",
                "status": "queried",
                "project_id": project_id,
                "manifest_hash": sha256_json(self.expected_manifest),
                "result_count": len(rows),
                "results": rows,
            }
        )

    def tombstone(self, artifact_id: str) -> dict[str, Any]:
        self._ready()
        identifier(artifact_id, "request.artifact_id")
        with self._artifact_guard(artifact_id):
            if RuntimeCoordinator(self.foundation).unresolved_external_target(
                "graphiti_put_fact", sha256_json({"artifact_id": artifact_id})
            ):
                return receipt(
                    {
                        "schema_version": 1,
                        "contract": "GraphitiLifecycleReceipt",
                        "status": "unknown_outcome",
                        "artifact_id": artifact_id,
                        "requires_reconciliation": True,
                        "safe_to_retry": False,
                        "external_call_attempted": False,
                        "deletion_observed": None,
                        "reason": "unresolved_put_may_still_complete",
                    }
                )
            return guarded_external(
                self.foundation,
                "graphiti_tombstone",
                {"artifact_id": artifact_id},
                {"artifact_id": artifact_id},
                lambda: self._tombstone_prepared(artifact_id),
                {"propagated"},
            )

    def _tombstone_prepared(self, artifact_id: str) -> dict[str, Any]:
        result = self._invoke("tombstone", {"artifact_id": artifact_id})
        count = integer(result.get("deactivated_count"), "provider.deactivated_count")
        return receipt(
            {
                "schema_version": 1,
                "contract": "GraphitiTombstoneReceipt",
                "status": result["status"],
                "artifact_id": artifact_id,
                "deactivated_count": count,
                "active_query_visibility": False,
                "restore_view_active": False,
            }
        )

    def tombstone_request(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "artifact_id"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        return self.tombstone(identifier(data["artifact_id"], "request.artifact_id"))
