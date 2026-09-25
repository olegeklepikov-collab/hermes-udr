"""Account for executed control searches without equating a plateau with completeness."""

from __future__ import annotations

from .canonical import verify_receipt_hash, with_receipt_hash


def assess_control_stop(
    content: dict,
    lineage: dict,
    plan: dict,
    observations: list[dict],
    *,
    resource_limit_reached: bool,
    limit_reasons: list[str] | None = None,
) -> dict:
    if (
        not all(verify_receipt_hash(row) for row in (content, lineage, plan))
        or lineage.get("content_receipt_hash") != content["receipt_hash"]
        or plan.get("frame_receipt_hash") != content["frame_receipt_hash"]
        or type(resource_limit_reached) is not bool
    ):
        raise ValueError("control_stop_inputs_unbound")
    queries = {row["control_id"]: row for row in plan["queries"]}
    if len(queries) != len(plan["queries"]) or not queries:
        raise ValueError("control_stop_plan_invalid")
    indexed = {}
    for observed in observations:
        key = observed.get("control_id")
        if (
            not verify_receipt_hash(observed)
            or key not in queries
            or key in indexed
            or observed.get("control_plan_receipt_hash") != plan["receipt_hash"]
            or observed.get("frame_receipt_hash") != content["frame_receipt_hash"]
        ):
            raise ValueError("control_stop_observation_unbound")
        indexed[key] = observed
    complete_ids = [
        key
        for key, row in indexed.items()
        if row.get("status") == "assessed"
        and row.get("all_retained_candidates_assessed") is True
        and row.get("raw_inputs_verified") is True
    ]
    failed_ids = sorted(set(queries) - set(complete_ids))
    candidate_count = sum(len(row.get("assessments", [])) for row in indexed.values())
    material = [
        item
        for row in indexed.values()
        for item in row.get("assessments", [])
        if item.get("novelty") == "adds_material"
    ]
    uncertainty = [
        item
        for row in indexed.values()
        for item in row.get("assessments", [])
        if item.get("novelty") == "uncertain"
    ]
    access_gaps = sum(row.get("unread_extraction_count", 0) for row in indexed.values())
    seeds_planned = {q["seed_id"] for q in queries.values()}
    seeds_completed = {queries[key]["seed_id"] for key in complete_ids}
    queried_atoms = {queries[key]["atom_id"] for key in complete_ids}
    expected_atoms = {answer["atom_id"] for answer in content["answers"]}
    if not queried_atoms.issubset(expected_atoms):
        raise ValueError("control_stop_atom_unknown")
    nonempty = any(indexed[key].get("assessments") for key in complete_ids)
    comparable = (
        not failed_ids
        and len(seeds_completed) >= 2
        and seeds_completed == seeds_planned
    )
    content_complete = (
        content.get("scope_complete") is True
        and content.get("atom_count") == len(expected_atoms)
        and not content.get("technical_gaps")
    )
    stable = (
        comparable
        and nonempty
        and not material
        and not uncertainty
        and content_complete
        and not access_gaps
    )
    if resource_limit_reached:
        decision = "resource_stop_with_residual"
    elif material:
        decision = "continue_new_material"
    elif failed_ids or uncertainty:
        decision = "continue_unresolved_controls"
    elif stable:
        decision = "bounded_control_stability"
    else:
        decision = "continue_insufficient_control_yield"
    residual = []
    if access_gaps:
        residual.append("source_access_gaps")
    if not content_complete:
        residual.append("base_content_scope_incomplete")
    if failed_ids:
        residual.append("control_execution_or_assessment_incomplete")
    if expected_atoms - queried_atoms:
        residual.append("not_all_atoms_control_sampled")
    if lineage["single_publisher_risk_atoms"]:
        residual.append("publisher_concentration_risk")
    if not lineage["verified_independent_primary_origins"]:
        residual.append("independent_primary_origins_unverified")
    if material:
        residual.append("new_material_requires_answer_revision")
    if uncertainty:
        residual.append("candidate_novelty_uncertain")
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaExecutedControlStopAssessment",
            "run_id": content["run_id"],
            "frame_receipt_hash": content["frame_receipt_hash"],
            "content_receipt_hash": content["receipt_hash"],
            "lineage_receipt_hash": lineage["receipt_hash"],
            "control_plan_receipt_hash": plan["receipt_hash"],
            "observation_receipt_hashes": [r["receipt_hash"] for r in observations],
            "planned_query_count": len(queries),
            "completed_query_count": len(complete_ids),
            "unresolved_control_ids": failed_ids,
            "distinct_completed_seed_count": len(seeds_completed),
            "provider_independence_verified": False,
            "control_sampled_atom_count": len(queried_atoms),
            "answer_atom_count": len(expected_atoms),
            "uncontrolled_atom_ids": sorted(expected_atoms - queried_atoms),
            "assessed_candidate_count": candidate_count,
            "unread_extraction_count": access_gaps,
            "new_material_candidate_count": len(material),
            "uncertain_candidate_count": len(uncertainty),
            "observed_control_stability": stable,
            "decision": decision,
            "resource_limit_reasons": limit_reasons or [],
            "residual_reasons": residual,
            "statistical_residual_upper_bound": None,
            "sampling_independence_established": False,
            "topic_saturation_verified": False,
            "partial_result_allowed": True,
            "release_authorized": False,
        }
    )
