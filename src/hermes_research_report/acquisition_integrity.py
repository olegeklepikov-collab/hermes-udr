"""Acquisition policy, target validation, transformation, and version binding."""

from __future__ import annotations

import re
from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

_TEXT = {"type": "string", "minLength": 1}
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

ACQUISITION_INTEGRITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "source",
        "policy",
        "acquisition",
        "original",
        "transformation",
        "locator_authorization",
        "requested_source_version",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "source": {"type": "object"},
        "policy": {"type": "object"},
        "acquisition": {"type": "object"},
        "original": {"type": "object"},
        "transformation": {"type": "object"},
        "locator_authorization": {"type": "object"},
        "requested_source_version": _TEXT,
    },
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повтор элемента запрещён.")
    return result


def assess_acquisition_integrity(request: object) -> dict[str, Any]:
    """Assess one acquisition path without executing a network request."""

    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "source",
            "policy",
            "acquisition",
            "original",
            "transformation",
            "locator_authorization",
            "requested_source_version",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    issues: list[str] = []

    source = require_mapping(data["source"], "request.source")
    require_exact_keys(source, {"source_id", "version", "media_type"}, "request.source")
    source_id = require_string(source["source_id"], "request.source.source_id")
    source_version = require_string(source["version"], "request.source.version")
    media_type = require_string(source["media_type"], "request.source.media_type")

    policy = require_mapping(data["policy"], "request.policy")
    require_exact_keys(
        policy, {"allowed_routes", "external_transfer_allowed"}, "request.policy"
    )
    allowed_routes = _strings(policy["allowed_routes"], "request.policy.allowed_routes")
    external_allowed = require_bool(
        policy["external_transfer_allowed"], "request.policy.external_transfer_allowed"
    )

    acquisition = require_mapping(data["acquisition"], "request.acquisition")
    require_exact_keys(
        acquisition,
        {
            "route",
            "route_is_external",
            "object_media_type",
            "payload_bytes",
            "payload_hash",
            "target_match",
            "observed_external_call_count",
        },
        "request.acquisition",
    )
    route = require_string(acquisition["route"], "request.acquisition.route")
    route_external = require_bool(
        acquisition["route_is_external"], "request.acquisition.route_is_external"
    )
    external_calls = require_int(
        acquisition["observed_external_call_count"],
        "request.acquisition.observed_external_call_count",
    )
    route_allowed = route in allowed_routes and (external_allowed or not route_external)
    if not route_allowed:
        issues.append("access_policy_block")
    if not route_allowed and external_calls:
        issues.append("forbidden_route_called")
    payload_bytes = require_int(
        acquisition["payload_bytes"], "request.acquisition.payload_bytes"
    )
    payload_hash = _hash(
        acquisition["payload_hash"], "request.acquisition.payload_hash"
    )
    object_media_type = require_string(
        acquisition["object_media_type"], "request.acquisition.object_media_type"
    )
    target_match = require_bool(
        acquisition["target_match"], "request.acquisition.target_match"
    )
    acquired = (
        route_allowed
        and payload_bytes > 0
        and target_match
        and object_media_type == media_type
    )
    if payload_bytes == 0:
        issues.append("empty_payload")
    if not target_match or object_media_type != media_type:
        issues.append("target_document_mismatch")

    original = require_mapping(data["original"], "request.original")
    require_exact_keys(
        original, {"asset_ref", "content_hash", "immutable"}, "request.original"
    )
    original_hash = _hash(original["content_hash"], "request.original.content_hash")
    immutable = require_bool(original["immutable"], "request.original.immutable")
    if not immutable or original_hash != payload_hash:
        issues.append("protected_original")

    transformation = require_mapping(data["transformation"], "request.transformation")
    require_exact_keys(
        transformation,
        {
            "derived_ref",
            "input_hash",
            "output_hash",
            "parameters_json",
            "segment_map",
            "reverse_mapping_complete",
            "quote_raw",
        },
        "request.transformation",
    )
    derived_ref = require_string(
        transformation["derived_ref"], "request.transformation.derived_ref"
    )
    input_hash = _hash(
        transformation["input_hash"], "request.transformation.input_hash"
    )
    output_hash = _hash(
        transformation["output_hash"], "request.transformation.output_hash"
    )
    require_string(
        transformation["parameters_json"], "request.transformation.parameters_json"
    )
    reverse_complete = require_bool(
        transformation["reverse_mapping_complete"],
        "request.transformation.reverse_mapping_complete",
    )
    quote_raw = require_string(
        transformation["quote_raw"], "request.transformation.quote_raw"
    )
    segment_map = []
    for index, raw in enumerate(
        require_list(
            transformation["segment_map"], "request.transformation.segment_map"
        )
    ):
        path = f"request.transformation.segment_map[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "source_page",
                "source_start",
                "source_end",
                "derived_start",
                "derived_end",
            },
            path,
        )
        source_start = require_int(row["source_start"], f"{path}.source_start")
        source_end = require_int(row["source_end"], f"{path}.source_end")
        derived_start = require_int(row["derived_start"], f"{path}.derived_start")
        derived_end = require_int(row["derived_end"], f"{path}.derived_end")
        if source_end <= source_start or derived_end <= derived_start:
            issues.append("invalid_segment_map")
        segment_map.append(
            {
                "source_page": require_int(
                    row["source_page"], f"{path}.source_page", minimum=1
                ),
                "source_start": source_start,
                "source_end": source_end,
                "derived_start": derived_start,
                "derived_end": derived_end,
            }
        )
    if input_hash != original_hash:
        issues.append("transformation_input_mismatch")
    if output_hash == original_hash or derived_ref == original["asset_ref"]:
        issues.append("derived_identity_not_separate")
    if not reverse_complete or not segment_map:
        issues.append("missing_reverse_mapping")

    authorization = require_mapping(
        data["locator_authorization"], "request.locator_authorization"
    )
    require_exact_keys(
        authorization,
        {"source_id", "source_version", "locator", "authorized"},
        "request.locator_authorization",
    )
    authorized = require_bool(
        authorization["authorized"], "request.locator_authorization.authorized"
    )
    requested_version = require_string(
        data["requested_source_version"], "request.requested_source_version"
    )
    version_binding_current = (
        authorized
        and require_string(
            authorization["source_id"], "request.locator_authorization.source_id"
        )
        == source_id
        and require_string(
            authorization["source_version"],
            "request.locator_authorization.source_version",
        )
        == source_version
        == requested_version
    )
    if not version_binding_current:
        issues.append("version_binding_mismatch")
    locator = require_string(
        authorization["locator"], "request.locator_authorization.locator"
    )
    evidence_fragment_allowed = (
        acquired
        and immutable
        and reverse_complete
        and bool(segment_map)
        and version_binding_current
        and not issues
    )
    return with_receipt_hash(
        {
            "contract": "AcquisitionIntegrityReceipt",
            "status": "accepted" if not issues else "blocked",
            "source_ref": {"id": source_id, "version": source_version},
            "route": route,
            "route_allowed": route_allowed,
            "observed_external_call_count": external_calls,
            "acquisition_status": "acquired" if acquired else "not_acquired",
            "original": {
                "asset_ref": original["asset_ref"],
                "content_hash": original_hash,
                "immutable": immutable,
            },
            "transformation": {
                "derived_ref": derived_ref,
                "input_hash": input_hash,
                "output_hash": output_hash,
                "segment_map": segment_map,
                "quote_raw": quote_raw,
                "reverse_mapping_complete": reverse_complete,
            },
            "locator": locator,
            "version_binding_current": version_binding_current,
            "evidence_fragment_allowed": evidence_fragment_allowed,
            "issues": sorted(set(issues)),
        }
    )
