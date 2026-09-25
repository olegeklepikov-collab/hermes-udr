"""Provider-neutral execution, required-set, conformance, and failure controls."""

from __future__ import annotations

import re
from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_list,
    require_mapping,
    require_string,
)

_TEXT = {"type": "string", "minLength": 1}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_TYPES = {
    "capability_request",
    "required_set",
    "conformance",
    "independence",
    "failure_normalization",
}

PROVIDER_EXECUTION_ASSESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "control_type", "payload"],
    "properties": {
        "schema_version": {"const": 1},
        "control_type": {"enum": sorted(_CONTROL_TYPES)},
        "payload": {"type": "object"},
    },
}


def _nullable(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def _strings(value: object, path: str) -> list[str]:
    rows = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(rows) != len(set(rows)):
        fail("duplicate_item", path, "Повтор элемента запрещён.")
    return rows


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _capability(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {
            "request_ref",
            "capability_id",
            "contract_version",
            "arguments_hash",
            "adapters",
        },
        "request.payload",
    )
    request_ref = require_string(payload["request_ref"], "request.payload.request_ref")
    capability_id = _nullable(payload["capability_id"], "request.payload.capability_id")
    contract_version = require_string(
        payload["contract_version"], "request.payload.contract_version"
    )
    arguments_hash = _hash(payload["arguments_hash"], "request.payload.arguments_hash")
    issues = []
    if capability_id is None or capability_id.startswith("/"):
        issues.append("missing_capability_id")
    results = []
    for index, raw in enumerate(
        require_list(payload["adapters"], "request.payload.adapters")
    ):
        path = f"request.payload.adapters[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "adapter_id",
                "capability_id",
                "contract_version",
                "executable_ref",
                "route_receipt_ref",
                "result_status",
            },
            path,
        )
        adapter_capability = require_string(
            row["capability_id"], f"{path}.capability_id"
        )
        adapter_version = require_string(
            row["contract_version"], f"{path}.contract_version"
        )
        compatible = (
            capability_id == adapter_capability and contract_version == adapter_version
        )
        if not compatible:
            issues.append(f"adapter_contract_mismatch:{index}")
        results.append(
            {
                "adapter_id": require_string(row["adapter_id"], f"{path}.adapter_id"),
                "request_ref": request_ref,
                "arguments_hash": arguments_hash,
                "route_receipt_ref": require_string(
                    row["route_receipt_ref"], f"{path}.route_receipt_ref"
                ),
                "executable_ref": require_string(
                    row["executable_ref"], f"{path}.executable_ref"
                ),
                "result_status": require_string(
                    row["result_status"], f"{path}.result_status"
                ),
                "compatible": compatible,
            }
        )
    return {
        "request_ref": request_ref,
        "capability_id": capability_id,
        "results": results,
        "ready": not issues and bool(results),
        "issues": issues,
    }


def _required_set(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {"required_capabilities", "optional_capabilities", "available_capabilities"},
        "request.payload",
    )
    required = set(
        _strings(
            payload["required_capabilities"], "request.payload.required_capabilities"
        )
    )
    optional = set(
        _strings(
            payload["optional_capabilities"], "request.payload.optional_capabilities"
        )
    )
    available = set(
        _strings(
            payload["available_capabilities"], "request.payload.available_capabilities"
        )
    )
    missing_required = sorted(required - available)
    missing_optional = sorted(optional - available)
    return {
        "execution_status": "ready" if not missing_required else "waiting_dependency",
        "missing_required": missing_required,
        "warnings": [f"optional_unavailable:{item}" for item in missing_optional],
        "ready": not missing_required,
        "issues": [f"required_unavailable:{item}" for item in missing_required],
    }


def _conformance(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "capability_id",
        "fixture_hash",
        "expected_text",
        "expected_locator",
        "observed_text",
        "observed_locator",
        "dependencies",
        "test_receipt_ref",
        "test_receipt_current",
    }
    require_exact_keys(payload, keys, "request.payload")
    issues = []
    dependencies = []
    for index, raw in enumerate(
        require_list(payload["dependencies"], "request.payload.dependencies")
    ):
        path = f"request.payload.dependencies[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"name", "required", "available"}, path)
        required = require_bool(row["required"], f"{path}.required")
        available = require_bool(row["available"], f"{path}.available")
        name = require_string(row["name"], f"{path}.name")
        if required and not available:
            issues.append(f"dependency_missing:{name}")
        dependencies.append(
            {"name": name, "required": required, "available": available}
        )
    if require_string(
        payload["expected_text"], "request.payload.expected_text"
    ) != require_string(
        payload["observed_text"], "request.payload.observed_text"
    ) or require_string(
        payload["expected_locator"], "request.payload.expected_locator"
    ) != require_string(
        payload["observed_locator"], "request.payload.observed_locator"
    ):
        issues.append("contract_test_failed")
    current = require_bool(
        payload["test_receipt_current"], "request.payload.test_receipt_current"
    )
    if not current:
        issues.append("contract_test_stale")
    return {
        "capability_id": require_string(
            payload["capability_id"], "request.payload.capability_id"
        ),
        "fixture_hash": _hash(payload["fixture_hash"], "request.payload.fixture_hash"),
        "test_receipt_ref": require_string(
            payload["test_receipt_ref"], "request.payload.test_receipt_ref"
        ),
        "dependencies": dependencies,
        "route_selected": not issues,
        "issues": issues,
    }


