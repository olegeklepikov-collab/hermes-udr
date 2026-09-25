"""Bounded, mode-specific beta plans; planning never implies qualification."""

from __future__ import annotations

import math
import re
from typing import Any, cast

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

_ID = re.compile(r"^[A-Z][A-Z0-9-]{2,63}$")
_FAMILY = re.compile(r"^[a-z][a-z_]{2,39}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
ARXIV_VERSIONED_ID = re.compile(
    r"(?<![A-Za-z0-9.])[0-9]{4}\.[0-9]{4,5}v[1-9][0-9]*(?![A-Za-z0-9])"
)
_SENSITIVE = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|password|secret|authorization|bearer)\s*[:=]"
    r"|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
)
_MODES = {"search", "deep", "ultra", "academic"}
_MIN_LEAVES = {"search": 1, "deep": 2, "ultra": 3, "academic": 2}
_MIN_FAMILIES = {"search": 1, "deep": 2, "ultra": 3, "academic": 2}
_PROFILED_FAMILIES = {
    "web",
    "official",
    "scholarly_index",
    "preprint_archive",
    "dataset",
}
_HARD_CAPS = {
    "search": (2, 3, 1, 120, 0.02),
    "deep": (8, 16, 4, 600, 0.20),
    "ultra": (16, 32, 8, 1200, 0.50),
    "academic": (12, 40, 64, 3600, 0.30),
}
_HARD_CAPS_V2 = {**_HARD_CAPS, "search": (2, 3, 2, 120, 0.02)}
_COMMON_STEPS = (
    "decomposition_assess",
    "instrument_strategy_assess",
    "search_and_extract",
    "exact_source_verify",
    "source_selection",
)
_MODE_STEPS = {
    "search": ("partial_dossier",),
    "deep": ("coverage_assess", "fact_map", "cross_check", "challenge"),
    "ultra": (
        "coverage_assess",
        "fact_map",
        "independence_assess",
        "rival_hypothesis_test",
        "sensitivity_assess",
        "recovery_assess",
    ),
    "academic": (
        "protocol_verify",
        "search_environment_record",
        "deduplicate_studies",
        "screening_adjudicate",
        "study_graph_resolve",
        "academic_synthesis_gate",
    ),
}

BETA_MODE_PLAN_BUILD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "mode",
        "question",
        "leaves",
        "rival_hypotheses",
        "academic_protocol",
        "limits",
        "oversight",
    ],
    "properties": {
        "schema_version": {"enum": [1, 2]},
        "run_id": {"type": "string", "pattern": _ID.pattern},
        "mode": {"enum": sorted(_MODES)},
        "question": {"type": "string", "minLength": 5, "maxLength": 500},
        "leaves": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {"type": "object"},
        },
        "rival_hypotheses": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string"},
        },
        "academic_protocol": {"oneOf": [{"type": "null"}, {"type": "object"}]},
        "limits": {"type": "object"},
        "oversight": {"type": "object"},
    },
}


def _public_text(
    value: object, path: str, *, minimum: int = 5, maximum: int = 500
) -> str:
    result = require_string(value, path).strip()
    if (
        not minimum <= len(result) <= maximum
        or any(ord(character) < 32 for character in result)
        or _SENSITIVE.search(result)
    ):
        fail("unsafe_public_text", path, "Текст вне границ или похож на секрет.")
    return result


def validate_public_question(value: object) -> str:
    return _public_text(value, "question")


def validate_public_protocol_rule(value: object) -> str:
    return _public_text(value, "academic_protocol.rule", maximum=1600)


def question_scoped_short_identifier(term: str, question: str) -> bool:
    """Allow an exact two-character letter-digit label only when the question names it."""
    return bool(
        re.fullmatch(r"[A-Z][0-9]", term)
        and re.search(
            r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])",
            question,
        )
    )


def _hash(value: object, path: str) -> str:
    result = require_string(value, path)
    if not _HASH.fullmatch(result):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return result


