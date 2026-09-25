"""Pure provider manifests, readiness, lifecycle, receipts, and qualification."""

from __future__ import annotations

import hashlib
from itertools import pairwise
from typing import Any

from .canonical import sha256_json, with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_int,
    require_list,
    require_mapping,
    require_string,
)
from .provider_catalog import PROVIDER_IDS, provider_manifest

_TEXT = {"type": "string", "minLength": 1}
_TEXTS = {
    "type": "array",
    "maxItems": 1000,
    "uniqueItems": True,
    "items": _TEXT,
}
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_PROVIDER_ENUM = {"enum": list(PROVIDER_IDS)}

PROVIDER_CATALOG_GET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "provider_ids"],
    "properties": {
        "schema_version": {"const": 1},
        "provider_ids": {
            "type": "array",
            "maxItems": len(PROVIDER_IDS),
            "uniqueItems": True,
            "items": _PROVIDER_ENUM,
        },
    },
}

_OPERATION_INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "capability",
        "lifecycle",
        "auth",
        "input_schema",
        "output_schema",
        "native_extensions",
        "limits",
        "cost_model",
        "status",
        "risk",
        "destructive",
    ],
    "properties": {
        "id": _TEXT,
        "capability": _TEXT,
        "lifecycle": {
            "enum": ["sync", "async", "batch", "poll", "stream", "webhook", "dump"]
        },
        "auth": _TEXT,
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "native_extensions": _TEXTS,
        "limits": {"type": "object"},
        "cost_model": {"type": "object"},
        "status": {
            "enum": [
                "documented",
                "experimental",
                "access_blocked",
                "entitlement_required",
                "policy_gated",
                "legacy",
            ]
        },
        "risk": {"enum": ["low", "medium", "high"]},
        "destructive": {"type": "boolean"},
    },
}

PROVIDER_MANIFEST_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "provider_id",
        "adapter_version",
        "endpoint_version",
        "source_contract_refs",
        "documented_operations",
        "provider_extensions",
        "policy",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "provider_id": _TEXT,
        "adapter_version": _TEXT,
        "endpoint_version": _TEXT,
        "source_contract_refs": _TEXTS,
        "documented_operations": {
            "type": "array",
            "maxItems": 1000,
            "items": _OPERATION_INPUT_SCHEMA,
        },
        "provider_extensions": {
            "type": "array",
            "maxItems": 1000,
            "items": _OPERATION_INPUT_SCHEMA,
        },
        "policy": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "terms_ref",
                "license",
                "retention_class",
                "redistribution_allowed",
                "privacy_class",
                "egress_class",
            ],
            "properties": {
                "terms_ref": _TEXT,
                "license": _TEXT,
                "retention_class": _TEXT,
                "redistribution_allowed": {"type": "boolean"},
                "privacy_class": _TEXT,
                "egress_class": _TEXT,
            },
        },
    },
}

PROVIDER_SCHEMA_DIFF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "prior_manifest",
        "current_manifest",
        "qualified_operation_ids",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "prior_manifest": {"type": "object"},
        "current_manifest": {"type": "object"},
        "qualified_operation_ids": _TEXTS,
    },
}

PROVIDER_OPERATION_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "operation",
        "state",
        "policy_allowed",
        "schema_drift",
        "prior_qualification_ref",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "operation": {"type": "object"},
        "state": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "available",
                "authenticated",
                "entitled",
                "structurally_valid",
                "functionally_verified",
            ],
            "properties": {
                "available": {"type": "boolean"},
                "authenticated": {"type": "boolean"},
                "entitled": {"type": "boolean"},
                "structurally_valid": {"type": "boolean"},
                "functionally_verified": {"type": "boolean"},
            },
        },
        "policy_allowed": {"type": "boolean"},
        "schema_drift": {"type": "boolean"},
        "prior_qualification_ref": {"type": ["string", "null"]},
    },
}

PROVIDER_FALLBACK_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "required_capability",
        "required_properties",
        "primary_operation",
        "fallback_operation",
        "accepted_property_losses",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "required_capability": _TEXT,
        "required_properties": _TEXTS,
        "primary_operation": {"type": "object"},
        "fallback_operation": {"type": "object"},
        "accepted_property_losses": _TEXTS,
    },
}

PROVIDER_BUDGET_RESERVE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "provider_id", "limits", "reservations"],
    "properties": {
        "schema_version": {"const": 1},
        "provider_id": _TEXT,
        "limits": {
            "type": "object",
            "additionalProperties": False,
            "required": ["credits", "concurrency", "cost", "batch_items"],
            "properties": {
                "credits": {"type": "integer", "minimum": 0},
                "concurrency": {"type": "integer", "minimum": 0},
                "cost": {"type": "integer", "minimum": 0},
                "batch_items": {"type": "integer", "minimum": 0},
            },
        },
        "reservations": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "request_id",
                    "sequence",
                    "credits",
                    "concurrency",
                    "cost",
                    "batch_items",
                ],
                "properties": {
                    "request_id": _TEXT,
                    "sequence": {"type": "integer", "minimum": 0},
                    "credits": {"type": "integer", "minimum": 0},
                    "concurrency": {"type": "integer", "minimum": 0},
                    "cost": {"type": "integer", "minimum": 0},
                    "batch_items": {"type": "integer", "minimum": 0},
                },
            },
        },
    },
}

