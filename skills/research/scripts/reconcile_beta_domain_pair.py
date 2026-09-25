"""Recover nested model query groups from one saved paid domain-pair reply."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path
from typing import Any, cast

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, read_private_bytes, write_exclusive_json
    from .plan_beta_coverage_source import persist_coverage_source_plan
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from plan_beta_coverage_source import persist_coverage_source_plan

from hermes_research_report.beta_domain_source import (
    build_domain_pair_prompt,
    normalize_domain_pair_reply,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--decomposition", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--saved-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        decomposition, _ = load_json(args.decomposition)
        review, _ = load_json(args.review)
        directory = args.saved_dir
        if (
            type(frame) is not dict
            or type(decomposition) is not dict
            or type(review) is not dict
            or not all(
                verify_receipt_hash(row) for row in (frame, decomposition, review)
            )
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or directory.is_symlink()
            or not directory.is_dir()
            or stat.S_IMODE(directory.stat().st_mode) & 0o077
            or directory
            != args.output_root / f"{frame['run_id']}-B01-coverage-source-plan"
        ):
            raise ValueError("domain_pair_reconciliation_paths_invalid")
        attempt, _ = load_json(directory / "attempt.json")
        failure, _ = load_json(directory / "failure.json")
        usage, _ = load_json(directory / "model-usage.json")
        trace, _ = load_json(directory / "model-trace.json")
        if any(type(row) is not dict for row in (attempt, failure, usage, trace)):
            raise ValueError("domain_pair_reconciliation_records_invalid")
        attempt = cast(dict[str, Any], attempt)
        failure = cast(dict[str, Any], failure)
        usage = cast(dict[str, Any], usage)
        trace = cast(dict[str, Any], trace)
        if (
            attempt.get("purpose") != "domain_empirical_source_pair"
            or attempt.get("frame_receipt_hash") != frame["receipt_hash"]
            or attempt.get("decomposition_receipt_hash")
            != decomposition["receipt_hash"]
            or attempt.get("review_receipt_hash") != review["receipt_hash"]
            or failure.get("reconciliation_required") is not True
            or failure.get("retry_allowed") is not False
            or attempt.get("retry_allowed") is not False
        ):
            raise ValueError("domain_pair_reconciliation_lineage_invalid")
        atom_id = attempt["atom_id"]
        prompt = build_domain_pair_prompt(frame, decomposition, review, atom_id=atom_id)
        raw = (
            read_private_bytes(directory / "model.raw.json", maximum=1_048_576)
            .decode("utf-8")
            .rstrip("\n")
        )
        messages = trace.get("messages")
        if (
            attempt.get("prompt_sha256") != hashlib.sha256(prompt.encode()).hexdigest()
            or type(messages) is not list
            or len(messages) != 2
            or messages[0].get("content") != prompt
            or messages[1].get("content", "").strip() != raw
        ):
            raise ValueError("domain_pair_reconciliation_trace_invalid")
        normalized, details = normalize_domain_pair_reply(raw)
        plan, batch = persist_coverage_source_plan(
            output=directory,
            frame=frame,
            review=review,
            atom_id=atom_id,
            batch_number=1,
            raw=normalized,
            usage=usage,
            trace=trace,
            reconciled=True,
        )
        atom = next(row for row in frame["atoms"] if row["atom_id"] == atom_id)
        route = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaDomainEmpiricalSourceRoute",
                "run_id": plan["run_id"],
                "atom_id": atom_id,
                "frame_receipt_hash": frame["receipt_hash"],
                "decomposition_receipt_hash": decomposition["receipt_hash"],
                "review_receipt_hash": review["receipt_hash"],
                "batch_plan_receipt_hash": batch["receipt_hash"],
                "plan_receipt_hash": plan["receipt_hash"],
                "required_families_from_atom": atom["required_families"],
                "scholarly_index_is_optional_challenge": "scholarly_index"
                not in atom["required_families"],
                "academic_absence_does_not_block_partial_result": True,
                "parent_profile_qualified": False,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        normalization = with_receipt_hash(
            {
                **details,
                "run_id": plan["run_id"],
                "plan_receipt_hash": plan["receipt_hash"],
                "batch_receipt_hash": batch["receipt_hash"],
            }
        )
        write_exclusive_json(directory / "domain-route.json", route)
        write_exclusive_json(directory / "normalization.json", normalization)
        print(
            json.dumps(
                {
                    "status": "domain_pair_reconciled",
                    "run_id": plan["run_id"],
                    "atom_id": atom_id,
                    "nested_group_shape_repaired": normalization[
                        "nested_group_shape_repaired"
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
