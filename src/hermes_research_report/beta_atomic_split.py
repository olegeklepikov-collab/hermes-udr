"""Version a coverage frame after critic and analyst atom splits."""

from __future__ import annotations

from typing import Any

from .beta_coverage import assess_beta_coverage
from .canonical import sha256_json, verify_receipt_hash, with_receipt_hash

_PROVISIONAL_CLOSURE = (
    "Определены понятия и границы этого вопроса, указаны прямой источник, "
    "точный фрагмент и ограничения; для сравнения или причинного вывода "
    "дополнительно проверены сопоставимость и альтернативные объяснения. "
    "При недостатке опоры вопрос остаётся открытым."
)


def split_coverage_atoms(
    frame: object, review: object, *, extra: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        type(frame) is not dict
        or type(review) is not dict
        or not verify_receipt_hash(frame)
        or not verify_receipt_hash(review)
        or review.get("contract") != "BetaCoverageCriticReview"
        or review.get("frame_receipt_hash") != frame["receipt_hash"]
        or type(extra) is not dict
    ):
        raise ValueError("atomic_split_inputs_invalid")
    assess_beta_coverage(frame, [], budget_exhausted=False)
    critic = {
        row["atom_id"]: row["split_questions"] for row in review["non_atomic_atoms"]
    }
    known = {row["atom_id"]: row for row in frame["atoms"]}
    if not critic or not set(critic).issubset(known) or set(extra) & set(critic):
        raise ValueError("atomic_split_targets_invalid")
    for atom_id, rows in extra.items():
        if atom_id not in known or type(rows) is not list or not 1 <= len(rows) <= 8:
            raise ValueError("atomic_split_extra_invalid")
        for row in rows:
            if (
                type(row) is not dict
                or set(row) != {"question", "closure_criterion"}
                or type(row["question"]) is not str
                or not 10 <= len(row["question"].strip()) <= 500
                or type(row["closure_criterion"]) is not str
                or not 15 <= len(row["closure_criterion"].strip()) <= 600
            ):
                raise ValueError("atomic_split_extra_invalid")
    next_id = (
        max(int(row["atom_id"].removeprefix("ATOM-")) for row in known.values()) + 1
    )
    replacement_map = {}
    additions = []
    for atom in frame["atoms"]:
        atom_id = atom["atom_id"]
        if atom_id in critic:
            proposed = [
                {
                    "question": question,
                    "closure_criterion": _PROVISIONAL_CLOSURE,
                }
                for question in critic[atom_id]
            ]
        elif atom_id in extra:
            proposed = extra[atom_id]
        else:
            continue
        replacement_map[atom_id] = []
        for row in proposed:
            new_id = f"ATOM-{next_id:03d}"
            next_id += 1
            additions.append(
                {
                    **atom,
                    "atom_id": new_id,
                    "question": row["question"].strip(),
                    "closure_criterion": row["closure_criterion"].strip(),
                }
            )
            replacement_map[atom_id].append(new_id)
    retained = [row for row in frame["atoms"] if row["atom_id"] not in replacement_map]
    questions = [row["question"].casefold() for row in [*retained, *additions]]
    if len(set(questions)) != len(questions):
        raise ValueError("atomic_split_question_duplicate")
    revised = with_receipt_hash(
        {
            **{key: value for key, value in frame.items() if key != "receipt_hash"},
            "atoms": [*retained, *additions],
        }
    )
    structural = assess_beta_coverage(revised, [], budget_exhausted=False)
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageAtomicSplit",
            "run_id": frame["run_id"],
            "parent_frame_receipt_hash": frame["receipt_hash"],
            "review_receipt_hash": review["receipt_hash"],
            "revised_frame_receipt_hash": revised["receipt_hash"],
            "extra_spec_sha256": sha256_json(extra),
            "critic_split_atom_ids": sorted(critic),
            "analyst_rewritten_atom_ids": sorted(extra),
            "old_to_new_atom_ids": replacement_map,
            "remaining_critic_omissions": [
                row["name"] for row in review["omitted_facets"]
            ],
            "remaining_overlaps": review["overlaps"],
            "remaining_unsupported_assumptions": review["unsupported_assumptions"],
            "remaining_empty_branches": structural["empty_branch_ids"],
            "remaining_rank_gaps": structural["required_importance_rank_gaps"],
            "critic_split_questions_preserved_exactly": True,
            "source_observations_transfer_allowed": False,
            "semantic_atomicity_verified": False,
            "source_calls": 0,
            "release_authorized": False,
        }
    )
    return revised, receipt
