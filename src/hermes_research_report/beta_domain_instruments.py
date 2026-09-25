"""Calibrate mandatory discovery families from domain-specific evidence bases."""

from __future__ import annotations

from typing import Any

from .beta_coverage import assess_beta_coverage
from .canonical import verify_receipt_hash, with_receipt_hash

_WEB_BASES = {
    "web_primary",
    "practice",
    "expert",
    "conceptual",
    "case",
    "direct_observation",
}


def calibrate_domain_instruments(
    frame: object, decomposition: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        type(frame) is not dict
        or type(decomposition) is not dict
        or not verify_receipt_hash(frame)
        or not verify_receipt_hash(decomposition)
        or decomposition.get("contract") != "BetaDomainDecomposition"
        or frame.get("decomposition_receipt_hash") != decomposition["receipt_hash"]
        or frame.get("question") != decomposition.get("question")
        or frame.get("profile") != decomposition.get("profile")
    ):
        raise ValueError("domain_instrument_inputs_invalid")
    assess_beta_coverage(frame, [], budget_exhausted=False)
    aspects = {row["name"].casefold(): row for row in decomposition["aspects"]}
    facet_to_aspect = {}
    seen_labels: set[str] = set()
    for facet_id in frame["facets"]:
        label = frame["facet_labels"][facet_id].casefold()
        if label not in aspects or label in seen_labels:
            raise ValueError("domain_instrument_facet_unmapped")
        facet_to_aspect[facet_id] = aspects[label]
        seen_labels.add(label)
    if len(facet_to_aspect) != len(aspects):
        raise ValueError("domain_instrument_facet_unmapped")
    revised_atoms = []
    decisions = []
    for atom in frame["atoms"]:
        aspect = facet_to_aspect[atom["facet_id"]]
        bases = set(aspect["evidence_bases"])
        minimal = set()
        if bases & _WEB_BASES:
            minimal.add("web")
        if "official" in bases:
            minimal.add("official")
        if "scholarly" in bases:
            minimal.add("scholarly_index")
        if "dataset" in bases:
            minimal.add("dataset")
        if not minimal:
            raise ValueError("domain_instrument_no_discovery_basis")
        prior = set(atom["required_families"])
        empirical_comparison = aspect["question_type"] in {
            "comparative",
            "causal",
            "forecast",
        }
        unresolved_academic = (
            aspect["academic_role_effective"] == "unresolved_basis_conflict"
        )
        optional_challenges = (
            sorted({"scholarly_index", "dataset"} - minimal)
            if empirical_comparison
            else ["scholarly_index"]
            if unresolved_academic and "scholarly_index" not in minimal
            else []
        )
        revised_atoms.append({**atom, "required_families": sorted(minimal)})
        decisions.append(
            {
                "atom_id": atom["atom_id"],
                "aspect_id": aspect["aspect_id"],
                "question_type": aspect["question_type"],
                "academic_role_model_proposed": aspect["academic_role"],
                "academic_role_effective": aspect["academic_role_effective"],
                "evidence_bases": sorted(bases),
                "prior_required_families": sorted(prior),
                "calibrated_required_families": sorted(minimal),
                "removed_unjustified_families": sorted(prior - minimal),
                "added_from_explicit_basis": sorted(minimal - prior),
                "empirical_inference_still_needs_source_review": empirical_comparison,
                "academic_route_unresolved": unresolved_academic,
                "web_monoculture_risk": minimal == {"web"}
                and (empirical_comparison or unresolved_academic),
                "optional_challenge_families_not_mandatory": optional_challenges,
                "web_route_confers_no_source_authority": "web" in minimal,
            }
        )
    body = {key: value for key, value in frame.items() if key != "receipt_hash"}
    body["atoms"] = revised_atoms
    calibrated = with_receipt_hash(body)
    structural = assess_beta_coverage(calibrated, [], budget_exhausted=False)
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaDomainInstrumentCalibration",
            "run_id": frame["run_id"],
            "prior_frame_receipt_hash": frame["receipt_hash"],
            "decomposition_receipt_hash": decomposition["receipt_hash"],
            "calibrated_frame_receipt_hash": calibrated["receipt_hash"],
            "decisions": decisions,
            "atom_count": len(decisions),
            "removed_family_requirement_count": sum(
                len(row["removed_unjustified_families"]) for row in decisions
            ),
            "added_family_requirement_count": sum(
                len(row["added_from_explicit_basis"]) for row in decisions
            ),
            "academic_route_unresolved_atom_count": sum(
                row["academic_route_unresolved"] for row in decisions
            ),
            "web_monoculture_risk_atom_count": sum(
                row["web_monoculture_risk"] for row in decisions
            ),
            "required_importance_rank_gaps": structural[
                "required_importance_rank_gaps"
            ],
            "empty_branch_ids": structural["empty_branch_ids"],
            "academic_family_not_forced_by_profile": True,
            "calibration_is_provisional_not_source_truth": True,
            "source_calls": 0,
            "release_authorized": False,
        }
    )
    return calibrated, receipt