def _independence(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {"author_family", "author_process_signature", "candidates"},
        "request.payload",
    )
    author_family = require_string(
        payload["author_family"], "request.payload.author_family"
    )
    author_process = require_string(
        payload["author_process_signature"], "request.payload.author_process_signature"
    )
    candidates = []
    for index, raw in enumerate(
        require_list(payload["candidates"], "request.payload.candidates")
    ):
        path = f"request.payload.candidates[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {"route_id", "family", "process_signature", "author_verdict_included"},
            path,
        )
        family = require_string(row["family"], f"{path}.family")
        process = require_string(row["process_signature"], f"{path}.process_signature")
        verdict = require_bool(
            row["author_verdict_included"], f"{path}.author_verdict_included"
        )
        independent = (
            family != author_family and process != author_process and not verdict
        )
        candidates.append(
            {
                "route_id": require_string(row["route_id"], f"{path}.route_id"),
                "family": family,
                "process_signature": process,
                "author_verdict_included": verdict,
                "independent": independent,
            }
        )
    selected = next((row for row in candidates if row["independent"]), None)
    issues = [] if selected else ["independence_unavailable"]
    return {
        "selected_route": selected,
        "result_status": "review_ready" if selected else "review_required",
        "positive_acceptance_created": False,
        "issues": issues,
    }


def _failures(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(payload, {"cases"}, "request.payload")
    mapping = {
        "401": ("auth_required", "not_started"),
        "429": ("rate_limited", "not_started"),
        "timeout_after_acceptance": ("unknown_outcome", "unknown"),
        "invalid_json": ("contract_mismatch", "not_started"),
    }
    results = []
    issues = []
    seen = set()
    for index, raw in enumerate(
        require_list(payload["cases"], "request.payload.cases")
    ):
        path = f"request.payload.cases[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {"case_id", "raw_kind", "reported_execution_status", "output_ref"},
            path,
        )
        case_id = require_string(row["case_id"], f"{path}.case_id")
        raw_kind = require_string(row["raw_kind"], f"{path}.raw_kind")
        if raw_kind not in mapping:
            fail("unknown_failure_kind", f"{path}.raw_kind", "Неизвестный отказ.")
        normalized, side_effect = mapping[raw_kind]
        reported = require_string(
            row["reported_execution_status"], f"{path}.reported_execution_status"
        )
        output_ref = _nullable(row["output_ref"], f"{path}.output_ref")
        if (
            raw_kind == "timeout_after_acceptance"
            and reported == "succeeded"
            and output_ref is None
        ):
            issues.append(f"false_success:{case_id}")
        seen.add(normalized)
        results.append(
            {
                "case_id": case_id,
                "normalized_status": normalized,
                "side_effect_state": side_effect,
                "output_ref": output_ref,
            }
        )
    required = {value[0] for value in mapping.values()}
    for missing in sorted(required - seen):
        issues.append(f"failure_class_missing:{missing}")
    return {"cases": results, "issues": issues}


_ASSESSORS = {
    "capability_request": _capability,
    "required_set": _required_set,
    "conformance": _conformance,
    "independence": _independence,
    "failure_normalization": _failures,
}


def assess_provider_execution(request: object) -> dict[str, Any]:
    """Assess one provider execution control without invoking a provider."""

    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "control_type", "payload"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    control_type = require_string(data["control_type"], "request.control_type")
    if control_type not in _ASSESSORS:
        fail("invalid_control_type", "request.control_type", "Неизвестный контроль.")
    result = _ASSESSORS[control_type](
        require_mapping(data["payload"], "request.payload")
    )
    issues = _strings(result.get("issues", []), "result.issues")
    return with_receipt_hash(
        {
            "contract": "ProviderExecutionControlReceipt",
            "control_type": control_type,
            "status": "accepted" if not issues else "blocked",
            **result,
        }
    )
