"""Public JSON schemas for Hermes tool registration."""

from __future__ import annotations

_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_ID = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"}

GREENFIELD_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "deployment_mode",
        "target",
        "source_instances",
        "target_roots",
        "stores",
        "profiles",
        "new_identity_flags",
        "old_instance_dependency",
        "operational_assets_copied",
        "bootstrap_import_count",
        "transfer_items",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "deployment_mode": {"const": "greenfield"},
        "target": {
            "type": "object",
            "additionalProperties": False,
            "required": ["instance_id", "service_identity"],
            "properties": {"instance_id": _ID, "service_identity": _ID},
        },
        "source_instances": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["instance_id", "root"],
                "properties": {
                    "instance_id": _ID,
                    "root": {"type": "string", "minLength": 2},
                },
            },
        },
        "target_roots": {
            "type": "array",
            "minItems": 7,
            "maxItems": 7,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["root_kind", "path", "existed_before", "empty_before"],
                "properties": {
                    "root_kind": {"type": "string"},
                    "path": {"type": "string", "minLength": 2},
                    "existed_before": {"type": "boolean"},
                    "empty_before": {"type": "boolean"},
                },
            },
        },
        "stores": {
            "type": "array",
            "minItems": 8,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "store_type",
                    "created_from_empty",
                    "initial_object_count",
                    "source",
                ],
                "properties": {
                    "store_type": {"type": "string"},
                    "created_from_empty": {"type": "boolean"},
                    "initial_object_count": {"type": "integer", "minimum": 0},
                    "source": {"enum": ["migration", "manifest", "empty_root"]},
                },
            },
        },
        "profiles": {
            "type": "array",
            "minItems": 8,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "profile_id",
                    "created_blank",
                    "cloned_from",
                    "initial_state_count",
                    "qualification_status",
                ],
                "properties": {
                    "profile_id": {"type": "string"},
                    "created_blank": {"type": "boolean"},
                    "cloned_from": {"type": "null"},
                    "initial_state_count": {"type": "integer", "minimum": 0},
                    "qualification_status": {"const": "not_started"},
                },
            },
        },
        "new_identity_flags": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "service_identity",
                "instance",
                "profiles",
                "service_units",
                "ports",
                "secrets",
                "telegram",
            ],
            "properties": {
                key: {"type": "boolean"}
                for key in (
                    "service_identity",
                    "instance",
                    "profiles",
                    "service_units",
                    "ports",
                    "secrets",
                    "telegram",
                )
            },
        },
        "old_instance_dependency": {"type": "boolean"},
        "operational_assets_copied": {"type": "integer", "minimum": 0},
        "bootstrap_import_count": {"type": "integer", "minimum": 0},
        "transfer_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "asset_class",
                    "transfer_mode",
                    "reference",
                    "content_hash",
                ],
                "properties": {
                    "asset_class": {"type": "string"},
                    "transfer_mode": {
                        "enum": [
                            "normative_document",
                            "exact_release",
                            "synthetic_fixture",
                        ]
                    },
                    "reference": {"type": "string", "minLength": 1},
                    "content_hash": _HASH,
                },
            },
        },
    },
}

GREENFIELD_ACCEPT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "target_instance_id",
        "baseline_receipt",
        "gate_vector",
        "characteristic_receipts",
        "old_instance_available",
        "old_instance_dependency",
        "operational_assets_copied",
        "bootstrap_import_count",
        "qualification_status",
        "optional_imports",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "target_instance_id": _ID,
        "baseline_receipt": {"type": "object"},
        "gate_vector": {
            "type": "array",
            "minItems": 9,
            "maxItems": 9,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["gate", "status", "receipt_ref", "instance_id"],
                "properties": {
                    "gate": {"type": "string"},
                    "status": {"type": "string"},
                    "receipt_ref": {"type": "string"},
                    "instance_id": _ID,
                },
            },
        },
        "characteristic_receipts": {
            "type": "array",
            "minItems": 7,
            "maxItems": 7,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "capability_class",
                    "status",
                    "receipt_ref",
                    "instance_id",
                ],
                "properties": {
                    "capability_class": {"type": "string"},
                    "status": {"type": "string"},
                    "receipt_ref": {"type": "string"},
                    "instance_id": _ID,
                },
            },
        },
        "old_instance_available": {"type": "boolean"},
        "old_instance_dependency": {"type": "boolean"},
        "operational_assets_copied": {"type": "integer", "minimum": 0},
        "bootstrap_import_count": {"type": "integer", "minimum": 0},
        "qualification_status": {"const": "not_started"},
        "optional_imports": {"type": "array", "maxItems": 0},
    },
}