PROVIDER_LIFECYCLE_RECONCILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "provider_id",
        "provider_run_id",
        "current_state",
        "provider_accepted",
        "timeout_after_send",
        "events",
        "readback_state",
        "result_available",
        "batch_items",
        "continuation_token",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "provider_id": _TEXT,
        "provider_run_id": _TEXT,
        "current_state": _TEXT,
        "provider_accepted": {"type": "boolean"},
        "timeout_after_send": {"type": "boolean"},
        "events": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "event_id",
                    "sequence",
                    "kind",
                    "state",
                    "run_id",
                    "transport",
                    "signature_status",
                    "timestamp_status",
                ],
                "properties": {
                    "event_id": _TEXT,
                    "sequence": {"type": "integer", "minimum": 0},
                    "kind": _TEXT,
                    "state": _TEXT,
                    "run_id": _TEXT,
                    "transport": {"enum": ["poll", "sse", "webhook"]},
                    "signature_status": {
                        "enum": ["valid", "invalid", "not_applicable"]
                    },
                    "timestamp_status": {
                        "enum": ["valid", "invalid", "not_applicable"]
                    },
                },
            },
        },
        "readback_state": {"type": ["string", "null"]},
        "result_available": {"type": "boolean"},
        "batch_items": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item_id", "status", "result_ref", "error_code"],
                "properties": {
                    "item_id": _TEXT,
                    "status": {"enum": ["success", "error"]},
                    "result_ref": {"type": ["string", "null"]},
                    "error_code": {"type": ["string", "null"]},
                },
            },
        },
        "continuation_token": {"type": ["string", "null"]},
    },
}

PROVIDER_RECEIPT_NORMALIZE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "provider_id",
        "product",
        "endpoint",
        "endpoint_version",
        "operation_id",
        "capability",
        "profile_ref",
        "strategy_ref",
        "auth_decision_ref",
        "entitlement_decision_ref",
        "request_id",
        "run_id",
        "attempt_id",
        "idempotency_key",
        "request_hash",
        "raw_response_ref",
        "raw_response_json",
        "normalized_result_ref",
        "normalized_fields",
        "native_extensions",
        "page",
        "continuation_token",
        "completeness",
        "status",
        "errors",
        "warnings",
        "cost",
        "latency_ms",
        "limitations",
        "started_at",
        "completed_at",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "provider_id": _TEXT,
        "product": _TEXT,
        "endpoint": _TEXT,
        "endpoint_version": _TEXT,
        "operation_id": _TEXT,
        "capability": _TEXT,
        "profile_ref": _TEXT,
        "strategy_ref": _TEXT,
        "auth_decision_ref": _TEXT,
        "entitlement_decision_ref": _TEXT,
        "request_id": _TEXT,
        "run_id": {"type": ["string", "null"]},
        "attempt_id": _TEXT,
        "idempotency_key": _TEXT,
        "request_hash": _HASH,
        "raw_response_ref": _TEXT,
        "raw_response_json": {"type": "string"},
        "normalized_result_ref": _TEXT,
        "normalized_fields": {"type": "object"},
        "native_extensions": {"type": "object"},
        "page": {"type": ["integer", "null"], "minimum": 0},
        "continuation_token": {"type": ["string", "null"]},
        "completeness": {"type": "boolean"},
        "status": _TEXT,
        "errors": _TEXTS,
        "warnings": _TEXTS,
        "cost": {"type": "integer", "minimum": 0},
        "latency_ms": {"type": "integer", "minimum": 0},
        "limitations": _TEXTS,
        "started_at": _TEXT,
        "completed_at": {"type": ["string", "null"]},
    },
}

PROVIDER_CONFORMANCE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "provider_id",
        "adapter_version",
        "manifest_hash",
        "environment",
        "credentials_class",
        "evidence_kind",
        "verified_at",
        "expires_at",
        "recheck_triggers",
        "operation_results",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "provider_id": _PROVIDER_ENUM,
        "adapter_version": _TEXT,
        "manifest_hash": _HASH,
        "environment": _TEXT,
        "credentials_class": _TEXT,
        "evidence_kind": {"enum": ["controlled_fixture", "live_provider"]},
        "verified_at": _TEXT,
        "expires_at": _TEXT,
        "recheck_triggers": _TEXTS,
        "operation_results": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "operation_id",
                    "available",
                    "structural_status",
                    "boundary_status",
                    "error_status",
                    "live_status",
                    "authenticated",
                    "entitled",
                    "receipt_ref",
                ],
                "properties": {
                    "operation_id": _TEXT,
                    "available": {"type": "boolean"},
                    "structural_status": {"enum": ["pass", "fail"]},
                    "boundary_status": {"enum": ["pass", "fail", "not_run"]},
                    "error_status": {"enum": ["pass", "fail", "not_run"]},
                    "live_status": {"enum": ["pass", "fail", "not_run"]},
                    "authenticated": {"type": "boolean"},
                    "entitled": {"type": "boolean"},
                    "receipt_ref": {"type": ["string", "null"]},
                },
            },
        },
    },
}

