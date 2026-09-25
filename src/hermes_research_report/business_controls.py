"""Decision-bound business research controls with no implicit external action."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, cast

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
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_TYPES = {
    "method_plan",
    "survey",
    "causal",
    "commercial",
    "question_design",
    "primary_action",
    "dataset",
    "observation",
    "assignment",
    "projection",
    "recommendation",
    "stop",
}

BUSINESS_CONTROL_ASSESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "control_type", "payload"],
    "properties": {
        "schema_version": {"const": 1},
        "control_type": {"enum": sorted(_CONTROL_TYPES)},
        "payload": {"type": "object"},
    },
}


_NEW_CONTROL_PAYLOAD_SCHEMAS = {
    "method_plan": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "question_kind",
            "alternatives",
            "method",
            "discriminator",
            "limitation",
            "design_basis_refs",
        ],
        "properties": {
            "question_kind": {
                "enum": [
                    "description",
                    "behavior",
                    "meaning",
                    "prevalence",
                    "causal_effect",
                ]
            },
            "alternatives": {
                "type": "array",
                "maxItems": 1000,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "method": {
                "enum": [
                    "desk",
                    "internal_data",
                    "observation",
                    "interview",
                    "survey",
                    "experiment",
                ]
            },
            "discriminator": {"type": "string", "minLength": 1},
            "limitation": {"type": "string", "minLength": 1},
            "design_basis_refs": {
                "type": "array",
                "maxItems": 1000,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
    "survey": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "sampling_method",
            "frame",
            "target_population",
            "requested_scope",
            "respondents",
            "successes",
            "invited",
            "nonresponse_limitation",
            "sampling_basis_ref",
        ],
        "properties": {
            "sampling_method": {"enum": ["probability", "voluntary"]},
            "frame": {"type": "string", "minLength": 1},
            "target_population": {"type": "string", "minLength": 1},
            "requested_scope": {"type": "string", "minLength": 1},
            "respondents": {"type": "integer", "minimum": 1},
            "successes": {"type": "integer", "minimum": 0},
            "invited": {"type": "integer", "minimum": 1},
            "nonresponse_limitation": {"type": "string", "minLength": 1},
            "sampling_basis_ref": {"type": ["string", "null"]},
        },
    },
    "causal": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "design",
            "requested_wording",
            "association_support_refs",
            "assumptions",
            "diagnostics",
        ],
        "properties": {
            "design": {"type": "string", "minLength": 1},
            "requested_wording": {"enum": ["causal", "association"]},
            "association_support_refs": {
                "type": "array",
                "maxItems": 1000,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "assumptions": {
                "type": "array",
                "maxItems": 1000,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "diagnostics": {
                "type": "array",
                "maxItems": 10000,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "assumption",
                        "test_ref",
                        "statistic",
                        "minimum",
                        "maximum",
                    ],
                    "properties": {
                        "assumption": {"type": "string", "minLength": 1},
                        "test_ref": {"type": "string", "minLength": 1},
                        "statistic": {"type": "number"},
                        "minimum": {"type": "number"},
                        "maximum": {"type": "number"},
                    },
                },
            },
        },
    },
    "commercial": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "statement",
            "supplier_ref",
            "source_ref",
            "as_of",
            "conditions",
            "source_kind",
            "requested_kind",
            "measurement",
        ],
        "properties": {
            "statement": {"type": "string", "minLength": 1},
            "supplier_ref": {"type": "string", "minLength": 1},
            "source_ref": {"type": "string", "minLength": 1},
            "as_of": {"type": "string", "minLength": 1},
            "conditions": {
                "type": "array",
                "maxItems": 1000,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "source_kind": {"enum": ["advertised", "self_report", "measured"]},
            "requested_kind": {"enum": ["advertised", "self_report", "measured"]},
            "measurement": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "tester_ref",
                            "test_ref",
                            "observed_value",
                            "conditions",
                        ],
                        "properties": {
                            "tester_ref": {"type": "string", "minLength": 1},
                            "test_ref": {"type": "string", "minLength": 1},
                            "observed_value": {"type": "string", "minLength": 1},
                            "conditions": {
                                "type": "array",
                                "maxItems": 1000,
                                "uniqueItems": True,
                                "items": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                ]
            },
        },
    },
}
BUSINESS_CONTROL_ASSESS_SCHEMA["allOf"] = [
    {
        "if": {"properties": {"control_type": {"const": name}}},
        "then": {"properties": {"payload": definition}},
    }
    for name, definition in _NEW_CONTROL_PAYLOAD_SCHEMAS.items()
]


def _nullable(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


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


def _time(value: object, path: str) -> str:
    text = require_string(value, path)
    try:
        datetime.fromisoformat(text)
    except ValueError:
        fail("invalid_time", path, "Ожидалось время ISO-8601.")
    return text


def _question_design(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(payload, {"questions"}, "request.payload")
    packets = []
    issues = []
    for index, raw in enumerate(
        require_list(payload["questions"], "request.payload.questions")
    ):
        path = f"request.payload.questions[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"question_id", "purpose", "decision_link", "decision_rule"}, path
        )
        question_id = require_string(row["question_id"], f"{path}.question_id")
        purpose = require_string(row["purpose"], f"{path}.purpose")
        decision_link = _nullable(row["decision_link"], f"{path}.decision_link")
        decision_rule = _nullable(row["decision_rule"], f"{path}.decision_rule")
        ready = purpose == "information" or (
            purpose == "decision"
            and decision_link is not None
            and decision_rule is not None
        )
        if purpose not in {"decision", "information"}:
            fail(
                "invalid_purpose", f"{path}.purpose", "Неизвестное назначение вопроса."
            )
        if not ready:
            issues.append(f"missing_decision_link:{question_id}")
        packets.append(
            {
                "question_id": question_id,
                "purpose": purpose,
                "decision_link": decision_link,
                "decision_rule": decision_rule,
                "status": "ready" if ready else "blocked",
            }
        )
    return {"packets": packets, "issues": issues, "external_action_count": 0}


def _primary_action(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "protocol_hash",
        "protocol_revision",
        "approval_ref",
        "approval_protocol_hash",
        "approval_revision",
        "observed_external_call_count",
    }
    require_exact_keys(payload, keys, "request.payload")
    protocol_hash = _hash(payload["protocol_hash"], "request.payload.protocol_hash")
    approval_hash = _hash(
        payload["approval_protocol_hash"], "request.payload.approval_protocol_hash"
    )
    protocol_revision = require_int(
        payload["protocol_revision"], "request.payload.protocol_revision", minimum=1
    )
    approval_revision = require_int(
        payload["approval_revision"], "request.payload.approval_revision", minimum=1
    )
    approval_ref = require_string(
        payload["approval_ref"], "request.payload.approval_ref"
    )
    calls = require_int(
        payload["observed_external_call_count"],
        "request.payload.observed_external_call_count",
    )
    matched = protocol_hash == approval_hash and protocol_revision == approval_revision
    issues = []
    if not matched:
        issues.append("approval_scope_mismatch")
        if calls:
            issues.append("unauthorized_external_call")
    elif calls != 1:
        issues.append("external_call_count_mismatch")
    return {
        "approval_ref": approval_ref,
        "protocol_hash": protocol_hash,
        "execution_status": "ready" if matched and calls == 1 else "waiting_approval",
        "observed_external_call_count": calls,
        "issues": issues,
    }


def _dataset(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "snapshot_ref",
        "snapshot_hash",
        "measurement_contract_ref",
        "measurement_contract_hash",
        "expected_grain",
        "observed_grain",
        "business_key",
        "period",
        "timezone",
        "denominator",
        "quality_checks",
    }
    require_exact_keys(payload, keys, "request.payload")
    expected = require_string(
        payload["expected_grain"], "request.payload.expected_grain"
    )
    observed = require_string(
        payload["observed_grain"], "request.payload.observed_grain"
    )
    checks = []
    for index, raw in enumerate(
        require_list(payload["quality_checks"], "request.payload.quality_checks")
    ):
        path = f"request.payload.quality_checks[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"check", "status"}, path)
        check = require_string(row["check"], f"{path}.check")
        status = require_string(row["status"], f"{path}.status")
        if status not in {"pass", "fail"}:
            fail("invalid_check_status", f"{path}.status", "Неизвестный статус.")
        checks.append({"check": check, "status": status})
    issues = []
    if expected != observed:
        issues.append("measurement_contract_mismatch")
    if any(row["status"] != "pass" for row in checks):
        issues.append("dataset_quality_check_failed")
    return {
        "snapshot_ref": require_string(
            payload["snapshot_ref"], "request.payload.snapshot_ref"
        ),
        "snapshot_hash": _hash(
            payload["snapshot_hash"], "request.payload.snapshot_hash"
        ),
        "measurement_contract_ref": require_string(
            payload["measurement_contract_ref"],
            "request.payload.measurement_contract_ref",
        ),
        "measurement_contract_hash": _hash(
            payload["measurement_contract_hash"],
            "request.payload.measurement_contract_hash",
        ),
        "business_key": require_string(
            payload["business_key"], "request.payload.business_key"
        ),
        "period": require_string(payload["period"], "request.payload.period"),
        "timezone": require_string(payload["timezone"], "request.payload.timezone"),
        "denominator": require_string(
            payload["denominator"], "request.payload.denominator"
        ),
        "quality_checks": checks,
        "calculation_allowed": not issues,
        "numeric_result_published": False,
        "issues": issues,
    }


def _observation(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload, {"event", "motive_claim", "motive_in_event"}, "request.payload"
    )
    event = require_mapping(payload["event"], "request.payload.event")
    require_exact_keys(
        event,
        {"occurred_at", "window", "locator", "observed_event"},
        "request.payload.event",
    )
    motive = require_mapping(payload["motive_claim"], "request.payload.motive_claim")
    require_exact_keys(motive, {"text", "claim_status"}, "request.payload.motive_claim")
    motive_in_event = require_bool(
        payload["motive_in_event"], "request.payload.motive_in_event"
    )
    issues = ["observation_type_mismatch"] if motive_in_event else []
    return {
        "event": {
            "occurred_at": _time(
                event["occurred_at"], "request.payload.event.occurred_at"
            ),
            "window": require_string(event["window"], "request.payload.event.window"),
            "locator": require_string(
                event["locator"], "request.payload.event.locator"
            ),
            "observed_event": require_string(
                event["observed_event"], "request.payload.event.observed_event"
            ),
        },
        "motive_claim": {
            "text": require_string(motive["text"], "request.payload.motive_claim.text"),
            "claim_status": require_string(
                motive["claim_status"], "request.payload.motive_claim.claim_status"
            ),
        },
        "issues": issues,
    }


def _assignment(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "protocol_ref",
        "protocol_hash",
        "protocol_fields",
        "frozen_at",
        "assigned_at",
        "observed_assignment_count",
    }
    require_exact_keys(payload, keys, "request.payload")
    required = {
        "treatment",
        "control",
        "randomization_unit",
        "primary_outcome",
        "sample_rule",
        "guardrails",
        "stop_rule",
        "analysis_plan",
    }
    fields = set(
        _strings(payload["protocol_fields"], "request.payload.protocol_fields")
    )
    missing = sorted(required - fields)
    frozen = _time(payload["frozen_at"], "request.payload.frozen_at")
    assigned = _time(payload["assigned_at"], "request.payload.assigned_at")
    count = require_int(
        payload["observed_assignment_count"],
        "request.payload.observed_assignment_count",
    )
    issues = [f"missing_preregistered_{field}" for field in missing]
    if frozen >= assigned:
        issues.append("protocol_not_frozen_before_assignment")
    if issues and count:
        issues.append("assignment_without_complete_protocol")
    return {
        "protocol_ref": require_string(
            payload["protocol_ref"], "request.payload.protocol_ref"
        ),
        "protocol_hash": _hash(
            payload["protocol_hash"], "request.payload.protocol_hash"
        ),
        "frozen_at": frozen,
        "assigned_at": assigned,
        "execution_status": "ready"
        if not issues and count == 1
        else "waiting_dependency",
        "assignment_created": not issues and count == 1,
        "observed_assignment_count": count,
        "issues": issues,
    }


def _projection(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(payload, {"cards"}, "request.payload")
    cards = []
    issues = []
    for index, raw in enumerate(
        require_list(payload["cards"], "request.payload.cards")
    ):
        path = f"request.payload.cards[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "card_ref",
                "kind",
                "horizon",
                "cutoff",
                "validation_window",
                "comparator",
                "uncertainty",
            },
            path,
        )
        card_ref = require_string(row["card_ref"], f"{path}.card_ref")
        kind = require_string(row["kind"], f"{path}.kind")
        if kind not in {"scenario", "forecast"}:
            fail("invalid_projection_kind", f"{path}.kind", "Неизвестный тип.")
        fields = {
            key: _nullable(row[key], f"{path}.{key}")
            for key in (
                "horizon",
                "cutoff",
                "validation_window",
                "comparator",
                "uncertainty",
            )
        }
        if kind == "forecast" and any(value is None for value in fields.values()):
            issues.append(f"forecast_validation_missing:{card_ref}")
        cards.append({"card_ref": card_ref, "kind": kind, **fields})
    return {"cards": cards, "issues": issues}


def _recommendation(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "owner",
        "alternative_no_change",
        "basis",
        "tradeoffs",
        "applicability",
        "reopen_trigger",
        "execute_requested",
        "authorized_decision_ref",
        "observed_action_call_count",
    }
    require_exact_keys(payload, keys, "request.payload")
    execute = require_bool(
        payload["execute_requested"], "request.payload.execute_requested"
    )
    authority = _nullable(
        payload["authorized_decision_ref"], "request.payload.authorized_decision_ref"
    )
    calls = require_int(
        payload["observed_action_call_count"],
        "request.payload.observed_action_call_count",
    )
    issues = []
    if execute and authority is None:
        issues.append("recommendation_is_not_authority")
    if authority is None and calls:
        issues.append("unauthorized_action_call")
    return {
        "choice_object": {
            key: require_string(payload[key], f"request.payload.{key}")
            for key in (
                "owner",
                "alternative_no_change",
                "basis",
                "tradeoffs",
                "applicability",
                "reopen_trigger",
            )
        },
        "release_decision": "approved" if authority and execute else "not_requested",
        "observed_action_call_count": calls,
        "issues": issues,
    }


def _stop(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "desk_pass_discriminator_refs",
        "proposed_identical_pass",
        "interview_authorized",
        "observed_interview_count",
        "unresolved_question",
        "collection_proposal",
    }
    require_exact_keys(payload, keys, "request.payload")
    passes = require_list(
        payload["desk_pass_discriminator_refs"],
        "request.payload.desk_pass_discriminator_refs",
    )
    normalized_passes = [
        _strings(value, f"request.payload.desk_pass_discriminator_refs[{index}]")
        for index, value in enumerate(passes)
    ]
    no_new = len(normalized_passes) >= 2 and not any(normalized_passes[-2:])
    proposed_same = require_bool(
        payload["proposed_identical_pass"], "request.payload.proposed_identical_pass"
    )
    interview_authorized = require_bool(
        payload["interview_authorized"], "request.payload.interview_authorized"
    )
    interview_count = require_int(
        payload["observed_interview_count"], "request.payload.observed_interview_count"
    )
    issues = []
    if no_new and proposed_same:
        issues.append("no_new_discriminator")
    if not interview_authorized and interview_count:
        issues.append("unauthorized_interview")
    return {
        "result_status": "partial" if no_new else "continue",
        "unresolved_question": require_string(
            payload["unresolved_question"], "request.payload.unresolved_question"
        ),
        "collection_proposal": require_string(
            payload["collection_proposal"], "request.payload.collection_proposal"
        ),
        "new_desk_pass_created": not no_new and proposed_same,
        "observed_interview_count": interview_count,
        "issues": issues,
    }


def _method_plan(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {
            "question_kind",
            "alternatives",
            "method",
            "discriminator",
            "limitation",
            "design_basis_refs",
        },
        "request.payload",
    )
    kinds = {
        "description": {"desk", "internal_data", "observation"},
        "behavior": {"internal_data", "observation"},
        "meaning": {"interview"},
        "prevalence": {"survey"},
        "causal_effect": {"experiment"},
    }
    kind = require_string(payload["question_kind"], "request.payload.question_kind")
    method = require_string(payload["method"], "request.payload.method")
    alternatives = _strings(payload["alternatives"], "request.payload.alternatives")
    discriminator = require_string(
        payload["discriminator"], "request.payload.discriminator"
    )
    limitation = require_string(payload["limitation"], "request.payload.limitation")
    basis = _strings(payload["design_basis_refs"], "request.payload.design_basis_refs")
    issues = []
    if kind not in kinds or method not in kinds[kind]:
        issues.append("method_not_identifying")
    if len(alternatives) < 2 or not basis:
        issues.append("identification_basis_incomplete")
    return {
        "method_plan": {
            "question_kind": kind,
            "alternatives": alternatives,
            "method": method,
            "discriminator": discriminator,
            "limitation": limitation,
            "design_basis_refs": basis,
        },
        "causal_question_open": kind == "causal_effect",
        "collection_performed": False,
        "issues": issues,
    }


def _survey(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {
            "sampling_method",
            "frame",
            "target_population",
            "requested_scope",
            "respondents",
            "successes",
            "invited",
            "nonresponse_limitation",
            "sampling_basis_ref",
        },
        "request.payload",
    )
    method = require_string(
        payload["sampling_method"], "request.payload.sampling_method"
    )
    if method not in {"probability", "voluntary"}:
        fail(
            "invalid_sampling_method",
            "request.payload.sampling_method",
            "Неизвестный способ выборки.",
        )
    n = require_int(payload["respondents"], "request.payload.respondents", minimum=1)
    successes = require_int(payload["successes"], "request.payload.successes")
    invited = require_int(payload["invited"], "request.payload.invited", minimum=1)
    if successes > n or n > invited:
        fail(
            "invalid_sample_counts",
            "request.payload",
            "Нарушены границы численности выборки.",
        )
    frame = require_string(payload["frame"], "request.payload.frame")
    target = require_string(
        payload["target_population"], "request.payload.target_population"
    )
    scope = require_string(
        payload["requested_scope"], "request.payload.requested_scope"
    )
    limitation = require_string(
        payload["nonresponse_limitation"], "request.payload.nonresponse_limitation"
    )
    basis = _nullable(
        payload["sampling_basis_ref"], "request.payload.sampling_basis_ref"
    )
    issues = []
    allowed_scope = frame if method == "probability" and basis else "respondents_only"
    if scope != allowed_scope:
        issues.append("population_generalization_unsupported")
    if method == "probability" and not basis:
        issues.append("probability_sampling_basis_missing")
    proportion = successes / n
    # Wilson interval describes binomial sampling variability only, never selection bias.
    z = 1.959963984540054
    denominator = 1 + z * z / n
    center = (proportion + z * z / (2 * n)) / denominator
    radius = (
        z
        * ((proportion * (1 - proportion) / n + z * z / (4 * n * n)) ** 0.5)
        / denominator
    )
    return {
        "result_status": "accepted_for_scope" if not issues else "qualified",
        "proportion": proportion,
        "population_scope": allowed_scope,
        "target_population": target,
        "frame": frame,
        "response_rate": n / invited,
        "sampling_interval_95": [max(0, center - radius), min(1, center + radius)]
        if method == "probability" and basis
        else None,
        "nonresponse_limitation": limitation,
        "selection_bias_excluded_from_interval": True,
        "market_representative": False,
        "issues": issues,
    }


def _causal(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {
            "design",
            "requested_wording",
            "association_support_refs",
            "assumptions",
            "diagnostics",
        },
        "request.payload",
    )
    design = require_string(payload["design"], "request.payload.design")
    wording = require_string(
        payload["requested_wording"], "request.payload.requested_wording"
    )
    if wording not in {"causal", "association"}:
        fail(
            "invalid_wording",
            "request.payload.requested_wording",
            "Неизвестная сила вывода.",
        )
    assumptions = _strings(payload["assumptions"], "request.payload.assumptions")
    support = _strings(
        payload["association_support_refs"], "request.payload.association_support_refs"
    )
    rows = require_list(payload["diagnostics"], "request.payload.diagnostics")
    results = {}
    issues = []
    for index, raw in enumerate(rows):
        path = f"request.payload.diagnostics[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"assumption", "test_ref", "statistic", "minimum", "maximum"}, path
        )
        name = require_string(row["assumption"], path + ".assumption")
        if name in results or name not in assumptions:
            fail(
                "invalid_diagnostic_assumption",
                path + ".assumption",
                "Повтор или неизвестное предположение.",
            )
        values = [row[key] for key in ("statistic", "minimum", "maximum")]
        import math

        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            for v in values
        ) or cast(int | float, values[1]) > cast(int | float, values[2]):
            fail("invalid_diagnostic_range", path, "Неверная численная диагностика.")
        results[name] = {
            "test_ref": require_string(row["test_ref"], path + ".test_ref"),
            "statistic": values[0],
            "bounds": values[1:],
            "passed": cast(int | float, values[1])
            <= cast(int | float, values[0])
            <= cast(int | float, values[2]),
        }
    required_assumptions = {
        "randomized": {"random_assignment", "attrition"},
        "difference_in_differences": {"parallel_trend", "no_anticipation"},
        "regression_discontinuity": {"continuity", "no_manipulation"},
        "instrumental_variable": {"relevance", "exclusion", "independence"},
    }
    identifying_design = design in required_assumptions and required_assumptions[
        design
    ].issubset(assumptions)
    if wording == "causal" and not identifying_design:
        issues.append("method_not_identifying")
    identified = (
        identifying_design
        and bool(assumptions)
        and set(results) == set(assumptions)
        and all(r["passed"] for r in results.values())
        and bool(support)
    )
    if wording == "causal" and not identified:
        issues.append("causal_identification_failed")
    return {
        "design": design,
        "claim_status": "qualified" if support else "unresolved",
        "allowed_wording": "conditional_causal"
        if identified and wording == "causal"
        else "association"
        if support
        else "insufficient_evidence",
        "assumptions": assumptions,
        "diagnostics": results,
        "support_refs": support,
        "unconditional_causal_claim_allowed": False,
        "issues": issues,
    }


def _commercial(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {
            "statement",
            "supplier_ref",
            "source_ref",
            "as_of",
            "conditions",
            "source_kind",
            "requested_kind",
            "measurement",
        },
        "request.payload",
    )
    statement = require_string(payload["statement"], "request.payload.statement")
    supplier = require_string(payload["supplier_ref"], "request.payload.supplier_ref")
    source = require_string(payload["source_ref"], "request.payload.source_ref")
    date = _time(payload["as_of"], "request.payload.as_of")
    conditions = _strings(payload["conditions"], "request.payload.conditions")
    kind = require_string(payload["source_kind"], "request.payload.source_kind")
    requested = require_string(
        payload["requested_kind"], "request.payload.requested_kind"
    )
    if kind not in {"advertised", "self_report", "measured"} or requested not in {
        "advertised",
        "self_report",
        "measured",
    }:
        fail("invalid_commercial_kind", "request.payload", "Неизвестный вид заявления.")
    measurement = payload["measurement"]
    verified = False
    measured = None
    if measurement is not None:
        measurement = require_mapping(measurement, "request.payload.measurement")
        require_exact_keys(
            measurement,
            {"tester_ref", "test_ref", "observed_value", "conditions"},
            "request.payload.measurement",
        )
        tester = require_string(
            measurement["tester_ref"], "request.payload.measurement.tester_ref"
        )
        measured = {
            "tester_ref": tester,
            "test_ref": require_string(
                measurement["test_ref"], "request.payload.measurement.test_ref"
            ),
            "observed_value": require_string(
                measurement["observed_value"],
                "request.payload.measurement.observed_value",
            ),
            "conditions": _strings(
                measurement["conditions"], "request.payload.measurement.conditions"
            ),
        }
        verified = (
            tester != supplier
            and bool(measured["conditions"])
            and set(measured["conditions"]) == set(conditions)
        )
    issues = []
    if requested == "measured" and not verified:
        issues.append("unsupported_upgrade")
    if not conditions:
        issues.append("commercial_conditions_missing")
    result_kind = (
        "measured"
        if requested == "measured" and verified
        else kind
        if kind != "measured"
        else "self_report"
    )
    return {
        "statement": cast(dict[str, Any], measured)["observed_value"]
        if result_kind == "measured"
        else statement,
        "supplier_statement": statement,
        "statement_kind": result_kind,
        "source_ref": source,
        "as_of": date,
        "conditions": conditions,
        "measurement": measured if verified else None,
        "independent_measurement_bound": verified,
        "issues": issues,
    }


_ASSESSORS = {
    "method_plan": _method_plan,
    "survey": _survey,
    "causal": _causal,
    "commercial": _commercial,
    "question_design": _question_design,
    "primary_action": _primary_action,
    "dataset": _dataset,
    "observation": _observation,
    "assignment": _assignment,
    "projection": _projection,
    "recommendation": _recommendation,
    "stop": _stop,
}


def assess_business_control(request: object) -> dict[str, Any]:
    """Assess one explicit business control without performing external action."""

    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "control_type", "payload"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    control_type = require_string(data["control_type"], "request.control_type")
    if control_type not in _ASSESSORS:
        fail("invalid_control_type", "request.control_type", "Неизвестный контроль.")
    payload = require_mapping(data["payload"], "request.payload")
    result = _ASSESSORS[control_type](payload)
    issues = _strings(result.get("issues", []), "result.issues")
    return with_receipt_hash(
        {
            "contract": "BusinessControlReceipt",
            "control_type": control_type,
            "status": "accepted" if not issues else "blocked",
            **result,
        }
    )
