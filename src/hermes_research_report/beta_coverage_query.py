"""Choose one uncovered atom and build a bounded two-family discovery subplan."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .beta_coverage import assess_beta_coverage
from .beta_modes import build_beta_mode_plan
from .canonical import verify_receipt_hash, with_receipt_hash


def select_coverage_atom(frame: object, observations: object) -> dict[str, Any]:
    progress = assess_beta_coverage(frame, observations, budget_exhausted=False)
    assert type(frame) is dict
    scores = {row["atom_id"]: row for row in progress["atoms"]}
    candidates = [
        atom
        for atom in frame["atoms"]
        if not scores[atom["atom_id"]]["evidence_floor_met"]
        and {"web", "scholarly_index"}.issubset(atom["required_families"])
    ]
    if not candidates:
        raise ValueError("coverage_no_supported_atom_pending")
    candidates.sort(
        key=lambda atom: (
            scores[atom["atom_id"]]["query_count"],
            {"central": 0, "peripheral": 1, "marginal": 2}[atom["importance"]],
            {"negative": 0, "latent": 1, "positive": 2}[atom["space"]],
            atom["atom_id"],
        )
    )
    return candidates[0]


def build_coverage_query_prompt(atom: object) -> str:
    if (
        type(atom) is not dict
        or type(atom.get("atom_id")) is not str
        or type(atom.get("question")) is not str
        or not {"web", "scholarly_index"}.issubset(atom.get("required_families", []))
    ):
        raise ValueError("coverage_query_atom_invalid")
    return (
        "Составьте ровно два предметных поисковых запроса для ОДНОГО вопроса. "
        "Не ищите источники и не отвечайте на вопрос. Верните только JSON с "
        "полями web и scholarly_index; каждое значение — объект с ровно query "
        "и concept_groups. query — обычный англоязычный запрос без URL и без "
        "префиксов arXiv; для scholarly_index задайте термины научного поиска, "
        "для web — первичные стандарты, материалы практики и контрпримеры. "
        "concept_groups — 2–4 массива предметных синонимов, по 1–4 строки; "
        "каждая группа должна быть представлена в найденном тексте. "
        "Не используйте только общий термин PDLC; включите отличительные "
        "понятия данного атома. Не обещайте релевантность результата.\n\n"
        f"ATOM_ID: {atom['atom_id']}\nВОПРОС: {atom['question']}"
    )


def parse_coverage_query_reply(
    raw: str,
    *,
    frame: object,
    atom_id: str,
    batch_number: int,
    review: object,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        type(frame) is not dict
        or type(review) is not dict
        or not verify_receipt_hash(frame)
        or not verify_receipt_hash(review)
        or review.get("frame_receipt_hash") != frame["receipt_hash"]
        or type(batch_number) is not int
        or not 1 <= batch_number <= 99
        or type(raw) is not str
        or not raw
        or len(raw.encode()) > 1_048_576
    ):
        raise ValueError("coverage_query_inputs_invalid")
    matching = [atom for atom in frame["atoms"] if atom["atom_id"] == atom_id]
    if len(matching) != 1:
        raise ValueError("coverage_query_atom_invalid")

    def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("coverage_query_duplicate_key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs)
    except json.JSONDecodeError:
        raise ValueError("coverage_query_json_invalid") from None
    alternatives: list[dict[str, Any]] = []
    if type(value) is list:
        if not 1 <= len(value) <= 3 or any(
            type(row) is not dict or set(row) != {"web", "scholarly_index"}
            for row in value
        ):
            raise ValueError("coverage_query_shape_invalid")
        alternatives = value[1:]
        value = value[0]
    if type(value) is not dict or set(value) != {"web", "scholarly_index"}:
        raise ValueError("coverage_query_shape_invalid")
    leaves = []
    for index, family in enumerate(("web", "scholarly_index"), 1):
        row = value[family]
        if type(row) is not dict or set(row) != {"query", "concept_groups"}:
            raise ValueError("coverage_query_shape_invalid")
        leaves.append(
            {
                "leaf_id": f"LEAF-{index:03d}",
                "source_family": family,
                "query": row["query"],
                "concept_groups": row["concept_groups"],
            }
        )
    run_id = f"{frame['run_id']}-B{batch_number:02d}"
    request = {
        "schema_version": 2,
        "run_id": run_id,
        "mode": "deep",
        "question": matching[0]["question"],
        "leaves": leaves,
        "rival_hypotheses": [],
        "academic_protocol": None,
        "limits": {
            "search_calls": 2,
            "max_sources": 7,
            "model_calls": 1,
            "wall_seconds": 180,
            "max_estimated_cost_usd": 0.05,
        },
        "oversight": {
            "internal_human_gate": False,
            "external_delivery_allowed": False,
        },
    }
    plan = build_beta_mode_plan(request)
    if plan["status"] != "ready_to_execute":
        raise ValueError("coverage_query_subplan_not_ready")
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageSourceBatchPlan",
            "run_id": frame["run_id"],
            "batch_run_id": run_id,
            "batch_number": batch_number,
            "frame_receipt_hash": frame["receipt_hash"],
            "review_receipt_hash": review["receipt_hash"],
            "atom_id": atom_id,
            "atom_question_sha256": hashlib.sha256(
                matching[0]["question"].encode()
            ).hexdigest(),
            "subplan_receipt_hash": plan["receipt_hash"],
            "subplan_mode": "deep_source_discovery_only",
            "unexecuted_alternative_pairs": alternatives,
            "parent_profile": frame["profile"],
            "independent_origin_count": 0,
            "source_calls": 0,
            "topic_completeness_verified": False,
            "release_authorized": False,
        }
    )
    return plan, receipt


def build_cross_domain_query_prompt(atom: object, previous: object) -> str:
    if (
        type(atom) is not dict
        or type(previous) is not dict
        or not verify_receipt_hash(previous)
        or previous.get("contract") != "BetaCoverageSourceBatchObservation"
        or previous.get("atom_id") != atom.get("atom_id")
        or not {"web", "scholarly_index"}.issubset(atom.get("required_families", []))
    ):
        raise ValueError("coverage_cross_domain_inputs_invalid")
    return (
        "Две прошлые общие формулировки дали шесть записей без совпадения "
        "предметных групп и неудачное извлечение веб-текста. НЕ считайте это "
        "отсутствием исследований. Разделите исходный вопрос на цифровые и "
        "физические продукты и на два инструмента для каждого домена. "
        "Верните только JSON с полями digital и physical; в каждом ровно web "
        "и scholarly_index; у каждого ровно query и concept_groups. "
        "Всего ЧЕТЫРЕ запроса. query — 4–12 английских поисковых слов, не "
        "полное вопросительное предложение, без URL и префиксов arXiv. "
        "concept_groups — 2–3 группы по 1–3 синонима, предметные, но не "
        "требующие, чтобы ОДИН источник сравнивал оба домена. web ищет "
        "практику/первичные руководства, scholarly_index — исследования. "
        "Не повторяйте длинную общую формулировку и не заявляйте вывод.\n\n"
        f"ATOM_ID: {atom['atom_id']}\nВОПРОС: {atom['question']}"
    )


def parse_cross_domain_query_reply(
    raw: str,
    *,
    frame: object,
    review: object,
    atom_id: str,
    previous: object,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        type(frame) is not dict
        or type(review) is not dict
        or type(previous) is not dict
        or not verify_receipt_hash(frame)
        or not verify_receipt_hash(review)
        or not verify_receipt_hash(previous)
        or review.get("frame_receipt_hash") != frame["receipt_hash"]
        or previous.get("frame_receipt_hash") != frame["receipt_hash"]
        or previous.get("atom_id") != atom_id
        or previous.get("batch_number") != 2
        or type(raw) is not str
        or not raw
        or len(raw.encode()) > 1_048_576
    ):
        raise ValueError("coverage_cross_domain_inputs_invalid")
    matching = [atom for atom in frame["atoms"] if atom["atom_id"] == atom_id]
    if len(matching) != 1:
        raise ValueError("coverage_cross_domain_atom_invalid")
    build_cross_domain_query_prompt(matching[0], previous)

    def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("coverage_cross_domain_duplicate_key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs)
    except json.JSONDecodeError:
        raise ValueError("coverage_cross_domain_json_invalid") from None
    if type(value) is not dict or set(value) != {"digital", "physical"}:
        raise ValueError("coverage_cross_domain_shape_invalid")
    leaves = []
    unexecuted: dict[str, list[dict[str, Any]]] = {}
    for domain in ("digital", "physical"):
        domain_routes = value[domain]
        if type(domain_routes) is not dict or set(domain_routes) != {
            "web",
            "scholarly_index",
        }:
            raise ValueError("coverage_cross_domain_shape_invalid")
        for family in ("web", "scholarly_index"):
            row = domain_routes[family]
            if type(row) is list:
                if not 1 <= len(row) <= 3 or any(
                    type(item) is not dict or set(item) != {"query", "concept_groups"}
                    for item in row
                ):
                    raise ValueError("coverage_cross_domain_shape_invalid")
                unexecuted[f"{domain}:{family}"] = row[1:]
                row = row[0]
            if type(row) is not dict or set(row) != {"query", "concept_groups"}:
                raise ValueError("coverage_cross_domain_shape_invalid")
            leaves.append(
                {
                    "leaf_id": f"LEAF-{len(leaves) + 1:03d}",
                    "query": row["query"],
                    "source_family": family,
                    "concept_groups": row["concept_groups"],
                }
            )
    run_id = f"{frame['run_id']}-B03"
    request = {
        "schema_version": 2,
        "run_id": run_id,
        "mode": "deep",
        "question": matching[0]["question"],
        "leaves": leaves,
        "rival_hypotheses": [],
        "academic_protocol": None,
        "limits": {
            "search_calls": 4,
            "max_sources": 14,
            "model_calls": 1,
            "wall_seconds": 300,
            "max_estimated_cost_usd": 0.05,
        },
        "oversight": {
            "internal_human_gate": False,
            "external_delivery_allowed": False,
        },
    }
    plan = build_beta_mode_plan(request)
    if plan["status"] != "ready_to_execute":
        raise ValueError("coverage_cross_domain_subplan_not_ready")
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageSourceBatchPlan",
            "run_id": frame["run_id"],
            "batch_run_id": run_id,
            "batch_number": 3,
            "frame_receipt_hash": frame["receipt_hash"],
            "review_receipt_hash": review["receipt_hash"],
            "atom_id": atom_id,
            "atom_question_sha256": hashlib.sha256(
                matching[0]["question"].encode()
            ).hexdigest(),
            "subplan_receipt_hash": plan["receipt_hash"],
            "subplan_mode": "deep_source_discovery_only",
            "decomposition": "digital_physical_by_instrument",
            "leaf_domains": {
                "LEAF-001": "digital",
                "LEAF-002": "digital",
                "LEAF-003": "physical",
                "LEAF-004": "physical",
            },
            "unexecuted_alternatives": unexecuted,
            "prior_observation_receipt_hash": previous["receipt_hash"],
            "source_calls": 0,
            "topic_completeness_verified": False,
            "release_authorized": False,
        }
    )
    return plan, receipt