FOUNDATION_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "target_instance_id",
        "foundation_contract_version",
        "bridge_release",
        "runtime_coordinator",
        "artifact_service",
        "authority_map",
        "bot_mode_absent",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "target_instance_id": _ID,
        "foundation_contract_version": {"type": "string", "minLength": 1},
        "bridge_release": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "version",
                "commit",
                "content_hash",
                "signature_status",
                "license",
                "sbom_hash",
                "migrations_hash",
                "tests_hash",
                "rollback_ref",
                "public_hooks_only",
                "no_second_agent_loop",
            ],
            "properties": {
                "version": {"type": "string", "minLength": 1},
                "commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                "content_hash": _HASH,
                "signature_status": {"type": "string"},
                "license": {"type": "string", "minLength": 1},
                "sbom_hash": _HASH,
                "migrations_hash": _HASH,
                "tests_hash": _HASH,
                "rollback_ref": {"type": "string", "minLength": 1},
                "public_hooks_only": {"type": "boolean"},
                "no_second_agent_loop": {"type": "boolean"},
            },
        },
        "runtime_coordinator": {"$ref": "#/$defs/service"},
        "artifact_service": {"$ref": "#/$defs/service"},
        "authority_map": {
            "type": "array",
            "minItems": 11,
            "maxItems": 11,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["state_type", "authority", "writer_count", "access_mode"],
                "properties": {
                    "state_type": {"type": "string"},
                    "authority": {"type": "string"},
                    "writer_count": {"type": "integer", "minimum": 0},
                    "access_mode": {"type": "string"},
                },
            },
        },
        "bot_mode_absent": {"type": "boolean"},
    },
    "$defs": {
        "service": {
            "type": "object",
            "additionalProperties": False,
            "required": ["release_ref", "status", "receipt_ref"],
            "properties": {
                "release_ref": {"type": "string", "minLength": 1},
                "status": {"type": "string"},
                "receipt_ref": {"type": "string", "minLength": 1},
            },
        }
    },
}

STATE_RECONCILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
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
    "properties": {
        "schema_version": {"const": 1},
        "work_id": {"type": "string", "minLength": 1},
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
}

ARTIFACT_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "operation",
        "artifact_id",
        "file_kind",
        "path",
        "allowed_root",
        "byte_size",
        "max_byte_size",
        "content_hash",
        "original_ref",
        "existing_same_hash_ref",
        "write_receipt",
        "tombstone",
        "propagation",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "operation": {"enum": ["ingest", "derive", "release", "delete"]},
        "artifact_id": {"type": "string", "minLength": 1},
        "file_kind": {"enum": ["regular", "symlink", "fifo", "device"]},
        "path": {"type": "string", "minLength": 2},
        "allowed_root": {"type": "string", "minLength": 2},
        "byte_size": {"type": "integer", "minimum": 0},
        "max_byte_size": {"type": "integer", "minimum": 1},
        "content_hash": _HASH,
        "original_ref": {"type": ["string", "null"]},
        "existing_same_hash_ref": {"type": ["string", "null"]},
        "write_receipt": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "temporary_write",
                "file_fsync",
                "atomic_rename",
                "directory_fsync",
                "metadata_committed",
                "readback_hash",
                "crash_point",
            ],
            "properties": {
                "temporary_write": {"type": "boolean"},
                "file_fsync": {"type": "boolean"},
                "atomic_rename": {"type": "boolean"},
                "directory_fsync": {"type": "boolean"},
                "metadata_committed": {"type": "boolean"},
                "readback_hash": _HASH,
                "crash_point": {
                    "enum": [
                        "none",
                        "before_rename",
                        "after_rename_before_metadata",
                        "after_metadata",
                    ]
                },
            },
        },
        "tombstone": {"type": "boolean"},
        "propagation": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["target", "status"],
                "properties": {
                    "target": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
        },
    },
}

FRAGMENT_PROMOTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "fragment", "checks", "requested_evidence_class"],
    "properties": {
        "schema_version": {"const": 1},
        "fragment": {
            "type": "object",
            "additionalProperties": False,
            "required": [
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
            "properties": {
                "fragment_id": {"type": "string", "minLength": 1},
                "run_id": {"type": "string", "minLength": 1},
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
                "content_hash": _HASH,
                "transformation_refs": {"type": "array", "items": {"type": "string"}},
                "retrieval_query": {"type": "string"},
                "rank_or_score": {"type": ["number", "null"]},
            },
        },
        "checks": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "source_resolved",
                "version_resolved",
                "locator_verified",
                "exact_hash_verified",
                "within_limits",
                "secret_scan_pass",
                "transformations_resolved",
                "primary_readback",
            ],
            "properties": {
                key: {"type": "boolean"}
                for key in (
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
        },
        "requested_evidence_class": {"type": "string"},
    },
}

