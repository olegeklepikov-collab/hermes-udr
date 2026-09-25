"""Separate executable discovery routes from scientific source requirements."""

from __future__ import annotations

from typing import Any, cast

from .beta_coverage import assess_beta_coverage
from .canonical import with_receipt_hash

KNOWN_FAMILIES = frozenset(
    {"web", "scholarly_index", "preprint_archive", "official", "dataset"}
)
_METADATA_ONLY_FAMILIES = frozenset({"dataset"})


def assess_instrument_portfolio(
    frame: object, *, executable_families: object
) -> dict[str, Any]:
    assess_beta_coverage(frame, [], budget_exhausted=False)
    if type(executable_families) not in (set, frozenset):
        raise ValueError("instrument_portfolio_invalid")
    family_set = cast(set[str] | frozenset[str], executable_families)
    if (
        not family_set
        or any(type(value) is not str for value in family_set)
        or not family_set.issubset(KNOWN_FAMILIES)
    ):
        raise ValueError("instrument_portfolio_invalid")
    assert type(frame) is dict
    available = frozenset(family_set)
    atom_rows = []
    for atom in frame["atoms"]:
        required = frozenset(atom["required_families"])
        executable = sorted(required & available)
        unavailable = sorted(required - available)
        atom_rows.append(
            {
                "atom_id": atom["atom_id"],
                "required_families": sorted(required),
                "executable_required_families": executable,
                "unavailable_required_families": unavailable,
                "has_any_executable_route": bool(executable),
                "all_required_routes_executable": not unavailable,
                "requires_dataset_content_not_supplied": bool(
                    required & _METADATA_ONLY_FAMILIES
                ),
                "source_absence_in_domain_inferred": False,
            }
        )
    unavailable_counts = {
        family: sum(family in row["unavailable_required_families"] for row in atom_rows)
        for family in sorted(KNOWN_FAMILIES - available)
    }
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageInstrumentPortfolio",
            "run_id": frame["run_id"],
            "frame_receipt_hash": frame["receipt_hash"],
            "known_families": sorted(KNOWN_FAMILIES),
            "executable_families": sorted(available),
            "metadata_only_families": sorted(available & _METADATA_ONLY_FAMILIES),
            "unavailable_family_atom_counts": unavailable_counts,
            "atom_count": len(atom_rows),
            "atoms_with_all_required_routes": sum(
                row["all_required_routes_executable"] for row in atom_rows
            ),
            "atoms_with_any_executable_route": sum(
                row["has_any_executable_route"] for row in atom_rows
            ),
            "atoms_requiring_unread_dataset_content": sum(
                row["requires_dataset_content_not_supplied"] for row in atom_rows
            ),
            "atoms": atom_rows,
            "research_can_continue_on_executable_routes": any(
                row["has_any_executable_route"] for row in atom_rows
            ),
            "required_family_unavailable_is_not_evidence_absence": True,
            "topic_completeness_verified": False,
            "saturation_verified": False,
            "partial_result_allowed": True,
            "release_authorized": False,
        }
    )
