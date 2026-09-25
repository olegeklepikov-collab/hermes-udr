"""Immutable RunContract creation and revision proposals for FR-001--007."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .canonical import sha256_json, with_receipt_hash
from .errors import (
    ContractError,
    fail,
    require_bool,
    require_exact_keys,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

DOMAINS = ("general", "business", "academic")
ENGAGEMENT_LEVELS = (
    "parsing",
    "search",
    "research",
    "deep_research",
    "ultra_deep_research",
)
DEPTHS = ("search", "deep", "ultra")
RISKS = ("low", "medium", "high")
AUTONOMY_LEVELS = ("advisory", "approval_gated")
ASSURANCE_TIERS = ("mvp", "standard", "high_stakes")
EPISTEMIC_LEVELS = ("baseline", "strict", "forensic")
THINKING_LEVELS = ("bounded", "adversarial", "exhaustive")
OVERSIGHT_LEVELS = ("H0", "H1", "H2", "H3")
FRAME_FIELDS = ("question", "object", "period", "scope", "answer_adequacy")
BUDGET_FIELDS = (
    "wall_seconds",
    "external_cost_units",
    "attempts",
    "max_source_bytes",
)
DRAFT_FIELDS = (
    "topic",
    "intended_use",
    "domain",
    "engagement_level",
    "depth",
    "risk",
    "autonomy",
    "assurance_tier",
    "epistemic_strictness",
    "thinking_strictness",
    "human_oversight_level",
    "executor_topology",
    "model_topology",
    "modalities",
    "languages",
    "geographies",
    "time_window",
    "frame",
    "budget",
)
_CHANGE_FIELDS = {"frame", "domain", "engagement_level", "depth", "risk", "budget"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BAD_TEXT_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufeff\ud800-\udfff]")

_TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
_STRING_ARRAY = {
    "type": "array",
    "minItems": 1,
    "maxItems": 100,
    "uniqueItems": True,
    "items": _TEXT,
}
_OPTIONAL_STRING_ARRAY = {
    "type": "array",
    "maxItems": 100,
    "uniqueItems": True,
    "items": _TEXT,
}
_FRAME_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "question": _TEXT,
        "object": _TEXT,
        "period": _TEXT,
        "scope": _TEXT,
        "answer_adequacy": _STRING_ARRAY,
    },
}
_BUDGET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": list(BUDGET_FIELDS),
    "properties": {
        "wall_seconds": {"type": "integer", "minimum": 1},
        "external_cost_units": {"type": "integer", "minimum": 0},
        "attempts": {"type": "integer", "minimum": 1},
        "max_source_bytes": {"type": "integer", "minimum": 1},
    },
}
_DRAFT_PROPERTIES = {
    "topic": _TEXT,
    "intended_use": _TEXT,
    "domain": {"enum": list(DOMAINS)},
    "engagement_level": {"enum": list(ENGAGEMENT_LEVELS)},
    "depth": {"enum": list(DEPTHS)},
    "risk": {"enum": list(RISKS)},
    "autonomy": {"enum": list(AUTONOMY_LEVELS)},
    "assurance_tier": {"enum": list(ASSURANCE_TIERS)},
    "epistemic_strictness": {"enum": list(EPISTEMIC_LEVELS)},
    "thinking_strictness": {"enum": list(THINKING_LEVELS)},
    "human_oversight_level": {"enum": list(OVERSIGHT_LEVELS)},
    "executor_topology": _TEXT,
    "model_topology": _TEXT,
    "modalities": _STRING_ARRAY,
    "languages": _STRING_ARRAY,
    "geographies": _STRING_ARRAY,
    "time_window": _TEXT,
    "frame": _FRAME_SCHEMA,
    "budget": _BUDGET_SCHEMA,
}
_POLICY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "version",
        "meaning",
        "domain_obligations",
        "depth_obligations",
        "risk_obligations",
    ],
    "properties": {
        "version": _TEXT,
        "meaning": _TEXT,
        "domain_obligations": {
            "type": "object",
            "additionalProperties": False,
            "required": list(DOMAINS),
            "properties": {key: _OPTIONAL_STRING_ARRAY for key in DOMAINS},
        },
        "depth_obligations": {
            "type": "object",
            "additionalProperties": False,
            "required": list(DEPTHS),
            "properties": {key: _OPTIONAL_STRING_ARRAY for key in DEPTHS},
        },
        "risk_obligations": {
            "type": "object",
            "additionalProperties": False,
            "required": list(RISKS),
            "properties": {key: _OPTIONAL_STRING_ARRAY for key in RISKS},
        },
    },
}
_COMPLETE_FRAME_SCHEMA = {
    **_FRAME_SCHEMA,
    "required": list(FRAME_FIELDS),
}
_PAYLOAD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        *DRAFT_FIELDS,
        "policy_version",
        "obligations",
        "status",
    ],
    "properties": {
        **_DRAFT_PROPERTIES,
        "frame": _COMPLETE_FRAME_SCHEMA,
        "policy_version": _TEXT,
        "obligations": _STRING_ARRAY,
        "status": {
            "enum": [
                "proposed",
                "needs_clarification",
                "ready_for_host_decision",
                "accepted",
                "superseded",
            ]
        },
    },
}
_CONTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "project_id",
        "run_id",
        "id",
        "revision",
        "payload",
        "content_hash",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "project_id": _TEXT,
        "run_id": _TEXT,
        "id": _TEXT,
        "revision": {"type": "integer", "minimum": 1},
        "payload": _PAYLOAD_SCHEMA,
        "content_hash": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
    },
}
RUN_CONTRACT_CREATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "project_id", "draft", "policy"],
    "properties": {
        "schema_version": {"const": 1},
        "project_id": _TEXT,
        "draft": {
            "type": "object",
            "additionalProperties": False,
            "required": [field for field in DRAFT_FIELDS if field != "frame"],
            "properties": _DRAFT_PROPERTIES,
        },
        "policy": _POLICY_SCHEMA,
    },
}
RUN_CONTRACT_REVISE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "contract",
        "expected_revision",
        "changes",
        "dependencies",
        "user_consent",
        "policy",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "contract": _CONTRACT_SCHEMA,
        "expected_revision": {"type": "integer", "minimum": 1},
        "changes": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "frame": _FRAME_SCHEMA,
                "domain": {"enum": list(DOMAINS)},
                "engagement_level": {"enum": list(ENGAGEMENT_LEVELS)},
                "depth": {"enum": list(DEPTHS)},
                "risk": {"enum": list(RISKS)},
                "budget": _BUDGET_SCHEMA,
            },
        },
        "dependencies": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["output_id", "depends_on"],
                "properties": {
                    "output_id": _TEXT,
                    "depends_on": _STRING_ARRAY,
                },
            },
        },
        "user_consent": {"type": "boolean"},
        "policy": _POLICY_SCHEMA,
    },
}


def _enum(value: object, path: str, allowed: tuple[str, ...]) -> str:
    text = require_string(value, path)
    if text not in allowed:
        fail("invalid_value", path, "Значение не входит в допустимый набор.")
    return text


def _text(value: object, path: str, *, allow_blank: bool = False) -> str:
    text = require_string(value, path, nonempty=not allow_blank)
    if len(text) > 4096:
        fail("size_limit", path, "Строка длиннее 4096 символов.")
    if _BAD_TEXT_RE.search(text):
        fail("invalid_control", path, "Строка содержит запрещённый символ.")
    return text


def _identifier(value: object, path: str) -> str:
    text = _text(value, path)
    if not _ID_RE.fullmatch(text):
        fail("invalid_identifier", path, "Недопустимый идентификатор.")
    return text


def _strings(value: object, path: str, *, allow_empty: bool = False) -> list[str]:
    raw = require_list(value, path)
    if len(raw) > 100:
        fail("size_limit", path, "Массив длиннее 100 элементов.")
    if not allow_empty and not raw:
        fail("empty_array", path, "Пустой массив запрещён.")
    result = [_text(item, f"{path}[{index}]") for index, item in enumerate(raw)]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повторные элементы запрещены.")
    return result


def _policy_unchecked(value: object, path: str) -> dict[str, Any]:
    data = require_mapping(value, path)
    require_exact_keys(
        data,
        {
            "version",
            "meaning",
            "domain_obligations",
            "depth_obligations",
            "risk_obligations",
        },
        path,
    )
    try:
        version = _text(data["version"], f"{path}.version")
        meaning = _text(data["meaning"], f"{path}.meaning")
        groups: dict[str, dict[str, list[str]]] = {}
        for field, keys in (
            ("domain_obligations", DOMAINS),
            ("depth_obligations", DEPTHS),
            ("risk_obligations", RISKS),
        ):
            mapping = require_mapping(data[field], f"{path}.{field}")
            require_exact_keys(mapping, set(keys), f"{path}.{field}")
            groups[field] = {
                key: _strings(mapping[key], f"{path}.{field}.{key}", allow_empty=True)
                for key in keys
            }
        depth = groups["depth_obligations"]
        minimum = {
            "search": {"bounded_answer", "source_trace", "limitations"},
            "deep": {"cross_source_comparison", "contradiction_analysis"},
            "ultra": {
                "alternative_explanations",
                "coverage_gaps",
                "robustness_review",
            },
        }
        previous: set[str] = set()
        for level in DEPTHS:
            current = set(depth[level])
            if not (previous | minimum[level]).issubset(current):
                fail(
                    "invalid_policy",
                    path,
                    "Политика глубины не накапливает обязательства.",
                )
            previous = current
        risk = groups["risk_obligations"]
        if (
            risk["low"]
            or "risk_limitations" not in risk["medium"]
            or not set(risk["medium"]).issubset(risk["high"])
            or "independent_substantive_review" not in risk["high"]
        ):
            fail("invalid_policy", path, "Политика риска некорректна.")
    except KeyError:
        fail("invalid_policy", path, "Политика неполна.")
    return {
        "version": version,
        "meaning": meaning,
        **groups,
    }


def _policy(value: object, path: str = "request.policy") -> dict[str, Any]:
    try:
        return _policy_unchecked(value, path)
    except ContractError:
        fail("invalid_policy", path, "Версионная политика некорректна.")


def _budget(value: object, path: str) -> dict[str, int]:
    data = require_mapping(value, path)
    require_exact_keys(data, set(BUDGET_FIELDS), path)
    return {
        "wall_seconds": require_int(
            data["wall_seconds"], f"{path}.wall_seconds", minimum=1
        ),
        "external_cost_units": require_int(
            data["external_cost_units"], f"{path}.external_cost_units"
        ),
        "attempts": require_int(data["attempts"], f"{path}.attempts", minimum=1),
        "max_source_bytes": require_int(
            data["max_source_bytes"], f"{path}.max_source_bytes", minimum=1
        ),
    }


def _draft(value: object, path: str) -> tuple[dict[str, Any], list[str]]:
    data = require_mapping(value, path)
    required = set(DRAFT_FIELDS) - {"frame"}
    missing_top = sorted(required - set(data))
    unknown = sorted(set(data) - set(DRAFT_FIELDS))
    if missing_top:
        fail(
            "missing_field",
            f"{path}.{missing_top[0]}",
            "Отсутствует обязательное поле.",
        )
    if unknown:
        fail("unknown_field", f"{path}.{unknown[0]}", "Неизвестное поле запрещено.")
    normalized: dict[str, Any] = {
        "topic": _text(data["topic"], f"{path}.topic"),
        "intended_use": _text(data["intended_use"], f"{path}.intended_use"),
        "domain": _enum(data["domain"], f"{path}.domain", DOMAINS),
        "engagement_level": _enum(
            data["engagement_level"],
            f"{path}.engagement_level",
            ENGAGEMENT_LEVELS,
        ),
        "depth": _enum(data["depth"], f"{path}.depth", DEPTHS),
        "risk": _enum(data["risk"], f"{path}.risk", RISKS),
        "autonomy": _enum(data["autonomy"], f"{path}.autonomy", AUTONOMY_LEVELS),
        "assurance_tier": _enum(
            data["assurance_tier"], f"{path}.assurance_tier", ASSURANCE_TIERS
        ),
        "epistemic_strictness": _enum(
            data["epistemic_strictness"],
            f"{path}.epistemic_strictness",
            EPISTEMIC_LEVELS,
        ),
        "thinking_strictness": _enum(
            data["thinking_strictness"],
            f"{path}.thinking_strictness",
            THINKING_LEVELS,
        ),
        "human_oversight_level": _enum(
            data["human_oversight_level"],
            f"{path}.human_oversight_level",
            OVERSIGHT_LEVELS,
        ),
        "executor_topology": _text(
            data["executor_topology"], f"{path}.executor_topology"
        ),
        "model_topology": _text(data["model_topology"], f"{path}.model_topology"),
        "modalities": _strings(data["modalities"], f"{path}.modalities"),
        "languages": _strings(data["languages"], f"{path}.languages"),
        "geographies": _strings(data["geographies"], f"{path}.geographies"),
        "time_window": _text(data["time_window"], f"{path}.time_window"),
        "budget": _budget(data["budget"], f"{path}.budget"),
    }
    frame_raw = require_mapping(data.get("frame", {}), f"{path}.frame")
    unknown_frame = sorted(set(frame_raw) - set(FRAME_FIELDS))
    if unknown_frame:
        fail(
            "unknown_field",
            f"{path}.frame.{unknown_frame[0]}",
            "Неизвестное поле рамки запрещено.",
        )
    frame: dict[str, Any] = {}
    missing: list[str] = []
    for field in FRAME_FIELDS:
        if field not in frame_raw:
            missing.append(f"frame.{field}")
            continue
        if field == "answer_adequacy":
            frame[field] = _strings(
                frame_raw[field], f"{path}.frame.{field}", allow_empty=True
            )
            if not frame[field]:
                missing.append(f"frame.{field}")
        else:
            frame[field] = _text(
                frame_raw[field], f"{path}.frame.{field}", allow_blank=True
            )
            if not frame[field].strip():
                missing.append(f"frame.{field}")
    normalized["frame"] = frame
    return normalized, missing


def _obligations(draft: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    values = (
        policy["domain_obligations"][draft["domain"]]
        + policy["depth_obligations"][draft["depth"]]
        + policy["risk_obligations"][draft["risk"]]
    )
    return list(dict.fromkeys(values))


def _envelope(contract: dict[str, Any] | None, missing: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "RunContractDecisionReceipt",
        "status": "needs_clarification" if missing else "ready_for_host_decision",
        "structural_valid": not missing,
        "missing_details": missing,
        "review_required": bool(
            contract
            and (
                contract["payload"]["risk"] == "high"
                or contract["payload"]["depth"] != "search"
            )
        ),
        "semantic_certified": False,
        "host_decision_required": True,
        "persistence_applied": False,
        "run_contract": deepcopy(contract),
    }
    return with_receipt_hash(payload)


def create_run_contract(request: object) -> dict[str, Any]:
    """Create revision one or return exact missing frame paths."""
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "project_id", "draft", "policy"}, "request"
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    project_id = _identifier(data["project_id"], "request.project_id")
    policy = _policy(data["policy"])
    draft, missing = _draft(data["draft"], "request.draft")
    if missing:
        return _envelope(None, missing)
    draft["policy_version"] = policy["version"]
    draft["obligations"] = _obligations(draft, policy)
    draft["status"] = "ready_for_host_decision"
    identity_hash = sha256_json(
        {"schema_version": 1, "project_id": project_id, "payload": draft}
    )
    run_id = f"RUN-{identity_hash[:20]}"
    contract_body = {
        "schema_version": 1,
        "project_id": project_id,
        "run_id": run_id,
        "id": run_id,
        "revision": 1,
        "payload": draft,
    }
    contract = {**contract_body, "content_hash": sha256_json(contract_body)}
    return _envelope(contract, [])


def _validate_contract(
    value: object, policy: dict[str, Any], path: str
) -> dict[str, Any]:
    contract = require_mapping(value, path)
    require_exact_keys(
        contract,
        {
            "schema_version",
            "project_id",
            "run_id",
            "id",
            "revision",
            "payload",
            "content_hash",
        },
        path,
    )
    if contract["schema_version"] != 1:
        fail(
            "unsupported_schema", f"{path}.schema_version", "Неверная схема контракта."
        )
    project_id = _identifier(contract["project_id"], f"{path}.project_id")
    run_id = _identifier(contract["run_id"], f"{path}.run_id")
    if contract["id"] != run_id:
        fail("contract_identity_mismatch", f"{path}.id", "id и run_id не совпадают.")
    revision = require_int(contract["revision"], f"{path}.revision", minimum=1)
    body = {
        "schema_version": 1,
        "project_id": project_id,
        "run_id": run_id,
        "id": run_id,
        "revision": revision,
        "payload": contract["payload"],
    }
    if contract["content_hash"] != sha256_json(body):
        fail(
            "content_hash_mismatch",
            f"{path}.content_hash",
            "Хеш контракта не совпадает.",
        )
    payload = require_mapping(contract["payload"], f"{path}.payload")
    expected_keys = set(DRAFT_FIELDS) | {"policy_version", "obligations", "status"}
    require_exact_keys(payload, expected_keys, f"{path}.payload")
    normalized, missing = _draft(
        {key: payload[key] for key in DRAFT_FIELDS}, f"{path}.payload"
    )
    if missing:
        fail("incomplete_contract", f"{path}.payload.frame", "Рамка контракта неполна.")
    if payload["policy_version"] != policy["version"]:
        fail(
            "policy_version_mismatch",
            f"{path}.payload.policy_version",
            "Версия политики не совпадает.",
        )
    obligations = _strings(payload["obligations"], f"{path}.payload.obligations")
    if obligations != _obligations(normalized, policy):
        fail(
            "obligations_mismatch",
            f"{path}.payload.obligations",
            "Обязательства не совпадают с политикой.",
        )
    if payload["status"] not in {
        "proposed",
        "needs_clarification",
        "ready_for_host_decision",
        "accepted",
        "superseded",
    }:
        fail("invalid_status", f"{path}.payload.status", "Неверный статус контракта.")
    return deepcopy(contract)


def _dependencies(value: object, path: str) -> list[dict[str, Any]]:
    rows = require_list(value, path)
    if len(rows) > 1000:
        fail("size_limit", path, "Слишком много зависимостей.")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    allowed = {"frame." + field for field in FRAME_FIELDS} | (
        _CHANGE_FIELDS - {"frame"}
    )
    for index, raw in enumerate(rows):
        row_path = f"{path}[{index}]"
        row = require_mapping(raw, row_path)
        require_exact_keys(row, {"output_id", "depends_on"}, row_path)
        output_id = _identifier(row["output_id"], f"{row_path}.output_id")
        if output_id in seen:
            fail("duplicate_output_id", f"{row_path}.output_id", "Повторный output_id.")
        seen.add(output_id)
        depends_on = _strings(row["depends_on"], f"{row_path}.depends_on")
        unknown = sorted(set(depends_on) - allowed)
        if unknown:
            fail(
                "invalid_dependency",
                f"{row_path}.depends_on",
                "Неизвестное поле зависимости.",
            )
        result.append({"output_id": output_id, "depends_on": depends_on})
    return result


def propose_run_contract_revision(request: object) -> dict[str, Any]:
    """Create one detached next revision and an explicit invalidation set."""
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "contract",
            "expected_revision",
            "changes",
            "dependencies",
            "user_consent",
            "policy",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    policy = _policy(data["policy"])
    contract = _validate_contract(data["contract"], policy, "request.contract")
    expected_revision = require_int(
        data["expected_revision"], "request.expected_revision", minimum=1
    )
    if expected_revision != contract["revision"]:
        fail(
            "stale_revision",
            "request.expected_revision",
            "Ожидаемая редакция устарела.",
        )
    user_consent = require_bool(data["user_consent"], "request.user_consent")
    dependencies = _dependencies(data["dependencies"], "request.dependencies")
    changes = require_mapping(data["changes"], "request.changes")
    unknown_changes = sorted(set(changes) - _CHANGE_FIELDS)
    if unknown_changes:
        fail(
            "unknown_field",
            f"request.changes.{unknown_changes[0]}",
            "Неизвестное изменение.",
        )
    if not changes:
        fail("no_changes", "request.changes", "Пустое изменение запрещено.")

    prior_payload = contract["payload"]
    updated = {key: deepcopy(prior_payload[key]) for key in DRAFT_FIELDS}
    changed_fields: list[str] = []
    if "frame" in changes:
        frame_changes = require_mapping(changes["frame"], "request.changes.frame")
        unknown_frame = sorted(set(frame_changes) - set(FRAME_FIELDS))
        if unknown_frame:
            fail(
                "unknown_field",
                f"request.changes.frame.{unknown_frame[0]}",
                "Неизвестное поле рамки.",
            )
        for field, value in frame_changes.items():
            if value != updated["frame"][field]:
                updated["frame"][field] = deepcopy(value)
                changed_fields.append(f"frame.{field}")
    for field in ("domain", "engagement_level", "depth", "risk"):
        if field in changes and changes[field] != updated[field]:
            updated[field] = deepcopy(changes[field])
            changed_fields.append(field)
    if "budget" in changes:
        new_budget = _budget(changes["budget"], "request.changes.budget")
        if new_budget != updated["budget"]:
            updated["budget"] = new_budget
            changed_fields.append("budget")
    if not changed_fields:
        fail("no_changes", "request.changes", "Значения не изменились.")
    normalized, missing = _draft(updated, "request.changes.result")
    if missing:
        fail(
            "incomplete_contract",
            "request.changes.frame",
            "Изменение делает рамку неполной.",
        )
    if RISKS.index(normalized["risk"]) < RISKS.index(prior_payload["risk"]):
        fail(
            "risk_downgrade_forbidden",
            "request.changes.risk",
            "Снижение риска в истории запрещено.",
        )
    if {"domain", "depth"} & set(changed_fields) and not user_consent:
        fail(
            "consent_required",
            "request.user_consent",
            "Смена направления или глубины требует согласия.",
        )

    normalized["policy_version"] = policy["version"]
    normalized["obligations"] = _obligations(normalized, policy)
    normalized["status"] = "ready_for_host_decision"
    new_body = {
        "schema_version": 1,
        "project_id": contract["project_id"],
        "run_id": contract["run_id"],
        "id": contract["id"],
        "revision": contract["revision"] + 1,
        "payload": normalized,
    }
    new_contract = {**new_body, "content_hash": sha256_json(new_body)}
    affected = sorted(
        row["output_id"]
        for row in dependencies
        if set(row["depends_on"]) & set(changed_fields)
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "RunContractRevisionReceipt",
        "status": "revision_proposed",
        "run_contract": new_contract,
        "supersedes": {
            "id": contract["id"],
            "revision": contract["revision"],
            "content_hash": contract["content_hash"],
        },
        "changed_fields": changed_fields,
        "outputs_to_revisit": affected,
        "impact_scope": "explicit_dependencies_only",
        "expected_revision": expected_revision,
        "user_consent": user_consent,
        "persistence_applied": False,
        "review_required": normalized["risk"] == "high"
        or normalized["depth"] != "search",
        "semantic_certified": False,
        "host_decision_required": True,
    }
    return with_receipt_hash(payload)
