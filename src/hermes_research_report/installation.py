"""Pure staging-installation gate for the new foundation instance."""

from __future__ import annotations

from typing import Any

from .canonical import verify_receipt_hash, with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

REQUIRED_INSTALL_PROBES = frozenset(
    {
        "public_hooks",
        "dolt_state",
        "runtime",
        "artifact",
        "agentmemory",
        "graphiti",
        "zvec",
        "evidence_capture",
    }
)


def assess_installation(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
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
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    instance_id = require_string(
        data["target_instance_id"], "request.target_instance_id"
    )
    greenfield = require_mapping(
        data["greenfield_acceptance_receipt"], "request.greenfield_acceptance_receipt"
    )
    foundation = require_mapping(
        data["foundation_receipt"], "request.foundation_receipt"
    )
    for name, receipt in (
        ("greenfield_acceptance", greenfield),
        ("foundation", foundation),
    ):
        if not verify_receipt_hash(receipt):
            fail(
                "receipt_hash_mismatch",
                f"request.{name}_receipt.receipt_hash",
                "Хеш квитанции не совпадает.",
            )
        if receipt.get("target_instance_id") != instance_id:
            fail(
                "receipt_target_mismatch",
                f"request.{name}_receipt.target_instance_id",
                "Квитанция относится к другому instance.",
            )

    staging = require_mapping(data["staging_profile"], "request.staging_profile")
    require_exact_keys(
        staging,
        {
            "profile_id",
            "created_blank",
            "private_import_count",
            "copied_live_asset_count",
        },
        "request.staging_profile",
    )
    profile_id = require_string(
        staging["profile_id"], "request.staging_profile.profile_id"
    )
    created_blank = require_bool(
        staging["created_blank"], "request.staging_profile.created_blank"
    )
    private_imports = require_int(
        staging["private_import_count"], "request.staging_profile.private_import_count"
    )
    copied_live = require_int(
        staging["copied_live_asset_count"],
        "request.staging_profile.copied_live_asset_count",
    )

    migration = require_string(
        data["migration_dry_run_status"], "request.migration_dry_run_status"
    )
    native_e2e = require_string(data["native_e2e_status"], "request.native_e2e_status")
    rollback = require_string(
        data["rollback_smoke_status"], "request.rollback_smoke_status"
    )
    qualification = require_string(
        data["research_qualification_status"], "request.research_qualification_status"
    )

    probe_rows = require_list(
        data["characteristic_probes"], "request.characteristic_probes"
    )
    probes: dict[str, tuple[str, str, bool]] = {}
    for index, item in enumerate(probe_rows):
        path = f"request.characteristic_probes[{index}]"
        row = require_mapping(item, path)
        require_exact_keys(
            row, {"capability", "status", "receipt_ref", "current"}, path
        )
        capability = require_string(row["capability"], f"{path}.capability")
        status = require_string(row["status"], f"{path}.status")
        receipt_ref = require_string(row["receipt_ref"], f"{path}.receipt_ref")
        current = require_bool(row["current"], f"{path}.current")
        if capability in probes:
            fail(
                "duplicate_probe",
                f"{path}.capability",
                "Повторная характерная проба запрещена.",
            )
        probes[capability] = (status, receipt_ref, current)
    if set(probes) != set(REQUIRED_INSTALL_PROBES):
        fail(
            "incomplete_probe_set",
            "request.characteristic_probes",
            "Требуется полный набор установочных проб.",
        )

    blockers: list[str] = []
    if greenfield.get("status") != "greenfield_accepted":
        blockers.append("greenfield acceptance is not complete")
    if foundation.get("status") != "foundation_ready":
        blockers.append("foundation contract is not ready")
    if not created_blank:
        blockers.append("staging profile was not created blank")
    if private_imports:
        blockers.append("private Hermes imports are forbidden")
    if copied_live:
        blockers.append("copied live assets are forbidden")
    if migration != "pass":
        blockers.append("migration dry run failed")
    for capability, (status, _ref, current) in sorted(probes.items()):
        if status != "pass":
            blockers.append(f"characteristic probe failed: {capability}")
        if not current:
            blockers.append(f"characteristic receipt is stale: {capability}")
    if native_e2e != "pass":
        blockers.append("native Hermes E2E failed")
    if rollback != "pass":
        blockers.append("rollback smoke failed")
    if qualification != "not_started":
        blockers.append("research qualification cannot be inherited")

    blockers = sorted(set(blockers))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "FoundationInstallReceipt",
        "status": "integration_ready" if not blockers else "blocked",
        "target_instance_id": instance_id,
        "staging_profile_id": profile_id,
        "probe_count": len(probes),
        "current_probe_count": sum(
            current for _status, _ref, current in probes.values()
        ),
        "private_import_count": private_imports,
        "copied_live_asset_count": copied_live,
        "research_qualification_status": qualification,
        "allowed_claims": ["foundation_integration_ready"] if not blockers else [],
        "prohibited_claims": [
            "parsing_qualified",
            "search_qualified",
            "research_qualified",
            "deep_research_qualified",
            "ultra_deep_research_qualified",
            "academic_qualified",
        ],
        "blocking_issues": blockers,
        "next_gate": "research_component_qualification"
        if not blockers
        else "repair_staging_installation",
    }
    return with_receipt_hash(payload)