def build_beta_mode_plan(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(BETA_MODE_PLAN_BUILD_SCHEMA["required"]), "request")
    version = data["schema_version"]
    if type(version) is not int or version not in (1, 2):
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживаются версии 1 и 2.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    if not _ID.fullmatch(run_id):
        fail("invalid_run_id", "request.run_id", "Недопустимый идентификатор.")
    mode = require_string(data["mode"], "request.mode")
    if mode not in _MODES:
        fail("invalid_mode", "request.mode", "Неизвестный режим.")
    question = _public_text(data["question"], "request.question")

    leaves: list[dict[str, Any]] = []
    leaf_ids: set[str] = set()
    families: set[str] = set()
    raw_leaves = require_list(data["leaves"], "request.leaves")
    if not 1 <= len(raw_leaves) <= 20:
        fail("leaf_count_invalid", "request.leaves", "Нужно от 1 до 20 листьев.")
    for index, raw in enumerate(raw_leaves):
        path = f"request.leaves[{index}]"
        leaf = require_mapping(raw, path)
        fields = {"leaf_id", "query", "source_family"}
        if version == 2 and "concept_groups" in leaf:
            fields.add("concept_groups")
        require_exact_keys(leaf, fields, path)
        leaf_id = require_string(leaf["leaf_id"], f"{path}.leaf_id")
        if not _ID.fullmatch(leaf_id) or leaf_id in leaf_ids:
            fail(
                "leaf_id_invalid_or_duplicate",
                f"{path}.leaf_id",
                "Идентификатор повторён или недопустим.",
            )
        family = require_string(leaf["source_family"], f"{path}.source_family")
        if not _FAMILY.fullmatch(family):
            fail(
                "source_family_invalid",
                f"{path}.source_family",
                "Нужна именованная семья источников.",
            )
        record: dict[str, Any] = {
            "leaf_id": leaf_id,
            "query": _public_text(leaf["query"], f"{path}.query"),
            "source_family": family,
        }
        if version == 2 and family == "preprint_archive":
            query = record["query"]
            if not (
                re.match(r"^(all|ti|abs|au|cat):", query)
                or query.startswith("id_list:")
                and ARXIV_VERSIONED_ID.fullmatch(query.removeprefix("id_list:"))
            ):
                fail(
                    "preprint_query_not_structured",
                    f"{path}.query",
                    "Нужен поисковый запрос arXiv либо точный ID с версией.",
                )
        if "concept_groups" in leaf:
            raw_groups = require_list(leaf["concept_groups"], f"{path}.concept_groups")
            if not 1 <= len(raw_groups) <= 8:
                fail(
                    "concept_groups_invalid",
                    f"{path}.concept_groups",
                    "Нужно 1–8 групп понятий.",
                )
            groups: list[list[str]] = []
            all_terms: set[str] = set()
            for group_index, raw_group in enumerate(raw_groups):
                group_path = f"{path}.concept_groups[{group_index}]"
                raw_terms = require_list(raw_group, group_path)
                if not 1 <= len(raw_terms) <= 12:
                    fail(
                        "concept_group_invalid",
                        group_path,
                        "Нужно 1–12 вариантов понятия.",
                    )
                terms = []
                for term_index, raw_term in enumerate(raw_terms):
                    term = _public_text(
                        raw_term, f"{group_path}[{term_index}]", minimum=2
                    )
                    if len(term) < 3 and not question_scoped_short_identifier(
                        term, question
                    ):
                        fail(
                            "unsafe_public_text",
                            f"{group_path}[{term_index}]",
                            "Короткое обозначение отсутствует в вопросе.",
                        )
                    if len(term) > 80 or term.casefold() in all_terms:
                        fail(
                            "concept_term_invalid_or_duplicate",
                            group_path,
                            "Термин повторён или слишком длинный.",
                        )
                    all_terms.add(term.casefold())
                    terms.append(term)
                groups.append(terms)
            record["concept_groups"] = groups
        leaves.append(record)
        leaf_ids.add(leaf_id)
        families.add(family)

    raw_rivals = require_list(data["rival_hypotheses"], "request.rival_hypotheses")
    if len(raw_rivals) > 12:
        fail(
            "rival_count_invalid",
            "request.rival_hypotheses",
            "Слишком много альтернатив.",
        )
    rivals = [
        _public_text(value, f"request.rival_hypotheses[{index}]")
        for index, value in enumerate(raw_rivals)
    ]
    if len(set(rivals)) != len(rivals):
        fail(
            "duplicate_rival",
            "request.rival_hypotheses",
            "Повтор альтернативы запрещён.",
        )

    protocol_value = data["academic_protocol"]
    protocol: dict[str, Any] | None = None
    if protocol_value is not None:
        raw_protocol = require_mapping(protocol_value, "request.academic_protocol")
        require_exact_keys(
            raw_protocol,
            {
                "protocol_ref",
                "accepted_before_results",
                "search_strategy_ref",
                "screening_rule_ref",
            },
            "request.academic_protocol",
        )
        protocol = {
            "protocol_ref": _hash(
                raw_protocol["protocol_ref"], "request.academic_protocol.protocol_ref"
            ),
            "accepted_before_results": require_bool(
                raw_protocol["accepted_before_results"],
                "request.academic_protocol.accepted_before_results",
            ),
            "search_strategy_ref": _hash(
                raw_protocol["search_strategy_ref"],
                "request.academic_protocol.search_strategy_ref",
            ),
            "screening_rule_ref": _hash(
                raw_protocol["screening_rule_ref"],
                "request.academic_protocol.screening_rule_ref",
            ),
        }
    if mode != "academic" and protocol is not None:
        fail(
            "protocol_not_applicable",
            "request.academic_protocol",
            "Протокол допустим только в Academic.",
        )

    limits = require_mapping(data["limits"], "request.limits")
    require_exact_keys(
        limits,
        {
            "search_calls",
            "max_sources",
            "model_calls",
            "wall_seconds",
            "max_estimated_cost_usd",
        },
        "request.limits",
    )
    capped: dict[str, int | float] = {}
    hard_caps = _HARD_CAPS[mode] if version == 1 else _HARD_CAPS_V2[mode]
    for field, hard_cap in zip(
        ("search_calls", "max_sources", "model_calls", "wall_seconds"),
        hard_caps[:4],
        strict=True,
    ):
        value = require_int(limits[field], f"request.limits.{field}", minimum=1)
        if value > hard_cap:
            fail(
                "limit_above_beta_cap",
                f"request.limits.{field}",
                "Лимит превышает потолок беты.",
            )
        capped[field] = value
    cost = limits["max_estimated_cost_usd"]
    if type(cost) not in (int, float):
        fail(
            "limit_above_beta_cap",
            "request.limits.max_estimated_cost_usd",
            "Недопустимый денежный предел.",
        )
    cost_number = float(cast(int | float, cost))
    if not math.isfinite(cost_number) or not 0 < cost_number <= hard_caps[4]:
        fail(
            "limit_above_beta_cap",
            "request.limits.max_estimated_cost_usd",
            "Недопустимый денежный предел.",
        )
    capped["max_estimated_cost_usd"] = cost_number

    oversight = require_mapping(data["oversight"], "request.oversight")
    if version == 1:
        require_exact_keys(
            oversight,
            {"human_review_required", "external_delivery_allowed"},
            "request.oversight",
        )
        internal_gate = require_bool(
            oversight["human_review_required"],
            "request.oversight.human_review_required",
        )
        if internal_gate is not True:
            fail(
                "unsafe_oversight",
                "request.oversight",
                "Историческая версия требует человека.",
            )
    else:
        require_exact_keys(
            oversight,
            {"internal_human_gate", "external_delivery_allowed"},
            "request.oversight",
        )
        internal_gate = require_bool(
            oversight["internal_human_gate"],
            "request.oversight.internal_human_gate",
        )
        if internal_gate is not False:
            fail(
                "unsafe_oversight",
                "request.oversight",
                "Внутренний человеческий шлюз исключён.",
            )
    if (
        require_bool(
            oversight["external_delivery_allowed"],
            "request.oversight.external_delivery_allowed",
        )
        is not False
    ):
        fail(
            "unsafe_oversight",
            "request.oversight",
            "Автоматическая внешняя доставка запрещена.",
        )

    missing = []
    if len(leaves) < _MIN_LEAVES[mode]:
        missing.append("decomposition_leaves")
    if len(families) < _MIN_FAMILIES[mode]:
        missing.append("source_family_diversity")
    if version == 2:
        missing.extend(
            f"source_family_unavailable:{family}"
            for family in sorted(families - _PROFILED_FAMILIES)
        )
    if int(capped["search_calls"]) < len(leaves):
        missing.append("search_call_budget")
    if int(capped["max_sources"]) < len(leaves):
        missing.append("source_budget")
    if mode == "ultra" and len(rivals) < 2:
        missing.append("rival_hypotheses")
    if mode == "academic" and (
        protocol is None or not protocol["accepted_before_results"]
    ):
        missing.append("preaccepted_review_protocol")

    body: dict[str, Any] = {
        "schema_version": version,
        "contract": "BetaModeExecutionPlan",
        "status": "ready_to_execute" if not missing else "blocked",
        "run_id": run_id,
        "mode": mode,
        "question": question,
        "leaves": leaves,
        "source_families": sorted(families),
        "rival_hypotheses": rivals,
        "academic_protocol": protocol,
        "limits": capped,
        "steps": list(
            _COMMON_STEPS
            + _MODE_STEPS[mode]
            + (("human_review",) if version == 1 else ("automated_result_assembly",))
        ),
        "missing_obligations": missing,
        "execution_allowed": not missing,
        "source_independence_verified": False,
        "protocol_preacceptance_verified": False,
        "qualification_status": "not_verified",
        "release_authorized": False,
        "external_delivery_authorized": False,
        "initial_key_setup_in_scope": False,
    }
    if version == 2:
        body["internal_human_gate_required"] = False
        body["final_acceptance_external"] = True
    return with_receipt_hash(body)


def verify_beta_mode_plan(value: object) -> dict[str, Any]:
    """Rebuild an external plan before any network activity."""
    plan = require_mapping(value, "plan")
    if not verify_receipt_hash(plan):
        fail("plan_hash_invalid", "plan.receipt_hash", "Хеш плана не совпадает.")
    request = {
        "schema_version": plan.get("schema_version"),
        "run_id": plan.get("run_id"),
        "mode": plan.get("mode"),
        "question": plan.get("question"),
        "leaves": plan.get("leaves"),
        "rival_hypotheses": plan.get("rival_hypotheses"),
        "academic_protocol": plan.get("academic_protocol"),
        "limits": plan.get("limits"),
        "oversight": (
            {"human_review_required": True, "external_delivery_allowed": False}
            if plan.get("schema_version") == 1
            else {"internal_human_gate": False, "external_delivery_allowed": False}
        ),
    }
    expected = build_beta_mode_plan(request)
    if plan != expected or expected["status"] != "ready_to_execute":
        fail("plan_not_executable", "plan", "План изменён или заблокирован.")
    return expected
