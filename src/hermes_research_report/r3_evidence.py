"""R3 evidence-field qualification across official, dataset, adaptive, and stop gates."""

from __future__ import annotations

from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

R3_EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "official_document",
        "dataset",
        "atoms",
        "batches",
        "calibration",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "official_document": {"type": "object"},
        "dataset": {"type": "object"},
        "atoms": {"type": "array", "minItems": 1},
        "batches": {"type": "array", "minItems": 2},
        "calibration": {"type": "object"},
    },
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        fail("invalid_hash", path, "Ожидался SHA-256.")
    return text


def assess_r3_evidence_field(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "official_document",
            "dataset",
            "atoms",
            "batches",
            "calibration",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    official = require_mapping(data["official_document"], "request.official_document")
    require_exact_keys(
        official,
        {
            "atom_id",
            "publisher_host",
            "controlled_hosts",
            "final_url",
            "source_bytes_hash",
            "text_hash",
            "text_read",
            "origin_verified",
            "relevance",
            "independence_claimed",
        },
        "request.official_document",
    )
    official_atom = require_string(
        official["atom_id"], "request.official_document.atom_id"
    )
    host = require_string(
        official["publisher_host"], "request.official_document.publisher_host"
    )
    hosts = [
        require_string(value, f"request.official_document.controlled_hosts[{index}]")
        for index, value in enumerate(
            require_list(
                official["controlled_hosts"],
                "request.official_document.controlled_hosts",
            )
        )
    ]
    official_ok = (
        host in hosts
        and require_string(
            official["final_url"], "request.official_document.final_url"
        ).startswith(f"https://{host}/")
        and bool(
            _hash(
                official["source_bytes_hash"],
                "request.official_document.source_bytes_hash",
            )
        )
        and bool(_hash(official["text_hash"], "request.official_document.text_hash"))
        and require_bool(official["text_read"], "request.official_document.text_read")
        and require_bool(
            official["origin_verified"], "request.official_document.origin_verified"
        )
        and official["relevance"] in {"direct", "context_only"}
    )
    independence_claimed = require_bool(
        official["independence_claimed"],
        "request.official_document.independence_claimed",
    )

    dataset = require_mapping(data["dataset"], "request.dataset")
    require_exact_keys(
        dataset,
        {
            "atom_id",
            "doi",
            "resource_type",
            "rights_allowed",
            "file_available",
            "file_hash",
            "schema_verified",
            "fields_verified",
            "provenance_verified",
            "measurements_verified",
            "reanalysis_terms_recorded",
        },
        "request.dataset",
    )
    dataset_atom = require_string(dataset["atom_id"], "request.dataset.atom_id")
    dataset_checks = [
        require_bool(dataset[key], f"request.dataset.{key}")
        for key in (
            "rights_allowed",
            "file_available",
            "schema_verified",
            "fields_verified",
            "provenance_verified",
            "measurements_verified",
            "reanalysis_terms_recorded",
        )
    ]
    dataset_ok = (
        require_string(dataset["resource_type"], "request.dataset.resource_type")
        == "Dataset"
        and bool(require_string(dataset["doi"], "request.dataset.doi"))
        and bool(_hash(dataset["file_hash"], "request.dataset.file_hash"))
        and all(dataset_checks)
    )

    atoms = [
        require_string(value, f"request.atoms[{index}]")
        for index, value in enumerate(require_list(data["atoms"], "request.atoms"))
    ]
    covered: set[str] = set()
    excluded = []
    root_by_atom: dict[str, set[str]] = {atom: set() for atom in atoms}
    novelty = []
    batches = require_list(data["batches"], "request.batches")
    for batch_index, raw_batch in enumerate(batches):
        path = f"request.batches[{batch_index}]"
        batch = require_mapping(raw_batch, path)
        require_exact_keys(batch, {"batch_id", "new_material_claims", "sources"}, path)
        require_string(batch["batch_id"], f"{path}.batch_id")
        novelty.append(
            require_int(batch["new_material_claims"], f"{path}.new_material_claims")
        )
        for source_index, raw_source in enumerate(
            require_list(batch["sources"], f"{path}.sources")
        ):
            source_path = f"{path}.sources[{source_index}]"
            source = require_mapping(raw_source, source_path)
            require_exact_keys(
                source,
                {
                    "source_id",
                    "family",
                    "atom_id",
                    "status",
                    "exclusion_reason",
                    "receipt_verified",
                    "origin_root",
                },
                source_path,
            )
            source_id = require_string(source["source_id"], f"{source_path}.source_id")
            family = require_string(source["family"], f"{source_path}.family")
            atom = require_string(source["atom_id"], f"{source_path}.atom_id")
            status = require_string(source["status"], f"{source_path}.status")
            receipt_verified = require_bool(
                source["receipt_verified"], f"{source_path}.receipt_verified"
            )
            root = require_string(
                source["origin_root"], f"{source_path}.origin_root", nonempty=False
            )
            reason = require_string(
                source["exclusion_reason"],
                f"{source_path}.exclusion_reason",
                nonempty=False,
            )
            if atom not in atoms:
                fail(
                    "unknown_atom",
                    f"{source_path}.atom_id",
                    "Источник связан с неизвестным атомом.",
                )
            if status == "relevant" and receipt_verified and root:
                covered.add(atom)
                root_by_atom[atom].add(root)
            else:
                excluded.append(
                    {
                        "source_id": source_id,
                        "family": family,
                        "atom_id": atom,
                        "status": status,
                        "reason": reason or "not_verified",
                    }
                )
    if official_ok and official["relevance"] == "direct":
        covered.add(official_atom)
        root_by_atom.setdefault(official_atom, set()).add(f"official:{host}")
    if dataset_ok:
        covered.add(dataset_atom)
        root_by_atom.setdefault(dataset_atom, set()).add(f"dataset:{dataset['doi']}")
    missing = sorted(set(atoms) - covered)
    calibration = require_mapping(data["calibration"], "request.calibration")
    require_exact_keys(
        calibration,
        {
            "residual_fraction",
            "independently_calibrated",
            "citation_seed_count",
            "negative_space_closed",
            "latent_space_closed",
        },
        "request.calibration",
    )
    residual = calibration["residual_fraction"]
    if (
        isinstance(residual, bool)
        or not isinstance(residual, (int, float))
        or not 0 <= residual <= 1
    ):
        fail(
            "invalid_residual",
            "request.calibration.residual_fraction",
            "Ожидалась доля 0..1.",
        )
    independent_roots = len({root for roots in root_by_atom.values() for root in roots})
    saturation = (
        not missing
        and len(batches) >= 3
        and len(novelty) >= 2
        and novelty[-2:] == [0, 0]
        and residual <= 0.05
        and require_bool(
            calibration["independently_calibrated"],
            "request.calibration.independently_calibrated",
        )
        and require_int(
            calibration["citation_seed_count"],
            "request.calibration.citation_seed_count",
        )
        >= 2
        and require_bool(
            calibration["negative_space_closed"],
            "request.calibration.negative_space_closed",
        )
        and require_bool(
            calibration["latent_space_closed"],
            "request.calibration.latent_space_closed",
        )
        and independent_roots >= 2
    )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "R3EvidenceFieldDecision",
            "status": "saturated" if saturation else "continue",
            "official_document": {
                "status": "verified" if official_ok else "blocked",
                "atom_id": official_atom,
                "independence_automatically_granted": False,
                "independence_claim_rejected": independence_claimed,
            },
            "dataset": {
                "status": "verified_file" if dataset_ok else "doi_candidate_only",
                "atom_id": dataset_atom,
                "metadata_closes_atom": False,
            },
            "batch_count": len(batches),
            "covered_atoms": sorted(covered),
            "missing_atoms": missing,
            "excluded_sources": excluded,
            "independent_origin_count": independent_roots,
            "novelty_by_batch": novelty,
            "residual_fraction": residual,
            "saturation_verified": saturation,
            "next_action": "stop" if saturation else "redirect_or_deepen",
        }
    )