_MANIFEST_FIELDS = {
    "schema_version",
    "provider_id",
    "adapter_version",
    "endpoint_version",
    "source_contract_refs",
    "operations",
    "policy",
    "excluded_operation_classes",
    "qualification_state",
    "manifest_hash",
}
_OPERATION_FIELDS = {
    "id",
    "capability",
    "lifecycle",
    "auth",
    "input_schema_ref",
    "output_schema_ref",
    "schema_hash",
    "native_extensions",
    "limits",
    "cost_model",
    "status",
    "risk",
    "destructive",
    "origin",
}
_DANGEROUS_TOKENS = {
    "admin",
    "billing",
    "payment",
    "delete_key",
    "top_up_balance",
    "key_management",
}
_LIFECYCLE_STATES = {
    "prepared",
    "submitted",
    "queued",
    "running",
    "completed",
    "partial",
    "failed",
    "cancel_requested",
    "cancelled",
    "unknown_outcome",
}
_EVENT_KINDS = {
    "submitted",
    "queued",
    "running",
    "progress",
    "source",
    "completed",
    "partial",
    "failed",
    "cancel_requested",
    "cancelled",
    "done",
    "result_ready",
}
_ALLOWED_TRANSITIONS = {
    "prepared": {"submitted", "failed", "cancelled"},
    "submitted": {
        "queued",
        "running",
        "completed",
        "partial",
        "failed",
        "cancel_requested",
        "unknown_outcome",
    },
    "queued": {
        "running",
        "completed",
        "partial",
        "failed",
        "cancel_requested",
        "unknown_outcome",
    },
    "running": {
        "completed",
        "partial",
        "failed",
        "cancel_requested",
        "unknown_outcome",
    },
    "cancel_requested": {"cancelled", "completed", "failed", "unknown_outcome"},
    "completed": set(),
    "partial": set(),
    "failed": set(),
    "cancelled": set(),
    "unknown_outcome": set(),
}


def _version(request: dict[str, object]) -> None:
    if request["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )


def get_provider_catalog(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "provider_ids"}, "request")
    _version(data)
    requested = [
        require_string(item, f"request.provider_ids[{index}]")
        for index, item in enumerate(
            require_list(data["provider_ids"], "request.provider_ids")
        )
    ]
    if len(requested) != len(set(requested)):
        fail(
            "duplicate_provider",
            "request.provider_ids",
            "Провайдеры должны быть уникальны.",
        )
    unknown = sorted(set(requested) - set(PROVIDER_IDS))
    if unknown:
        fail(
            "unknown_provider",
            "request.provider_ids",
            f"Неизвестный провайдер: {unknown[0]}.",
        )
    selected = requested or list(PROVIDER_IDS)
    manifests = [provider_manifest(provider_id) for provider_id in selected]
    return with_receipt_hash(
        {
            "contract": "ProviderCatalogReceipt",
            "status": "contract_catalogued",
            "provider_count": len(manifests),
            "provider_ids": selected,
            "manifests": manifests,
            "all_product_parity_false": all(
                manifest["product_parity"] is False for manifest in manifests
            ),
            "live_calls_performed": 0,
            "product_status": "not_verified",
        }
    )


def _normalize_operation(value: object, path: str, origin: str) -> dict[str, Any]:
    data = require_mapping(value, path)
    expected = set(_OPERATION_INPUT_SCHEMA["required"])
    require_exact_keys(data, expected, path)
    operation_id = require_string(data["id"], f"{path}.id")
    lowered = operation_id.lower().replace("-", "_").replace(".", "_")
    if require_bool(data["destructive"], f"{path}.destructive") or any(
        token in lowered for token in _DANGEROUS_TOKENS
    ):
        fail(
            "operation_out_of_scope",
            f"{path}.id",
            "Административная, платежная или разрушительная операция запрещена.",
        )
    lifecycle = require_string(data["lifecycle"], f"{path}.lifecycle")
    if lifecycle not in {"sync", "async", "batch", "poll", "stream", "webhook", "dump"}:
        fail("invalid_lifecycle", f"{path}.lifecycle", "Неизвестный жизненный цикл.")
    native = [
        require_string(item, f"{path}.native_extensions[{index}]")
        for index, item in enumerate(
            require_list(data["native_extensions"], f"{path}.native_extensions")
        )
    ]
    if len(native) != len(set(native)):
        fail(
            "duplicate_native_extension",
            f"{path}.native_extensions",
            "Расширения должны быть уникальны.",
        )
    input_schema = require_mapping(data["input_schema"], f"{path}.input_schema")
    output_schema = require_mapping(data["output_schema"], f"{path}.output_schema")
    limits = require_mapping(data["limits"], f"{path}.limits")
    cost_model = require_mapping(data["cost_model"], f"{path}.cost_model")
    status = require_string(data["status"], f"{path}.status")
    if status not in {
        "documented",
        "experimental",
        "access_blocked",
        "entitlement_required",
        "policy_gated",
        "legacy",
    }:
        fail(
            "invalid_operation_status", f"{path}.status", "Неизвестен статус операции."
        )
    risk = require_string(data["risk"], f"{path}.risk")
    if risk not in {"low", "medium", "high"}:
        fail("invalid_risk", f"{path}.risk", "Неизвестен класс риска.")
    normalized: dict[str, Any] = {
        "id": operation_id,
        "capability": require_string(data["capability"], f"{path}.capability"),
        "lifecycle": lifecycle,
        "auth": require_string(data["auth"], f"{path}.auth"),
        "input_schema_ref": f"inline://{operation_id}/input",
        "output_schema_ref": f"inline://{operation_id}/output",
        "schema_hash": sha256_json({"input": input_schema, "output": output_schema}),
        "native_extensions": native,
        "limits": limits,
        "cost_model": cost_model,
        "status": status,
        "risk": risk,
        "destructive": False,
        "origin": origin,
    }
    return normalized


