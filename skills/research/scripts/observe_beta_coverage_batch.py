"""Record the relevance uncertainty and gaps from one source-discovery batch."""

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

from hermes_research_report.beta_coverage_loop import observe_coverage_source_batch
from hermes_research_report.canonical import verify_receipt_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--batch-plan", type=Path, required=True)
    parser.add_argument("--previous-observations", type=Path)
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
            raise ValueError("coverage_observation_inputs_invalid")
        frame = cast(dict[str, Any], frame)
        review = cast(dict[str, Any], review)
        batch = cast(dict[str, Any], batch)
        run_id = frame["run_id"]
        batch_run_id = batch["batch_run_id"]
        domain_batch = args.frame == args.output_root / f"{run_id}-hole-fill/frame.json"
        expected_review = (
            args.output_root / f"{run_id}-hole-review/review.json"
            if domain_batch
            else args.output_root / f"{run_id}-coverage-route-review/review.json"
        )
        expected_frame = (
            args.output_root / f"{run_id}-hole-fill/frame.json"
            if domain_batch
            else args.output_root / f"{run_id}-coverage-route-repair/frame.json"
        )
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame != expected_frame
            or args.review != expected_review
            or args.batch_plan
            != args.output_root / f"{batch_run_id}-coverage-source-plan/batch-plan.json"
        ):
            raise ValueError("coverage_observation_paths_invalid")
        if domain_batch:
            route, _ = load_json(args.batch_plan.parent / "domain-route.json")
            if (
                type(route) is not dict
                or not verify_receipt_hash(route)
                or route.get("contract") != "BetaDomainEmpiricalSourceRoute"
                or route.get("frame_receipt_hash") != frame["receipt_hash"]
                or route.get("review_receipt_hash") != review["receipt_hash"]
                or route.get("batch_plan_receipt_hash") != batch["receipt_hash"]
                or route.get("parent_profile_qualified") is not False
            ):
                raise ValueError("coverage_domain_route_invalid")
        plan, _ = load_json(args.batch_plan.parent / "plan.json")
        execution, _ = load_json(
            args.output_root / f"{batch_run_id}-execution/execution.json"
        )
        portfolio, _ = load_json(
            args.output_root / f"{batch_run_id}-execution/portfolio.json"
        )
        web, _ = load_json(
            args.output_root / f"{batch_run_id}-LEAF-001-keenable/capture.json"
        )
        scholarly, _ = load_json(
            args.output_root / f"{batch_run_id}-LEAF-002-openalex/capture.json"
        )
        previous = None
        if batch["batch_number"] > 1:
            expected = (
                args.output_root
                / f"{run_id}-B{batch['batch_number'] - 1:02d}-coverage-observed/observations.json"
            )
            if args.previous_observations != expected:
                raise ValueError("coverage_previous_observations_path_invalid")
            previous, _ = load_json(expected)
        elif args.previous_observations is not None:
            raise ValueError("coverage_previous_observations_unexpected")
        observations, progress, receipt = observe_coverage_source_batch(
            frame=frame,
            review=review,
            plan=plan,
            batch_plan=batch,
            execution=execution,
            portfolio=portfolio,
            web_capture=web,
            scholarly_capture=scholarly,
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
