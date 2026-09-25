"""Observed atomic coverage and novelty; not a self-certified saturation claim."""

from __future__ import annotations

import re
from typing import Any

from .canonical import verify_receipt_hash, with_receipt_hash

_ID = re.compile(r"^[A-Z][A-Z0-9-]{2,63}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_FAMILIES = {"web", "scholarly_index", "preprint_archive", "official", "dataset"}
_POLARITIES = {"neutral", "confirming", "refuting"}
_RELEVANCE = {"relevant", "irrelevant", "uncertain"}
_READ_SCOPE = {"none", "metadata", "abstract", "partial_text", "full_text"}
_RESULT_STATUS = {"hit", "empty", "error", "refused"}
_GAP_KINDS = {
    "search_absence",
    "access_barrier",
    "evidence_absence",
    "conceptual_conflict",
    "method_limit",
    "source_monoculture",
}
_SPACES = {"positive", "negative", "latent"}
_IMPORTANCE = {"central", "peripheral", "marginal"}
_DISCOVERY_KINDS = {
    "unanticipated_dimension",
    "hidden_assumption",
    "anomalous_result",
    "unmapped_contradiction",
}


def _string(value: object, code: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(code)
    return value.strip()


def _terms(value: object, allowed: set[str], code: str) -> list[str]:
    if (
        type(value) is not list
        or not value
        or any(type(item) is not str or item not in allowed for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(code)
    return list(value)


def assess_beta_coverage(
    frame: object,
    observations: object,
    *,
    budget_exhausted: bool,
    discovery_signals: object | None = None,
) -> dict[str, Any]:
    """Measure observable coverage; a plateau is not proof of field saturation."""
    if (
        type(frame) is not dict
        or set(frame) - {"decomposition_receipt_hash"}
        != {
            "schema_version",
            "contract",
            "run_id",
            "profile",
            "question",
            "scope",
            "sealed_before_search",
            "facets",
            "facet_labels",
            "facet_definitions",
            "branches",
            "atoms",
            "receipt_hash",
        }
        or frame.get("contract") != "BetaCoverageFrame"
        or not verify_receipt_hash(frame)
        or frame.get("schema_version") != 1
        or type(observations) is not list
        or type(budget_exhausted) is not bool
        or (discovery_signals is not None and type(discovery_signals) is not list)
    ):
        raise ValueError("coverage_inputs_invalid")
    signals = [] if discovery_signals is None else discovery_signals
    profile = frame.get("profile")
    if (
        profile not in {"search", "deep", "ultra", "academic"}
        or type(frame.get("run_id")) is not str
        or not _ID.fullmatch(frame["run_id"])
        or frame.get("sealed_before_search") is not True
    ):
        raise ValueError("coverage_profile_invalid")
    _string(frame["question"], "coverage_question_invalid")
    if "decomposition_receipt_hash" in frame and (
        type(frame["decomposition_receipt_hash"]) is not str
        or not _HASH.fullmatch(frame["decomposition_receipt_hash"])
    ):
        raise ValueError("coverage_decomposition_hash_invalid")
    _string(frame["scope"], "coverage_scope_invalid")
    atoms = frame.get("atoms")
    facets = frame.get("facets")
    facet_labels = frame.get("facet_labels")
    facet_definitions = frame.get("facet_definitions")
    branches = frame.get("branches")
    if (
        type(atoms) is not list
        or not atoms
        or type(facets) is not list
        or not facets
        or type(facet_labels) is not dict
        or type(facet_definitions) is not dict
        or type(branches) is not list
        or not branches
    ):
        raise ValueError("coverage_frame_invalid")
    facet_ids = [_string(value, "coverage_facet_invalid") for value in facets]
    if len(set(facet_ids)) != len(facet_ids) or any(
        not _ID.fullmatch(value) for value in facet_ids
    ):
        raise ValueError("coverage_facet_invalid")
    if set(facet_labels) != set(facet_ids) or set(facet_definitions) != set(facet_ids):
        raise ValueError("coverage_facet_invalid")
    for value in [*facet_labels.values(), *facet_definitions.values()]:
        _string(value, "coverage_facet_invalid")
    branch_to_facet: dict[str, str] = {}
    for raw in branches:
        if type(raw) is not dict or set(raw) != {
            "branch_id",
            "facet_id",
            "question",
        }:
            raise ValueError("coverage_branch_invalid")
        branch_id = _string(raw["branch_id"], "coverage_branch_invalid")
        facet_id = _string(raw["facet_id"], "coverage_branch_invalid")
        _string(raw["question"], "coverage_branch_invalid")
        if (
            not _ID.fullmatch(branch_id)
            or branch_id in branch_to_facet
            or facet_id not in facet_ids
        ):
            raise ValueError("coverage_branch_invalid")
        branch_to_facet[branch_id] = facet_id
    if set(facet_ids) != set(branch_to_facet.values()):
        raise ValueError("coverage_empty_facet")
    by_atom: dict[str, dict[str, Any]] = {}
    for raw in atoms:
        if type(raw) is not dict or set(raw) != {
            "atom_id",
            "facet_id",
            "branch_id",
            "question",
            "closure_criterion",
            "importance",
            "space",
            "required_families",
            "required_polarities",
            "required_independent_origins",
        }:
            raise ValueError("coverage_atom_invalid")
        atom_id = _string(raw["atom_id"], "coverage_atom_invalid")
        facet_id = _string(raw["facet_id"], "coverage_atom_invalid")
        branch_id = _string(raw["branch_id"], "coverage_atom_invalid")
        minimum = raw["required_independent_origins"]
        if (
            not _ID.fullmatch(atom_id)
            or atom_id in by_atom
            or facet_id not in facet_ids
            or branch_to_facet.get(branch_id) != facet_id
            or raw["importance"] not in _IMPORTANCE
            or raw["space"] not in _SPACES
            or type(minimum) is not int
            or minimum < 1
        ):
            raise ValueError("coverage_atom_invalid")
        by_atom[atom_id] = {
            "atom_id": atom_id,
            "facet_id": facet_id,
            "branch_id": branch_id,
            "question": _string(raw["question"], "coverage_atom_invalid"),
            "closure_criterion": _string(
                raw["closure_criterion"], "coverage_atom_invalid"
            ),
            "importance": raw["importance"],
            "space": raw["space"],
            "required_families": _terms(
                raw["required_families"], _FAMILIES, "coverage_atom_invalid"
            ),
            "required_polarities": _terms(
                raw["required_polarities"], _POLARITIES, "coverage_atom_invalid"
            ),
            "required_independent_origins": minimum,
        }
    empty_branches = sorted(
        set(branch_to_facet) - {atom["branch_id"] for atom in by_atom.values()}
    )
    rank_gaps = (
        sorted(_IMPORTANCE - {atom["importance"] for atom in by_atom.values()})
        if profile == "ultra"
        else []
    )
    space_gaps = (
        sorted({"negative", "latent"} - {atom["space"] for atom in by_atom.values()})
        if profile == "ultra"
        else []
    )
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in by_atom}
    batches: dict[int, list[dict[str, Any]]] = {}
    seen_query_sources: set[tuple[str, str, str | None]] = set()
    for raw in observations:
        if type(raw) is not dict or set(raw) != {
            "atom_id",
            "batch",
            "query_receipt_hash",
            "source_family",
            "polarity",
            "source_ref",
            "origin_ref",
            "relevance",
            "read_scope",
            "material_claim_refs",
            "origin_verified",
            "result_status",
            "gap_kind",
        }:
            raise ValueError("coverage_observation_invalid")
        atom_id = raw["atom_id"]
        batch = raw["batch"]
        query_hash = raw["query_receipt_hash"]
        source_ref = raw["source_ref"]
        origin_ref = raw["origin_ref"]
        claims = raw["material_claim_refs"]
        gap_kind = raw["gap_kind"]
        if (
            type(atom_id) is not str
            or atom_id not in by_atom
            or type(batch) is not int
            or batch < 1
            or type(query_hash) is not str
            or not _HASH.fullmatch(query_hash)
            or raw["source_family"] not in _FAMILIES
            or raw["polarity"] not in _POLARITIES
            or type(source_ref) not in (str, type(None))
            or type(origin_ref) not in (str, type(None))
            or raw["relevance"] not in _RELEVANCE
            or raw["read_scope"] not in _READ_SCOPE
            or raw["result_status"] not in _RESULT_STATUS
            or (gap_kind is not None and gap_kind not in _GAP_KINDS)
            or type(claims) is not list
            or any(type(item) is not str or not item for item in claims)
            or type(raw["origin_verified"]) is not bool
            or (raw["result_status"] != "hit" and source_ref is not None)
        ):
            raise ValueError("coverage_observation_invalid")
        if (atom_id, query_hash, source_ref) in seen_query_sources:
            raise ValueError("coverage_duplicate_observation")
        seen_query_sources.add((atom_id, query_hash, source_ref))
        grouped[atom_id].append(raw)
        batches.setdefault(batch, []).append(raw)
    recorded_signals: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    for raw in signals:
        if type(raw) is not dict or set(raw) != {
            "signal_id",
            "batch",
            "kind",
            "source_ref",
            "proposed_facet",
            "description",
        }:
            raise ValueError("coverage_discovery_signal_invalid")
        signal_id = _string(raw["signal_id"], "coverage_discovery_signal_invalid")
        batch = raw["batch"]
        if (
            signal_id in seen_signals
            or type(batch) is not int
            or batch < 1
            or raw["kind"] not in _DISCOVERY_KINDS
            or type(raw["source_ref"]) is not str
            or not raw["source_ref"]
        ):
            raise ValueError("coverage_discovery_signal_invalid")
        seen_signals.add(signal_id)
        recorded_signals.append(
            {
                "signal_id": signal_id,
                "batch": batch,
                "kind": raw["kind"],
                "source_ref": raw["source_ref"],
                "proposed_facet": _string(
                    raw["proposed_facet"], "coverage_discovery_signal_invalid"
                ),
                "description": _string(
                    raw["description"], "coverage_discovery_signal_invalid"
                ),
            }
        )
    atom_rows: list[dict[str, Any]] = []
    for atom in by_atom.values():
        rows = grouped[atom["atom_id"]]
        attempted_families = {row["source_family"] for row in rows}
        attempted_polarities = {row["polarity"] for row in rows}
        relevant = [row for row in rows if row["relevance"] == "relevant"]
        read = [
            row
            for row in relevant
            if row["read_scope"] in {"partial_text", "full_text"}
        ]
        read_evidence_families = {row["source_family"] for row in read}
        roots = {
            row["origin_ref"]
            for row in read
            if row["origin_verified"] and row["origin_ref"]
        }
        claims = {claim for row in read for claim in row["material_claim_refs"]}
        gap_kinds = sorted(
            {row["gap_kind"] for row in rows if row["gap_kind"] is not None}
        )
        missing_families = sorted(set(atom["required_families"]) - attempted_families)
        missing_polarities = sorted(
            set(atom["required_polarities"]) - attempted_polarities
        )
        evidence_floor = (
            not missing_families
            and not missing_polarities
            and len(roots) >= atom["required_independent_origins"]
            and bool(claims)
        )
        atom_rows.append(
            {
                "atom_id": atom["atom_id"],
                "facet_id": atom["facet_id"],
                "branch_id": atom["branch_id"],
                "importance": atom["importance"],
                "space": atom["space"],
                "query_count": len({row["query_receipt_hash"] for row in rows}),
                "candidate_count": sum(row["source_ref"] is not None for row in rows),
                "relevant_count": len(relevant),
                "read_relevant_count": len(read),
                "verified_independent_origin_count": len(roots),
                "material_claim_count": len(claims),
                "material_claim_refs": sorted(claims),
                "empty_query_count": sum(
                    row["result_status"] == "empty" for row in rows
                ),
                "gap_kinds": gap_kinds,
                "missing_families": missing_families,
                "required_families_without_read_relevant_evidence": sorted(
                    set(atom["required_families"]) - read_evidence_families
                ),
                "missing_polarities": missing_polarities,
                "evidence_floor_met": evidence_floor,
                "claim_truth_verified": False,
            }
        )
    seen_roots: set[str] = set()
    seen_claims: set[str] = set()
    seen_gaps: set[tuple[str, str]] = set()
    novelty = []
    for number in sorted(set(batches) | {row["batch"] for row in recorded_signals}):
        rows = batches.get(number, [])
        roots = {
            row["origin_ref"]
            for row in rows
            if row["relevance"] == "relevant"
            and row["read_scope"] in {"partial_text", "full_text"}
            and row["origin_verified"]
            and row["origin_ref"]
        }
        claims = {
            claim
            for row in rows
            if row["relevance"] == "relevant"
            and row["read_scope"] in {"partial_text", "full_text"}
            for claim in row["material_claim_refs"]
        }
        gaps = {
            (row["atom_id"], row["gap_kind"])
            for row in rows
            if row["gap_kind"] is not None
        }
        new_signals = sum(row["batch"] == number for row in recorded_signals)
        novelty.append(
            {
                "batch": number,
                "queried_atom_ids": sorted({row["atom_id"] for row in rows}),
                "observation_count": len(rows),
                "failed_or_refused_count": sum(
                    row["result_status"] in {"error", "refused"} for row in rows
                ),
                "unassessed_hit_count": sum(
                    row["result_status"] == "hit"
                    and (
                        row["relevance"] == "uncertain"
                        or row["read_scope"] in {"none", "metadata", "abstract"}
                    )
                    for row in rows
                ),
                "novelty_assessable": bool(rows)
                and all(
                    row["result_status"] == "empty"
                    or (
                        row["result_status"] == "hit"
                        and row["relevance"] != "uncertain"
                        and row["read_scope"] in {"partial_text", "full_text"}
                    )
                    for row in rows
                ),
                "new_relevant_origins": len(roots - seen_roots),
                "new_material_claims": len(claims - seen_claims),
                "new_gap_classes": len(gaps - seen_gaps),
                "new_latent_signals": new_signals,
            }
        )
        seen_roots.update(roots)
        seen_claims.update(claims)
        seen_gaps.update(gaps)
    plateau = len(novelty) >= 3 and all(
        row["novelty_assessable"]
        and row["new_relevant_origins"]
        == row["new_material_claims"]
        == row["new_gap_classes"]
        == row["new_latent_signals"]
        == 0
        for row in novelty[-2:]
    )
    evidence_floor_count = sum(row["evidence_floor_met"] for row in atom_rows)
    plateau_interpretation = (
        "not_observed"
        if not plateau
        else "no_verified_evidence_yield"
        if evidence_floor_count == 0
        else "partial_coverage_only"
        if evidence_floor_count < len(atom_rows)
        else "observed_routes_only_not_independent_field_saturation"
    )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageProgressAssessment",
            "frame_receipt_hash": frame["receipt_hash"],
            "run_id": frame["run_id"],
            "facet_count": len(facet_ids),
            "facet_labels": facet_labels,
            "facet_definitions": facet_definitions,
            "branch_count": len(branch_to_facet),
            "empty_branch_ids": empty_branches,
            "central_atom_count": sum(
                atom["importance"] == "central" for atom in by_atom.values()
            ),
            "peripheral_atom_count": sum(
                atom["importance"] == "peripheral" for atom in by_atom.values()
            ),
            "marginal_atom_count": sum(
                atom["importance"] == "marginal" for atom in by_atom.values()
            ),
            "negative_space_atom_count": sum(
                atom["space"] == "negative" for atom in by_atom.values()
            ),
            "latent_space_atom_count": sum(
                atom["space"] == "latent" for atom in by_atom.values()
            ),
            "atom_count": len(atom_rows),
            "atoms": atom_rows,
            "evidence_floor_count": evidence_floor_count,
            "evidence_floor_fraction": evidence_floor_count / len(atom_rows),
            "novelty_by_batch": novelty,
            "discovery_signals": recorded_signals,
            "required_importance_rank_gaps": rank_gaps,
            "required_space_gaps": space_gaps,
            "frame_expansion_required": bool(
                recorded_signals or rank_gaps or space_gaps or empty_branches
            ),
            "observed_novelty_plateau": plateau,
            "plateau_interpretation": plateau_interpretation,
            "plateau_can_justify_stop": False,
            "saturation_verified": False,
            "topic_completeness_verified": False,
            "status": "partial_budget" if budget_exhausted else "continue",
            "reason": "requires_independent_frame_review_and_calibrated_search_stop",
            "partial_result_allowed": True,
            "release_authorized": False,
        }
    )