def build_provider_manifest(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(PROVIDER_MANIFEST_BUILD_SCHEMA["required"]), "request")
    _version(data)
    documented = require_list(
        data["documented_operations"], "request.documented_operations"
    )
    extensions = require_list(
        data["provider_extensions"], "request.provider_extensions"
    )
    operations = [
        _normalize_operation(
            value, f"request.documented_operations[{index}]", "official_surface"
        )
        for index, value in enumerate(documented)
    ] + [
        _normalize_operation(
            value, f"request.provider_extensions[{index}]", "native_extension"
        )
        for index, value in enumerate(extensions)
    ]
    operation_ids = [operation["id"] for operation in operations]
    if len(operation_ids) != len(set(operation_ids)):
        fail(
            "duplicate_operation",
            "request.documented_operations",
            "Идентификаторы операций должны быть уникальны.",
        )
    policy = require_mapping(data["policy"], "request.policy")
    policy_fields = {
        "terms_ref",
        "license",
        "retention_class",
        "redistribution_allowed",
        "privacy_class",
        "egress_class",
    }
    require_exact_keys(policy, policy_fields, "request.policy")
    normalized_policy = {
        "terms_ref": require_string(policy["terms_ref"], "request.policy.terms_ref"),
        "license": require_string(policy["license"], "request.policy.license"),
        "retention_class": require_string(
            policy["retention_class"], "request.policy.retention_class"
        ),
        "redistribution_allowed": require_bool(
            policy["redistribution_allowed"], "request.policy.redistribution_allowed"
        ),
        "privacy_class": require_string(
            policy["privacy_class"], "request.policy.privacy_class"
        ),
        "egress_class": require_string(
            policy["egress_class"], "request.policy.egress_class"
        ),
    }
    source_refs = [
        require_string(item, f"request.source_contract_refs[{index}]")
        for index, item in enumerate(
            require_list(data["source_contract_refs"], "request.source_contract_refs")
        )
    ]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "provider_id": require_string(data["provider_id"], "request.provider_id"),
        "adapter_version": require_string(
            data["adapter_version"], "request.adapter_version"
        ),
        "endpoint_version": require_string(
            data["endpoint_version"], "request.endpoint_version"
        ),
        "source_contract_refs": source_refs,
        "operations": operations,
        "policy": normalized_policy,
        "excluded_operation_classes": sorted(_DANGEROUS_TOKENS),
        "qualification_state": "not_verified",
    }
    manifest["manifest_hash"] = sha256_json(manifest)
    return with_receipt_hash(
        {
            "contract": "ProviderAdapterManifestReceipt",
            "status": "manifest_built",
            "manifest": manifest,
            "documented_operation_count": len(documented),
            "provider_extension_count": len(extensions),
            "operation_count": len(operations),
            "secret_material_accepted": False,
            "external_call_performed": False,
        }
    )


def _operation_index(
    manifest: object, path: str
) -> tuple[str, dict[str, dict[str, object]]]:
    data = require_mapping(manifest, path)
    provider_id = require_string(data.get("provider_id"), f"{path}.provider_id")
    operations = require_list(data.get("operations"), f"{path}.operations")
    result: dict[str, dict[str, object]] = {}
    for index, value in enumerate(operations):
        operation = require_mapping(value, f"{path}.operations[{index}]")
        operation_id = require_string(
            operation.get("id"), f"{path}.operations[{index}].id"
        )
        require_string(
            operation.get("schema_hash"), f"{path}.operations[{index}].schema_hash"
        )
        if operation_id in result:
            fail(
                "duplicate_operation",
                f"{path}.operations[{index}].id",
                "Повтор операции запрещен.",
            )
        result[operation_id] = operation
    return provider_id, result


def diff_provider_schema(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(PROVIDER_SCHEMA_DIFF_SCHEMA["required"]), "request")
    _version(data)
    prior_provider, prior = _operation_index(
        data["prior_manifest"], "request.prior_manifest"
    )
    current_provider, current = _operation_index(
        data["current_manifest"], "request.current_manifest"
    )
    if prior_provider != current_provider:
        fail(
            "provider_mismatch",
            "request.current_manifest.provider_id",
            "Сравниваются разные провайдеры.",
        )
    qualified = {
        require_string(item, f"request.qualified_operation_ids[{index}]")
        for index, item in enumerate(
            require_list(
                data["qualified_operation_ids"], "request.qualified_operation_ids"
            )
        )
    }
    added = sorted(set(current) - set(prior))
    removed = sorted(set(prior) - set(current))
    changed = sorted(
        operation_id
        for operation_id in set(prior) & set(current)
        if prior[operation_id]["schema_hash"] != current[operation_id]["schema_hash"]
    )
    impacted = sorted((set(changed) | set(removed)) & qualified)
    retained = sorted(qualified - set(impacted))
    return with_receipt_hash(
        {
            "contract": "ProviderSchemaDriftReceipt",
            "status": "schema_drift" if added or removed or changed else "unchanged",
            "provider_id": prior_provider,
            "added_operation_ids": added,
            "removed_operation_ids": removed,
            "changed_operation_ids": changed,
            "qualification_revoked_operation_ids": impacted,
            "qualification_retained_operation_ids": retained,
            "prior_manifest": data["prior_manifest"],
            "current_manifest_hash": require_mapping(
                data["current_manifest"], "request.current_manifest"
            ).get("manifest_hash"),
            "external_call_performed": False,
        }
    )


