"""Retain screened-out web attempts and assess observed domain coverage."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_json,
    )
except ImportError:
    from file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_json,
    )

from hermes_research_report.beta_domain_source import observe_domain_web_batch
from hermes_research_report.canonical import verify_receipt_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--plan-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        review, _ = load_json(args.review)
        plan, _ = load_json(args.plan_dir / "plan.json")
        batch, _ = load_json(args.plan_dir / "batch.json")
        if (
            type(frame) is not dict
            or type(review) is not dict
            or type(plan) is not dict
            or type(batch) is not dict
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{frame['run_id']}-hole-fill/frame.json"
            or args.review
            != args.output_root / f"{frame['run_id']}-hole-review/review.json"
            or args.plan_dir != args.output_root / f"{plan['run_id']}-domain-web-plan"
        ):
            raise ValueError("domain_web_observation_paths_invalid")
        run_id = plan["run_id"]
        execution, _ = load_json(
            args.output_root / f"{run_id}-execution/execution.json"
        )
        portfolio, _ = load_json(
            args.output_root / f"{run_id}-execution/portfolio.json"
        )
        capture_dir = args.output_root / run_id
        capture, _ = load_json(capture_dir / "capture.json")
        if type(capture) is not dict or not verify_receipt_hash(capture):
            raise ValueError("domain_web_capture_invalid")
        for leaf in capture["leaves"]:
            for attempt in leaf.get("candidate_attempts", []):
                source_id = attempt.get("source_id")
                source_hash = attempt.get("content_sha256")
                if source_id is None and source_hash is None:
                    continue
                if (
                    type(source_id) is not str
                    or type(source_hash) is not str
                    or not source_id.startswith("SRC-")
                    or not source_id.replace("-", "").isalnum()
                ):
                    raise ValueError("domain_web_content_reference_invalid")
                content = read_private_bytes(
                    capture_dir / f"{source_id}.txt", maximum=100_000
                )
                if hashlib.sha256(content).hexdigest() != source_hash:
                    raise ValueError("domain_web_content_hash_invalid")
        previous = None
        if batch["batch_number"] > 1:
            previous, _ = load_json(
                args.output_root
                / f"{frame['run_id']}-D{batch['batch_number'] - 1:02d}-domain-web-observed/observations.json"
            )
        observations, progress, receipt = observe_domain_web_batch(
            frame=frame,
            review=review,
            plan=plan,
            batch=batch,
            execution=execution,
            portfolio=portfolio,
            capture=capture,
            previous_observations=previous,
        )
        output = args.output_root / f"{run_id}-domain-web-observed"
        new_private_directory(output)
        write_exclusive_json(output / "observations.json", observations)
        write_exclusive_json(output / "coverage.json", progress)
        write_exclusive_json(output / "batch-observation.json", receipt)
        print(
            json.dumps(
                {
                    "status": "domain_web_observed_partial",
                    "run_id": run_id,
                    "candidate_attempt_count": receipt["candidate_count"],
                    "verified_relevant_source_count": 0,
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
