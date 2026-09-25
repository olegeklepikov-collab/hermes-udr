"""Public Hermes hook callbacks and composite bridge operations."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from .agentmemory_adapter import AgentMemoryAdapter
from .artifacts import ArtifactService
from .beads_adapter import BeadsAdapter
from .canonical import receipt, sha256_json
from .config import foundation_root
from .dolt_sql import DoltSQLAdapter
from .dolt_state import DATABASES, DoltStateAdapter
from .errors import BridgeError
from .graphiti_adapter import GraphitiAdapter
from .hook_queue import HookQueue
from .observability import ObservabilityService
from .profile_transport import ProfileTransportService
from .release import release_verified
from .runtime import RuntimeCoordinator
from .validation import boolean, exact, mapping
from .zvec_index import ZvecIndexer


def services(
    root: Path | None = None,
) -> tuple[RuntimeCoordinator, ArtifactService, DoltStateAdapter | DoltSQLAdapter]:
    resolved = root or foundation_root()
    sql_authority = resolved / "dolt" / "sql-authority.json"
    return (
        RuntimeCoordinator(resolved),
        ArtifactService(resolved),
        DoltSQLAdapter(resolved)
        if sql_authority.exists()
        else DoltStateAdapter(resolved),
    )


def migrate(request: object) -> dict[str, Any]:
    data = mapping(request, "request")
    exact(data, {"schema_version", "apply"}, "request")
    if data["schema_version"] != 1:
        from .errors import fail

        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    apply = boolean(data["apply"], "request.apply")
    runtime, artifacts, dolt = services()
    results = [
        runtime.migration_receipt(apply=apply),
        artifacts.prepare(dry_run=not apply),
        dolt.migrate(apply=apply),
        ObservabilityService(foundation_root()).migrate(request),
    ]
    ready = all(item["status"] in {"dry_run_ready", "applied"} for item in results)
    return receipt(
        {
            "schema_version": 1,
            "contract": "FoundationBridgeMigrationReceipt",
            "status": "applied"
            if apply and ready
            else "dry_run_ready"
            if ready
            else "blocked",
            "apply_requested": apply,
            "components": results,
            "rollback_ref": "ROLLBACK.md",
        }
    )


def health(request: object) -> dict[str, Any]:
    data = mapping(request, "request")
    exact(data, {"schema_version"}, "request")
    runtime, artifacts, dolt = services()
    runtime_receipt = runtime.health()
    artifact_ready = all(
        path.is_dir() and not path.is_symlink()
        for path in (
            artifacts.root,
            artifacts.quarantine,
            artifacts.originals,
            artifacts.metadata,
            artifacts.tombstones,
        )
    )
    dolt_ready = all((dolt.root / name / ".dolt").is_dir() for name in DATABASES)
    sql_authority_ready = False
    if isinstance(dolt, DoltSQLAdapter):
        try:
            sql_authority_ready = dolt.health()["status"] == "healthy"
        except (BridgeError, OSError, ValueError, RuntimeError):
            sql_authority_ready = False
    indexer = ZvecIndexer(foundation_root())
    zvec_ready = indexer.collection_path.is_dir() and indexer.manifest_path.is_file()
    graph = GraphitiAdapter(foundation_root())
    graph_ready = False
    if graph.manifest_path.is_file():
        try:
            graph_ready = graph.health({"schema_version": 1})["status"] == "healthy"
        except (BridgeError, OSError, ValueError):
            graph_ready = False
    memory = AgentMemoryAdapter(foundation_root())
    memory_ready = False
    if memory.manifest_path.is_file():
        try:
            memory_ready = memory.health({"schema_version": 1})["status"] == "healthy"
        except (BridgeError, OSError, ValueError):
            memory_ready = False
    beads = BeadsAdapter(foundation_root())
    beads_ready = False
    if beads.manifest_path.is_file():
        try:
            beads_ready = beads.health({"schema_version": 1})["status"] == "healthy"
        except (BridgeError, OSError, ValueError):
            beads_ready = False
    profile_transport = ProfileTransportService(foundation_root())
    profile_transport_ready = False
    if profile_transport.database.is_file():
        try:
            profile_transport_ready = (
                profile_transport.health({"schema_version": 1})["status"] == "healthy"
            )
        except (BridgeError, OSError, ValueError, sqlite3.Error):
            profile_transport_ready = False
    release_ready, release_receipt = release_verified(foundation_root())
    observability = ObservabilityService(foundation_root())
    observability_ready = False
    if observability.database.is_file():
        try:
            observability_ready = (
                observability.health({"schema_version": 1})["status"] == "healthy"
            )
        except (BridgeError, OSError, ValueError, sqlite3.Error):
            observability_ready = False
    components_ready = all(
        (
            runtime_receipt["status"] == "healthy",
            artifact_ready,
            dolt_ready,
            sql_authority_ready,
            memory_ready,
            graph_ready,
            zvec_ready,
            beads_ready,
            profile_transport_ready,
            observability_ready,
            release_ready,
        )
    )
    return receipt(
        {
            "schema_version": 1,
            "contract": "FoundationBridgeHealthReceipt",
            "status": "integration_ready" if components_ready else "degraded",
            "runtime_coordinator": runtime_receipt["status"],
            "artifact_service": "healthy" if artifact_ready else "unavailable",
            "dolt_state_adapter": "healthy" if dolt_ready else "unavailable",
            "dolt_sql_authority": "healthy" if sql_authority_ready else "unavailable",
            "agentmemory_adapter": "healthy" if memory_ready else "unavailable",
            "graphiti_adapter": "healthy" if graph_ready else "unavailable",
            "zvec_indexer": "healthy" if zvec_ready else "unavailable",
            "beads_adapter": "healthy" if beads_ready else "unavailable",
            "profile_transport": "healthy"
            if profile_transport_ready
            else "unavailable",
            "observability": "healthy" if observability_ready else "unavailable",
            "release_verification": "verified" if release_ready else "unverified",
            "release_source_commit": release_receipt["source_commit"]
            if release_receipt
            else None,
            "license_status": "Apache-2.0",
            "public_hooks_only": True,
            "second_agent_loop": False,
            "production_activation_allowed": False,
            "blockers": [
                *([] if release_ready else ["release_signature_unverified"]),
                *([] if memory_ready else ["agentmemory_release_missing"]),
                *([] if graph_ready else ["graphiti_release_missing"]),
                *([] if zvec_ready else ["zvec_release_missing"]),
                *([] if beads_ready else ["beads_service_probe_missing"]),
                *([] if sql_authority_ready else ["dolt_sql_authority_missing"]),
                *(
                    []
                    if profile_transport_ready
                    else ["profile_transport_release_missing"]
                ),
                *([] if observability_ready else ["observability_release_missing"]),
                "g0_g8_not_accepted",
            ],
        }
    )


def _coordinator() -> RuntimeCoordinator:
    return RuntimeCoordinator(foundation_root())


def _record(event_type: str, payload: dict[str, object]) -> None:
    try:
        queue = HookQueue(foundation_root())
        try:
            submitted = queue.admit(event_type, payload)
        except ValueError as error:
            if str(error) != "hook_queue_full":
                raise
            # A recovered coordinator must be able to make space before admission.
            result = queue.drain()
            submitted = queue.admit(event_type, payload)
        else:
            result = queue.drain()
        if submitted.get("fragment_issue"):
            logging.getLogger(__name__).warning(
                "foundation_fragment_registration_incomplete"
            )
        if result["quarantined"]:
            logging.getLogger(__name__).warning("foundation_hook_quarantined")
    except (BridgeError, OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
        logging.getLogger(__name__).warning("foundation_hook_not_fully_persisted")
        return


def on_session_start(**kwargs: object) -> None:
    _record("on_session_start", dict(kwargs))


def pre_llm_call(**kwargs: object) -> dict[str, str] | None:
    payload = dict(kwargs)
    _record("pre_llm_call", payload)
    try:
        memory = AgentMemoryAdapter(foundation_root())
        scope = memory.default_scope()
        user_message = payload.get("user_message")
        if scope is None or not isinstance(user_message, str) or not user_message:
            return None
        contribution = memory.context(
            {
                "schema_version": 1,
                "scope": scope,
                "query": user_message,
                "limit": 5,
            }
        )
        context = contribution["context"]
        if not isinstance(context, str) or not context:
            return None
        identity = str(payload.get("turn_id") or payload.get("session_id") or "unbound")
        _coordinator().enqueue(
            event_key=f"CTX-{sha256_json({'identity': identity})[:24]}",
            event_type="context_contribution",
            payload=contribution,
        )
        return {"context": context}
    except (BridgeError, OSError, RuntimeError, sqlite3.Error, ValueError):
        return None


def post_tool_call(**kwargs: object) -> None:
    _record("post_tool_call", dict(kwargs))


def post_llm_call(**kwargs: object) -> None:
    _record("post_llm_call", dict(kwargs))


def on_session_end(**kwargs: object) -> None:
    _record("on_session_end", dict(kwargs))