def assess_provider_operation(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, set(PROVIDER_OPERATION_ASSESS_SCHEMA["required"]), "request"
    )
    _version(data)
    operation = require_mapping(data["operation"], "request.operation")
    operation_id = require_string(operation.get("id"), "request.operation.id")
    operation_status = require_string(
        operation.get("status"), "request.operation.status"
    )
    lowered = operation_id.lower().replace("-", "_").replace(".", "_")
    if operation.get("destructive") is not False or any(
        token in lowered for token in _DANGEROUS_TOKENS
    ):
        fail(
            "operation_out_of_scope",
            "request.operation.destructive",
            "Разрушительная операция запрещена.",
        )
    state = require_mapping(data["state"], "request.state")
    state_fields = {
        "available",
        "authenticated",
        "entitled",
        "structurally_valid",
        "functionally_verified",
    }
    require_exact_keys(state, state_fields, "request.state")
    vector = {
        key: require_bool(state[key], f"request.state.{key}")
        for key in sorted(state_fields)
    }
    policy_allowed = require_bool(data["policy_allowed"], "request.policy_allowed")
    schema_drift = require_bool(data["schema_drift"], "request.schema_drift")
    eligible_status = operation_status == "documented"
    qualified = (
        all(vector.values()) and policy_allowed and not schema_drift and eligible_status
    )
    blockers = [key for key, value in vector.items() if not value]
    if not policy_allowed:
        blockers.append("policy_denied")
    if schema_drift:
        blockers.append("schema_drift")
    if not eligible_status:
        blockers.append(operation_status)
    return with_receipt_hash(
        {
            "contract": "ProviderOperationDecisionReceipt",
            "status": "qualified" if qualified else "blocked",
            "operation_id": operation_id,
            "state": {**vector, "qualified": qualified},
            "blockers": blockers,
            "prior_qualification_ref": data["prior_qualification_ref"],
            "secret_material_accepted": False,
            "routing_allowed": qualified,
            "external_call_performed": False,
        }
    )


def assess_provider_fallback(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, set(PROVIDER_FALLBACK_ASSESS_SCHEMA["required"]), "request"
    )
    _version(data)
    capability = require_string(
        data["required_capability"], "request.required_capability"
    )
    required = {
        require_string(item, f"request.required_properties[{index}]")
        for index, item in enumerate(
            require_list(data["required_properties"], "request.required_properties")
        )
    }
    accepted_losses = {
        require_string(item, f"request.accepted_property_losses[{index}]")
        for index, item in enumerate(
            require_list(
                data["accepted_property_losses"], "request.accepted_property_losses"
            )
        )
    }
    primary = require_mapping(data["primary_operation"], "request.primary_operation")
    fallback = require_mapping(data["fallback_operation"], "request.fallback_operation")
    primary_id = require_string(primary.get("id"), "request.primary_operation.id")
    fallback_id = require_string(fallback.get("id"), "request.fallback_operation.id")
    primary_capability = require_string(
        primary.get("capability"), "request.primary_operation.capability"
    )
    fallback_capability = require_string(
        fallback.get("capability"), "request.fallback_operation.capability"
    )
    primary_properties = {
        require_string(item, "request.primary_operation.native_extensions[]")
        for item in require_list(
            primary.get("native_extensions"),
            "request.primary_operation.native_extensions",
        )
    }
    fallback_properties = {
        require_string(item, "request.fallback_operation.native_extensions[]")
        for item in require_list(
            fallback.get("native_extensions"),
            "request.fallback_operation.native_extensions",
        )
    }
    required_on_primary = required & primary_properties
    lost = sorted(required_on_primary - fallback_properties)
    unaccepted = sorted(set(lost) - accepted_losses)
    capability_equivalent = primary_capability == capability == fallback_capability
    accepted = capability_equivalent and not unaccepted
    return with_receipt_hash(
        {
            "contract": "ProviderFallbackDecisionReceipt",
            "status": (
                "equivalent"
                if accepted and not lost
                else "accepted_with_explicit_losses"
                if accepted
                else "rejected"
            ),
            "primary_operation_id": primary_id,
            "fallback_operation_id": fallback_id,
            "capability_equivalent": capability_equivalent,
            "lost_properties": lost,
            "accepted_property_losses": sorted(accepted_losses & set(lost)),
            "unaccepted_property_losses": unaccepted,
            "routing_allowed": accepted,
            "silent_weakening": False,
            "external_call_performed": False,
        }
    )


