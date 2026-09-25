"""Calibrated thematic saturation decision over atomic coverage receipts."""

from __future__ import annotations

import re
from typing import Any

from .canonical import verify_receipt_hash, with_receipt_hash

_HASH = re.compile(r"^[0-9a-f]{64}$")


def assess_thematic_saturation(
    progress: object,
    independence: object,
    calibration: object | None = None,
) -> dict[str, Any]:
    if (
        type(progress) is not dict
        or progress.get("contract") != "BetaCoverageProgressAssessment"
        or not verify_receipt_hash(progress)
        or type(independence) is not dict
        or independence.get("contract") != "BetaEvidenceIndependenceAssessment"
        or not verify_receipt_hash(independence)
        or independence.get("frame_receipt_hash") != progress.get("frame_receipt_hash")
        or independence.get("progress_receipt_hash") != progress.get("receipt_hash")
    ):
        raise ValueError("saturation_inputs_invalid")
    calibrated = False
    calibration_hash = None
    residual_upper_bound = None
    holdout_count = 0
    calibration_issues = []
    if calibration is not None:
        if (
            type(calibration) is not dict
            or set(calibration)
            != {
                "schema_version",
                "contract",
                "frame_receipt_hash",
                "review_receipt_hash",
                "holdout_atom_ids",
                "estimated_material_residual_upper_bound",
                "control_cases_passed",
                "independent_review_verified",
                "receipt_hash",
            }
            or calibration.get("contract") != "BetaSaturationCalibration"
            or not verify_receipt_hash(calibration)
            or calibration.get("frame_receipt_hash") != progress["frame_receipt_hash"]
            or type(calibration.get("review_receipt_hash")) is not str
            or not _HASH.fullmatch(calibration["review_receipt_hash"])
            or type(calibration.get("holdout_atom_ids")) is not list
            or any(type(value) is not str for value in calibration["holdout_atom_ids"])
            or type(calibration.get("estimated_material_residual_upper_bound"))
            not in (int, float)
            or not 0 <= calibration["estimated_material_residual_upper_bound"] <= 1
            or type(calibration.get("control_cases_passed")) is not int
            or calibration["control_cases_passed"] < 1
            or calibration.get("independent_review_verified") is not True
        ):
            raise ValueError("saturation_calibration_invalid")
        calibration_hash = calibration["receipt_hash"]
        residual_upper_bound = float(
            calibration["estimated_material_residual_upper_bound"]
        )
        holdout_count = len(calibration["holdout_atom_ids"])
        atom_ids = {row["atom_id"] for row in progress.get("atoms", [])}
        holdout_ids = calibration["holdout_atom_ids"]
        if not holdout_ids:
            calibration_issues.append("holdout_sample_empty")
        if len(set(holdout_ids)) != len(holdout_ids):
            calibration_issues.append("holdout_sample_duplicate")
        if set(holdout_ids) - atom_ids:
            calibration_issues.append("holdout_atoms_outside_frame")
        calibrated = not calibration_issues
    novelty = progress.get("novelty_by_batch")
    repeated_plateau = (
        type(novelty) is list
        and len(novelty) >= 3
        and all(
            row.get("novelty_assessable") is True
            and row.get("new_relevant_origins")
            == row.get("new_material_claims")
            == row.get("new_gap_classes")
            == row.get("new_latent_signals")
            == 0
            for row in novelty[-2:]
        )
    )
    atom_count = progress.get("atom_count")
    all_atoms = (
        type(atom_count) is int
        and atom_count > 0
        and type(progress.get("evidence_floor_count")) is int
        and progress["evidence_floor_count"] == atom_count
    )
    no_frame_gap = (
        progress.get("frame_expansion_required") is False
        and not progress.get("required_importance_rank_gaps")
        and not progress.get("required_space_gaps")
        and not progress.get("empty_branch_ids")
        and not progress.get("discovery_signals")
    )
    independence_met = independence.get("all_atoms_meet_independence") is True
    residual_ok = (
        calibrated and residual_upper_bound is not None and residual_upper_bound <= 0.05
    )
    saturated = bool(
        all_atoms
        and no_frame_gap
        and independence_met
        and repeated_plateau
        and residual_ok
    )
    blockers = []
    for condition, code in (
        (all_atoms, "atomic_evidence_floor_incomplete"),
        (no_frame_gap, "frame_or_discovery_gaps_open"),
        (independence_met, "independent_origins_incomplete"),
        (repeated_plateau, "repeated_novelty_plateau_not_observed"),
        (calibrated, "independent_residual_calibration_missing"),
        (residual_ok, "estimated_material_residual_too_high"),
    ):
        if not condition and code not in blockers:
            blockers.append(code)
    if calibrated:
        blockers.append("executed_calibration_evidence_not_bound")
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaThematicSaturationAssessment",
            "run_id": progress["run_id"],
            "frame_receipt_hash": progress["frame_receipt_hash"],
            "progress_receipt_hash": progress["receipt_hash"],
            "independence_receipt_hash": independence["receipt_hash"],
            "calibration_receipt_hash": calibration_hash,
            "calibration_issues": calibration_issues,
            "holdout_atom_count": holdout_count,
            "estimated_material_residual_upper_bound": residual_upper_bound,
            "atomic_evidence_floor_complete": all_atoms,
            "frame_and_discovery_gaps_closed": no_frame_gap,
            "independent_origins_complete": independence_met,
            "repeated_novelty_plateau_observed": repeated_plateau,
            "calibration_declaration_structurally_valid": calibrated,
            "independent_residual_calibration_verified": False,
            "conditional_saturation_criteria_met": saturated,
            "saturation_verified": False,
            "topic_completeness_verified": False,
            "decision": "saturation_candidate_requires_executed_controls"
            if saturated
            else "partial"
            if progress.get("status") == "partial_budget"
            else "continue",
            "blockers": blockers,
            "partial_result_allowed": True,
            "release_authorized": False,
        }
    )
