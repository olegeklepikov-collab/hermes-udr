"""Bind one Deep assertion to an exact fragment and its work-level origin.

This map records a *candidate*, not an accepted fact. A second model call on
the same excerpt cannot create independent primary support.
"""

from __future__ import annotations

import hashlib
from typing import Any, cast

from .beta_modes import verify_beta_mode_plan
from .canonical import verify_receipt_hash, with_receipt_hash


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_beta_deep_fact_map(
    *,
    plan: object,
    execution: object,
    origin_graph: object,
    article: object,
    publisher: object,
    screen: object,
    candidate: object,
    semantic_check: object,
    excerpt: str,
) -> dict[str, Any]:
    """Fail closed unless every assertion edge reaches retained exact text."""
    verified = verify_beta_mode_plan(plan)
    receipts = (
        execution,
        origin_graph,
        article,
        publisher,
        screen,
        candidate,
        semantic_check,
    )
    if (
        verified["schema_version"] != 2
        or verified["mode"] != "deep"
        or type(excerpt) is not str
        or not all(type(row) is dict and verify_receipt_hash(row) for row in receipts)
    ):
        raise ValueError("fact_map_input_invalid")
    execution = cast(dict[str, Any], execution)
    origin_graph = cast(dict[str, Any], origin_graph)
    article = cast(dict[str, Any], article)
    publisher = cast(dict[str, Any], publisher)
    screen = cast(dict[str, Any], screen)
    candidate = cast(dict[str, Any], candidate)
    semantic_check = cast(dict[str, Any], semantic_check)
    run_id = verified["run_id"]
    plan_hash = verified["receipt_hash"]
    expected = (
        (execution, "BetaAutomaticSourceExecution"),
        (origin_graph, "BetaWorkOriginGraph"),
        (article, "BetaOpenAlexArticleTextAcquisition"),
        (publisher, "BetaPublisherRawAttestation"),
        (screen, "BetaOpenAlexArticleScreen"),
        (candidate, "BetaModelCandidate"),
        (semantic_check, "BetaSemanticModelCheck"),
    )
    if any(
        row.get("contract") != contract
        or row.get("run_id") != run_id
        or row.get("plan_receipt_hash") != plan_hash
        or row.get("release_authorized") is not False
        for row, contract in expected
    ):
        raise ValueError("fact_map_receipts_not_bound")
    if (
        origin_graph.get("execution_receipt_hash") != execution["receipt_hash"]
        or origin_graph.get("work_id") != article.get("work_id")
        or origin_graph.get("doi") != article.get("doi")
        or origin_graph.get("independent_second_work_verified") is not False
        or origin_graph.get("independent_primary_work_count_verified") != 0
        or publisher.get("article_receipt_hash") != article["receipt_hash"]
        or publisher.get("status") != "publisher_html_candidate"
        or publisher.get("publisher_extracted_text_overlap_verified") is not True
        or screen.get("article_receipt_hash") != article["receipt_hash"]
        or screen.get("candidate_receipt_hash") != candidate["receipt_hash"]
        or candidate.get("source_id") != article.get("source_id")
        or candidate.get("source_text_sha256") != _sha(excerpt)
        or candidate.get("exact_quote_verified") is not True
        or semantic_check.get("candidate_receipt_hash") != candidate["receipt_hash"]
        or semantic_check.get("screen_receipt_hash") != screen["receipt_hash"]
        or semantic_check.get("publisher_receipt_hash") != publisher["receipt_hash"]
        or semantic_check.get("execution_receipt_hash") != execution["receipt_hash"]
        or semantic_check.get("source_scope") != "excerpt_first_12000"
        or semantic_check.get("accepted_claim_count") != 0
        or semantic_check.get("independent_primary_support_verified") is not False
    ):
        raise ValueError("fact_map_edges_not_bound")
    quote = candidate.get("quote")
    start = candidate.get("quote_char_start")
    end = candidate.get("quote_char_end")
    claim = candidate.get("claim")
    if (
        type(quote) is not str
        or not quote
        or type(claim) is not str
        or not claim
        or type(start) is not int
        or type(end) is not int
        or start < 0
        or end != start + len(quote)
        or excerpt[start:end] != quote
    ):
        raise ValueError("fact_map_exact_fragment_invalid")
    verdict = semantic_check.get("verdict")
    if verdict not in {"supported", "overstated", "contradicted", "unclear"}:
        raise ValueError("fact_map_verdict_invalid")
    fragment_ref = (
        "FRG-"
        + _sha(article["source_id"] + "\0" + str(start) + "\0" + quote)[:16].upper()
    )
    assertion_ref = "CLM-" + _sha(claim)[:16].upper()
    status = (
        "provisional"
        if verdict == "supported"
        else "rejected"
        if verdict in {"overstated", "contradicted"}
        else "unknown"
    )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaDeepFactMap",
            "run_id": run_id,
            "mode": "deep",
            "plan_receipt_hash": plan_hash,
            "execution_receipt_hash": execution["receipt_hash"],
            "origin_graph_receipt_hash": origin_graph["receipt_hash"],
            "semantic_check_receipt_hash": semantic_check["receipt_hash"],
            "assertions": [
                {
                    "assertion_ref": assertion_ref,
                    "text": claim,
                    "status": status,
                    "semantic_verdict": verdict,
                    "fragment_ref": fragment_ref,
                    "source_id": article["source_id"],
                    "work_origin_ref": origin_graph["work_origin_ref"],
                    "quote": quote,
                    "quote_char_start": start,
                    "quote_char_end": end,
                    "excerpt_sha256": _sha(excerpt),
                    "publisher_receipt_hash": publisher["receipt_hash"],
                }
            ],
            "independent_primary_work_count_verified": 0,
            "accepted_fact_count": 0,
            "provisional_fact_count": int(status == "provisional"),
            "mode_qualified": False,
            "release_authorized": False,
        }
    )
