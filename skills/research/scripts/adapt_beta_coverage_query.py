"""Use a saved alternative query pair after an unproductive first batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, new_private_directory, write_exclusive_json
except ImportError:
    from file_io import load_json, new_private_directory, write_exclusive_json

from hermes_research_report.beta_coverage_query import parse_coverage_query_reply
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--first-batch-plan", type=Path, required=True)
    parser.add_argument("--first-observation", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        review, _ = load_json(args.review)
        first, _ = load_json(args.first_batch_plan)
        observed, _ = load_json(args.first_observation)
        if any(
            type(value) is not dict or not verify_receipt_hash(value)
            for value in (frame, review, first, observed)
        ):
            raise ValueError("coverage_adaptation_inputs_invalid")
        frame = cast(dict[str, Any], frame)
        review = cast(dict[str, Any], review)
        first = cast(dict[str, Any], first)
        observed = cast(dict[str, Any], observed)
        run_id = frame["run_id"]
        first_run_id = f"{run_id}-B01"
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{run_id}-coverage-route-repair/frame.json"
            or args.review
            != args.output_root / f"{run_id}-coverage-route-review/review.json"
            or args.first_batch_plan
            != args.output_root / f"{first_run_id}-coverage-source-plan/batch-plan.json"
            or args.first_observation
            != args.output_root
            / f"{first_run_id}-coverage-observed/batch-observation.json"
            or observed.get("batch_plan_receipt_hash") != first["receipt_hash"]
            or observed.get("frame_receipt_hash") != frame["receipt_hash"]
            or observed.get("review_receipt_hash") != review["receipt_hash"]
            or observed.get("semantic_relevance_verified_count") != 0
            or observed.get("candidate_count", 0) < 1
            or not all(
                type(row) is dict and row.get("missing_concept_group_indexes")
                for row in observed.get("lexical_screen", [])
            )
            or len(observed.get("lexical_screen", [])) != observed["candidate_count"]
        ):
            raise ValueError("coverage_adaptation_not_warranted")
        alternatives = first.get("unexecuted_alternative_pairs")
        if type(alternatives) is not list or not alternatives:
            raise ValueError("coverage_adaptation_no_saved_alternative")
        plan, batch = parse_coverage_query_reply(
            json.dumps(alternatives[0], ensure_ascii=False),
            frame=frame,
            atom_id=first["atom_id"],
            batch_number=2,
            review=review,
        )
        second_run_id = batch["batch_run_id"]
        output = args.output_root / f"{second_run_id}-coverage-source-plan"
        new_private_directory(output)
        adaptation = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageAdaptiveQueryPlan",
                "run_id": run_id,
                "atom_id": first["atom_id"],
                "from_batch_run_id": first_run_id,
                "to_batch_run_id": second_run_id,
                "parent_frame_receipt_hash": frame["receipt_hash"],
                "first_batch_plan_receipt_hash": first["receipt_hash"],
                "first_observation_receipt_hash": observed["receipt_hash"],
                "second_batch_plan_receipt_hash": batch["receipt_hash"],
                "second_subplan_receipt_hash": plan["receipt_hash"],
                "reason": "no_candidate_passed_all_concept_groups",
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        for name, value in (
            ("plan.json", plan),
            ("batch-plan.json", batch),
            ("adaptation.json", adaptation),
        ):
            write_exclusive_json(output / name, value)
        print(
            json.dumps(
                {
                    "status": "adaptive_batch_ready",
                    "batch_run_id": second_run_id,
                    "atom_id": first["atom_id"],
                    "additional_model_calls": 0,
                    "source_calls": 0,
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
