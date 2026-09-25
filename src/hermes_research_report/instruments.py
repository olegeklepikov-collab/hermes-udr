"""Instrument portfolio, strategy, query-envelope, and revision contracts."""

from __future__ import annotations

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

_TEXT = {"type": "string", "minLength": 1}
_TEXTS = {"type": "array", "maxItems": 1000, "uniqueItems": True, "items": _TEXT}
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_PROBE_STATES = {"pass", "fail", "stale"}

_INSTRUMENT_FIELDS = {
    "instrument_ref",
    "adapter_version",
    "capability",
    "required_query_fields",
    "optional_query_fields",
    "output_schema_ref",
    "input_formats",
    "output_formats",
    "modalities",
    "max_input_bytes",
    "latency_class",
    "cost_upper_bound",
    "risk_class",
    "permissions",
    "failure_modes",
    "cancellable",
    "idempotent",
    "probe",
    "observed_yield",
}

_INSTRUMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_INSTRUMENT_FIELDS),
    "properties": {
        "instrument_ref": _TEXT,
        "adapter_version": _TEXT,
        "capability": _TEXT,
        "required_query_fields": _TEXTS,
        "optional_query_fields": _TEXTS,
        "output_schema_ref": _TEXT,
        "input_formats": _TEXTS,
        "output_formats": _TEXTS,
        "modalities": _TEXTS,
        "max_input_bytes": {"type": "integer", "minimum": 1},
        "latency_class": _TEXT,
        "cost_upper_bound": {"type": "integer", "minimum": 0},
        "risk_class": {"enum": ["low", "medium", "high"]},
        "permissions": _TEXTS,
        "failure_modes": _TEXTS,
        "cancellable": {"type": "boolean"},
        "idempotent": {"type": "boolean"},
        "probe": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "receipt_ref", "observed_output_schema_ref"],
            "properties": {
                "status": {"enum": sorted(_PROBE_STATES)},
                "receipt_ref": _TEXT,
                "observed_output_schema_ref": _TEXT,
            },
        },
        "observed_yield": {
            "type": "object",
            "additionalProperties": False,
            "required": ["calls", "useful_results", "errors"],
            "properties": {
                "calls": {"type": "integer", "minimum": 0},
                "useful_results": {"type": "integer", "minimum": 0},
                "errors": {"type": "integer", "minimum": 0},
            },
        },
    },
}

INSTRUMENT_PORTFOLIO_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "portfolio_id", "candidates"],
    "properties": {
        "schema_version": {"const": 1},
        "portfolio_id": _TEXT,
        "candidates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": _INSTRUMENT_SCHEMA,
        },
    },
}

INSTRUMENT_STRATEGY_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "strategy_id",
        "portfolio_ref",
        "portfolio_revision",
        "portfolio_hash",
        "eligible_instruments",
        "profile_ref",
        "profile_version",
        "profile_hash",
        "items",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "strategy_id": _TEXT,
        "portfolio_ref": _TEXT,
        "portfolio_revision": {"type": "integer", "minimum": 1},
        "portfolio_hash": _HASH,
        "eligible_instruments": {
            "type": "array",
            "maxItems": 1000,
            "items": _INSTRUMENT_SCHEMA,
        },
        "profile_ref": _TEXT,
        "profile_version": {"type": "integer", "minimum": 1},
        "profile_hash": _HASH,
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "strategy_item_ref",
                    "subquestion_ref",
                    "construct_refs",
                    "capability",
                    "modalities",
                    "sequence",
                    "parallel_group",
                    "call_limit",
                    "cost_reserve",
                    "success_oracle",
                    "switch_condition",
                ],
                "properties": {
                    "strategy_item_ref": _TEXT,
                    "subquestion_ref": _TEXT,
                    "construct_refs": _TEXTS,
                    "capability": _TEXT,
                    "modalities": _TEXTS,
                    "sequence": {"type": "integer", "minimum": 1},
                    "parallel_group": {"type": ["string", "null"]},
                    "call_limit": {"type": "integer", "minimum": 1},
                    "cost_reserve": {"type": "integer", "minimum": 0},
                    "success_oracle": _TEXT,
                    "switch_condition": _TEXT,
                },
            },
        },
    },
}

