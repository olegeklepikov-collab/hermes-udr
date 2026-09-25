"""Conservative publication identities and synthesis boundary for Academic beta."""

from __future__ import annotations

import re
from typing import Any, cast

from .beta_modes import verify_beta_mode_plan
from .canonical import verify_receipt_hash, with_receipt_hash

_ARXIV = re.compile(r"^https://arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5})v([1-9][0-9]*)$")
_OPENALEX = re.compile(r"^https://openalex\.org/W[0-9]+$")


def build_beta_academic_study_graph(
    *,
    plan: object,
    execution: object,
    portfolio: object,
    screening: object,
    fulltext: object | None,
    structure: object | None,
    analysis: object | None,
) -> dict[str, Any]:
    verified = verify_beta_mode_plan(plan)
    if verified["schema_version"] != 2 or verified["mode"] != "academic":
        raise ValueError("study_graph_plan_invalid")
    required = (
        (execution, "BetaAutomaticSourceExecution"),
        (portfolio, "BetaSourcePortfolio"),
        (screening, "BetaAcademicPreliminaryScreen"),
    )
    optional = (
        (fulltext, "BetaArxivFullTextRead"),
        (structure, "BetaAcademicPdfStructure"),
        (analysis, "BetaAcademicFullTextAnalysis"),
    )
    for value, contract in required + optional:
        if value is None:
            if (value, contract) in required:
                raise ValueError("study_graph_required_receipt_missing")
            continue
        if (
            type(value) is not dict
            or not verify_receipt_hash(value)
            or value.get("contract") != contract
            or value.get("run_id") != verified["run_id"]
            or value.get("plan_receipt_hash") != verified["receipt_hash"]
            or value.get("release_authorized") is not False
        ):
            raise ValueError("study_graph_receipt_invalid")
    execution = cast(dict[str, Any], execution)
    portfolio = cast(dict[str, Any], portfolio)
    screening = cast(dict[str, Any], screening)
    fulltext = cast(dict[str, Any] | None, fulltext)
    structure = cast(dict[str, Any] | None, structure)
    analysis = cast(dict[str, Any] | None, analysis)
    if (
        execution.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
        or screening.get("execution_receipt_hash") != execution["receipt_hash"]
        or screening.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
        or screening.get("protocol_receipt_hash")
        != verified["academic_protocol"]["protocol_ref"]
        or (
            fulltext is not None
            and fulltext.get("screening_receipt_hash") != screening["receipt_hash"]
        )
        or (
            structure is not None
            and (
                fulltext is None
                or structure.get("fulltext_receipt_hash") != fulltext["receipt_hash"]
            )
        )
        or (
            analysis is not None
            and (
                fulltext is None
                or analysis.get("fulltext_receipt_hash") != fulltext["receipt_hash"]
            )
        )
    ):
        raise ValueError("study_graph_edges_invalid")
    raw_records = screening.get("records")
    decisions = screening.get("decisions")
    if (
        type(raw_records) is not list
        or type(decisions) is not list
        or len(raw_records) != len(decisions)
    ):
        raise ValueError("study_graph_screening_invalid")
    decision_by_ref = {
        row.get("record_id"): row for row in decisions if type(row) is dict
    }
    if len(decision_by_ref) != len(decisions):
        raise ValueError("study_graph_decision_duplicate")
    nodes = []
    seen: set[str] = set()
    for row in raw_records:
        if type(row) is not dict:
            raise ValueError("study_graph_record_invalid")
        ref, provider, title = (
            row.get("record_id"),
            row.get("provider"),
            row.get("title"),
        )
        if (
            type(ref) is not str
            or type(title) is not str
            or ref in seen
            or ref not in decision_by_ref
        ):
            raise ValueError("study_graph_record_invalid")
        seen.add(ref)
        arxiv = _ARXIV.fullmatch(ref)
        if arxiv and provider == "arxiv":
            identity = "ARXIV-" + arxiv.group(1)
            version = int(arxiv.group(2))
            publication_kind = "versioned_preprint"
        elif _OPENALEX.fullmatch(ref) and provider == "openalex":
            identity = "OPENALEX-" + ref.rsplit("/", 1)[-1]
            version = None
            publication_kind = "indexed_work_metadata"
        else:
            raise ValueError("study_graph_record_identity_invalid")
        verdict = decision_by_ref[ref].get("verdict")
        if verdict not in {"include_candidate", "exclude", "uncertain"}:
            raise ValueError("study_graph_screening_invalid")
        nodes.append(
            {
                "record_id": ref,
                "identity_key": identity,
                "version": version,
                "publication_kind": publication_kind,
                "title": title,
                "screening_verdict": verdict,
                "fulltext_read": fulltext is not None
                and fulltext.get("record_id") == ref,
                "peer_review_status": "unverified_preprint"
                if arxiv
                else "not_established",
                "cross_provider_identity_verified": False,
            }
        )
    if set(decision_by_ref) != seen or (
        fulltext is not None and fulltext.get("record_id") not in seen
    ):
        raise ValueError("study_graph_record_set_invalid")
    grouped: dict[str, list[str]] = {}
    for node in nodes:
        grouped.setdefault(node["identity_key"], []).append(node["record_id"])
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaAcademicStudyGraph",
            "run_id": verified["run_id"],
            "mode": "academic",
            "plan_receipt_hash": verified["receipt_hash"],
            "execution_receipt_hash": execution["receipt_hash"],
            "portfolio_receipt_hash": portfolio["receipt_hash"],
            "screening_receipt_hash": screening["receipt_hash"],
            "fulltext_receipt_hash": fulltext["receipt_hash"] if fulltext else None,
            "structure_receipt_hash": structure["receipt_hash"] if structure else None,
            "analysis_receipt_hash": analysis["receipt_hash"] if analysis else None,
            "records": nodes,
            "identity_groups": [
                {"identity_key": key, "record_ids": refs, "same_study_verified": False}
                for key, refs in sorted(grouped.items())
            ],
            "identified_record_count": len(nodes),
            "candidate_for_fulltext_count": sum(
                node["screening_verdict"] == "include_candidate" for node in nodes
            ),
            "fulltext_read_count": int(fulltext is not None),
            "formally_included_study_count": 0,
            "independent_study_count_verified": 0,
            "risk_of_bias_status": "not_appraised",
            "quantitative_pooling_allowed": False,
            "cross_study_synthesis_allowed": False,
            "synthesis_reason": "no_appraised_independent_study_outcomes",
            "accepted_claim_count": 0,
            "mode_qualified": False,
            "release_authorized": False,
        }
    )