def reserve_provider_budget(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(PROVIDER_BUDGET_RESERVE_SCHEMA["required"]), "request")
    _version(data)
    provider_id = require_string(data["provider_id"], "request.provider_id")
    limit_data = require_mapping(data["limits"], "request.limits")
    dimensions = ("credits", "concurrency", "cost", "batch_items")
    require_exact_keys(limit_data, set(dimensions), "request.limits")
    limits = {
        key: require_int(limit_data[key], f"request.limits.{key}") for key in dimensions
    }
    parsed: list[dict[str, Any]] = []
    request_ids: set[str] = set()
    for index, value in enumerate(
        require_list(data["reservations"], "request.reservations")
    ):
        path = f"request.reservations[{index}]"
        row = require_mapping(value, path)
        require_exact_keys(row, {"request_id", "sequence", *dimensions}, path)
        request_id = require_string(row["request_id"], f"{path}.request_id")
        if request_id in request_ids:
            fail(
                "duplicate_request", f"{path}.request_id", "Повтор request_id запрещен."
            )
        request_ids.add(request_id)
        parsed.append(
            {
                "request_id": request_id,
                "sequence": require_int(row["sequence"], f"{path}.sequence"),
                **{key: require_int(row[key], f"{path}.{key}") for key in dimensions},
            }
        )
    parsed.sort(key=lambda row: (row["sequence"], row["request_id"]))
    used = {key: 0 for key in dimensions}
    decisions = []
    for row in parsed:
        exceeded = [key for key in dimensions if used[key] + row[key] > limits[key]]
        accepted = not exceeded
        if accepted:
            for key in dimensions:
                used[key] += row[key]
        decisions.append(
            {
                "request_id": row["request_id"],
                "sequence": row["sequence"],
                "accepted": accepted,
                "rejection_reasons": [f"{key}_limit_exceeded" for key in exceeded],
            }
        )
    return with_receipt_hash(
        {
            "contract": "ProviderBudgetReservationReceipt",
            "status": "reserved"
            if all(row["accepted"] for row in decisions)
            else "partially_reserved",
            "provider_id": provider_id,
            "limits": limits,
            "used": used,
            "decisions": decisions,
            "accepted_count": sum(row["accepted"] for row in decisions),
            "atomic_contention_set_hash": sha256_json(parsed),
            "external_calls_authorized": [
                row["request_id"] for row in decisions if row["accepted"]
            ],
        }
    )


def reconcile_provider_lifecycle(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, set(PROVIDER_LIFECYCLE_RECONCILE_SCHEMA["required"]), "request"
    )
    _version(data)
    provider_id = require_string(data["provider_id"], "request.provider_id")
    run_id = require_string(data["provider_run_id"], "request.provider_run_id")
    current_state = require_string(data["current_state"], "request.current_state")
    if current_state not in _LIFECYCLE_STATES:
        fail(
            "invalid_lifecycle_state",
            "request.current_state",
            "Неизвестное состояние операции.",
        )
    seen: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []
    conflicting_ids: set[str] = set()
    conflicting_events: list[dict[str, Any]] = []
    rejected_ids: list[str] = []
    unknown_events: list[dict[str, Any]] = []
    valid_events: list[dict[str, Any]] = []
    raw_sequences: list[int] = []
    for index, value in enumerate(require_list(data["events"], "request.events")):
        path = f"request.events[{index}]"
        event = require_mapping(value, path)
        fields = {
            "event_id",
            "sequence",
            "kind",
            "state",
            "run_id",
            "transport",
            "signature_status",
            "timestamp_status",
        }
        require_exact_keys(event, fields, path)
        event_id = require_string(event["event_id"], f"{path}.event_id")
        sequence = require_int(event["sequence"], f"{path}.sequence")
        kind = require_string(event["kind"], f"{path}.kind")
        state = require_string(event["state"], f"{path}.state")
        event_run_id = require_string(event["run_id"], f"{path}.run_id")
        transport = require_string(event["transport"], f"{path}.transport")
        signature_status = require_string(
            event["signature_status"], f"{path}.signature_status"
        )
        if signature_status not in {"valid", "invalid", "not_applicable"}:
            fail(
                "invalid_signature_status",
                f"{path}.signature_status",
                "Неизвестен статус проверки подписи.",
            )
        timestamp_status = require_string(
            event["timestamp_status"], f"{path}.timestamp_status"
        )
        if transport not in {"poll", "sse", "webhook"}:
            fail(
                "invalid_event_transport",
                f"{path}.transport",
                "Неизвестен транспорт события.",
            )
        if timestamp_status not in {"valid", "invalid", "not_applicable"}:
            fail(
                "invalid_timestamp_status",
                f"{path}.timestamp_status",
                "Неизвестен статус времени события.",
            )
        raw_sequences.append(sequence)
        normalized = {
            "event_id": event_id,
            "sequence": sequence,
            "kind": kind,
            "state": state,
            "run_id": event_run_id,
            "transport": transport,
            "signature_status": signature_status,
            "timestamp_status": timestamp_status,
        }
        webhook_invalid = transport == "webhook" and (
            signature_status != "valid" or timestamp_status != "valid"
        )
        if event_run_id != run_id or signature_status == "invalid" or webhook_invalid:
            rejected_ids.append(event_id)
            continue
        if kind not in _EVENT_KINDS:
            unknown_events.append(normalized)
            continue
        if state not in _LIFECYCLE_STATES:
            rejected_ids.append(event_id)
            continue
        if event_id in seen:
            duplicate_ids.append(event_id)
            if seen[event_id]["state"] != state:
                if event_id not in conflicting_ids:
                    conflicting_events.append(seen[event_id])
                conflicting_ids.add(event_id)
                conflicting_events.append(normalized)
            continue
        seen[event_id] = normalized
        valid_events.append(normalized)
    out_of_order = any(left > right for left, right in pairwise(raw_sequences))
    valid_events.sort(key=lambda row: (row["sequence"], row["event_id"]))
    valid_events = [
        event for event in valid_events if event["event_id"] not in conflicting_ids
    ]
    state_history = [current_state]
    transition_rejected_ids = []
    applied_events = []
    for event in valid_events:
        proposed = event["state"]
        current = state_history[-1]
        if proposed == current:
            applied_events.append(event)
            continue
        if proposed not in _ALLOWED_TRANSITIONS[current]:
            rejected_ids.append(event["event_id"])
            transition_rejected_ids.append(event["event_id"])
            continue
        state_history.append(proposed)
        applied_events.append(event)
    readback = data["readback_state"]
    if readback is not None:
        readback = require_string(readback, "request.readback_state")
        if readback not in _LIFECYCLE_STATES:
            fail(
                "invalid_lifecycle_state",
                "request.readback_state",
                "Неизвестно состояние сверки.",
            )
        if readback != state_history[-1]:
            state_history.append(readback)
    require_bool(data["provider_accepted"], "request.provider_accepted")
    timed_out = require_bool(data["timeout_after_send"], "request.timeout_after_send")
    result_available = require_bool(
        data["result_available"], "request.result_available"
    )
    final_state = state_history[-1]
    reconciliation_required = False
    if (timed_out or conflicting_ids) and readback is None:
        final_state = "unknown_outcome"
        state_history.append(final_state)
        reconciliation_required = True
    if final_state == "completed" and not result_available:
        reconciliation_required = True
    items = []
    for index, value in enumerate(
        require_list(data["batch_items"], "request.batch_items")
    ):
        path = f"request.batch_items[{index}]"
        item = require_mapping(value, path)
        fields = {"item_id", "status", "result_ref", "error_code"}
        require_exact_keys(item, fields, path)
        status = require_string(item["status"], f"{path}.status")
        if status not in {"success", "error"}:
            fail(
                "invalid_item_status",
                f"{path}.status",
                "Неизвестен статус элемента пакета.",
            )
        result_ref = item["result_ref"]
        error_code = item["error_code"]
        if (status == "success") != (
            type(result_ref) is str and bool(result_ref.strip())
        ):
            fail(
                "invalid_batch_item",
                path,
                "Успех требует result_ref, ошибка его запрещает.",
            )
        if (status == "error") != (
            type(error_code) is str and bool(error_code.strip())
        ):
            fail(
                "invalid_batch_item",
                path,
                "Ошибка требует error_code, успех его запрещает.",
            )
        items.append(dict(item))
    continuation = data["continuation_token"]
    if continuation is not None:
        continuation = require_string(continuation, "request.continuation_token")
    completeness = continuation is None and not any(
        item["status"] == "error" for item in items
    )
    return with_receipt_hash(
        {
            "contract": "ProviderLifecycleReceipt",
            "status": "reconciliation_required"
            if reconciliation_required
            else "reconciled",
            "provider_id": provider_id,
            "provider_run_id": run_id,
            "state_history": state_history,
            "final_state": final_state,
            "applied_event_ids": [event["event_id"] for event in applied_events],
            "duplicate_event_ids": duplicate_ids,
            "conflicting_event_ids": sorted(conflicting_ids),
            "conflicting_event_observations": conflicting_events,
            "rejected_event_ids": rejected_ids,
            "transition_rejected_event_ids": transition_rejected_ids,
            "unknown_events": unknown_events,
            "out_of_order_detected": out_of_order,
            "result_read_allowed": final_state == "completed" and result_available,
            "retry_allowed": final_state not in {"completed", "unknown_outcome"},
            "reconciliation_required": reconciliation_required,
            "batch_items": items,
            "continuation_token": continuation,
            "completeness": completeness,
        }
    )


