"""Expose comparability differences without discarding qualitative evidence."""

from __future__ import annotations

from itertools import combinations

from .beta_source_lineage import document_identity
from .canonical import verify_receipt_hash, with_receipt_hash

_DIMENSIONS = ("population", "design", "outcome", "unit", "timepoint", "denominator")


def assess_academic_comparability(studies: list[dict]) -> dict:
    if not studies or len({s.get("study_id") for s in studies}) != len(studies):
        raise ValueError("academic_comparison_inventory_invalid")
    for study in studies:
        if not verify_receipt_hash(study):
            raise ValueError("academic_comparison_receipt_invalid")
        if study.get("read_scope") not in {
            "abstract_only",
            "partial_text",
            "full_text",
        }:
            raise ValueError("academic_comparison_read_scope_invalid")
        if any(
            study.get(key) is not None and type(study[key]) is not str
            for key in _DIMENSIONS
        ):
            raise ValueError("academic_comparison_profile_invalid")
    pairs = []
    for left, right in combinations(studies, 2):
        missing = [d for d in _DIMENSIONS if not left.get(d) or not right.get(d)]
        differences = [
            d
            for d in _DIMENSIONS
            if left.get(d) and right.get(d) and left[d] != right[d]
        ]
        same_work = (
            document_identity(left["url"])[0] == document_identity(right["url"])[0]
        )
        shared_data = bool(
            left.get("data_origin")
            and left.get("data_origin") == right.get("data_origin")
        )
        issues = []
        if same_work:
            issues.append("same_work_or_version")
        if shared_data:
            issues.append("shared_declared_data_origin")
        if missing:
            issues.append("comparison_dimensions_missing")
        if differences:
            issues.append("comparison_dimensions_differ")
        if left["read_scope"] != "full_text" or right["read_scope"] != "full_text":
            issues.append("full_text_not_read_for_both")
        pairs.append(
            {
                "left": left["study_id"],
                "right": right["study_id"],
                "missing_dimensions": missing,
                "different_dimensions": differences,
                "issues": issues,
                "declared_dimensions_match": not missing and not differences,
                "qualitative_comparison_allowed": True,
                "quantitative_pooling_allowed": False,
                "pooling_reason": "study_methods_outcome_extraction_and_covariance_not_verified",
                "independence_verified": False,
            }
        )
    return with_receipt_hash(
        {
            "contract": "AcademicComparabilityAssessment",
            "study_receipt_hashes": [s["receipt_hash"] for s in studies],
            "pairs": pairs,
            "profile_basis": "submitted_descriptions_not_independent_validation",
            "release_authorized": False,
        }
    )
