"""Pure greenfield bootstrap assessment and acceptance contracts."""

from __future__ import annotations

import posixpath
import re
from typing import Any
from urllib.parse import urlsplit

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
from .policy import (
    ALLOWED_BOOTSTRAP_TRANSFER_MODES,
    GREENFIELD_POLICY,
    POLICY_BY_ASSET,
    POLICY_HASH,
    POLICY_VERSION,
    REQUIRED_CHARACTERISTIC_CLASSES,
    REQUIRED_FOUNDATION_GATES,
    REQUIRED_IDENTITY_FLAGS,
    REQUIRED_PROFILE_IDS,
    REQUIRED_ROOT_KINDS,
    REQUIRED_STORE_TYPES,
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_REF_RE = re.compile(
    r"(?i)(?:token|secret|password|api[_-]?key|authorization|signature)="
)

_MODE_ASSET_ALLOWLIST = {
    "normative_document": frozenset(
        {"foundation_repository", "current_instance_observations", "logs_and_receipts"}
    ),
    "exact_release": frozenset(
        {
            "hermes_runtime",
            "plugins_and_bridge",
            "skills_and_external_snapshots",
            "hermes_local_patches",
        }
    ),
    "synthetic_fixture": frozenset(
        {
            "current_instance_observations",
            "logs_and_receipts",
            "domain_knowledge_and_artifacts",
        }
    ),
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


def _absolute_path(value: object, path: str) -> str:
    text = require_string(value, path)
    if "\x00" in text or not text.startswith("/"):
        fail("invalid_path", path, "Ожидался абсолютный POSIX-путь без NUL.")
    normalized = posixpath.normpath(text)
    if normalized != text or text == "/":
        fail(
            "noncanonical_path",
            path,
            "Путь должен быть каноническим и не равняться корню файловой системы.",
        )
    return text


def _is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _reference(value: object, path: str) -> str:
    text = require_string(value, path)
    if "\x00" in text or _SENSITIVE_REF_RE.search(text):
        fail(
            "sensitive_reference",
            path,
            "Ссылка содержит запрещенные секретные параметры.",
        )
    parsed = urlsplit(text)
    if parsed.scheme in {"http", "https"} and (parsed.username or parsed.password):
        fail("sensitive_reference", path, "URL с реквизитами доступа запрещен.")
    return text


def _unique_rows(
    raw: object,
    path: str,
    key_name: str,
    required_values: frozenset[str],
    validator: Any,
) -> dict[str, dict[str, object]]:
    rows = require_list(raw, path)
    indexed: dict[str, dict[str, object]] = {}
    for index, item in enumerate(rows):
        row_path = f"{path}[{index}]"
        row = require_mapping(item, row_path)
        key = require_string(row.get(key_name), f"{row_path}.{key_name}")
        if key in indexed:
            fail(
                "duplicate_item",
                f"{row_path}.{key_name}",
                "Повторное значение запрещено.",
            )
        validator(row, row_path, key)
        indexed[key] = row
    missing = sorted(required_values - set(indexed))
    unknown = sorted(set(indexed) - required_values)
    if missing:
        fail("missing_item", path, f"Отсутствует обязательный элемент: {missing[0]}.")
    if unknown:
        fail("unknown_item", path, f"Неизвестный элемент: {unknown[0]}.")
    return indexed


def _validate_root(row: dict[str, object], path: str, _key: str) -> None:
    require_exact_keys(
        row, {"root_kind", "path", "existed_before", "empty_before"}, path
    )
    _absolute_path(row["path"], f"{path}.path")
    require_bool(row["existed_before"], f"{path}.existed_before")
    require_bool(row["empty_before"], f"{path}.empty_before")


def _validate_store(row: dict[str, object], path: str, _key: str) -> None:
    require_exact_keys(
        row,
        {"store_type", "created_from_empty", "initial_object_count", "source"},
        path,
    )
    require_bool(row["created_from_empty"], f"{path}.created_from_empty")
    require_int(row["initial_object_count"], f"{path}.initial_object_count")
    source = require_string(row["source"], f"{path}.source")
    if source not in {"migration", "manifest", "empty_root"}:
        fail(
            "invalid_store_source",
            f"{path}.source",
            "Недопустимый источник нового хранилища.",
        )


def _validate_profile(row: dict[str, object], path: str, _key: str) -> None:
    require_exact_keys(
        row,
        {
            "profile_id",
            "created_blank",
            "cloned_from",
            "initial_state_count",
            "qualification_status",
        },
        path,
    )
    require_bool(row["created_blank"], f"{path}.created_blank")
    if row["cloned_from"] is not None:
        fail(
            "profile_clone_forbidden",
            f"{path}.cloned_from",
            "Клонирование профиля запрещено.",
        )
    require_int(row["initial_state_count"], f"{path}.initial_state_count")
    if row["qualification_status"] != "not_started":
        fail(
            "status_inheritance_forbidden",
            f"{path}.qualification_status",
            "Новый профиль начинает с not_started.",
        )


def _validate_transfer_items(raw: object) -> tuple[list[dict[str, str]], list[str]]:
    items = require_list(raw, "request.transfer_items")
    normalized: list[dict[str, str]] = []
    blockers: list[str] = []
    seen_refs: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        path = f"request.transfer_items[{index}]"
        row = require_mapping(item, path)
        require_exact_keys(
            row, {"asset_class", "transfer_mode", "reference", "content_hash"}, path
        )
        asset_class = require_string(row["asset_class"], f"{path}.asset_class")
        transfer_mode = require_string(row["transfer_mode"], f"{path}.transfer_mode")
        reference = _reference(row["reference"], f"{path}.reference")
        content_hash = _hash(row["content_hash"], f"{path}.content_hash")
        if asset_class not in POLICY_BY_ASSET:
            fail(
                "unknown_asset_class",
                f"{path}.asset_class",
                "Класс актива отсутствует в GIP.",
            )
        if transfer_mode not in ALLOWED_BOOTSTRAP_TRANSFER_MODES:
            blockers.append(
                f"GIP forbids bootstrap transfer mode {transfer_mode} for {asset_class}"
            )
        elif asset_class not in _MODE_ASSET_ALLOWLIST[transfer_mode]:
            blockers.append(f"GIP forbids {transfer_mode} for {asset_class}")
        identity = (asset_class, reference)
        if identity in seen_refs:
            fail(
                "duplicate_transfer",
                path,
                "Повторная передача одного актива запрещена.",
            )
        seen_refs.add(identity)
        normalized.append(
            {
                "asset_class": asset_class,
                "transfer_mode": transfer_mode,
                "reference": reference,
                "content_hash": content_hash,
            }
        )
    return normalized, blockers


def assess_greenfield(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
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
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    if data["deployment_mode"] != "greenfield":
        fail(
            "deployment_mode_invalid",
            "request.deployment_mode",
            "Допустим только greenfield.",
        )

    target = require_mapping(data["target"], "request.target")
    require_exact_keys(target, {"instance_id", "service_identity"}, "request.target")
    target_instance_id = _identifier(
        target["instance_id"], "request.target.instance_id"
    )
    service_identity = _identifier(
        target["service_identity"], "request.target.service_identity"
    )

    source_instances_raw = require_list(
        data["source_instances"], "request.source_instances"
    )
    source_instances: list[dict[str, str]] = []
    source_ids: set[str] = set()
    source_roots: list[str] = []
    for index, item in enumerate(source_instances_raw):
        path = f"request.source_instances[{index}]"
        row = require_mapping(item, path)
        require_exact_keys(row, {"instance_id", "root"}, path)
        instance_id = _identifier(row["instance_id"], f"{path}.instance_id")
        root = _absolute_path(row["root"], f"{path}.root")
        if instance_id in source_ids:
            fail(
                "duplicate_source_instance",
                f"{path}.instance_id",
                "Повторный source instance запрещен.",
            )
        source_ids.add(instance_id)
        source_roots.append(root)
        source_instances.append({"instance_id": instance_id, "root": root})

    roots = _unique_rows(
        data["target_roots"],
        "request.target_roots",
        "root_kind",
        REQUIRED_ROOT_KINDS,
        _validate_root,
    )
    stores = _unique_rows(
        data["stores"],
        "request.stores",
        "store_type",
        REQUIRED_STORE_TYPES,
        _validate_store,
    )
    profiles = _unique_rows(
        data["profiles"],
        "request.profiles",
        "profile_id",
        REQUIRED_PROFILE_IDS,
        _validate_profile,
    )

    flags = require_mapping(data["new_identity_flags"], "request.new_identity_flags")
    require_exact_keys(
        flags, set(REQUIRED_IDENTITY_FLAGS), "request.new_identity_flags"
    )
    for key in sorted(REQUIRED_IDENTITY_FLAGS):
        require_bool(flags[key], f"request.new_identity_flags.{key}")

    old_dependency = require_bool(
        data["old_instance_dependency"], "request.old_instance_dependency"
    )
    copied = require_int(
        data["operational_assets_copied"], "request.operational_assets_copied"
    )
    imports = require_int(
        data["bootstrap_import_count"], "request.bootstrap_import_count"
    )
    transfers, transfer_blockers = _validate_transfer_items(data["transfer_items"])

    blockers = list(transfer_blockers)
    if target_instance_id in source_ids:
        blockers.append("target instance ID matches a source instance")
    for root_kind, row in sorted(roots.items()):
        target_path = str(row["path"])
        if bool(row["existed_before"]) and not bool(row["empty_before"]):
            blockers.append(f"target root was not empty: {root_kind}")
        for source_root in source_roots:
            if _is_within(target_path, source_root):
                blockers.append(f"target root is inside source instance: {root_kind}")
    for store_type, row in sorted(stores.items()):
        created_from_empty = require_bool(
            row["created_from_empty"],
            f"request.stores[{store_type}].created_from_empty",
        )
        initial_object_count = require_int(
            row["initial_object_count"],
            f"request.stores[{store_type}].initial_object_count",
        )
        if not created_from_empty or initial_object_count != 0:
            blockers.append(f"store did not start empty: {store_type}")
    for profile_id, row in sorted(profiles.items()):
        created_blank = require_bool(
            row["created_blank"], f"request.profiles[{profile_id}].created_blank"
        )
        initial_state_count = require_int(
            row["initial_state_count"],
            f"request.profiles[{profile_id}].initial_state_count",
        )
        if not created_blank or initial_state_count != 0:
            blockers.append(f"profile did not start blank: {profile_id}")
    for key in sorted(REQUIRED_IDENTITY_FLAGS):
        if not bool(flags[key]):
            blockers.append(f"identity was not newly provisioned: {key}")
    if old_dependency:
        blockers.append("old instance dependency is forbidden")
    if copied != 0:
        blockers.append("inherited operational assets must equal zero")
    if imports != 0:
        blockers.append("bootstrap import is forbidden before production activation")

    blockers = sorted(set(blockers))
    status = "greenfield_ready" if not blockers else "blocked"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "GreenfieldBaselineReceipt",
        "status": status,
        "deployment_mode": "greenfield",
        "target_instance_id": target_instance_id,
        "service_identity": service_identity,
        "policy_version": POLICY_VERSION,
        "policy_hash": POLICY_HASH,
        "policy_asset_count": len(GREENFIELD_POLICY),
        "source_instance_count": len(source_instances),
        "root_count": len(roots),
        "store_count": len(stores),
        "profile_count": len(profiles),
        "allowed_transfer_count": len(transfers),
        "inherited_operational_assets": copied,
        "bootstrap_import_count": imports,
        "old_instance_dependency": old_dependency,
        "blocking_issues": blockers,
        "next_gate": "foundation_bootstrap"
        if not blockers
        else "repair_greenfield_baseline",
    }
    return with_receipt_hash(payload)


def _validate_gate_vector(raw: object, target_instance_id: str) -> list[dict[str, str]]:
    rows = require_list(raw, "request.gate_vector")
    indexed: dict[str, dict[str, str]] = {}
    for index, item in enumerate(rows):
        path = f"request.gate_vector[{index}]"
        row = require_mapping(item, path)
        require_exact_keys(row, {"gate", "status", "receipt_ref", "instance_id"}, path)
        gate = require_string(row["gate"], f"{path}.gate")
        status = require_string(row["status"], f"{path}.status")
        receipt_ref = _reference(row["receipt_ref"], f"{path}.receipt_ref")
        instance_id = _identifier(row["instance_id"], f"{path}.instance_id")
        if gate in indexed:
            fail("duplicate_gate", f"{path}.gate", "Повторный gate запрещен.")
        indexed[gate] = {
            "gate": gate,
            "status": status,
            "receipt_ref": receipt_ref,
            "instance_id": instance_id,
        }
    if set(indexed) != set(REQUIRED_FOUNDATION_GATES):
        fail("incomplete_gate_vector", "request.gate_vector", "Требуются ровно G0–G8.")
    return [indexed[gate] for gate in REQUIRED_FOUNDATION_GATES]


def _validate_characteristic_receipts(
    raw: object, target_instance_id: str
) -> list[dict[str, str]]:
    rows = require_list(raw, "request.characteristic_receipts")
    indexed: dict[str, dict[str, str]] = {}
    for index, item in enumerate(rows):
        path = f"request.characteristic_receipts[{index}]"
        row = require_mapping(item, path)
        require_exact_keys(
            row, {"capability_class", "status", "receipt_ref", "instance_id"}, path
        )
        capability_class = require_string(
            row["capability_class"], f"{path}.capability_class"
        )
        status = require_string(row["status"], f"{path}.status")
        receipt_ref = _reference(row["receipt_ref"], f"{path}.receipt_ref")
        instance_id = _identifier(row["instance_id"], f"{path}.instance_id")
        if capability_class in indexed:
            fail(
                "duplicate_capability_class",
                f"{path}.capability_class",
                "Повторный класс запрещен.",
            )
        indexed[capability_class] = {
            "capability_class": capability_class,
            "status": status,
            "receipt_ref": receipt_ref,
            "instance_id": instance_id,
        }
    if set(indexed) != set(REQUIRED_CHARACTERISTIC_CLASSES):
        fail(
            "incomplete_characteristic_set",
            "request.characteristic_receipts",
            "Требуются cli/mcp/plugin/profile/service/cron/browser.",
        )
    return [indexed[key] for key in sorted(indexed)]


def accept_greenfield(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
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
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    target_instance_id = _identifier(
        data["target_instance_id"], "request.target_instance_id"
    )
    baseline = require_mapping(data["baseline_receipt"], "request.baseline_receipt")
    if not verify_receipt_hash(baseline):
        fail(
            "baseline_receipt_hash_mismatch",
            "request.baseline_receipt.receipt_hash",
            "Хеш baseline receipt не совпадает.",
        )
    if (
        baseline.get("contract") != "GreenfieldBaselineReceipt"
        or baseline.get("status") != "greenfield_ready"
    ):
        fail(
            "baseline_not_ready",
            "request.baseline_receipt.status",
            "Baseline не разрешает bootstrap.",
        )
    if baseline.get("target_instance_id") != target_instance_id:
        fail(
            "baseline_target_mismatch",
            "request.target_instance_id",
            "Baseline относится к другому instance.",
        )

    gates = _validate_gate_vector(data["gate_vector"], target_instance_id)
    characteristics = _validate_characteristic_receipts(
        data["characteristic_receipts"], target_instance_id
    )
    require_bool(data["old_instance_available"], "request.old_instance_available")
    old_dependency = require_bool(
        data["old_instance_dependency"], "request.old_instance_dependency"
    )
    copied = require_int(
        data["operational_assets_copied"], "request.operational_assets_copied"
    )
    imports = require_int(
        data["bootstrap_import_count"], "request.bootstrap_import_count"
    )
    optional_imports = require_list(
        data["optional_imports"], "request.optional_imports"
    )
    qualification_status = require_string(
        data["qualification_status"], "request.qualification_status"
    )

    blockers: list[str] = []
    for row in gates:
        if row["status"] != "pass":
            blockers.append(f"foundation gate did not pass: {row['gate']}")
        if row["instance_id"] != target_instance_id:
            blockers.append(
                f"foundation gate belongs to another instance: {row['gate']}"
            )
    for row in characteristics:
        if row["status"] != "pass":
            blockers.append(
                f"characteristic probe did not pass: {row['capability_class']}"
            )
        if row["instance_id"] != target_instance_id:
            blockers.append(
                f"characteristic probe belongs to another instance: {row['capability_class']}"
            )
    if old_dependency:
        blockers.append("old instance dependency is forbidden")
    if copied != 0:
        blockers.append("inherited operational assets must equal zero")
    if imports != 0 or optional_imports:
        blockers.append("imports are forbidden before production activation")
    if qualification_status != "not_started":
        blockers.append(
            "research qualification cannot be inherited during foundation activation"
        )

    blockers = sorted(set(blockers))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "GreenfieldAcceptanceReceipt",
        "status": "greenfield_accepted" if not blockers else "blocked",
        "deployment_mode": "greenfield",
        "target_instance_id": target_instance_id,
        "baseline_receipt_hash": baseline["receipt_hash"],
        "foundation_gate_count": len(gates),
        "characteristic_class_count": len(characteristics),
        "inherited_operational_assets": copied,
        "bootstrap_import_count": imports,
        "old_instance_independent": not old_dependency,
        "research_qualification_status": qualification_status,
        "blocking_issues": blockers,
        "next_gate": "foundation_component_install"
        if not blockers
        else "repair_greenfield_acceptance",
    }
    return with_receipt_hash(payload)
