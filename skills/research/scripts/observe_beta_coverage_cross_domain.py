"""Retain text candidates and metadata from the four-route comparison batch."""

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

from hermes_research_report.beta_coverage_loop import observe_cross_domain_batch
from hermes_research_report.canonical import verify_receipt_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--batch-plan", type=Path, required=True)
    parser.add_argument("--previous-observations", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        review, _ = load_json(args.review)
        batch, _ = load_json(args.batch_plan)
        if any(
            type(value) is not dict or not verify_receipt_hash(value)
            for value in (frame, review, batch)
        ):
            raise ValueError("coverage_cross_domain_observation_inputs_invalid")
        frame = cast(dict[str, Any], frame)
        review = cast(dict[str, Any], review)
        batch = cast(dict[str, Any], batch)
        run_id = frame["run_id"]
        batch_run_id = batch["batch_run_id"]
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{run_id}-coverage-route-repair/frame.json"
            or args.review
            != args.output_root / f"{run_id}-coverage-route-review/review.json"
            or args.batch_plan
            != args.output_root / f"{batch_run_id}-coverage-source-plan/batch-plan.json"
            or args.previous_observations
            != args.output_root / f"{run_id}-B02-coverage-observed/observations.json"
        ):
            raise ValueError("coverage_cross_domain_observation_paths_invalid")
        plan, _ = load_json(args.batch_plan.parent / "plan.json")
        execution, _ = load_json(
            args.output_root / f"{batch_run_id}-execution/execution.json"
        )
        portfolio, _ = load_json(
            args.output_root / f"{batch_run_id}-execution/portfolio.json"
        )
        previous, _ = load_json(args.previous_observations)
        captures = {}
        for leaf_id, provider in (
            ("LEAF-001", "keenable"),
            ("LEAF-002", "openalex"),
            ("LEAF-003", "keenable"),
            ("LEAF-004", "openalex"),
        ):
            captures[leaf_id], _ = load_json(
                args.output_root / f"{batch_run_id}-{leaf_id}-{provider}/capture.json"
            )
        observations, progress, receipt = observe_cross_domain_batch(
            frame=frame,
            review=review,
            plan=plan,
            batch_plan=batch,
            execution=execution,
            portfolio=portfolio,
            captures=captures,
            previous_observations=previous,
        )
        output = args.output_root / f"{batch_run_id}-coverage-observed"
        new_private_directory(output)
        write_exclusive_json(output / "observations.json", observations)
        write_exclusive_json(output / "coverage.json", progress)
        write_exclusive_json(output / "batch-observation.json", receipt)
        print(
            json.dumps(
                {
                    "status": "partial_observation",
                    "batch_run_id": batch_run_id,
                    "atom_id": batch["atom_id"],
                    "candidate_count": receipt["candidate_count"],
                    "semantic_relevance_verified_count": 0,
                    "evidence_floor_count": progress["evidence_floor_count"],
                    "saturation_verified": False,
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