TOOL_QUERY_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "strategy_ref",
        "strategy_revision",
        "strategy_hash",
        "strategy_item",
        "profile_ref",
        "profile_version",
        "profile_hash",
        "query_fields",
        "raw_question_copied",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "strategy_ref": _TEXT,
        "strategy_revision": {"type": "integer", "minimum": 1},
        "strategy_hash": _HASH,
        "strategy_item": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "strategy_item_ref",
                "subquestion_ref",
                "construct_refs",
                "capability",
                "modality",
                "instrument_ref",
                "required_query_fields",
                "optional_query_fields",
                "expected_output_schema",
                "success_oracle",
                "sequence",
                "parallel_group",
                "call_limit",
                "cost_reserve",
                "switch_condition",
            ],
            "properties": {
                "strategy_item_ref": _TEXT,
                "subquestion_ref": _TEXT,
                "construct_refs": _TEXTS,
                "capability": _TEXT,
                "modality": _TEXT,
                "instrument_ref": _TEXT,
                "required_query_fields": _TEXTS,
                "optional_query_fields": _TEXTS,
                "expected_output_schema": _TEXT,
                "success_oracle": _TEXT,
                "sequence": {"type": "integer", "minimum": 1},
                "parallel_group": {"type": ["string", "null"]},
                "call_limit": {"type": "integer", "minimum": 1},
                "cost_reserve": {"type": "integer", "minimum": 0},
                "switch_condition": _TEXT,
            },
        },
        "profile_ref": _TEXT,
        "profile_version": {"type": "integer", "minimum": 1},
        "profile_hash": _HASH,
        "query_fields": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "value_json"],
                "properties": {"name": _TEXT, "value_json": _TEXT},
            },
        },
        "raw_question_copied": {"type": "boolean"},
    },
}

INSTRUMENT_STRATEGY_REVISE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "strategy_ref",
        "current_revision",
        "expected_revision",
        "current_hash",
        "prior_receipt_refs",
        "yield_observations",
        "change_reason",
        "proposed_assignment_refs",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "strategy_ref": _TEXT,
        "current_revision": {"type": "integer", "minimum": 1},
        "expected_revision": {"type": "integer", "minimum": 1},
        "current_hash": _HASH,
        "prior_receipt_refs": _TEXTS,
        "yield_observations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["instrument_ref", "calls", "useful_results", "errors"],
                "properties": {
                    "instrument_ref": _TEXT,
                    "calls": {"type": "integer", "minimum": 1},
                    "useful_results": {"type": "integer", "minimum": 0},
                    "errors": {"type": "integer", "minimum": 0},
                },
            },
        },
        "change_reason": _TEXT,
        "proposed_assignment_refs": _TEXTS,
    },
}


def _schema(request: object, fields: set[str]) -> dict[str, object]:
    data = require_mapping(request, "request")
    require_exact_keys(data, fields, "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    return data


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{i}]")
        for i, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_value", path, "Повтор значения запрещён.")
    return result


def _instrument(value: object, path: str) -> dict[str, Any]:
    row = require_mapping(value, path)
    require_exact_keys(row, _INSTRUMENT_FIELDS, path)
    probe = require_mapping(row["probe"], f"{path}.probe")
    require_exact_keys(
        probe, {"status", "receipt_ref", "observed_output_schema_ref"}, f"{path}.probe"
    )
    probe_status = require_string(probe["status"], f"{path}.probe.status")
    if probe_status not in _PROBE_STATES:
        fail(
            "invalid_probe_status", f"{path}.probe.status", "Неизвестный статус пробы."
        )
    output_schema = require_string(
        row["output_schema_ref"], f"{path}.output_schema_ref"
    )
    observed_schema = require_string(
        probe["observed_output_schema_ref"], f"{path}.probe.observed_output_schema_ref"
    )
    observed = require_mapping(row["observed_yield"], f"{path}.observed_yield")
    require_exact_keys(
        observed, {"calls", "useful_results", "errors"}, f"{path}.observed_yield"
    )
    required_fields = _strings(
        row["required_query_fields"], f"{path}.required_query_fields"
    )
    optional_fields = _strings(
        row["optional_query_fields"], f"{path}.optional_query_fields"
    )
    if set(required_fields) & set(optional_fields):
        fail(
            "query_field_overlap",
            path,
            "Обязательные и необязательные поля пересекаются.",
        )
    record = {
        "instrument_ref": require_string(
            row["instrument_ref"], f"{path}.instrument_ref"
        ),
        "adapter_version": require_string(
            row["adapter_version"], f"{path}.adapter_version"
        ),
        "capability": require_string(row["capability"], f"{path}.capability"),
        "required_query_fields": required_fields,
        "optional_query_fields": optional_fields,
        "output_schema_ref": output_schema,
        "input_formats": _strings(row["input_formats"], f"{path}.input_formats"),
        "output_formats": _strings(row["output_formats"], f"{path}.output_formats"),
        "modalities": _strings(row["modalities"], f"{path}.modalities"),
        "max_input_bytes": require_int(
            row["max_input_bytes"], f"{path}.max_input_bytes", minimum=1
        ),
        "latency_class": require_string(row["latency_class"], f"{path}.latency_class"),
        "cost_upper_bound": require_int(
            row["cost_upper_bound"], f"{path}.cost_upper_bound"
        ),
        "risk_class": require_string(row["risk_class"], f"{path}.risk_class"),
        "permissions": _strings(row["permissions"], f"{path}.permissions"),
        "failure_modes": _strings(row["failure_modes"], f"{path}.failure_modes"),
        "cancellable": require_bool(row["cancellable"], f"{path}.cancellable"),
        "idempotent": require_bool(row["idempotent"], f"{path}.idempotent"),
        "probe": {
            "status": probe_status,
            "receipt_ref": require_string(
                probe["receipt_ref"], f"{path}.probe.receipt_ref"
            ),
            "observed_output_schema_ref": observed_schema,
        },
        "observed_yield": {
            key: require_int(observed[key], f"{path}.observed_yield.{key}")
            for key in ("calls", "useful_results", "errors")
        },
    }
    record["eligible"] = probe_status == "pass" and observed_schema == output_schema
    record["exclusion_reasons"] = (
        []
        if record["eligible"]
        else (
            ["probe_not_passed"]
            if probe_status != "pass"
            else ["output_schema_probe_mismatch"]
        )
    )
    return record