INSTALLATION_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "target_instance_id",
        "greenfield_acceptance_receipt",
        "foundation_receipt",
        "staging_profile",
        "migration_dry_run_status",
        "characteristic_probes",
        "native_e2e_status",
        "rollback_smoke_status",
        "research_qualification_status",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "target_instance_id": _ID,
        "greenfield_acceptance_receipt": {"type": "object"},
        "foundation_receipt": {"type": "object"},
        "staging_profile": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "profile_id",
                "created_blank",
                "private_import_count",
                "copied_live_asset_count",
            ],
            "properties": {
                "profile_id": {"type": "string", "minLength": 1},
                "created_blank": {"type": "boolean"},
                "private_import_count": {"type": "integer", "minimum": 0},
                "copied_live_asset_count": {"type": "integer", "minimum": 0},
            },
        },
        "migration_dry_run_status": {"type": "string"},
        "characteristic_probes": {
            "type": "array",
            "minItems": 8,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["capability", "status", "receipt_ref", "current"],
                "properties": {
                    "capability": {"type": "string"},
                    "status": {"type": "string"},
                    "receipt_ref": {"type": "string"},
                    "current": {"type": "boolean"},
                },
            },
        },
        "native_e2e_status": {"type": "string"},
        "rollback_smoke_status": {"type": "string"},
        "research_qualification_status": {"type": "string"},
    },
}

CONTEXT_LIFECYCLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "tenant_id",
        "project_id",
        "run_id",
        "profile_id",
        "work_kind",
        "managed_run",
        "requires_agentmemory",
        "requires_graphiti",
        "agentmemory",
        "graphiti",
        "context_receipts_before_llm",
        "degraded_decision",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "tenant_id": {"type": "string", "minLength": 1},
        "project_id": {"type": "string", "minLength": 1},
        "run_id": {"type": "string", "minLength": 1},
        "profile_id": {"type": "string", "minLength": 1},
        "work_kind": {"type": "string", "minLength": 1},
        "managed_run": {"type": "boolean"},
        "requires_agentmemory": {"type": "boolean"},
        "requires_graphiti": {"type": "boolean"},
        "context_receipts_before_llm": {"type": "boolean"},
        "agentmemory": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "status",
                "session_start",
                "health_scope",
                "prefetch_receipt",
                "turn_sync",
                "session_close",
                "scope_key_complete",
            ],
            "properties": {
                "status": {"type": "string"},
                "session_start": {"type": "boolean"},
                "health_scope": {"type": "boolean"},
                "prefetch_receipt": {"type": "boolean"},
                "turn_sync": {"type": "boolean"},
                "session_close": {"type": "boolean"},
                "scope_key_complete": {"type": "boolean"},
            },
        },
        "graphiti": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "status",
                "health_schema",
                "read_receipt",
                "write_receipt",
                "outbox_reconciled",
                "admin_operations_hidden",
            ],
            "properties": {
                "status": {"type": "string"},
                "health_schema": {"type": "boolean"},
                "read_receipt": {"type": "boolean"},
                "write_receipt": {"type": "boolean"},
                "outbox_reconciled": {"type": "boolean"},
                "admin_operations_hidden": {"type": "boolean"},
            },
        },
        "degraded_decision": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "approved",
                        "missing_services",
                        "scope",
                        "acceptance_ceiling",
                    ],
                    "properties": {
                        "approved": {"type": "boolean"},
                        "missing_services": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "scope": {"type": "string"},
                        "acceptance_ceiling": {"type": "string"},
                    },
                },
            ]
        },
    },
}

CIRCUIT_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "route_id",
        "error_class",
        "failure_count",
        "retry_budget",
        "current_state",
        "state_change_trigger",
        "manual_probe_pass",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "route_id": {"type": "string", "minLength": 1},
        "error_class": {
            "enum": ["none", "transient", "permanent", "configuration", "dependency"]
        },
        "failure_count": {"type": "integer", "minimum": 0},
        "retry_budget": {"type": "integer", "minimum": 1},
        "current_state": {"enum": ["closed", "half_open", "open"]},
        "state_change_trigger": {"type": "boolean"},
        "manual_probe_pass": {"type": "boolean"},
    },
}

DOLT_COMMIT_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "operation_id",
        "run_id",
        "object_refs",
        "logical_change",
        "no_op",
        "sql_transaction_status",
        "dolt_commit_ref",
        "commit_message_refs",
        "contains_secret_or_user_text",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "operation_id": {"type": "string", "minLength": 1},
        "run_id": {"type": "string", "minLength": 1},
        "object_refs": {"type": "array", "items": {"type": "string"}},
        "logical_change": {"type": "boolean"},
        "no_op": {"type": "boolean"},
        "sql_transaction_status": {"enum": ["not_started", "committed", "rolled_back"]},
        "dolt_commit_ref": {"type": ["string", "null"]},
        "commit_message_refs": {"type": "array", "items": {"type": "string"}},
        "contains_secret_or_user_text": {"type": "boolean"},
    },
}
