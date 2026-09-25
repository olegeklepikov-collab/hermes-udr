"""Closed public tool schemas."""

ID = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"}
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
COMMIT = {"type": "string", "pattern": "^[0-9a-f]{40}$"}
IDS = {"type": "array", "items": ID, "uniqueItems": True}
NULLABLE_ID = {"anyOf": [ID, {"type": "null"}]}
NULLABLE_HASH = {"anyOf": [HASH, {"type": "null"}]}


def closed(required: list[str], properties: dict) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


VERSION_ONLY = closed(["schema_version"], {"schema_version": {"const": 1}})
RUNTIME_OBSERVATION = closed(
    ["status", "observed_at", "ttl_seconds"],
    {
        "status": {"type": "string"},
        "observed_at": {"type": "string", "format": "date-time"},
        "ttl_seconds": {"type": "integer", "minimum": 1},
    },
)
RUNTIME_SCHEMA_CACHE = closed(
    ["status", "observed_at", "ttl_seconds", "fingerprint"],
    {
        "status": {"enum": ["hit", "miss", "error"]},
        "observed_at": {"type": "string", "format": "date-time"},
        "ttl_seconds": {"type": "integer", "minimum": 1},
        "fingerprint": HASH,
    },
)
RUNTIME_CONTROL = closed(
    [
        "consecutive_failures",
        "failure_class",
        "retries_used",
        "circuit_state",
        "opened_until",
        "state_change_observed",
    ],
    {
        "consecutive_failures": {"type": "integer", "minimum": 0},
        "failure_class": {"enum": ["none", "transient", "permanent", "auth", "config"]},
        "retries_used": {"type": "integer", "minimum": 0},
        "circuit_state": {"enum": ["closed", "open", "half_open"]},
        "opened_until": {"type": ["string", "null"], "format": "date-time"},
        "state_change_observed": {"type": "boolean"},
    },
)
DESIRED_RUNTIME = closed(
    [
        "instance_id",
        "profile_id",
        "operation_id",
        "config_hash",
        "schema_fingerprint",
        "retry_budget",
        "open_after_failures",
        "observation_ttl_seconds",
    ],
    {
        "instance_id": ID,
        "profile_id": ID,
        "operation_id": ID,
        "config_hash": HASH,
        "schema_fingerprint": HASH,
        "retry_budget": {"type": "integer", "minimum": 0},
        "open_after_failures": {"type": "integer", "minimum": 1},
        "observation_ttl_seconds": {"type": "integer", "minimum": 1},
    },
)
EFFECTIVE_RUNTIME = closed(
    [
        "instance_id",
        "profile_id",
        "operation_id",
        "process_id",
        "loaded_config_hash",
        "loaded_at",
        "schema_cache",
        "live_connection",
        "characteristic_verification",
        "control",
    ],
    {
        "instance_id": ID,
        "profile_id": ID,
        "operation_id": ID,
        "process_id": ID,
        "loaded_config_hash": HASH,
        "loaded_at": {"type": "string", "format": "date-time"},
        "schema_cache": RUNTIME_SCHEMA_CACHE,
        "live_connection": RUNTIME_OBSERVATION,
        "characteristic_verification": RUNTIME_OBSERVATION,
        "control": RUNTIME_CONTROL,
    },
)
SCHEDULE_STATE = closed(
    [
        "schedule_id",
        "configured_enabled",
        "next_run_at",
        "last_run_at",
        "last_status",
        "last_success_at",
        "freshness_ttl_seconds",
    ],
    {
        "schedule_id": ID,
        "configured_enabled": {"type": "boolean"},
        "next_run_at": {"type": ["string", "null"], "format": "date-time"},
        "last_run_at": {"type": ["string", "null"], "format": "date-time"},
        "last_status": {"enum": ["never", "success", "failure", "running"]},
        "last_success_at": {"type": ["string", "null"], "format": "date-time"},
        "freshness_ttl_seconds": {"type": "integer", "minimum": 1},
    },
)
BACKUP_STATE = closed(
    [
        "backup_id",
        "expected_enabled",
        "last_attempt_at",
        "last_verified_success_at",
        "integrity_status",
        "max_age_seconds",
    ],
    {
        "backup_id": ID,
        "expected_enabled": {"type": "boolean"},
        "last_attempt_at": {"type": ["string", "null"], "format": "date-time"},
        "last_verified_success_at": {"type": ["string", "null"], "format": "date-time"},
        "integrity_status": {"enum": ["pass", "fail", "unknown"]},
        "max_age_seconds": {"type": "integer", "minimum": 1},
    },
)
EFFECTIVE_RUNTIME_RECONCILE = closed(
    [
        "schema_version",
        "captured_at",
        "desired_configs",
        "effective_runtimes",
        "schedules",
        "backups",
    ],
    {
        "schema_version": {"const": 1},
        "captured_at": {"type": "string", "format": "date-time"},
        "desired_configs": {"type": "array", "minItems": 1, "items": DESIRED_RUNTIME},
        "effective_runtimes": {
            "type": "array",
            "minItems": 1,
            "items": EFFECTIVE_RUNTIME,
        },
        "schedules": {"type": "array", "items": SCHEDULE_STATE},
        "backups": {"type": "array", "items": BACKUP_STATE},
    },
)
RELEASE_VERIFY = closed(
    ["schema_version", "expected_version", "expected_commit"],
    {
        "schema_version": {"const": 1},
        "expected_version": {"const": "0.12.0"},
        "expected_commit": COMMIT,
    },
)
PROFILE_GET = closed(
    ["schema_version", "profile_id"],
    {"schema_version": {"const": 1}, "profile_id": ID},
)
HANDOFF = closed(
    [
        "schema_version",
        "package_id",
        "revision",
        "from_profile",
        "to_profile",
        "artifact_refs",
        "test_refs",
        "computation_refs",
        "commit_refs",
        "checkpoint_ref",
        "accepted_effect_refs",
        "merge_owner",
    ],
    {
        "schema_version": {"const": 1},
        "package_id": ID,
        "revision": {"type": "integer", "minimum": 1},
        "from_profile": ID,
        "to_profile": ID,
        "artifact_refs": IDS,
        "test_refs": IDS,
        "computation_refs": IDS,
        "commit_refs": IDS,
        "checkpoint_ref": NULLABLE_ID,
        "accepted_effect_refs": IDS,
        "merge_owner": ID,
    },
)
REVIEW_POSITION = closed(
    [
        "schema_version",
        "package_id",
        "reviewer_profile",
        "reviewer_id",
        "artifact_refs",
        "author_conclusion_excluded",
        "author_acceptance_excluded",
        "position",
        "position_hash",
    ],
    {
        "schema_version": {"const": 1},
        "package_id": ID,
        "reviewer_profile": ID,
        "reviewer_id": ID,
        "artifact_refs": IDS,
        "author_conclusion_excluded": {"type": "boolean"},
        "author_acceptance_excluded": {"type": "boolean"},
        "position": {"type": "string", "minLength": 1},
        "position_hash": HASH,
    },
)
OPERATOR_EFFECT = closed(
    [
        "schema_version",
        "operator_profile",
        "effect_ref",
        "signed_decision_hash",
        "basis_hash_before",
        "basis_hash_after",
        "acceptance_ref_before",
        "acceptance_ref_after",
        "output_hash",
        "idempotency_key",
    ],
    {
        "schema_version": {"const": 1},
        "operator_profile": ID,
        "effect_ref": ID,
        "signed_decision_hash": HASH,
        "basis_hash_before": HASH,
        "basis_hash_after": HASH,
        "acceptance_ref_before": ID,
        "acceptance_ref_after": ID,
        "output_hash": HASH,
        "idempotency_key": ID,
    },
)
CHECKPOINT_RESUME = closed(
    [
        "schema_version",
        "package_id",
        "checkpoint_ref",
        "prior_worker_id",
        "new_worker_id",
        "new_lease_ref",
        "accepted_effect_refs",
        "requested_effect_refs",
    ],
    {
        "schema_version": {"const": 1},
        "package_id": ID,
        "checkpoint_ref": ID,
        "prior_worker_id": ID,
        "new_worker_id": ID,
        "new_lease_ref": ID,
        "accepted_effect_refs": IDS,
        "requested_effect_refs": IDS,
    },
)
MERGE_ASSESS = closed(
    [
        "schema_version",
        "writer_profile",
        "writer_id",
        "reviewer_profile",
        "reviewer_id",
        "worktree_ref",
        "commit_ref",
        "bead_ref",
        "review_ref",
        "review_status",
    ],
    {
        "schema_version": {"const": 1},
        "writer_profile": ID,
        "writer_id": ID,
        "reviewer_profile": ID,
        "reviewer_id": ID,
        "worktree_ref": ID,
        "commit_ref": ID,
        "bead_ref": ID,
        "review_ref": ID,
        "review_status": {"enum": ["accepted", "changes_required", "absent"]},
    },
)
TELEGRAM_INGRESS = closed(
    [
        "schema_version",
        "route",
        "route_qualified",
        "user_allowed",
        "chat_allowed",
        "user_hash",
        "chat_hash",
        "project_id",
        "run_id",
        "bead_id",
        "profile_id",
    ],
    {
        "schema_version": {"const": 1},
        "route": {"enum": ["dm_polling", "group", "webhook", "local_bot_api"]},
        "route_qualified": {"type": "boolean"},
        "user_allowed": {"type": "boolean"},
        "chat_allowed": {"type": "boolean"},
        "user_hash": HASH,
        "chat_hash": HASH,
        "project_id": ID,
        "run_id": ID,
        "bead_id": ID,
        "profile_id": ID,
    },
)
TELEGRAM_MEDIA = closed(
    [
        "schema_version",
        "media_ref",
        "binding_ref",
        "media_kind",
        "quarantined",
        "artifact_hash",
        "transcript_hash",
        "transformation_ref",
    ],
    {
        "schema_version": {"const": 1},
        "media_ref": ID,
        "binding_ref": ID,
        "media_kind": {"enum": ["file", "audio"]},
        "quarantined": {"type": "boolean"},
        "artifact_hash": HASH,
        "transcript_hash": NULLABLE_HASH,
        "transformation_ref": NULLABLE_ID,
    },
)
DELIVERY_PREPARE = closed(
    [
        "schema_version",
        "idempotency_key",
        "artifact_hash",
        "model_run_id",
        "host_visible_output",
        "accepted_artifact",
    ],
    {
        "schema_version": {"const": 1},
        "idempotency_key": ID,
        "artifact_hash": HASH,
        "model_run_id": ID,
        "host_visible_output": {"type": "boolean"},
        "accepted_artifact": {"type": "boolean"},
    },
)
DELIVERY_RECONCILE = closed(
    [
        "schema_version",
        "idempotency_key",
        "provider_status",
        "provider_accepted",
        "model_run_id",
    ],
    {
        "schema_version": {"const": 1},
        "idempotency_key": ID,
        "provider_status": {"enum": ["delivered", "timeout", "rejected", "unknown"]},
        "provider_accepted": {"type": "boolean"},
        "model_run_id": ID,
    },
)
DELIVERY_REDELIVER = closed(
    [
        "schema_version",
        "idempotency_key",
        "artifact_hash",
        "user_approved",
        "duplicate_visible",
        "model_rerun",
    ],
    {
        "schema_version": {"const": 1},
        "idempotency_key": ID,
        "artifact_hash": HASH,
        "user_approved": {"type": "boolean"},
        "duplicate_visible": {"type": "boolean"},
        "model_rerun": {"type": "boolean"},
    },
)
TELEGRAM_ROUTE = closed(
    ["schema_version", "route", "qualified"],
    {
        "schema_version": {"const": 1},
        "route": {"enum": ["dm_polling", "group", "webhook", "local_bot_api"]},
        "qualified": {"type": "boolean"},
    },
)
TRACE_RECORD = closed(
    [
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
    ],
    {
        "schema_version": {"const": 1},
        "trace_id": ID,
        "project_id": ID,
        "run_id": ID,
        "bead_id": ID,
        "profile_id": ID,
        "session_hash": HASH,
        "operation_id": ID,
        "attempt": {"type": "integer", "minimum": 1},
        "model_ref": ID,
        "tool_ref": NULLABLE_ID,
        "context_refs": IDS,
        "evidence_link_refs": IDS,
        "commit_refs": IDS,
        "latency_ms": {"type": "integer", "minimum": 0},
        "cost_microunits": {"type": "integer", "minimum": 0},
        "outcome_status": {
            "enum": ["success", "failed", "unknown", "blocked", "recovered"]
        },
        "priority": {"enum": ["P0", "P1", "P2"]},
        "collector_available": {"type": "boolean"},
        "sampling_decision": {"enum": ["keep", "drop"]},
        "ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
        "attributes": {"type": "object"},
    },
)
TRACE_RECONCILE = closed(
    ["schema_version", "collector_available"],
    {
        "schema_version": {"const": 1},
        "collector_available": {"type": "boolean"},
    },
)
_SYSTEM_CLASS = {
    "enum": [
        "profiles_gateway",
        "beads",
        "dolt_databases",
        "dolt_privileges_branch_control",
        "runtime_sqlite",
        "agentmemory",
        "graphiti_falkordb",
        "zvec_source_rebuild",
        "artifacts",
        "git_repositories",
        "dependency_locks",
        "configuration_manifests",
    ]
}
BACKUP_INVENTORY = closed(
    [
        "schema_version",
        "snapshot_id",
        "created_at",
        "max_age_seconds",
        "archive_receipts",
    ],
    {
        "schema_version": {"const": 1},
        "snapshot_id": ID,
        "created_at": {"type": "string", "minLength": 1},
        "max_age_seconds": {"type": "integer", "minimum": 1, "maximum": 2592000},
        "archive_receipts": {
            "type": "array",
            "minItems": 12,
            "maxItems": 12,
            "items": closed(
                [
                    "system_class",
                    "archive_name",
                    "archive_sha256",
                    "source_quiesced",
                    "encrypted",
                    "snapshot_readback",
                    "source_version_ref",
                ],
                {
                    "system_class": _SYSTEM_CLASS,
                    "archive_name": {"type": "string"},
                    "archive_sha256": HASH,
                    "source_quiesced": {"type": "boolean"},
                    "encrypted": {"type": "boolean"},
                    "snapshot_readback": {"type": "boolean"},
                    "source_version_ref": ID,
                },
            ),
        },
    },
)
RECOVERY_OBJECTIVES = closed(
    ["schema_version", "snapshot_id", "measurements"],
    {
        "schema_version": {"const": 1},
        "snapshot_id": ID,
        "measurements": {
            "type": "array",
            "minItems": 12,
            "maxItems": 12,
            "items": closed(
                [
                    "system_class",
                    "rpo_seconds",
                    "rto_seconds",
                    "measured_rpo_seconds",
                    "measured_rto_seconds",
                    "readback_verified",
                    "source_sequence_ref",
                ],
                {
                    "system_class": _SYSTEM_CLASS,
                    "rpo_seconds": {"type": "integer", "minimum": 0},
                    "rto_seconds": {"type": "integer", "minimum": 0},
                    "measured_rpo_seconds": {"type": "integer", "minimum": 0},
                    "measured_rto_seconds": {"type": "integer", "minimum": 0},
                    "readback_verified": {"type": "boolean"},
                    "source_sequence_ref": ID,
                },
            ),
        },
    },
)
RESTORE_ASSESS = closed(
    [
        "schema_version",
        "snapshot_id",
        "alternate_root_id",
        "gateway_autostart",
        "restore_receipts",
    ],
    {
        "schema_version": {"const": 1},
        "snapshot_id": ID,
        "alternate_root_id": ID,
        "gateway_autostart": {"type": "boolean"},
        "restore_receipts": {
            "type": "array",
            "minItems": 12,
            "maxItems": 12,
            "items": closed(
                [
                    "system_class",
                    "snapshot_id",
                    "restored_ref",
                    "content_hash",
                    "readback_hash",
                    "semantic_probe",
                    "secret_boundary_verified",
                ],
                {
                    "system_class": _SYSTEM_CLASS,
                    "snapshot_id": ID,
                    "restored_ref": {"type": "string"},
                    "content_hash": HASH,
                    "readback_hash": HASH,
                    "semantic_probe": {"type": "boolean"},
                    "secret_boundary_verified": {"type": "boolean"},
                },
            ),
        },
    },
)
CHECKPOINT_ASSESS = closed(
    [
        "schema_version",
        "checkpoint_id",
        "max_age_seconds",
        "max_capture_window_seconds",
        "barrier",
        "systems",
    ],
    {
        "schema_version": {"const": 1},
        "checkpoint_id": ID,
        "max_age_seconds": {"type": "integer", "minimum": 1, "maximum": 2592000},
        "max_capture_window_seconds": {
            "type": "integer",
            "minimum": 1,
            "maximum": 3600,
        },
        "barrier": closed(
            [
                "owner_id",
                "gateway_off",
                "sql_server_off",
                "docker_writers_off",
                "active_tool_invocations",
                "write_lease_count",
                "before_sequence_hash",
                "after_sequence_hash",
                "started_at",
                "released_at",
            ],
            {
                "owner_id": ID,
                "gateway_off": {"type": "boolean"},
                "sql_server_off": {"type": "boolean"},
                "docker_writers_off": {"type": "boolean"},
                "active_tool_invocations": {"type": "integer", "minimum": 0},
                "write_lease_count": {"type": "integer", "minimum": 0},
                "before_sequence_hash": HASH,
                "after_sequence_hash": HASH,
                "started_at": {"type": "string", "minLength": 1},
                "released_at": {"type": "string", "minLength": 1},
            },
        ),
        "systems": {
            "type": "array",
            "minItems": 12,
            "maxItems": 12,
            "items": closed(
                [
                    "system_class",
                    "checkpoint_id",
                    "archive_sha256",
                    "captured_at",
                    "source_sequence_ref",
                    "restored_sequence_ref",
                    "authenticated_decryption",
                    "alternate_readback",
                    "semantic_probe",
                    "secret_boundary",
                    "rpo_limit_seconds",
                    "rto_limit_seconds",
                    "measured_rpo_seconds",
                    "measured_rto_seconds",
                ],
                {
                    "system_class": _SYSTEM_CLASS,
                    "checkpoint_id": ID,
                    "archive_sha256": HASH,
                    "captured_at": {"type": "string", "minLength": 1},
                    "source_sequence_ref": ID,
                    "restored_sequence_ref": ID,
                    "authenticated_decryption": {"type": "boolean"},
                    "alternate_readback": {"type": "boolean"},
                    "semantic_probe": {"type": "boolean"},
                    "secret_boundary": {"type": "boolean"},
                    "rpo_limit_seconds": {"type": "integer", "minimum": 0},
                    "rto_limit_seconds": {"type": "integer", "minimum": 0},
                    "measured_rpo_seconds": {"type": "integer", "minimum": 0},
                    "measured_rto_seconds": {"type": "integer", "minimum": 0},
                },
            ),
        },
    },
)
MIGRATE = closed(
    ["schema_version", "apply"],
    {"schema_version": {"const": 1}, "apply": {"type": "boolean"}},
)
LEASE = closed(
    ["schema_version", "work_id", "holder_id", "expected_revision", "ttl_seconds"],
    {
        "schema_version": {"const": 1},
        "work_id": ID,
        "holder_id": ID,
        "expected_revision": {"type": "integer", "minimum": 1},
        "ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 86400},
    },
)
OUTBOX = closed(
    ["schema_version", "event_key", "event_type", "payload"],
    {
        "schema_version": {"const": 1},
        "event_key": ID,
        "event_type": ID,
        "payload": {"type": "object"},
    },
)
DOLT_PUT = closed(
    [
        "schema_version",
        "database",
        "project_id",
        "object_id",
        "expected_revision",
        "content_hash",
        "schema_id",
        "object",
        "operation_id",
        "run_id",
    ],
    {
        "schema_version": {"const": 1},
        "database": {"enum": ["kw_core", "kw_context", "kw_quant", "kw_registry"]},
        "project_id": ID,
        "object_id": ID,
        "expected_revision": {"type": "integer", "minimum": 0},
        "content_hash": HASH,
        "schema_id": ID,
        "object": {"type": "object"},
        "operation_id": ID,
        "run_id": ID,
    },
)
DOLT_GET = closed(
    ["schema_version", "database", "project_id", "object_id"],
    {
        "schema_version": {"const": 1},
        "database": {"enum": ["kw_core", "kw_context", "kw_quant", "kw_registry"]},
        "project_id": ID,
        "object_id": ID,
    },
)
ARTIFACT_INGEST = closed(
    ["schema_version", "acquisition_id", "relative_path", "media_type", "max_bytes"],
    {
        "schema_version": {"const": 1},
        "acquisition_id": ID,
        "relative_path": {"type": "string", "minLength": 1, "maxLength": 512},
        "media_type": {"type": "string", "minLength": 1, "maxLength": 128},
        "max_bytes": {"type": "integer", "minimum": 1, "maximum": 67108864},
    },
)
ARTIFACT_TOMBSTONE = closed(
    ["schema_version", "artifact_id", "reason_code"],
    {"schema_version": {"const": 1}, "artifact_id": ID, "reason_code": ID},
)
INDEX_UPSERT = closed(
    [
        "schema_version",
        "document_id",
        "artifact_id",
        "source_ref",
        "content",
        "content_hash",
    ],
    {
        "schema_version": {"const": 1},
        "document_id": ID,
        "artifact_id": ID,
        "source_ref": {"type": "string", "minLength": 1},
        "content": {"type": "string", "minLength": 1},
        "content_hash": HASH,
    },
)
INDEX_QUERY = closed(
    ["schema_version", "query", "limit"],
    {
        "schema_version": {"const": 1},
        "query": {"type": "string", "minLength": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    },
)
INDEX_REBUILD = closed(
    ["schema_version", "apply", "expected_document_count", "expected_active_count"],
    {
        "schema_version": {"const": 1},
        "apply": {"type": "boolean"},
        "expected_document_count": {"type": "integer", "minimum": 0},
        "expected_active_count": {"type": "integer", "minimum": 0},
        "generation_action": {"enum": ["replace", "rollback"]},
        "generation_id": ID,
    },
)
INDEX_REBUILD["dependentRequired"] = {
    "generation_action": ["generation_id"],
    "generation_id": ["generation_action"],
}
INDEX_TOMBSTONE = closed(
    ["schema_version", "artifact_id"],
    {"schema_version": {"const": 1}, "artifact_id": ID},
)
MEMORY_SCOPE = closed(
    ["tenant_id", "project_id", "profile_id", "work_kind"],
    {
        "tenant_id": ID,
        "project_id": ID,
        "profile_id": ID,
        "work_kind": ID,
    },
)
MEMORY_SCOPE_SET = closed(
    ["schema_version", "scope"],
    {"schema_version": {"const": 1}, "scope": MEMORY_SCOPE},
)
MEMORY_SAVE = closed(
    ["schema_version", "scope", "content", "concepts"],
    {
        "schema_version": {"const": 1},
        "scope": MEMORY_SCOPE,
        "content": {"type": "string", "minLength": 1},
        "concepts": {"type": "array", "items": {"type": "string"}},
    },
)
MEMORY_SEARCH = closed(
    ["schema_version", "scope", "query", "limit"],
    {
        "schema_version": {"const": 1},
        "scope": MEMORY_SCOPE,
        "query": {"type": "string", "minLength": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
)
BEADS_CREATE = closed(
    ["schema_version", "title", "description", "priority", "issue_type"],
    {
        "schema_version": {"const": 1},
        "operation_key": ID,
        "title": {"type": "string", "minLength": 1, "maxLength": 160},
        "description": {"type": "string", "minLength": 1, "maxLength": 4000},
        "priority": {"type": "integer", "minimum": 0, "maximum": 4},
        "issue_type": {"enum": ["task", "feature", "bug", "chore"]},
    },
)
BEADS_GET = closed(
    ["schema_version", "issue_id"],
    {"schema_version": {"const": 1}, "issue_id": {"type": "string"}},
)
BEADS_CLAIM = closed(
    ["schema_version", "issue_id", "worker_id"],
    {
        "schema_version": {"const": 1},
        "operation_key": ID,
        "issue_id": {"type": "string"},
        "worker_id": ID,
    },
)
BEADS_CLOSE = closed(
    ["schema_version", "issue_id", "reason_code", "worker_id"],
    {
        "schema_version": {"const": 1},
        "operation_key": ID,
        "issue_id": {"type": "string"},
        "reason_code": ID,
        "worker_id": ID,
    },
)
WORK_RECONCILE = closed(
    [
        "schema_version",
        "issue_id",
        "lease_status",
        "artifact_status",
        "review_status",
        "dolt_commit_ref",
        "outbox_status",
        "writer_count",
        "expected_revision",
        "current_revision",
    ],
    {
        "schema_version": {"const": 1},
        "issue_id": {"type": "string"},
        "lease_status": {"enum": ["absent", "active", "stale"]},
        "artifact_status": {"enum": ["absent", "draft", "submitted", "accepted"]},
        "review_status": {
            "enum": ["absent", "review_required", "changes_required", "accepted"]
        },
        "dolt_commit_ref": {"type": ["string", "null"]},
        "outbox_status": {"enum": ["empty", "pending", "done", "failed"]},
        "writer_count": {"type": "integer", "minimum": 0},
        "expected_revision": {"type": "integer", "minimum": 1},
        "current_revision": {"type": "integer", "minimum": 1},
    },
)
GRAPH_PUT = closed(
    [
        "schema_version",
        "project_id",
        "fact_id",
        "text",
        "text_hash",
        "source_ref",
        "artifact_id",
    ],
    {
        "schema_version": {"const": 1},
        "project_id": ID,
        "fact_id": ID,
        "text": {"type": "string", "minLength": 1},
        "text_hash": HASH,
        "source_ref": {"type": "string", "minLength": 1},
        "artifact_id": ID,
    },
)
GRAPH_SEARCH = closed(
    ["schema_version", "project_id", "query", "limit"],
    {
        "schema_version": {"const": 1},
        "project_id": ID,
        "query": {"type": "string", "minLength": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    },
)
FRAGMENT = closed(
    [
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
    ],
    {
        "fragment_id": ID,
        "run_id": ID,
        "source_system": {
            "enum": [
                "zvec",
                "web",
                "file",
                "agentmemory",
                "graphiti",
                "user",
                "tool",
                "database",
            ]
        },
        "source_ref": {"type": "string"},
        "source_version": {"type": "string"},
        "locator": {"type": "string"},
        "exact_fragment": {"type": "string"},
        "content_hash": HASH,
        "transformation_refs": {"type": "array", "items": {"type": "string"}},
        "retrieval_query": {"type": "string"},
        "rank_or_score": {"type": ["number", "null"]},
    },
)
FRAGMENT_RECORD = closed(
    ["schema_version", "event_key", "fragment"],
    {"schema_version": {"const": 1}, "event_key": ID, "fragment": FRAGMENT},
)
PROMOTION_CHECKS = closed(
    [
        "source_resolved",
        "version_resolved",
        "locator_verified",
        "exact_hash_verified",
        "within_limits",
        "secret_scan_pass",
        "transformations_resolved",
        "primary_readback",
    ],
    {
        name: {"type": "boolean"}
        for name in (
            "source_resolved",
            "version_resolved",
            "locator_verified",
            "exact_hash_verified",
            "within_limits",
            "secret_scan_pass",
            "transformations_resolved",
            "primary_readback",
        )
    },
)
FRAGMENT_PROMOTE = closed(
    ["schema_version", "fragment", "checks", "requested_evidence_class"],
    {
        "schema_version": {"const": 1},
        "fragment": FRAGMENT,
        "checks": PROMOTION_CHECKS,
        "requested_evidence_class": {"type": "string"},
    },
)
RECONCILE = closed(
    [
        "schema_version",
        "work_id",
        "bead_status",
        "lease_status",
        "artifact_status",
        "review_status",
        "dolt_commit_ref",
        "outbox_status",
        "writer_count",
        "expected_revision",
        "current_revision",
    ],
    {
        "schema_version": {"const": 1},
        "work_id": ID,
        "bead_status": {"enum": ["open", "claimed", "closed"]},
        "lease_status": {"enum": ["absent", "active", "stale"]},
        "artifact_status": {"enum": ["absent", "draft", "submitted", "accepted"]},
        "review_status": {
            "enum": ["absent", "review_required", "changes_required", "accepted"]
        },
        "dolt_commit_ref": {"type": ["string", "null"]},
        "outbox_status": {"enum": ["empty", "pending", "done", "failed"]},
        "writer_count": {"type": "integer", "minimum": 0},
        "expected_revision": {"type": "integer", "minimum": 1},
        "current_revision": {"type": "integer", "minimum": 1},
    },
)
