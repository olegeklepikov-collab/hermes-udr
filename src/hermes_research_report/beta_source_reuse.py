"""Suggest other open atoms for one retained text; never infer source support."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any

from .canonical import verify_receipt_hash, with_receipt_hash

_WORDS = re.compile(r"[A-Za-z][A-Za-z0-9-]{4,}")
_STOP = {
    "about",
    "across",
    "against",
    "before",
    "between",
    "better",
    "changes",
    "could",
    "digital",
    "during",
    "early",
    "effect",
    "effects",
    "evidence",
    "family",
    "from",
    "higher",
    "improve",
    "later",
    "makes",
    "methods",
    "needs",
    "observed",
    "often",
    "other",
    "physical",
    "product",
    "products",
    "question",
    "rather",
    "results",
    "should",
    "their",
    "there",
    "these",
    "using",
    "where",
    "which",
    "within",
    "would",
}


def _terms(value: str) -> set[str]:
    return {
        word.lower().strip("-")
        for word in _WORDS.findall(value)
        if word.lower().strip("-") not in _STOP
    }


def suggest_source_reuse(
    *,
    frame: object,
    source_id: str,
    title: str,
    text: str,
    screened_atom_id: str,
    screen: object,
    limit: int = 6,
) -> dict[str, Any]:
    if (
        type(frame) is not dict
        or not verify_receipt_hash(frame)
        or type(screen) is not dict
        or not verify_receipt_hash(screen)
        or screen.get("source_id") != source_id
        or screen.get("atom_id") != screened_atom_id
        or screen.get("frame_receipt_hash") != frame["receipt_hash"]
        or screen.get("source_text_sha256") != hashlib.sha256(text.encode()).hexdigest()
        or type(source_id) is not str
        or type(title) is not str
        or type(text) is not str
        or not 40 <= len(text) <= 50_000
        or type(limit) is not int
        or not 1 <= limit <= 10
    ):
        raise ValueError("source_reuse_inputs_invalid")
    question_terms = {
        atom["atom_id"]: _terms(atom["question"]) for atom in frame["atoms"]
    }
    frequencies: Counter[str] = Counter(
        term for terms in question_terms.values() for term in terms
    )
    source_terms = _terms(text)
    lead_terms = _terms(text[:4_000])
    title_terms = _terms(title)
    count = len(question_terms)
    ranked = []
    for atom in frame["atoms"]:
        atom_id = atom["atom_id"]
        matches = question_terms[atom_id] & source_terms
        if len(matches) < 2:
            continue
        if (
            not any(
                term in title_terms
                or term in lead_terms
                and frequencies[term] <= max(2, count // 6)
                for term in matches
            )
            and sum(
                term not in lead_terms and frequencies[term] <= 2 for term in matches
            )
            < 2
        ):
            continue
        weights = {
            term: math.log((count + 1) / (frequencies[term] + 1))
            for term in question_terms[atom_id]
        }
        total_weight = sum(weights.values())
        matched_weight = sum(
            weights[term]
            * (3 if term in title_terms else 1.5 if term in lead_terms else 0.2)
            for term in matches
        )
        weighted = matched_weight / total_weight if total_weight else 0.0
        ranked.append(
            {
                "atom_id": atom_id,
                "matched_terms": sorted(matches),
                "matched_title_terms": sorted(matches & title_terms),
                "matched_late_terms": sorted(matches - lead_terms),
                "lexical_score": round(weighted, 6),
                "text_scope": "full_retained_text_with_lead_weighting",
                "previously_screened_for_this_atom": atom_id == screened_atom_id,
                "semantic_screen_required": True,
                "source_support_verified": False,
            }
        )
    ranked.sort(
        key=lambda row: (
            -row["lexical_score"],
            -len(row["matched_title_terms"]),
            row["atom_id"],
        )
    )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCrossAtomReuseSuggestions",
            "run_id": frame["run_id"],
            "frame_receipt_hash": frame["receipt_hash"],
            "screen_receipt_hash": screen["receipt_hash"],
            "source_id": source_id,
            "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "screened_atom_id": screened_atom_id,
            "suggestions": ranked[:limit],
            "unsuggested_atom_count": count - len(ranked[:limit]),
            "method": "rare_term_recall_full_text_lead_weighted_v2",
            "late_text_terms_considered": True,
            "semantic_relevance_verified": False,
            "claim_support_verified": False,
            "release_authorized": False,
        }
    )
