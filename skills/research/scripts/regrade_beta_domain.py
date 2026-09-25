"""Regrade a saved domain map after inference-policy correction; no model call."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, read_private_bytes, write_exclusive_json
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json

from hermes_research_report.beta_domain_decomposition import parse_domain_decomposition
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--planning-dir", type=Path, required=True)
    parser.add_argument("--revision", type=int, choices=(2, 3), default=2)
    args = parser.parse_args(argv)
    try:
        directory = args.planning_dir
        prior_name = (
            "decomposition.json" if args.revision == 2 else "decomposition-v2.json"
        )
        target_name = f"decomposition-v{args.revision}.json"
        receipt_name = "regrade.json" if args.revision == 2 else "regrade-v3.json"
        if (
            not directory.is_absolute()
            or directory.is_symlink()
            or not directory.is_dir()
            or stat.S_IMODE(directory.stat().st_mode) & 0o077
            or (directory / target_name).exists()
        ):
            raise ValueError("domain_regrade_not_allowed")
        prior, _ = load_json(directory / prior_name)
        reconciliation, _ = load_json(directory / "reconciliation.json")
        previous_regrade = None
        if args.revision == 3:
            previous_regrade, _ = load_json(directory / "regrade.json")
        if (
            type(prior) is not dict
            or type(reconciliation) is not dict
            or not verify_receipt_hash(prior)
            or not verify_receipt_hash(reconciliation)
            or prior.get("contract") != "BetaDomainDecomposition"
            or (
                reconciliation.get("decomposition_receipt_hash")
                != prior["receipt_hash"]
                if args.revision == 2
                else type(previous_regrade) is not dict
                or not verify_receipt_hash(previous_regrade)
                or previous_regrade.get("revised_decomposition_receipt_hash")
                != prior["receipt_hash"]
            )
            or directory.name != f"{prior['run_id']}-domain-planning"
        ):
            raise ValueError("domain_regrade_lineage_invalid")
        raw = (
            read_private_bytes(directory / "model.raw.json", maximum=1_048_576)
            .decode("utf-8")
            .rstrip("\n")
        )
        if hashlib.sha256(raw.encode()).hexdigest() != prior["raw_response_sha256"]:
            raise ValueError("domain_regrade_raw_mismatch")
        revised = parse_domain_decomposition(
            raw,
            question=prior["question"],
            profile=prior["profile"],
            run_id=prior["run_id"],
        )
        if (
            revised["raw_response_sha256"] != prior["raw_response_sha256"]
            or len(revised["domains"]) != len(prior["domains"])
            or len(revised["aspects"]) != len(prior["aspects"])
            or len(revised["constructs"]) != len(prior["constructs"])
        ):
            raise ValueError("domain_regrade_structure_changed")
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaDomainInferenceRegrade",
                "run_id": prior["run_id"],
                "prior_decomposition_receipt_hash": prior["receipt_hash"],
                "revised_decomposition_receipt_hash": revised["receipt_hash"],
                "causal_hypotheses_before": sum(
                    row["pre_source_inference_ceiling"] == "causal_hypothesis_only"
                    for row in prior["aspects"]
                ),
                "causal_hypotheses_after": sum(
                    row["pre_source_inference_ceiling"] == "causal_hypothesis_only"
                    for row in revised["aspects"]
                ),
                "academic_role_conflicts_before": prior.get(
                    "academic_role_conflict_count", 0
                ),
                "academic_role_conflicts_after": revised[
                    "academic_role_conflict_count"
                ],
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(directory / target_name, revised)
        write_exclusive_json(directory / receipt_name, receipt)
        print(
            json.dumps(
                {
                    "status": "regraded",
                    "run_id": prior["run_id"],
                    "causal_hypotheses_before": receipt["causal_hypotheses_before"],
                    "causal_hypotheses_after": receipt["causal_hypotheses_after"],
                    "academic_role_conflicts_after": receipt[
                        "academic_role_conflicts_after"
                    ],
                    "additional_model_calls": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, UnicodeError, KeyError, TypeError) as error:
        print(json.dumps({"status": "error", "code": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
