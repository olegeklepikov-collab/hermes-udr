"""Honest leave-one-cited-source sensitivity for provisional Ultra rivals."""

from __future__ import annotations

import hashlib
from typing import Any, cast

from .beta_modes import verify_beta_mode_plan
from .canonical import verify_receipt_hash, with_receipt_hash


def assess_beta_ultra_sensitivity(
    *,
    plan: object,
    execution: object,
    portfolio: object,
    challenge: object,
    records: object,
) -> dict[str, Any]:
    verified = verify_beta_mode_plan(plan)
    if verified["mode"] != "ultra" or verified["schema_version"] != 2:
        raise ValueError("ultra_sensitivity_plan_invalid")
    inputs = (
        (execution, "BetaAutomaticSourceExecution"),
        (portfolio, "BetaSourcePortfolio"),
        (challenge, "BetaUltraRivalChallenge"),
    )
    if any(
        type(value) is not dict
        or not verify_receipt_hash(value)
        or value.get("contract") != contract
        or value.get("run_id") != verified["run_id"]
        or value.get("plan_receipt_hash") != verified["receipt_hash"]
        or value.get("release_authorized") is not False
        for value, contract in inputs
    ):
        raise ValueError("ultra_sensitivity_receipt_invalid")
    execution = cast(dict[str, Any], execution)
    portfolio = cast(dict[str, Any], portfolio)
    challenge = cast(dict[str, Any], challenge)
    if (
        execution.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
        or challenge.get("execution_receipt_hash") != execution["receipt_hash"]
        or challenge.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
        or challenge.get("rival_count") != len(verified["rival_hypotheses"])
        or type(records) is not list
    ):
        raise ValueError("ultra_sensitivity_binding_invalid")
    source_by_ref: dict[str, dict[str, Any]] = {}
    for row in records:
        if (
            type(row) is not dict
            or type(row.get("record_id")) is not str
            or type(row.get("capture_receipt_hash")) is not str
            or row["record_id"] in source_by_ref
        ):
            raise ValueError("ultra_sensitivity_sources_invalid")
        source_by_ref[row["record_id"]] = row
    if not source_by_ref:
        raise ValueError("ultra_sensitivity_sources_missing")
    judgments = challenge.get("judgments")
    if type(judgments) is not list or len(judgments) != len(
        verified["rival_hypotheses"]
    ):
        raise ValueError("ultra_sensitivity_judgments_invalid")
    outcomes = []
    seen: set[int] = set()
    for row in judgments:
        if type(row) is not dict:
            raise ValueError("ultra_sensitivity_judgments_invalid")
        index = row.get("rival_index")
        verdict = row.get("verdict")
        source_ref = row.get("source_ref")
        if (
            type(index) is not int
            or not 0 <= index < len(judgments)
            or index in seen
            or verdict not in {"supported", "contradicted", "unclear"}
        ):
            raise ValueError("ultra_sensitivity_judgments_invalid")
        seen.add(index)
        if verdict == "unclear":
            if source_ref is not None:
                raise ValueError("ultra_sensitivity_unclear_source_invalid")
            changed = "remains_unresolved"
            origin_ref = None
        else:
            if type(source_ref) is not str or source_ref not in source_by_ref:
                raise ValueError("ultra_sensitivity_citation_invalid")
            changed = "requires_reanalysis_without_cited_source"
            origin_ref = (
                "ORIGIN-" + hashlib.sha256(source_ref.encode()).hexdigest()[:16].upper()
            )
        outcomes.append(
            {
                "rival_index": index,
                "hypothesis": verified["rival_hypotheses"][index],
                "baseline_verdict": verdict,
                "cited_source_ref": source_ref,
                "cited_origin_ref": origin_ref,
                "leave_one_cited_source_out": changed,
                "robustness_verified": False,
            }
        )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaUltraSensitivity",
            "run_id": verified["run_id"],
            "mode": "ultra",
            "plan_receipt_hash": verified["receipt_hash"],
            "execution_receipt_hash": execution["receipt_hash"],
            "portfolio_receipt_hash": portfolio["receipt_hash"],
            "challenge_receipt_hash": challenge["receipt_hash"],
            "source_record_count": len(source_by_ref),
            "rivals": sorted(outcomes, key=lambda row: row["rival_index"]),
            "single_citation_dependent_count": sum(
                row["leave_one_cited_source_out"]
                == "requires_reanalysis_without_cited_source"
                for row in outcomes
            ),
            "independent_primary_work_count_verified": 0,
            "robustness_verified": False,
            "accepted_claim_count": 0,
            "mode_qualified": False,
            "release_authorized": False,
        }
    )
