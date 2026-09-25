"""Build one scholarly plus DataCite metadata discovery subplan for an open atom."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .beta_modes import build_beta_mode_plan
from .canonical import verify_receipt_hash, with_receipt_hash

_DATACITE_QUERY = re.compile(
    r"^(?:titles\.title|descriptions\.description):\([^)]{8,180}\)$"
)
_REQUIRED_PHRASE = re.compile(r"^\+[A-Za-z0-9 -]{3,80}$")


def build_dataset_query_prompt(atom: object) -> str:
    if (
        type(atom) is not dict
        or not {"dataset", "scholarly_index"}.issubset(
            atom.get("required_families", [])
        )
        or type(atom.get("question")) is not str
    ):
        raise ValueError("dataset_query_atom_invalid")
    return (
        "Составьте ДВА кратких запроса для открытого атомарного вопроса. "
        "Не ищите источники и не отвечайте на вопрос. Верните только JSON с "
        "ровно scholarly_index и dataset; каждый объект содержит ровно query "
        "и concept_groups. scholarly_index.query — 4–12 английских слов для "
        "OpenAlex. dataset.query — синтаксис DataCite OpenSearch вида "
        "titles.title:(+term +term) либо descriptions.description:(+term +term), "
        "2–4 действительно обязательных предметных термина; фильтр "
        "resource-type-id=dataset добавляется системой отдельно. "
        "concept_groups — 1–3 группы предметных синонимов по 1–3 строки. "
        "Не предполагайте, что запись Dataset содержит пригодные для анализа "
        "данные: это только поиск метаданных DOI. Не добавляйте URL, секреты или "
        "неподтверждённые выводы.\n\n"
        f"ATOM_ID: {atom['atom_id']}\nВОПРОС: {atom['question']}"
    )


def parse_dataset_query_reply(
    raw: str, *, frame: object, atom_id: str, previous: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        type(frame) is not dict
        or type(previous) is not dict
        or not verify_receipt_hash(frame)
        or not verify_receipt_hash(previous)
        or previous.get("frame_receipt_hash") != frame["receipt_hash"]
        or previous.get("atom_id") != atom_id
        or previous.get("batch_number") != 3
        or type(raw) is not str
        or not raw
        or len(raw.encode()) > 1_048_576
    ):
        raise ValueError("dataset_query_inputs_invalid")
    atoms = [atom for atom in frame["atoms"] if atom["atom_id"] == atom_id]
    if len(atoms) != 1:
        raise ValueError("dataset_query_atom_invalid")
    build_dataset_query_prompt(atoms[0])

    def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("dataset_query_duplicate_key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs)
    except json.JSONDecodeError:
        raise ValueError("dataset_query_json_invalid") from None
    alternatives: list[dict[str, Any]] = []
    if type(value) is list:
        if not 1 <= len(value) <= 3 or any(
            type(item) is not dict or set(item) != {"scholarly_index", "dataset"}
            for item in value
        ):
            raise ValueError("dataset_query_shape_invalid")
        alternatives = value[1:]
        value = value[0]
    if type(value) is not dict or set(value) != {"scholarly_index", "dataset"}:
        raise ValueError("dataset_query_shape_invalid")
    leaves = []
    normalizations: list[str] = []
    for family in ("scholarly_index", "dataset"):
        row = value[family]
        if (
            type(row) is not dict
            or set(row) not in ({"query", "concept_groups"}, {"query"})
            or family == "scholarly_index"
            and "concept_groups" not in row
        ):
            raise ValueError("dataset_query_shape_invalid")
        query = row["query"]
        groups = row.get("concept_groups")
        if family == "dataset":
            if type(query) is not str or not _DATACITE_QUERY.fullmatch(query):
                raise ValueError("dataset_query_not_fielded")
            field, rest = query.split(":(", 1)
            fragments = re.split(r"\s+(?=\+)", rest[:-1].strip())
            if len(fragments) < 2 or any(
                not _REQUIRED_PHRASE.fullmatch(fragment) for fragment in fragments
            ):
                raise ValueError("dataset_query_not_fielded")
            phrases = [fragment[1:].strip() for fragment in fragments]
            if groups is None:
                groups = [[phrase] for phrase in phrases]
                normalizations.append("dataset_groups_from_required_query_phrases")
            if any(" " in phrase for phrase in phrases):
                query = (
                    field
                    + ":("
                    + " ".join(
                        '+"' + phrase + '"' if " " in phrase else "+" + phrase
                        for phrase in phrases
                    )
                    + ")"
                )
                normalizations.append("datacite_required_multiword_phrases_quoted")
        elif (
            type(groups) is list
            and groups
            and all(type(group) is str for group in groups)
        ):
            groups = [
                [term.strip() for term in group.split(";") if term.strip()]
                for group in groups
            ]
            normalizations.append("semicolon_concept_groups_split")
        leaves.append(
            {
                "leaf_id": f"LEAF-{len(leaves) + 1:03d}",
                "source_family": family,
                "query": query,
                "concept_groups": groups,
            }
        )
    run_id = f"{frame['run_id']}-B04"
    plan = build_beta_mode_plan(
        {
            "schema_version": 2,
            "run_id": run_id,
            "mode": "deep",
            "question": atoms[0]["question"],
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
    )
    if plan["status"] != "ready_to_execute":
        raise ValueError("dataset_query_subplan_not_ready")
    batch = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageDatasetBatchPlan",
            "run_id": frame["run_id"],
            "batch_run_id": run_id,
            "batch_number": 4,
            "frame_receipt_hash": frame["receipt_hash"],
            "atom_id": atom_id,
            "atom_question_sha256": hashlib.sha256(
                atoms[0]["question"].encode()
            ).hexdigest(),
            "prior_observation_receipt_hash": previous["receipt_hash"],
            "subplan_receipt_hash": plan["receipt_hash"],
            "dataset_route_scope": "doi_metadata_only",
            "model_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "unexecuted_alternative_pairs": alternatives,
            "explicit_normalizations": normalizations,
            "dataset_content_read": False,
            "source_calls": 0,
            "saturation_verified": False,
            "release_authorized": False,
        }
    )
    return plan, batch
