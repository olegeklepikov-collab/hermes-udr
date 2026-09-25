"""Domain-aware beta decomposition with graded construct operationalization."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .beta_modes import validate_public_question
from .canonical import with_receipt_hash

_RUN = re.compile(r"^[A-Z][A-Z0-9-]{2,63}$")
_PROFILES = {"search", "deep", "ultra", "academic"}
_QUESTION_TYPES = {
    "descriptive",
    "comparative",
    "causal",
    "forecast",
    "normative",
    "interpretive",
}
_CONSTRUCT_KINDS = {"empirical", "qualitative", "conceptual", "normative"}
_BASES = {
    "scholarly",
    "official",
    "dataset",
    "web_primary",
    "practice",
    "expert",
    "conceptual",
    "case",
    "direct_observation",
}
_ACADEMIC = {"central", "supporting", "limited", "not_applicable"}
_IMPORTANCE = {"central", "peripheral", "marginal"}
_SPACE = {"positive", "negative", "latent"}


def build_domain_decomposition_prompt(
    *,
    question: str,
    profile: str,
    legacy_rule_instruction: bool = False,
    legacy_coverage_instruction: bool = False,
) -> str:
    question = validate_public_question(question)
    if profile not in _PROFILES:
        raise ValueError("domain_profile_invalid")
    rule_instruction = (
        ""
        if legacy_rule_instruction
        else "не оставляйте operational_rule пустым: если правило пока неизвестно, "
        "напишите, что именно требуется определить. "
    )
    return (
        "Сначала предметно разберите ВОПРОС, не ищите источники и не отвечайте. "
        "Верните только JSON с ровно scope, domains, aspects, constructs, "
        "exclusions, unresolved_terms. domains: массив {name,boundary}; "
        "разделяйте действительно разные предметные области/режимы. "
        "aspects: массив {domain_index,name,question,question_type,importance,space,"
        "construct_indices,evidence_bases,academic_role,academic_rationale}. "
        "domain_index и construct_indices — индексы с нуля. "
        "question_type: descriptive|comparative|causal|forecast|normative|interpretive. "
        "importance: central|peripheral|marginal; space: positive|negative|latent. "
        "evidence_bases — необходимые типы опоры из scholarly, official, dataset, "
        "web_primary, practice, expert, conceptual, case, direct_observation. "
        "academic_role: central|supporting|limited|not_applicable с конкретной "
        "причиной. Если роль central, включите scholarly в evidence_bases; "
        "если научные публикации не нужны либо неуместны, выберите supporting, "
        "limited или not_applicable по существу. Не добавляйте научные "
        "публикации и наборы данных только ради "
        "числа семейств: для практического, нормативного, концептуального или "
        "нового вопроса возможна иная опора, которую позже надо оценить по "
        "происхождению и пределам. constructs: массив {term,definition,kind,"
        "operational_rule,indicator,unit,acquisition,validity_limits}. "
        "kind: empirical|qualitative|conceptual|normative. Для эмпирического "
        "конструкта укажите наблюдаемый признак, измерение/единицу и способ "
        "получения, ЕСЛИ они определимы; если нет, используйте null и явно "
        "обозначьте неоперациональность в operational_rule. Для концептуального "
        "и нормативного конструкта operational_rule — правила границы понятия, "
        "сопоставления случаев или ценностного критерия, а не выдуманная цифра; "
        + rule_instruction
        + "indicator/unit/acquisition могут быть null. validity_limits — список "
        "ограничений, смешений и недопустимых выводов, допустим пустой до поиска. "
        "exclusions и unresolved_terms — массивы строк. Покройте определения, "
        "основные шаги/акторы/временные границы, периферию, отрицательные и "
        "латентные аспекты там, где применимо. Не превращайте гипотезу в факт и "
        "не заявляйте существование или отсутствие академических источников до поиска.\n\n"
        + (
            ""
            if legacy_coverage_instruction
            else "Для широкого исследования явно рассмотрите центральные, периферические "
            "и маргинальные позиции, включая редкие практики, спорные трактовки и "
            "краевые условия, а также отрицательные и латентные аспекты. "
            "Если направление неприменимо, укажите предметную причину в exclusions; "
            "не добавляйте фиктивный аспект ради заполнения категории.\n\n"
        )
        + f"ПРОФИЛЬ: {profile}\nВОПРОС: {question}"
    )


def _text(value: object, *, minimum: int = 5, maximum: int = 1000) -> str:
    if (
        type(value) is not str
        or not minimum <= len(value.strip()) <= maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("domain_text_invalid")
    return value.strip()


def _optional(value: object, *, minimum: int = 5, maximum: int = 1000) -> str | None:
    return None if value is None else _text(value, minimum=minimum, maximum=maximum)


def _strings(value: object, *, maximum: int = 50) -> list[str]:
    if type(value) is not list or len(value) > maximum:
        raise ValueError("domain_list_invalid")
    result = [_text(item) for item in value]
    if len(set(result)) != len(result):
        raise ValueError("domain_list_duplicate")
    return result


def parse_domain_decomposition(
    raw: str, *, question: str, profile: str, run_id: str
) -> dict[str, Any]:
    question = validate_public_question(question)
    if (
        profile not in _PROFILES
        or type(run_id) is not str
        or not _RUN.fullmatch(run_id)
        or type(raw) is not str
        or not raw
        or len(raw.encode()) > 1_048_576
    ):
        raise ValueError("domain_decomposition_inputs_invalid")

    identical_duplicate_keys: list[str] = []

    def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                if type(result[key]) is not type(value) or result[key] != value:
                    raise ValueError("domain_duplicate_json_key")
                identical_duplicate_keys.append(key)
                continue
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs)
    except json.JSONDecodeError:
        raise ValueError("domain_decomposition_json_invalid") from None
    nested_scope_recovered_from_question = False
    if (
        type(value) is dict
        and set(value) == {"scope"}
        and type(value["scope"]) is dict
        and set(value["scope"])
        == {"domains", "aspects", "constructs", "exclusions", "unresolved_terms"}
    ):
        value = {"scope": question, **value["scope"]}
        nested_scope_recovered_from_question = True
    if type(value) is not dict or set(value) != {
        "scope",
        "domains",
        "aspects",
        "constructs",
        "exclusions",
        "unresolved_terms",
    }:
        raise ValueError("domain_decomposition_shape_invalid")
    structured_scope_model = None
    scope_value = value["scope"]
    if type(scope_value) is dict and 1 <= len(scope_value) <= 8:
        if any(
            type(key) is not str
            or not 2 <= len(key) <= 64
            or any(ord(character) < 32 for character in key)
            for key in scope_value
        ):
            raise ValueError("domain_scope_field_invalid")
        structured_scope_model = {
            key: _text(scope_value[key], minimum=3, maximum=500) for key in scope_value
        }
        scope_value = "; ".join(
            f"{key}: {value}" for key, value in structured_scope_model.items()
        )
    scope = _text(scope_value, minimum=10, maximum=1500)
    raw_domains, raw_aspects, raw_constructs = (
        value["domains"],
        value["aspects"],
        value["constructs"],
    )
    if (
        type(raw_domains) is not list
        or not raw_domains
        or type(raw_aspects) is not list
        or not raw_aspects
        or type(raw_constructs) is not list
    ):
        raise ValueError("domain_decomposition_shape_invalid")
    domains = []
    for index, row in enumerate(raw_domains):
        if type(row) is not dict or set(row) != {"name", "boundary"}:
            raise ValueError("domain_node_invalid")
        domains.append(
            {
                "domain_id": f"DOMAIN-{index + 1:03d}",
                "name": _text(row["name"], minimum=2),
                "boundary": _text(row["boundary"], minimum=10),
            }
        )
    constructs = []
    normalized_construct_kinds = []
    compound_unit_candidates: list[int] = []
    for index, row in enumerate(raw_constructs):
        if type(row) is not dict or set(row) != {
            "term",
            "definition",
            "kind",
            "operational_rule",
            "indicator",
            "unit",
            "acquisition",
            "validity_limits",
        }:
            raise ValueError("domain_construct_invalid")
        kind = row["kind"]
        if kind == "interpretive":
            normalized_construct_kinds.append(
                {
                    "construct_index": index,
                    "model_kind": "interpretive",
                    "effective_kind": "qualitative",
                    "requires_semantic_review": True,
                }
            )
            kind = "qualitative"
        if kind == "forecast":
            normalized_construct_kinds.append(
                {
                    "construct_index": index,
                    "model_kind": "forecast",
                    "effective_kind": "conceptual",
                    "requires_semantic_review": True,
                    "prediction_validated": False,
                }
            )
            kind = "conceptual"
        if type(kind) is not str or kind not in _CONSTRUCT_KINDS:
            raise ValueError("domain_construct_kind_invalid")
        indicator = _optional(row["indicator"])
        unit = _optional(row["unit"], minimum=1, maximum=160)
        if unit is not None and len(unit) > 80:
            compound_unit_candidates.append(index)
        acquisition = _optional(row["acquisition"])
        rule_raw = row["operational_rule"]
        if rule_raw is not None and type(rule_raw) is not str:
            raise ValueError("domain_construct_rule_invalid")
        rule = (
            _text(rule_raw, minimum=10)
            if type(rule_raw) is str and rule_raw.strip()
            else None
        )
        grade = (
            "empirical_operational_candidate"
            if kind == "empirical" and rule and all((indicator, unit, acquisition))
            else "empirical_observable_unit_unset"
            if kind == "empirical" and rule and indicator and acquisition
            else "empirical_unmeasured_hypothesis"
            if kind == "empirical"
            else "qualitative_rule_missing"
            if kind == "qualitative" and rule is None
            else "qualitative_rule_candidate"
            if kind == "qualitative"
            else "conceptual_boundary_missing"
            if kind == "conceptual" and rule is None
            else "conceptual_boundary_candidate"
            if kind == "conceptual"
            else "normative_criterion_missing"
            if rule is None
            else "normative_criterion_candidate"
        )
        constructs.append(
            {
                "construct_id": f"CONSTRUCT-{index + 1:03d}",
                "term": _text(row["term"], minimum=2),
                "definition": _text(row["definition"], minimum=10),
                "kind": kind,
                "operational_rule": rule,
                "indicator": indicator,
                "unit": unit,
                "acquisition": acquisition,
                "validity_limits": _strings(row["validity_limits"]),
                "operationalization_grade": grade,
                "measurement_claim_allowed_before_sources": False,
            }
        )
    aspects = []
    unresolved_model_construct_indices = []
    normalized_null_academic_rationale_details_aspect_indexes = []
    for index, row in enumerate(raw_aspects):
        required_fields = {
            "domain_index",
            "name",
            "question",
            "question_type",
            "importance",
            "space",
            "construct_indices",
            "evidence_bases",
            "academic_role",
            "academic_rationale",
        }
        if (
            type(row) is not dict
            or set(row) - {"academic_rationale_details"} != required_fields
            or (
                "academic_rationale_details" in row
                and row["academic_rationale_details"] is not None
            )
        ):
            raise ValueError("domain_aspect_invalid")
        if "academic_rationale_details" in row:
            normalized_null_academic_rationale_details_aspect_indexes.append(index)
        parent = row["domain_index"]
        indices = row["construct_indices"]
        bases = row["evidence_bases"]
        if (
            type(parent) is not int
            or not 0 <= parent < len(domains)
            or row["question_type"] not in _QUESTION_TYPES
            or row["importance"] not in _IMPORTANCE
            or row["space"] not in _SPACE
            or type(indices) is not list
            or any(type(item) is not int or item < 0 for item in indices)
            or len(set(indices)) != len(indices)
            or type(bases) is not list
            or not bases
            or any(type(item) is not str or item not in _BASES for item in bases)
            or len(set(bases)) != len(bases)
            or row["academic_role"] not in _ACADEMIC
        ):
            raise ValueError("domain_aspect_invalid")
        issues = []
        unresolved = [item for item in indices if item >= len(constructs)]
        if unresolved:
            unresolved_model_construct_indices.append(
                {"aspect_index": index, "model_indices": unresolved}
            )
            issues.append("construct_reference_out_of_range")
            indices = [item for item in indices if item < len(constructs)]
            if not indices:
                issues.append("construct_operationalization_unlinked")
        if row["academic_role"] == "not_applicable" and bases == ["scholarly"]:
            issues.append("academic_role_basis_conflict")
        if row["academic_role"] == "central" and "scholarly" not in bases:
            issues.append("academic_central_without_scholarly_basis")
        effective_academic_role = (
            "unresolved_basis_conflict" if issues else row["academic_role"]
        )
        empirical_refs = [
            constructs[item]
            for item in indices
            if constructs[item]["kind"] == "empirical"
        ]
        unmeasured_refs = [
            item["construct_id"]
            for item in empirical_refs
            if item["operationalization_grade"] != "empirical_operational_candidate"
        ]
        missing_rules = [
            constructs[item]["construct_id"]
            for item in indices
            if constructs[item]["operational_rule"] is None
        ]
        ceiling = (
            "causal_hypothesis_only"
            if row["question_type"] == "causal"
            else "comparative_hypothesis_only"
            if row["question_type"] == "comparative"
            else "forecast_scenario_only"
            if row["question_type"] == "forecast"
            else "normative_position_not_empirical_fact"
            if row["question_type"] == "normative"
            else "interpretive_candidate"
            if row["question_type"] == "interpretive"
            else "source_review_required"
        )
        aspects.append(
            {
                "aspect_id": f"ASPECT-{index + 1:03d}",
                "domain_id": domains[parent]["domain_id"],
                "name": _text(row["name"], minimum=2),
                "question": _text(row["question"], minimum=10),
                "question_type": row["question_type"],
                "importance": row["importance"],
                "space": row["space"],
                "construct_refs": [
                    constructs[item]["construct_id"] for item in indices
                ],
                "evidence_bases": list(bases),
                "academic_role": row["academic_role"],
                "academic_role_effective": effective_academic_role,
                "academic_rationale": _text(row["academic_rationale"], minimum=10),
                "pre_source_inference_ceiling": ceiling,
                "unmeasured_empirical_construct_refs": unmeasured_refs,
                "construct_refs_missing_operational_rule": missing_rules,
                "issues": issues,
            }
        )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaDomainDecomposition",
            "run_id": run_id,
            "profile": profile,
            "question": question,
            "scope": scope,
            "structured_scope_model": structured_scope_model,
            "structured_scope_model_keys": list(structured_scope_model)
            if structured_scope_model is not None
            else [],
            "structured_scope_normalized": structured_scope_model is not None,
            "domains": domains,
            "aspects": aspects,
            "missing_importance_ranks": sorted(
                _IMPORTANCE - {a["importance"] for a in aspects}
            ),
            "missing_research_spaces": sorted(_SPACE - {a["space"] for a in aspects}),
            "coverage_completeness_verified": False,
            "academic_role_conflict_count": sum(
                any(
                    issue
                    in {
                        "academic_role_basis_conflict",
                        "academic_central_without_scholarly_basis",
                    }
                    for issue in aspect["issues"]
                )
                for aspect in aspects
            ),
            "constructs": constructs,
            "normalized_construct_kinds": normalized_construct_kinds,
            "nested_scope_recovered_from_public_question": nested_scope_recovered_from_question,
            "identical_duplicate_json_keys": identical_duplicate_keys,
            "compound_unit_candidate_indices": compound_unit_candidates,
            "compound_unit_semantics_verified": False,
            "unresolved_model_construct_indices": unresolved_model_construct_indices,
            **(
                {
                    "normalized_null_academic_rationale_details_aspect_indexes": (
                        normalized_null_academic_rationale_details_aspect_indexes
                    )
                }
                if normalized_null_academic_rationale_details_aspect_indexes
                else {}
            ),
            "construct_reference_issue_count": len(unresolved_model_construct_indices),
            "constructs_with_missing_operational_rule": sum(
                construct["operational_rule"] is None for construct in constructs
            ),
            "exclusions": _strings(value["exclusions"]),
            "unresolved_terms": _strings(value["unresolved_terms"]),
            "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "academic_applicability_is_question_specific": True,
            "academic_absence_does_not_block_nonacademic_partial_answer": True,
            "pre_source_claims_verified": False,
            "source_calls": 0,
            "release_authorized": False,
        }
    )
