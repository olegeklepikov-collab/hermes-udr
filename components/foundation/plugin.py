"""Hermes public plugin entry point for the greenfield foundation bridge."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

try:
    from .src.hermes_foundation_bridge.agentmemory_adapter import AgentMemoryAdapter
    from .src.hermes_foundation_bridge.artifacts import ArtifactService
    from .src.hermes_foundation_bridge.authority import authority_map
    from .src.hermes_foundation_bridge.beads_adapter import BeadsAdapter
    from .src.hermes_foundation_bridge.bridge import (
        health,
        migrate,
        on_session_end,
        on_session_start,
        post_llm_call,
        post_tool_call,
        pre_llm_call,
        services,
    )
    from .src.hermes_foundation_bridge.config import foundation_root
    from .src.hermes_foundation_bridge.dolt_sql import DoltSQLAdapter
    from .src.hermes_foundation_bridge.effective_runtime import (
        reconcile_effective_runtime,
    )
    from .src.hermes_foundation_bridge.errors import BridgeError
    from .src.hermes_foundation_bridge.fragments import promote, record_fragment
    from .src.hermes_foundation_bridge.gates import (
        FAILURE_SUITE_SCHEMA,
        GATE_VECTOR_SCHEMA,
        assess_failure_suite,
        evaluate_gate_vector,
    )
    from .src.hermes_foundation_bridge.graphiti_adapter import GraphitiAdapter
    from .src.hermes_foundation_bridge.observability import ObservabilityService
    from .src.hermes_foundation_bridge.profile_transport import ProfileTransportService
    from .src.hermes_foundation_bridge.recovery import RecoveryService
    from .src.hermes_foundation_bridge.release import verify_release
    from .src.hermes_foundation_bridge.runtime import outbox_request
    from .src.hermes_foundation_bridge.schemas import (
        ARTIFACT_INGEST,
        ARTIFACT_TOMBSTONE,
        BACKUP_INVENTORY,
        BEADS_CLAIM,
        BEADS_CLOSE,
        BEADS_CREATE,
        BEADS_GET,
        CHECKPOINT_ASSESS,
        CHECKPOINT_RESUME,
        DELIVERY_PREPARE,
        DELIVERY_RECONCILE,
        DELIVERY_REDELIVER,
        DOLT_GET,
        DOLT_PUT,
        EFFECTIVE_RUNTIME_RECONCILE,
        FRAGMENT_PROMOTE,
        FRAGMENT_RECORD,
        GRAPH_PUT,
        GRAPH_SEARCH,
        HANDOFF,
        INDEX_QUERY,
        INDEX_REBUILD,
        INDEX_TOMBSTONE,
        INDEX_UPSERT,
        LEASE,
        MEMORY_SAVE,
        MEMORY_SCOPE_SET,
        MEMORY_SEARCH,
        MERGE_ASSESS,
        MIGRATE,
        OPERATOR_EFFECT,
        OUTBOX,
        PROFILE_GET,
        RECONCILE,
        RECOVERY_OBJECTIVES,
        RELEASE_VERIFY,
        RESTORE_ASSESS,
        REVIEW_POSITION,
        TELEGRAM_INGRESS,
        TELEGRAM_MEDIA,
        TELEGRAM_ROUTE,
        TRACE_RECONCILE,
        TRACE_RECORD,
        VERSION_ONLY,
        WORK_RECONCILE,
    )
    from .src.hermes_foundation_bridge.zvec_index import ZvecIndexer, migrate_request
except ImportError:
    from hermes_foundation_bridge.agentmemory_adapter import AgentMemoryAdapter
    from hermes_foundation_bridge.artifacts import ArtifactService
    from hermes_foundation_bridge.authority import authority_map
    from hermes_foundation_bridge.beads_adapter import BeadsAdapter
    from hermes_foundation_bridge.bridge import (
        health,
        migrate,
        on_session_end,
        on_session_start,
        post_llm_call,
        post_tool_call,
        pre_llm_call,
        services,
    )
    from hermes_foundation_bridge.config import foundation_root
    from hermes_foundation_bridge.dolt_sql import DoltSQLAdapter
    from hermes_foundation_bridge.effective_runtime import reconcile_effective_runtime
    from hermes_foundation_bridge.errors import BridgeError
    from hermes_foundation_bridge.fragments import promote, record_fragment
    from hermes_foundation_bridge.gates import (
        FAILURE_SUITE_SCHEMA,
        GATE_VECTOR_SCHEMA,
        assess_failure_suite,
        evaluate_gate_vector,
    )
    from hermes_foundation_bridge.graphiti_adapter import GraphitiAdapter
    from hermes_foundation_bridge.observability import ObservabilityService
    from hermes_foundation_bridge.profile_transport import ProfileTransportService
    from hermes_foundation_bridge.recovery import RecoveryService
    from hermes_foundation_bridge.release import verify_release
    from hermes_foundation_bridge.runtime import outbox_request
    from hermes_foundation_bridge.schemas import (
        ARTIFACT_INGEST,
        ARTIFACT_TOMBSTONE,
        BACKUP_INVENTORY,
        BEADS_CLAIM,
        BEADS_CLOSE,
        BEADS_CREATE,
        BEADS_GET,
        CHECKPOINT_ASSESS,
        CHECKPOINT_RESUME,
        DELIVERY_PREPARE,
        DELIVERY_RECONCILE,
        DELIVERY_REDELIVER,
        DOLT_GET,
        DOLT_PUT,
        EFFECTIVE_RUNTIME_RECONCILE,
        FRAGMENT_PROMOTE,
        FRAGMENT_RECORD,
        GRAPH_PUT,
        GRAPH_SEARCH,
        HANDOFF,
        INDEX_QUERY,
        INDEX_REBUILD,
        INDEX_TOMBSTONE,
        INDEX_UPSERT,
        LEASE,
        MEMORY_SAVE,
        MEMORY_SCOPE_SET,
        MEMORY_SEARCH,
        MERGE_ASSESS,
        MIGRATE,
        OPERATOR_EFFECT,
        OUTBOX,
        PROFILE_GET,
        RECONCILE,
        RECOVERY_OBJECTIVES,
        RELEASE_VERIFY,
        RESTORE_ASSESS,
        REVIEW_POSITION,
        TELEGRAM_INGRESS,
        TELEGRAM_MEDIA,
        TELEGRAM_ROUTE,
        TRACE_RECONCILE,
        TRACE_RECORD,
        VERSION_ONLY,
        WORK_RECONCILE,
    )
    from hermes_foundation_bridge.zvec_index import ZvecIndexer, migrate_request


def _handle(function: Callable[[object], dict[str, Any]], request: object) -> str:
    try:
        result = function(request)
    except BridgeError as error:
        result = {"status": "error", "error": error.as_dict()}
    except (ValueError, OSError, RuntimeError) as error:
        as_dict = getattr(error, "as_dict", None)
        if callable(as_dict):
            result = {"status": "error", "error": as_dict()}
        else:
            result = {
                "status": "error",
                "error": {
                    "code": "bridge_internal_error",
                    "path": "request",
                    "message": type(error).__name__,
                },
            }
    return json.dumps(
        result,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def handle_migrate(args: object, **_kwargs: object) -> str:
    return _handle(migrate, args)


def handle_health(args: object, **_kwargs: object) -> str:
    return _handle(health, args)


def handle_release_verify(args: object, **_kwargs: object) -> str:
    return _handle(lambda request: verify_release(request, foundation_root()), args)


def _profile_transport() -> ProfileTransportService:
    return ProfileTransportService(foundation_root())


def handle_profiles_migrate(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().migrate, args)


def handle_profile_get(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().profile_get, args)


def handle_profiles_health(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().health, args)


def handle_handoff_record(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().handoff, args)


def handle_review_position_record(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().review_position, args)


def handle_operator_effect_record(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().operator_effect, args)


def handle_checkpoint_resume(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().resume, args)


def handle_merge_assess(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().merge_assess, args)


def handle_telegram_ingress(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().telegram_ingress, args)


def handle_telegram_media(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().media_ingest, args)


def handle_delivery_prepare(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().delivery_prepare, args)


def handle_delivery_reconcile(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().delivery_reconcile, args)


def handle_delivery_redeliver(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().delivery_redeliver, args)


def handle_telegram_route(args: object, **_kwargs: object) -> str:
    return _handle(_profile_transport().route_assess, args)


def _observability() -> ObservabilityService:
    return ObservabilityService(foundation_root())


def handle_observability_migrate(args: object, **_kwargs: object) -> str:
    return _handle(_observability().migrate, args)


def handle_trace_record(args: object, **_kwargs: object) -> str:
    return _handle(_observability().record, args)


def handle_trace_reconcile(args: object, **_kwargs: object) -> str:
    return _handle(_observability().reconcile, args)


def handle_trace_health(args: object, **_kwargs: object) -> str:
    return _handle(_observability().health, args)


def _recovery() -> RecoveryService:
    return RecoveryService(foundation_root())


def handle_backup_inventory(args: object, **_kwargs: object) -> str:
    return _handle(_recovery().inventory, args)


def handle_recovery_objectives(args: object, **_kwargs: object) -> str:
    return _handle(_recovery().objectives, args)


def handle_restore_assess(args: object, **_kwargs: object) -> str:
    return _handle(_recovery().restore_assess, args)


def handle_checkpoint_assess(args: object, **_kwargs: object) -> str:
    return _handle(_recovery().checkpoint_assess, args)


def handle_authority(args: object, **_kwargs: object) -> str:
    return _handle(authority_map, args)


def handle_lease(args: object, **_kwargs: object) -> str:
    coordinator, _artifacts, _dolt = services()
    return _handle(coordinator.acquire_lease, args)


def handle_outbox(args: object, **_kwargs: object) -> str:
    coordinator, _artifacts, _dolt = services()
    return _handle(lambda request: outbox_request(request, coordinator), args)


def handle_effective_runtime_reconcile(args: object, **_kwargs: object) -> str:
    return _handle(reconcile_effective_runtime, args)


def handle_failure_suite_assess(args: object, **_kwargs: object) -> str:
    return _handle(assess_failure_suite, args)


def handle_gate_vector_evaluate(args: object, **_kwargs: object) -> str:
    return _handle(evaluate_gate_vector, args)


def handle_dolt_put(args: object, **_kwargs: object) -> str:
    _runtime, _artifacts, dolt = services()
    return _handle(dolt.put, args)


def handle_dolt_get(args: object, **_kwargs: object) -> str:
    _runtime, _artifacts, dolt = services()
    return _handle(dolt.get, args)


def handle_dolt_sql_health(args: object, **_kwargs: object) -> str:
    return _handle(DoltSQLAdapter(foundation_root()).health, args)


def _artifact_service() -> ArtifactService:
    return ArtifactService(foundation_root())


def handle_artifact_ingest(args: object, **_kwargs: object) -> str:
    return _handle(_artifact_service().ingest, args)


def handle_artifact_recover(args: object, **_kwargs: object) -> str:
    def recover(_request: object) -> dict[str, Any]:
        return _artifact_service().recover()

    return _handle(recover, args)


def handle_artifact_tombstone(args: object, **_kwargs: object) -> str:
    return _handle(_artifact_service().tombstone, args)


def _zvec_indexer() -> ZvecIndexer:
    return ZvecIndexer(foundation_root())


def handle_index_migrate(args: object, **_kwargs: object) -> str:
    return _handle(lambda request: migrate_request(request, _zvec_indexer()), args)


def handle_index_upsert(args: object, **_kwargs: object) -> str:
    return _handle(_zvec_indexer().upsert, args)


def handle_index_query(args: object, **_kwargs: object) -> str:
    return _handle(_zvec_indexer().query, args)


def handle_index_rebuild(args: object, **_kwargs: object) -> str:
    return _handle(_zvec_indexer().rebuild_from_sources, args)


def handle_index_tombstone(args: object, **_kwargs: object) -> str:
    return _handle(_zvec_indexer().tombstone, args)


def _graphiti_adapter() -> GraphitiAdapter:
    return GraphitiAdapter(foundation_root())


def handle_graph_migrate(args: object, **_kwargs: object) -> str:
    return _handle(_graphiti_adapter().migrate, args)


def handle_graph_health(args: object, **_kwargs: object) -> str:
    return _handle(_graphiti_adapter().health, args)


def handle_graph_circuit_get(args: object, **_kwargs: object) -> str:
    return _handle(_graphiti_adapter().circuit_status, args)


def handle_graph_fact_put(args: object, **_kwargs: object) -> str:
    return _handle(_graphiti_adapter().put_fact, args)


def handle_graph_search(args: object, **_kwargs: object) -> str:
    return _handle(_graphiti_adapter().search, args)


def handle_graph_tombstone(args: object, **_kwargs: object) -> str:
    return _handle(_graphiti_adapter().tombstone_request, args)


def _memory_adapter() -> AgentMemoryAdapter:
    return AgentMemoryAdapter(foundation_root())


def handle_memory_migrate(args: object, **_kwargs: object) -> str:
    return _handle(_memory_adapter().migrate, args)


def handle_memory_health(args: object, **_kwargs: object) -> str:
    return _handle(_memory_adapter().health, args)


def handle_memory_scope_set(args: object, **_kwargs: object) -> str:
    return _handle(_memory_adapter().set_default_scope, args)


def handle_memory_save(args: object, **_kwargs: object) -> str:
    return _handle(_memory_adapter().save, args)


def handle_memory_search(args: object, **_kwargs: object) -> str:
    return _handle(_memory_adapter().search, args)


def handle_memory_context(args: object, **_kwargs: object) -> str:
    return _handle(_memory_adapter().context, args)


def _beads_adapter() -> BeadsAdapter:
    return BeadsAdapter(foundation_root())


def handle_beads_migrate(args: object, **_kwargs: object) -> str:
    return _handle(_beads_adapter().migrate, args)


def handle_beads_health(args: object, **_kwargs: object) -> str:
    return _handle(_beads_adapter().health, args)


def handle_beads_create(args: object, **_kwargs: object) -> str:
    return _handle(_beads_adapter().create, args)


def handle_beads_get(args: object, **_kwargs: object) -> str:
    return _handle(_beads_adapter().get, args)


def handle_beads_claim(args: object, **_kwargs: object) -> str:
    return _handle(_beads_adapter().claim, args)


def handle_beads_close(args: object, **_kwargs: object) -> str:
    return _handle(_beads_adapter().close, args)


def handle_work_reconcile(args: object, **_kwargs: object) -> str:
    return _handle(_beads_adapter().reconcile, args)


def handle_fragment_record(args: object, **_kwargs: object) -> str:
    coordinator, _artifacts, _dolt = services()
    return _handle(lambda request: record_fragment(request, coordinator), args)


def handle_fragment_promote(args: object, **_kwargs: object) -> str:
    coordinator, _artifacts, _dolt = services()
    return _handle(lambda request: promote(request, coordinator), args)


def handle_reconcile(args: object, **_kwargs: object) -> str:
    try:
        from hermes_research_report import reconcile_state
    except ImportError:
        return _handle(lambda _request: (_ for _ in ()).throw(RuntimeError()), args)
    return _handle(reconcile_state, args)


def register(ctx: Any) -> None:
    tools = (
        ("foundation_bridge_migrate", MIGRATE, handle_migrate),
        ("foundation_bridge_health", VERSION_ONLY, handle_health),
        ("foundation_release_verify", RELEASE_VERIFY, handle_release_verify),
        ("foundation_profiles_migrate", MIGRATE, handle_profiles_migrate),
        ("foundation_profiles_health", VERSION_ONLY, handle_profiles_health),
        ("foundation_profile_get", PROFILE_GET, handle_profile_get),
        ("foundation_handoff_record", HANDOFF, handle_handoff_record),
        (
            "foundation_review_position_record",
            REVIEW_POSITION,
            handle_review_position_record,
        ),
        (
            "foundation_operator_effect_record",
            OPERATOR_EFFECT,
            handle_operator_effect_record,
        ),
        ("foundation_checkpoint_resume", CHECKPOINT_RESUME, handle_checkpoint_resume),
        ("foundation_merge_assess", MERGE_ASSESS, handle_merge_assess),
        ("foundation_telegram_ingress", TELEGRAM_INGRESS, handle_telegram_ingress),
        ("foundation_telegram_media", TELEGRAM_MEDIA, handle_telegram_media),
        ("foundation_delivery_prepare", DELIVERY_PREPARE, handle_delivery_prepare),
        (
            "foundation_delivery_reconcile",
            DELIVERY_RECONCILE,
            handle_delivery_reconcile,
        ),
        (
            "foundation_delivery_redeliver",
            DELIVERY_REDELIVER,
            handle_delivery_redeliver,
        ),
        ("foundation_telegram_route", TELEGRAM_ROUTE, handle_telegram_route),
        ("foundation_observability_migrate", MIGRATE, handle_observability_migrate),
        ("foundation_trace_record", TRACE_RECORD, handle_trace_record),
        ("foundation_trace_reconcile", TRACE_RECONCILE, handle_trace_reconcile),
        ("foundation_trace_health", VERSION_ONLY, handle_trace_health),
        ("foundation_backup_inventory", BACKUP_INVENTORY, handle_backup_inventory),
        (
            "foundation_recovery_objectives",
            RECOVERY_OBJECTIVES,
            handle_recovery_objectives,
        ),
        ("foundation_restore_assess", RESTORE_ASSESS, handle_restore_assess),
        ("foundation_checkpoint_assess", CHECKPOINT_ASSESS, handle_checkpoint_assess),
        ("foundation_authority_get", VERSION_ONLY, handle_authority),
        ("foundation_runtime_lease", LEASE, handle_lease),
        ("foundation_outbox_enqueue", OUTBOX, handle_outbox),
        (
            "foundation_effective_runtime_reconcile",
            EFFECTIVE_RUNTIME_RECONCILE,
            handle_effective_runtime_reconcile,
        ),
        (
            "foundation_failure_suite_assess",
            FAILURE_SUITE_SCHEMA,
            handle_failure_suite_assess,
        ),
        (
            "foundation_gate_vector_evaluate",
            GATE_VECTOR_SCHEMA,
            handle_gate_vector_evaluate,
        ),
        ("foundation_dolt_put", DOLT_PUT, handle_dolt_put),
        ("foundation_dolt_get", DOLT_GET, handle_dolt_get),
        ("foundation_dolt_sql_health", VERSION_ONLY, handle_dolt_sql_health),
        ("foundation_artifact_ingest", ARTIFACT_INGEST, handle_artifact_ingest),
        ("foundation_artifact_recover", VERSION_ONLY, handle_artifact_recover),
        (
            "foundation_artifact_tombstone",
            ARTIFACT_TOMBSTONE,
            handle_artifact_tombstone,
        ),
        ("foundation_index_migrate", MIGRATE, handle_index_migrate),
        ("foundation_index_upsert", INDEX_UPSERT, handle_index_upsert),
        ("foundation_index_query", INDEX_QUERY, handle_index_query),
        ("foundation_index_rebuild", INDEX_REBUILD, handle_index_rebuild),
        ("foundation_index_tombstone", INDEX_TOMBSTONE, handle_index_tombstone),
        ("foundation_graph_migrate", MIGRATE, handle_graph_migrate),
        ("foundation_graph_health", VERSION_ONLY, handle_graph_health),
        ("foundation_graph_circuit_get", VERSION_ONLY, handle_graph_circuit_get),
        ("foundation_graph_fact_put", GRAPH_PUT, handle_graph_fact_put),
        ("foundation_graph_search", GRAPH_SEARCH, handle_graph_search),
        ("foundation_graph_tombstone", INDEX_TOMBSTONE, handle_graph_tombstone),
        ("foundation_memory_migrate", MIGRATE, handle_memory_migrate),
        ("foundation_memory_health", VERSION_ONLY, handle_memory_health),
        ("foundation_memory_scope_set", MEMORY_SCOPE_SET, handle_memory_scope_set),
        ("foundation_memory_save", MEMORY_SAVE, handle_memory_save),
        ("foundation_memory_search", MEMORY_SEARCH, handle_memory_search),
        ("foundation_memory_context", MEMORY_SEARCH, handle_memory_context),
        ("foundation_beads_migrate", MIGRATE, handle_beads_migrate),
        ("foundation_beads_health", VERSION_ONLY, handle_beads_health),
        ("foundation_beads_create", BEADS_CREATE, handle_beads_create),
        ("foundation_beads_get", BEADS_GET, handle_beads_get),
        ("foundation_beads_claim", BEADS_CLAIM, handle_beads_claim),
        ("foundation_beads_close", BEADS_CLOSE, handle_beads_close),
        ("foundation_work_reconcile", WORK_RECONCILE, handle_work_reconcile),
        ("foundation_fragment_record", FRAGMENT_RECORD, handle_fragment_record),
        ("foundation_fragment_promote", FRAGMENT_PROMOTE, handle_fragment_promote),
        ("foundation_state_reconcile", RECONCILE, handle_reconcile),
    )
    for name, schema, handler in tools:
        ctx.register_tool(
            name=name,
            toolset="foundation",
            schema=schema,
            handler=handler,
            check_fn=lambda: True,
        )
    for name, callback in (
        ("on_session_start", on_session_start),
        ("pre_llm_call", pre_llm_call),
        ("post_tool_call", post_tool_call),
        ("post_llm_call", post_llm_call),
        ("on_session_end", on_session_end),
    ):
        ctx.register_hook(name, callback)
