"""Foundation bridge and authority-map assessment."""

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

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_AUTHORITIES = {
    "hermes_sessions": "hermes_profile_state",
    "work_graph": "beads",
    "subject_state": "dolt",
    "runtime_state": "runtime_coordinator",
    "source_code": "git",
    "artifacts": "artifact_service",
    "long_term_memory": "agentmemory",
    "temporal_graph": "graphiti",
    "retrieval_index": "zvec_indexer",
    "datasets": "artifact_parquet",
    "configuration_secrets": "hermes_host",
}


def _identifier(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _ID_RE.fullmatch(text):
        fail("invalid_identifier", path, "Недопустимый идентификатор.")
    return text


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _service(value: object, path: str) -> dict[str, str]:
    data = require_mapping(value, path)
    require_exact_keys(data, {"release_ref", "status", "receipt_ref"}, path)
    return {
        "release_ref": require_string(data["release_ref"], f"{path}.release_ref"),
        "status": require_string(data["status"], f"{path}.status"),
        "receipt_ref": require_string(data["receipt_ref"], f"{path}.receipt_ref"),
    }


def assess_foundation(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "target_instance_id",
            "foundation_contract_version",
            "bridge_release",
            "runtime_coordinator",
            "artifact_service",
            "authority_map",
            "bot_mode_absent",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    instance_id = _identifier(data["target_instance_id"], "request.target_instance_id")
    contract_version = require_string(
        data["foundation_contract_version"], "request.foundation_contract_version"
    )
    if contract_version == "latest":
        fail(
            "floating_version_forbidden",
            "request.foundation_contract_version",
            "Плавающая версия запрещена.",
        )

    bridge = require_mapping(data["bridge_release"], "request.bridge_release")
    require_exact_keys(
        bridge,
        {
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
        },
        "request.bridge_release",
    )
    version = require_string(bridge["version"], "request.bridge_release.version")
    commit = require_string(bridge["commit"], "request.bridge_release.commit")
    if version == "latest":
        fail(
            "floating_version_forbidden",
            "request.bridge_release.version",
            "Плавающая версия запрещена.",
        )
    if not _COMMIT_RE.fullmatch(commit):
        fail(
            "invalid_commit",
            "request.bridge_release.commit",
            "Ожидался 40-символьный commit.",
        )
    for key in ("content_hash", "sbom_hash", "migrations_hash", "tests_hash"):
        _hash(bridge[key], f"request.bridge_release.{key}")
    signature_status = require_string(
        bridge["signature_status"], "request.bridge_release.signature_status"
    )
    require_string(bridge["license"], "request.bridge_release.license")
    require_string(bridge["rollback_ref"], "request.bridge_release.rollback_ref")
    public_hooks_only = require_bool(
        bridge["public_hooks_only"], "request.bridge_release.public_hooks_only"
    )
    no_second_loop = require_bool(
        bridge["no_second_agent_loop"], "request.bridge_release.no_second_agent_loop"
    )

    runtime = _service(data["runtime_coordinator"], "request.runtime_coordinator")
    artifacts = _service(data["artifact_service"], "request.artifact_service")
    bot_mode_absent = require_bool(data["bot_mode_absent"], "request.bot_mode_absent")

    authority_rows = require_list(data["authority_map"], "request.authority_map")
    authorities: dict[str, tuple[str, int, str]] = {}
    for index, item in enumerate(authority_rows):
        path = f"request.authority_map[{index}]"
        row = require_mapping(item, path)
        require_exact_keys(
            row, {"state_type", "authority", "writer_count", "access_mode"}, path
        )
        state_type = require_string(row["state_type"], f"{path}.state_type")
        authority = require_string(row["authority"], f"{path}.authority")
        writer_count = require_int(row["writer_count"], f"{path}.writer_count")
        access_mode = require_string(row["access_mode"], f"{path}.access_mode")
        if state_type in authorities:
            fail(
                "duplicate_authority",
                f"{path}.state_type",
                "Повторный тип состояния запрещен.",
            )
        authorities[state_type] = (authority, writer_count, access_mode)
    missing = sorted(set(REQUIRED_AUTHORITIES) - set(authorities))
    unknown = sorted(set(authorities) - set(REQUIRED_AUTHORITIES))
    if missing:
        fail(
            "missing_authority",
            "request.authority_map",
            f"Отсутствует authority: {missing[0]}.",
        )
    if unknown:
        fail(
            "unknown_authority",
            "request.authority_map",
            f"Неизвестный тип состояния: {unknown[0]}.",
        )

    blockers: list[str] = []
    if signature_status != "verified":
        blockers.append("bridge signature is not verified")
    if not public_hooks_only:
        blockers.append("bridge uses private Hermes hooks")
    if not no_second_loop:
        blockers.append("bridge may start a second agent loop")
    if not bot_mode_absent:
        blockers.append("Bot Mode state is present")
    for label, service in (
        ("runtime_coordinator", runtime),
        ("artifact_service", artifacts),
    ):
        if service["status"] not in {"characteristic_verified", "qualified"}:
            blockers.append(f"{label} is not characteristic_verified")
    for state_type, expected in sorted(REQUIRED_AUTHORITIES.items()):
        actual, writer_count, access_mode = authorities[state_type]
        if actual != expected:
            blockers.append(f"wrong authority for {state_type}: {actual}")
        if writer_count != 1:
            blockers.append(f"writer count is not one for {state_type}")
        if access_mode not in {"adapter", "public_api", "host_only", "read_only"}:
            blockers.append(f"invalid access mode for {state_type}")

    blockers = sorted(set(blockers))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "FoundationCompatibilityReceipt",
        "status": "foundation_ready" if not blockers else "blocked",
        "target_instance_id": instance_id,
        "foundation_contract_version": contract_version,
        "bridge_version": version,
        "bridge_commit": commit,
        "authority_count": len(authorities),
        "single_writer_count": sum(
            1 for _, writer_count, _ in authorities.values() if writer_count == 1
        ),
        "runtime_coordinator_status": runtime["status"],
        "artifact_service_status": artifacts["status"],
        "bot_mode_absent": bot_mode_absent,
        "blocking_issues": blockers,
        "next_gate": "state_and_artifact_contracts"
        if not blockers
        else "repair_foundation_contract",
    }
    return with_receipt_hash(payload)
