"""Verify evidential roots without confusing mirrors, versions, or providers."""

from __future__ import annotations

import re
from typing import Any, cast

from .beta_coverage import assess_beta_coverage
from .beta_source_lineage import document_identity
from .canonical import verify_receipt_hash, with_receipt_hash

_HASH = re.compile(r"^[0-9a-f]{64}$")
_ROOT_TYPES = {
    "study",
    "official_document",
    "dataset",
    "direct_observation",
    "unknown",
}
_ROLES = {
    "primary_empirical",
    "primary_official",
    "primary_dataset",
    "secondary_synthesis",
    "theoretical",
    "expert",
    "practice",
    "unknown",
}
_RELATIONS = {"supports", "contradicts", "context"}
_SCOPES = {"abstract", "partial_text", "full_text", "dataset_content"}


def assess_evidence_independence(
    frame: object, progress: object, evidence: object
) -> dict[str, Any]:
    """Count only roots whose provenance and independence were explicitly checked."""
    assess_beta_coverage(frame, [], budget_exhausted=False)
    if (
        type(progress) is not dict
        or progress.get("contract") != "BetaCoverageProgressAssessment"
        or not verify_receipt_hash(progress)
        or type(frame) is not dict
        or progress.get("frame_receipt_hash") != frame["receipt_hash"]
        or type(evidence) is not list
    ):
        raise ValueError("independence_inputs_invalid")
    atoms = {row["atom_id"]: row for row in frame["atoms"]}
    raw_progress_atoms = progress.get("atoms")
    if type(raw_progress_atoms) is not list:
        raise ValueError("independence_progress_atoms_invalid")
    checked_progress_atoms: list[dict[str, Any]] = []
    for value in raw_progress_atoms:
        if type(value) is not dict:
            raise ValueError("independence_progress_atoms_invalid")
        row = cast(dict[str, Any], value)
        claims = row.get("material_claim_refs")
        if (
            type(row.get("atom_id")) is not str
            or type(claims) is not list
            or any(type(claim) is not str for claim in claims)
        ):
            raise ValueError("independence_progress_atoms_invalid")
        checked_progress_atoms.append(row)
    progress_atoms = {row["atom_id"]: row for row in checked_progress_atoms}
    if set(progress_atoms) != set(atoms):
        raise ValueError("independence_progress_atoms_invalid")
    seen: set[tuple[str, str, str]] = set()
    duplicate_references = 0
    rows: list[dict[str, Any]] = []
    for raw in evidence:
        required = {
            "claim_id",
            "atom_id",
            "source_ref",
            "root_type",
            "root_id",
            "role",
            "relation",
            "read_scope",
            "provenance_receipt_hash",
            "provenance_verified",
            "independence_cluster",
            "independence_verified",
        }
        if type(raw) is not dict or set(raw) != required:
            raise ValueError("independence_evidence_invalid")
        claim_id, atom_id, source_ref, root_id, cluster = (
            raw[key]
            for key in (
                "claim_id",
                "atom_id",
                "source_ref",
                "root_id",
                "independence_cluster",
            )
        )
        if (
            any(
                type(value) is not str or not value.strip()
                for value in (claim_id, source_ref, root_id, cluster)
            )
            or atom_id not in atoms
            or raw["root_type"] not in _ROOT_TYPES
            or raw["role"] not in _ROLES
            or raw["relation"] not in _RELATIONS
            or raw["read_scope"] not in _SCOPES
            or type(raw["provenance_receipt_hash"]) is not str
            or not _HASH.fullmatch(raw["provenance_receipt_hash"])
            or type(raw["provenance_verified"]) is not bool
            or type(raw["independence_verified"]) is not bool
        ):
            raise ValueError("independence_evidence_invalid")
        identity = (claim_id.strip(), raw["root_type"], root_id.strip().casefold())
        if identity in seen:
            duplicate_references += 1
        seen.add(identity)
        claim_mapped = claim_id.strip() in progress_atoms[atom_id].get(
            "material_claim_refs", []
        )
        rows.append(
            {
                **raw,
                "claim_id": claim_id.strip(),
                "root_id": root_id.strip(),
                "independence_cluster": cluster.strip(),
                "claim_mapped_to_atom": claim_mapped,
            }
        )

    cluster_parents = {
        row["independence_cluster"]: row["independence_cluster"] for row in rows
    }

    def find(cluster):
        while cluster_parents[cluster] != cluster:
            cluster = cluster_parents[cluster]
        return cluster

    known_roots = {}
    for row in rows:
        identifiers = [(row["root_type"], row["root_id"].casefold())]
        for value in (row["root_id"], row["source_ref"]):
            if value.startswith(("https://", "http://")):
                identifiers.append(("document", document_identity(value)[0]))
        for identifier in identifiers:
            if identifier in known_roots:
                a, b = find(row["independence_cluster"]), find(known_roots[identifier])
                cluster_parents[max(a, b)] = min(a, b)
            else:
                known_roots[identifier] = row["independence_cluster"]
    for row in rows:
        row["independence_cluster"] = find(row["independence_cluster"])
    atom_rows = []
    for atom_id, atom in atoms.items():
        relevant = [row for row in rows if row["atom_id"] == atom_id]
        verified = [
            row
            for row in relevant
            if row["provenance_verified"]
            and row["independence_verified"]
            and row["claim_mapped_to_atom"]
            and row["root_type"] != "unknown"
            and row["role"] != "unknown"
        ]
        support_clusters = {
            row["independence_cluster"]
            for row in verified
            if row["relation"] == "supports"
        }
        contradiction_clusters = {
            row["independence_cluster"]
            for row in verified
            if row["relation"] == "contradicts"
        }
        supporting_roles = {
            row["role"] for row in verified if row["relation"] == "supports"
        }
        required_count = atom["required_independent_origins"]
        atom_rows.append(
            {
                "atom_id": atom_id,
                "required_independent_origins": required_count,
                "evidence_row_count": len(relevant),
                "verified_supporting_root_count": len(support_clusters),
                "verified_contradicting_root_count": len(contradiction_clusters),
                "verified_supporting_role_count": len(supporting_roles),
                "independence_requirement_met": len(support_clusters) >= required_count,
                "conflict_observed": bool(support_clusters and contradiction_clusters),
                "unknown_or_dependent_row_count": len(relevant) - len(verified),
                "unmapped_claim_row_count": sum(
                    not row["claim_mapped_to_atom"] for row in relevant
                ),
                "claim_truth_verified": False,
            }
        )
    met = sum(row["independence_requirement_met"] for row in atom_rows)
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaEvidenceIndependenceAssessment",
            "run_id": frame["run_id"],
            "frame_receipt_hash": frame["receipt_hash"],
            "progress_receipt_hash": progress["receipt_hash"],
            "evidence_row_count": len(rows),
            "verified_root_count": len(
                {
                    row["independence_cluster"]
                    for row in rows
                    if row["provenance_verified"]
                    and row["independence_verified"]
                    and row["claim_mapped_to_atom"]
                    and row["root_type"] != "unknown"
                    and row["role"] != "unknown"
                }
            ),
            "atom_count": len(atom_rows),
            "duplicate_root_references_preserved": duplicate_references,
            "assessment_basis": "submitted_root_assessments_not_independent_execution",
            "source_authentication_executed": False,
            "atoms_meeting_independence": met,
            "atoms": atom_rows,
            "all_atoms_meet_independence": met == len(atom_rows),
            "distinct_provider_or_url_does_not_imply_independence": True,
            "claim_truth_verified": False,
            "release_authorized": False,
        }
    )