def normalize_provider_receipt(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, set(PROVIDER_RECEIPT_NORMALIZE_SCHEMA["required"]), "request"
    )
    _version(data)
    text_fields = (
        "provider_id",
        "product",
        "endpoint",
        "endpoint_version",
        "operation_id",
        "capability",
        "profile_ref",
        "strategy_ref",
        "auth_decision_ref",
        "entitlement_decision_ref",
        "request_id",
        "attempt_id",
        "idempotency_key",
        "request_hash",
        "raw_response_ref",
        "normalized_result_ref",
        "status",
        "started_at",
    )
    normalized: dict[str, Any] = {
        key: require_string(data[key], f"request.{key}") for key in text_fields
    }
    request_hash = normalized["request_hash"]
    if len(request_hash) != 64 or any(
        character not in "0123456789abcdef" for character in request_hash
    ):
        fail(
            "invalid_hash",
            "request.request_hash",
            "Ожидался SHA-256 в нижнем регистре.",
        )
    raw_json = require_string(
        data["raw_response_json"], "request.raw_response_json", nonempty=False
    )
    native = require_mapping(data["native_extensions"], "request.native_extensions")
    normalized_fields = require_mapping(
        data["normalized_fields"], "request.normalized_fields"
    )
    for key in ("run_id", "continuation_token", "completed_at"):
        value = data[key]
        normalized[key] = (
            None if value is None else require_string(value, f"request.{key}")
        )
    page = data["page"]
    normalized["page"] = None if page is None else require_int(page, "request.page")
    normalized["raw_response_hash"] = hashlib.sha256(
        raw_json.encode("utf-8")
    ).hexdigest()
    normalized["raw_response_bytes"] = len(raw_json.encode("utf-8"))
    normalized["normalized_fields"] = normalized_fields
    normalized["native_extensions"] = native
    normalized["native_extensions_hash"] = sha256_json(native)
    normalized["completeness"] = require_bool(
        data["completeness"], "request.completeness"
    )
    normalized["errors"] = [
        require_string(item, "request.errors[]")
        for item in require_list(data["errors"], "request.errors")
    ]
    normalized["warnings"] = [
        require_string(item, "request.warnings[]")
        for item in require_list(data["warnings"], "request.warnings")
    ]
    normalized["limitations"] = [
        require_string(item, "request.limitations[]")
        for item in require_list(data["limitations"], "request.limitations")
    ]
    normalized["cost"] = require_int(data["cost"], "request.cost")
    normalized["latency_ms"] = require_int(data["latency_ms"], "request.latency_ms")
    return with_receipt_hash(
        {
            "contract": "ProviderReceipt",
            "status": "normalized",
            **normalized,
            "raw_response_embedded": False,
            "native_extensions_preserved": True,
            "external_call_performed": False,
        }
    )