def build_instrument_portfolio(request: object) -> dict[str, Any]:
    data = _schema(request, set(INSTRUMENT_PORTFOLIO_BUILD_SCHEMA["required"]))
    portfolio_id = require_string(data["portfolio_id"], "request.portfolio_id")
    instruments = [
        _instrument(raw, f"request.candidates[{i}]")
        for i, raw in enumerate(require_list(data["candidates"], "request.candidates"))
    ]
    refs = [row["instrument_ref"] for row in instruments]
    if len(refs) != len(set(refs)):
        fail("duplicate_instrument", "request.candidates", "Повтор инструмента.")
    eligible_cards = [
        {key: row[key] for key in sorted(_INSTRUMENT_FIELDS)}
        for row in instruments
        if row["eligible"]
    ]
    body = {"portfolio_id": portfolio_id, "revision": 1, "instruments": instruments}
    body["content_hash"] = sha256_json(body)
    payload = {
        "schema_version": 1,
        "contract": "InstrumentPortfolioReceipt",
        "status": "portfolio_ready",
        "portfolio": body,
        "eligible_instruments": eligible_cards,
        "eligible_instrument_refs": sorted(
            row["instrument_ref"] for row in instruments if row["eligible"]
        ),
        "excluded_instrument_refs": sorted(
            row["instrument_ref"] for row in instruments if not row["eligible"]
        ),
        "probe_declared_as_execution": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def build_instrument_strategy(request: object) -> dict[str, Any]:
    data = _schema(request, set(INSTRUMENT_STRATEGY_BUILD_SCHEMA["required"]))
    strategy_id = require_string(data["strategy_id"], "request.strategy_id")
    portfolio_ref = require_string(data["portfolio_ref"], "request.portfolio_ref")
    portfolio_revision = require_int(
        data["portfolio_revision"], "request.portfolio_revision", minimum=1
    )
    portfolio_hash = require_string(data["portfolio_hash"], "request.portfolio_hash")
    profile_ref = require_string(data["profile_ref"], "request.profile_ref")
    profile_version = require_int(
        data["profile_version"], "request.profile_version", minimum=1
    )
    profile_hash = require_string(data["profile_hash"], "request.profile_hash")
    instruments = [
        _instrument(raw, f"request.eligible_instruments[{i}]")
        for i, raw in enumerate(
            require_list(data["eligible_instruments"], "request.eligible_instruments")
        )
    ]
    instruments = [row for row in instruments if row["eligible"]]
    assignments: list[dict[str, Any]] = []
    uncovered: list[str] = []
    for index, raw in enumerate(require_list(data["items"], "request.items")):
        path = f"request.items[{index}]"
        row = require_mapping(raw, path)
        required = {
            "strategy_item_ref",
            "subquestion_ref",
            "construct_refs",
            "capability",
            "modalities",
            "sequence",
            "parallel_group",
            "call_limit",
            "cost_reserve",
            "success_oracle",
            "switch_condition",
        }
        require_exact_keys(row, required, path)
        capability = require_string(row["capability"], f"{path}.capability")
        modalities = _strings(row["modalities"], f"{path}.modalities")
        item_ref = require_string(row["strategy_item_ref"], f"{path}.strategy_item_ref")
        base = {
            "strategy_item_ref": item_ref,
            "subquestion_ref": require_string(
                row["subquestion_ref"], f"{path}.subquestion_ref"
            ),
            "construct_refs": _strings(row["construct_refs"], f"{path}.construct_refs"),
            "capability": capability,
            "sequence": require_int(row["sequence"], f"{path}.sequence", minimum=1),
            "parallel_group": row["parallel_group"],
            "call_limit": require_int(
                row["call_limit"], f"{path}.call_limit", minimum=1
            ),
            "cost_reserve": require_int(row["cost_reserve"], f"{path}.cost_reserve"),
            "success_oracle": require_string(
                row["success_oracle"], f"{path}.success_oracle"
            ),
            "switch_condition": require_string(
                row["switch_condition"], f"{path}.switch_condition"
            ),
        }
        if base["parallel_group"] is not None:
            base["parallel_group"] = require_string(
                base["parallel_group"], f"{path}.parallel_group"
            )
        for modality in modalities:
            candidates = sorted(
                (
                    candidate
                    for candidate in instruments
                    if candidate["capability"] == capability
                    and modality in candidate["modalities"]
                ),
                key=lambda candidate: (
                    candidate["cost_upper_bound"],
                    candidate["instrument_ref"],
                ),
            )
            if not candidates:
                uncovered.append(f"{item_ref}:{modality}")
                continue
            selected = candidates[0]
            assignments.append(
                {
                    **base,
                    "modality": modality,
                    "instrument_ref": selected["instrument_ref"],
                    "required_query_fields": selected["required_query_fields"],
                    "optional_query_fields": selected["optional_query_fields"],
                    "expected_output_schema": selected["output_schema_ref"],
                }
            )
    body = {
        "strategy_id": strategy_id,
        "revision": 1,
        "portfolio_ref": portfolio_ref,
        "portfolio_revision": portfolio_revision,
        "portfolio_hash": portfolio_hash,
        "profile_ref": profile_ref,
        "profile_version": profile_version,
        "profile_hash": profile_hash,
        "assignments": assignments,
        "uncovered_modalities": sorted(uncovered),
    }
    body["content_hash"] = sha256_json(body)
    payload = {
        "schema_version": 1,
        "contract": "InstrumentStrategyReceipt",
        "status": "strategy_ready" if not uncovered else "blocked",
        "strategy": body,
        "external_calls_performed": 0,
        "persistence_applied": False,
        "issues": [f"modality_uncovered:{value}" for value in sorted(uncovered)],
    }
    return with_receipt_hash(payload)


def build_tool_query(request: object) -> dict[str, Any]:
    data = _schema(request, set(TOOL_QUERY_BUILD_SCHEMA["required"]))
    item = require_mapping(data["strategy_item"], "request.strategy_item")
    require_exact_keys(
        item,
        set(TOOL_QUERY_BUILD_SCHEMA["properties"]["strategy_item"]["required"]),
        "request.strategy_item",
    )
    required_fields = _strings(
        item["required_query_fields"], "request.strategy_item.required_query_fields"
    )
    optional_fields = _strings(
        item["optional_query_fields"], "request.strategy_item.optional_query_fields"
    )
    fields: dict[str, str] = {}
    for index, raw in enumerate(
        require_list(data["query_fields"], "request.query_fields")
    ):
        path = f"request.query_fields[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"name", "value_json"}, path)
        name = require_string(row["name"], f"{path}.name")
        if name in fields:
            fail("duplicate_query_field", f"{path}.name", "Повтор поля.")
        fields[name] = require_string(row["value_json"], f"{path}.value_json")
    issues = [
        f"query_field_missing:{name}"
        for name in sorted(set(required_fields) - set(fields))
    ]
    issues.extend(
        f"query_field_unknown:{name}"
        for name in sorted(set(fields) - set(required_fields) - set(optional_fields))
    )
    raw_copied = require_bool(
        data["raw_question_copied"], "request.raw_question_copied"
    )
    if raw_copied:
        issues.append("raw_question_not_structured")
    parallel_group = item["parallel_group"]
    if parallel_group is not None:
        parallel_group = require_string(
            parallel_group, "request.strategy_item.parallel_group"
        )
    envelope = {
        "strategy_ref": require_string(data["strategy_ref"], "request.strategy_ref"),
        "strategy_revision": require_int(
            data["strategy_revision"], "request.strategy_revision", minimum=1
        ),
        "strategy_hash": require_string(data["strategy_hash"], "request.strategy_hash"),
        "strategy_item_ref": require_string(
            item["strategy_item_ref"], "request.strategy_item.strategy_item_ref"
        ),
        "profile_ref": require_string(data["profile_ref"], "request.profile_ref"),
        "profile_version": require_int(
            data["profile_version"], "request.profile_version", minimum=1
        ),
        "profile_hash": require_string(data["profile_hash"], "request.profile_hash"),
        "capability": require_string(
            item["capability"], "request.strategy_item.capability"
        ),
        "instrument_ref": require_string(
            item["instrument_ref"], "request.strategy_item.instrument_ref"
        ),
        "subquestion_ref": require_string(
            item["subquestion_ref"], "request.strategy_item.subquestion_ref"
        ),
        "construct_refs": _strings(
            item["construct_refs"], "request.strategy_item.construct_refs"
        ),
        "modality": require_string(item["modality"], "request.strategy_item.modality"),
        "query_fields": [
            {"name": name, "value_json": fields[name]} for name in sorted(fields)
        ],
        "expected_output_schema": require_string(
            item["expected_output_schema"],
            "request.strategy_item.expected_output_schema",
        ),
        "success_oracle": require_string(
            item["success_oracle"], "request.strategy_item.success_oracle"
        ),
        "sequence": require_int(
            item["sequence"], "request.strategy_item.sequence", minimum=1
        ),
        "parallel_group": parallel_group,
        "limits": {
            "call_limit": require_int(
                item["call_limit"], "request.strategy_item.call_limit", minimum=1
            ),
            "cost_reserve": require_int(
                item["cost_reserve"], "request.strategy_item.cost_reserve"
            ),
        },
        "fallback_condition": require_string(
            item["switch_condition"], "request.strategy_item.switch_condition"
        ),
    }
    payload = {
        "schema_version": 1,
        "contract": "ToolQueryEnvelopeReceipt",
        "status": "query_ready" if not issues else "blocked",
        "tool_query_envelope": envelope if not issues else None,
        "raw_question_copied": raw_copied,
        "external_call_performed": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def propose_instrument_strategy_revision(request: object) -> dict[str, Any]:
    data = _schema(request, set(INSTRUMENT_STRATEGY_REVISE_SCHEMA["required"]))
    strategy_ref = require_string(data["strategy_ref"], "request.strategy_ref")
    current = require_int(
        data["current_revision"], "request.current_revision", minimum=1
    )
    expected = require_int(
        data["expected_revision"], "request.expected_revision", minimum=1
    )
    if current != expected:
        fail(
            "stale_revision",
            "request.expected_revision",
            "Редакция стратегии устарела.",
        )
    current_hash = require_string(data["current_hash"], "request.current_hash")
    prior_refs = _strings(data["prior_receipt_refs"], "request.prior_receipt_refs")
    observations = []
    for index, raw in enumerate(
        require_list(data["yield_observations"], "request.yield_observations")
    ):
        path = f"request.yield_observations[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"instrument_ref", "calls", "useful_results", "errors"}, path
        )
        calls = require_int(row["calls"], f"{path}.calls", minimum=1)
        useful = require_int(row["useful_results"], f"{path}.useful_results")
        errors = require_int(row["errors"], f"{path}.errors")
        observations.append(
            {
                "instrument_ref": require_string(
                    row["instrument_ref"], f"{path}.instrument_ref"
                ),
                "calls": calls,
                "useful_results": useful,
                "errors": errors,
                "yield_fraction": useful / calls,
            }
        )
    reason = require_string(data["change_reason"], "request.change_reason")
    assignments = _strings(
        data["proposed_assignment_refs"], "request.proposed_assignment_refs"
    )
    proposal = {
        "strategy_ref": strategy_ref,
        "revision": current + 1,
        "prior_hash": current_hash,
        "assignment_refs": assignments,
        "change_reason": reason,
        "yield_observations": observations,
    }
    proposal["content_hash"] = sha256_json(proposal)
    payload = {
        "schema_version": 1,
        "contract": "InstrumentStrategyRevisionReceipt",
        "status": "revision_proposed",
        "strategy_revision": proposal,
        "prior_receipt_refs": prior_refs,
        "prior_receipts_mutated": False,
        "external_calls_performed": 0,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)
