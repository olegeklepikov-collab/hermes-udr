"""Typed, scope-bound adapter for a host-owned AgentMemory service."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt, sha256_json
from .config import child
from .errors import fail
from .external_operations import guarded_external
from .native_runtime import invoke_worker, load_native_runtime
from .validation import boolean, exact, identifier, integer, mapping, string

MEMORY_MANIFEST = {
    "schema_version": 1,
    "agentmemory_version": "0.9.29",
    "npm_shasum": "800309cb9e83ee5efc10739f8b481d79fa5544df",
    "npm_integrity": "sha512-NGHEi563Ap6MDan19slUH47qrTHRRyLCsuEsa1tRZ0y3e4urJnxedLJR9/agp47P1nw6LiCEvNRvK4LfUWj9Gg==",
    "iii_engine_version": "0.11.2",
    "runtime_kind": "native",
    "transport": "loopback_http",
    "published_ports": [],
    "agent_scope_mode": "isolated",
    "embedding_mode": "keyless_default",
}
_SENSITIVE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|secret|authorization|bearer)[\s:=]"
)
_SCOPE_KEYS = {"tenant_id", "project_id", "profile_id", "work_kind"}


def memory_manifest(root: Path) -> dict[str, Any]:
    return dict(MEMORY_MANIFEST)


class AgentMemoryAdapter:
    def __init__(self, root: Path):
        self.foundation = root
        self.expected_manifest = memory_manifest(root)
        self.root = child(root, "agentmemory")
        self.manifest_path = child(self.root, "memory-manifest.json")
        self.default_scope_path = child(self.root, "default-scope.json")

    def _invoke(
        self, operation: str, payload: dict[str, object] | None = None
    ) -> dict[str, Any]:
        config = load_native_runtime(self.foundation)
        return invoke_worker(
            str(config["node_path"]), Path(__file__).with_name("agentmemory_worker.mjs"),
            {"connection": {"agentmemory_url": config["agentmemory_url"]}, "operation": operation, "payload": payload or {}},
            failure_code="agentmemory_operation_failed", response_code="agentmemory_response_invalid",
            error_path="runtime.agentmemory",
        )

    @staticmethod
    def _scope(value: object, path: str = "request.scope") -> dict[str, str]:
        data = mapping(value, path)
        exact(data, _SCOPE_KEYS, path)
        return {
            key: identifier(data[key], f"{path}.{key}") for key in sorted(_SCOPE_KEYS)
        }

    @staticmethod
    def _agent_id(scope: dict[str, str]) -> str:
        return f"scope-{sha256_json(scope)[:24]}"

    def _write_json(self, path: Path, value: object) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(".tmp")
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
        os.replace(temporary, path)

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
        version = self._invoke("version")
        if (
            version.get("version") != "0.9.29"
            or version.get("engine_version") != "0.11.2"
        ):
            fail(
                "agentmemory_version_mismatch",
                "runtime.agentmemory",
                "Версия AgentMemory не совпадает.",
            )
        health = self._invoke("health") if apply else None
        if apply:
            if self.manifest_path.exists():
                if (
                    json.loads(self.manifest_path.read_text(encoding="utf-8"))
                    != self.expected_manifest
                ):
                    fail(
                        "memory_manifest_conflict",
                        "agentmemory.manifest",
                        "Манифест памяти отличается.",
                    )
            else:
                self._write_json(self.manifest_path, self.expected_manifest)
        return receipt(
            {
                "schema_version": 1,
                "contract": "AgentMemoryMigrationReceipt",
                "status": "applied" if apply else "dry_run_ready",
                "apply_requested": apply,
                "manifest": self.expected_manifest,
                "manifest_hash": sha256_json(self.expected_manifest),
                "health_verified": bool(health and health.get("status") == "healthy"),
            }
        )

    def _ready(self) -> None:
        load_native_runtime(self.foundation)
        if not self.manifest_path.is_file() or self.manifest_path.is_symlink():
            fail(
                "agentmemory_unavailable",
                "runtime.agentmemory",
                "AgentMemory не подготовлен.",
            )
        if (
            json.loads(self.manifest_path.read_text(encoding="utf-8"))
            != self.expected_manifest
        ):
            fail(
                "memory_manifest_conflict",
                "agentmemory.manifest",
                "Манифест памяти отличается.",
            )

    def health(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version"}, "request")
        self._ready()
        result = self._invoke("health")
        return receipt(
            {
                "schema_version": 1,
                "contract": "AgentMemoryHealthReceipt",
                "status": result["status"],
                "manifest_hash": sha256_json(self.expected_manifest),
                "version": "0.9.29",
                "engine_version": "0.11.2",
                "scope_mode": "isolated",
                "published_ports": 0,
            }
        )

    def set_default_scope(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "scope"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        scope = self._scope(data["scope"])
        self._write_json(self.default_scope_path, scope)
        return receipt(
            {
                "schema_version": 1,
                "contract": "AgentMemoryScopeReceipt",
                "status": "configured",
                "scope": scope,
                "agent_id": self._agent_id(scope),
            }
        )

    def default_scope(self) -> dict[str, str] | None:
        if (
            not self.default_scope_path.is_file()
            or self.default_scope_path.is_symlink()
        ):
            return None
        return self._scope(
            json.loads(self.default_scope_path.read_text(encoding="utf-8")),
            "default_scope",
        )

    def save(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "scope", "content", "concepts"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        scope = self._scope(data["scope"])
        content = string(data["content"], "request.content")
        if _SENSITIVE.search(content):
            fail(
                "secret_scan_failed",
                "request.content",
                "Потенциальный секрет запрещён.",
            )
        concepts_raw = data["concepts"]
        if type(concepts_raw) is not list:
            fail("invalid_type", "request.concepts", "Ожидался массив.")
        concepts = [
            string(item, f"request.concepts[{index}]")
            for index, item in enumerate(concepts_raw)
        ]
        if any(_SENSITIVE.search(item) for item in concepts):
            fail(
                "secret_scan_failed",
                "request.concepts",
                "Потенциальный секрет запрещён.",
            )
        agent_id = self._agent_id(scope)
        scoped_concepts = [
            *concepts,
            *(f"{key}:{value}" for key, value in sorted(scope.items())),
        ]
        self._ready()
        return guarded_external(
            self.foundation,
            "agentmemory_save",
            {
                "scope": scope,
                "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            },
            data,
            lambda: self._save_prepared(scope, content, scoped_concepts, agent_id),
            {"saved"},
        )

    def _save_prepared(
        self,
        scope: dict[str, str],
        content: str,
        scoped_concepts: list[str],
        agent_id: str,
    ) -> dict[str, Any]:
        result = self._invoke(
            "save",
            {
                "content": content,
                "concepts": scoped_concepts,
                "project": scope["project_id"],
                "agentId": agent_id,
            },
        )
        outer = mapping(result.get("result"), "provider.result")
        memory = mapping(outer.get("memory"), "provider.memory")
        memory_id = identifier(memory.get("id"), "provider.memory.id")
        if _SENSITIVE.search(memory_id):
            fail(
                "agentmemory_response_invalid",
                "provider.memory.id",
                "Ответ AgentMemory поврежден.",
            )
        verified = (
            result.get("status") == "saved"
            and outer.get("status") not in {"blocked", "error", "rejected", "failed"}
            and memory.get("agentId") == agent_id
            and memory.get("project") == scope["project_id"]
            and memory.get("content") == content
        )
        return receipt(
            {
                "schema_version": 1,
                "contract": "AgentMemoryWriteReceipt",
                "status": "saved" if verified else "blocked",
                "scope": scope,
                "agent_id": agent_id,
                "memory_id": memory_id,
                "content_hash": hashlib.sha256(content.encode()).hexdigest(),
                "readback_verified": verified,
                "content_recorded_in_receipt": False,
            }
        )

    def search(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "scope", "query", "limit"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        scope = self._scope(data["scope"])
        query = string(data["query"], "request.query")
        if _SENSITIVE.search(query):
            fail(
                "secret_scan_failed", "request.query", "Потенциальный секрет запрещён."
            )
        limit = integer(data["limit"], "request.limit", minimum=1)
        if limit > 50:
            fail("limit_too_large", "request.limit", "Предел превышает 50.")
        agent_id = self._agent_id(scope)
        self._ready()
        result = self._invoke(
            "search",
            {
                "query": query,
                "limit": limit,
                "project": scope["project_id"],
                "agentId": agent_id,
                "format": "full",
            },
        )
        raw = result.get("result", {})
        rows = raw.get("results", []) if isinstance(raw, dict) else []
        contributions = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            observation = row.get("observation")
            item = observation if isinstance(observation, dict) else row
            if item.get("agentId") not in {None, agent_id}:
                continue
            text = (
                item.get("content") or item.get("narrative") or item.get("title") or ""
            )
            if not isinstance(text, str) or not text or _SENSITIVE.search(text):
                continue
            memory_id = str(row.get("obsId") or item.get("id") or row.get("id") or "")
            if not memory_id:
                continue
            contributions.append(
                {
                    "source_ref": f"agentmemory:{memory_id}",
                    "source_version": str(
                        item.get("timestamp") or row.get("timestamp") or "unknown"
                    ),
                    "locator": memory_id,
                    "exact_fragment": text,
                    "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                    "score": row.get("score") or item.get("score"),
                    "primary_source_ref": None,
                }
            )
        return receipt(
            {
                "schema_version": 1,
                "contract": "AgentMemorySearchReceipt",
                "status": "queried",
                "scope": scope,
                "agent_id": agent_id,
                "result_count": len(contributions),
                "contributions": contributions,
                "primary_readback_verified": False,
            }
        )

    def context(self, request: object) -> dict[str, Any]:
        result = self.search(request)
        lines = [
            str(item["exact_fragment"])
            for item in result["contributions"]
            if item.get("exact_fragment")
        ]
        text = "\n".join(lines)
        return receipt(
            {
                "schema_version": 1,
                "contract": "ContextContributionReceipt",
                "status": "assembled",
                "source_system": "agentmemory",
                "scope": result["scope"],
                "contribution_count": len(lines),
                "context": text,
                "context_hash": hashlib.sha256(text.encode()).hexdigest(),
                "evidence_record_created": False,
                "claim_status_changed": False,
            }
        )