def assess_provider_conformance(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, set(PROVIDER_CONFORMANCE_ASSESS_SCHEMA["required"]), "request"
    )
    _version(data)
    provider_id = require_string(data["provider_id"], "request.provider_id")
    if provider_id not in PROVIDER_IDS:
        fail("unknown_provider", "request.provider_id", "Неизвестный провайдер.")
    manifest = provider_manifest(provider_id)
    supplied_hash = require_string(data["manifest_hash"], "request.manifest_hash")
    manifest_match = supplied_hash == manifest["manifest_hash"]
    adapter_version = require_string(data["adapter_version"], "request.adapter_version")
    adapter_match = adapter_version == manifest["adapter_version"]
    evidence_kind = require_string(data["evidence_kind"], "request.evidence_kind")
    if evidence_kind not in {"controlled_fixture", "live_provider"}:
        fail(
            "invalid_evidence_kind",
            "request.evidence_kind",
            "Неизвестен вид квалификационного доказательства.",
        )
    results_data = require_list(data["operation_results"], "request.operation_results")
    result_index: dict[str, dict[str, Any]] = {}
    fields = {
        "operation_id",
        "available",
        "structural_status",
        "boundary_status",
        "error_status",
        "live_status",
        "authenticated",
        "entitled",
        "receipt_ref",
    }
    for index, value in enumerate(results_data):
        path = f"request.operation_results[{index}]"
        row = require_mapping(value, path)
        require_exact_keys(row, fields, path)
        operation_id = require_string(row["operation_id"], f"{path}.operation_id")
        if operation_id in result_index:
            fail(
                "duplicate_operation_result",
                f"{path}.operation_id",
                "Повтор результата запрещен.",
            )
        result_index[operation_id] = dict(row)
    catalog_ids = {operation["id"] for operation in manifest["operations"]}
    unknown = sorted(set(result_index) - catalog_ids)
    if unknown:
        fail(
            "undocumented_operation",
            "request.operation_results",
            f"Операция не документирована: {unknown[0]}.",
        )
    operation_states = []
    for operation in manifest["operations"]:
        operation_id = operation["id"]
        result = result_index.get(operation_id)
        documented = operation["status"] == "documented"
        available = bool(result and result["available"] is True and documented)
        structurally_valid = bool(result and result["structural_status"] == "pass")
        authenticated = bool(result and result["authenticated"] is True)
        entitled = bool(result and result["entitled"] is True)
        functionally_verified = bool(
            result
            and evidence_kind == "live_provider"
            and result["boundary_status"] == "pass"
            and result["error_status"] == "pass"
            and result["live_status"] == "pass"
            and result["receipt_ref"]
        )
        qualified = (
            manifest_match
            and adapter_match
            and documented
            and available
            and structurally_valid
            and authenticated
            and entitled
            and functionally_verified
        )
        operation_states.append(
            {
                "operation_id": operation_id,
                "documented_status": operation["status"],
                "available": available,
                "authenticated": authenticated,
                "entitled": entitled,
                "structurally_valid": structurally_valid,
                "functionally_verified": functionally_verified,
                "qualified": qualified,
                "receipt_ref": result["receipt_ref"] if result else None,
            }
        )
    documented_states = [
        state
        for state in operation_states
        if state["documented_status"] == "documented"
    ]
    integration_qualified = bool(documented_states) and all(
        state["qualified"] for state in documented_states
    )
    fixture_conformance_pass = bool(documented_states) and all(
        state["available"]
        and state["structurally_valid"]
        and bool(result_index[state["operation_id"]]["boundary_status"] == "pass")
        and bool(result_index[state["operation_id"]]["error_status"] == "pass")
        for state in documented_states
    )
    return with_receipt_hash(
        {
            "contract": "ProviderQualificationReceipt",
            "status": (
                "qualified"
                if integration_qualified
                else "structurally_valid"
                if fixture_conformance_pass
                else "not_verified"
            ),
            "provider_id": provider_id,
            "adapter_version": adapter_version,
            "adapter_match": adapter_match,
            "manifest_hash": manifest["manifest_hash"],
            "manifest_match": manifest_match,
            "environment": require_string(data["environment"], "request.environment"),
            "credentials_class": require_string(
                data["credentials_class"], "request.credentials_class"
            ),
            "evidence_kind": evidence_kind,
            "verified_at": require_string(data["verified_at"], "request.verified_at"),
            "expires_at": require_string(data["expires_at"], "request.expires_at"),
            "recheck_triggers": [
                require_string(item, f"request.recheck_triggers[{index}]")
                for index, item in enumerate(
                    require_list(data["recheck_triggers"], "request.recheck_triggers")
                )
            ],
            "operation_states": operation_states,
            "qualified_operation_ids": [
                state["operation_id"]
                for state in operation_states
                if state["qualified"]
            ],
            "blocked_operation_ids": [
                state["operation_id"]
                for state in operation_states
                if not state["qualified"]
            ],
            "integration_qualified": integration_qualified,
            "fixture_conformance_pass": fixture_conformance_pass,
            "product_parity": False,
            "product_status": "not_verified",
            "qualification_not_transferrable": True,
        }
    )
