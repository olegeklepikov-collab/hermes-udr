"""Revise a challenged pre-search coverage frame in one bounded model call."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, write_exclusive_json
    from .model_call import ModelCallError, run_tool_free_model
except ImportError:
    from file_io import load_json, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model

from hermes_research_report.beta_coverage_planner import (
    build_coverage_revision_prompt,
    parse_coverage_revision,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--revision-index", type=int, choices=(1, 2), default=1)
    parser.add_argument("--public-query-ack", action="store_true")
    args = parser.parse_args(argv)
    if not args.public_query_ack:
        print(
            json.dumps({"status": "error", "code": "public_query_ack_required"}),
            file=sys.stderr,
        )
        return 2
    output: Path | None = None
    model_completed = False
    try:
        frame, _ = load_json(args.frame)
        review, _ = load_json(args.review)
        prompt = build_coverage_revision_prompt(frame, review)
        assert type(frame) is dict and type(review) is dict
        run_id = frame["run_id"]
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame != args.output_root / f"{run_id}-coverage-planning/frame.json"
            or args.review != args.output_root / f"{run_id}-coverage-review/review.json"
        ):
            raise ValueError("coverage_revision_paths_invalid")
        planning, _ = load_json(args.frame.parent / "planning-run.json")
        checking, _ = load_json(args.review.parent / "review-run.json")
        if (
            type(planning) is not dict
            or type(checking) is not dict
            or not verify_receipt_hash(planning)
            or not verify_receipt_hash(checking)
            or planning.get("frame_receipt_hash") != frame["receipt_hash"]
            or checking.get("review_receipt_hash") != review["receipt_hash"]
            or checking.get("frame_receipt_hash") != frame["receipt_hash"]
        ):
            raise ValueError("coverage_revision_lineage_invalid")
        prior_attempt_sha256 = None
        if args.revision_index == 2:
            previous = args.output_root / f"{run_id}-coverage-revision-01"
            prior, prior_attempt_sha256 = load_json(previous / "attempt.json")
            failure, _ = load_json(previous / "failure.json")
            if (
                type(prior) is not dict
                or prior.get("purpose") != "coverage_frame_revision"
                or prior.get("parent_frame_receipt_hash") != frame["receipt_hash"]
                or prior.get("review_receipt_hash") != review["receipt_hash"]
                or type(failure) is not dict
                or failure.get("reason_code") != "model_outcome_unknown_reconcile_first"
                or any(
                    (previous / name).exists()
                    for name in ("model.raw.json", "model-usage.json", "frame.json")
                )
            ):
                raise ValueError("coverage_revision_second_attempt_not_allowed")
        output = (
            args.output_root / f"{run_id}-coverage-revision-{args.revision_index:02d}"
        )
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": run_id,
                "wall_seconds": 120,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=prompt,
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "coverage_frame_revision",
                "parent_frame_receipt_hash": frame["receipt_hash"],
                "review_receipt_hash": review["receipt_hash"],
                "prior_attempt_sha256": prior_attempt_sha256,
            },
        )
        model_completed = True
        revised, proposal, revision = parse_coverage_revision(
            raw, frame=frame, review=review
        )
        if usage["session_id"] in {
            planning.get("model_session_id"),
            checking.get("review_session_id"),
        }:
            raise ValueError("coverage_revision_session_not_separate")
        run = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageRevisionRun",
                "run_id": run_id,
                "revision_receipt_hash": revision["receipt_hash"],
                "revised_frame_receipt_hash": revised["receipt_hash"],
                "model_session_id": usage["session_id"],
                "reported_model_cost_usd": usage["estimated_cost_usd"],
                "model_trace_message_count": len(trace["messages"]),
                "prior_attempt_sha256": prior_attempt_sha256,
                "same_model_family_as_generator": True,
                "independence_verified": False,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        for name, value in (
            ("frame.json", revised),
            ("proposal.json", proposal),
            ("revision.json", revision),
            ("revision-run.json", run),
        ):
            write_exclusive_json(output / name, value)
        print(
            json.dumps(
                {
                    "status": "revised_provisional_frame",
                    "run_id": run_id,
                    "facet_count": len(revised["facets"]),
                    "atom_count": len(revised["atoms"]),
                    "independence_verified": False,
                    "source_calls": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        ContractError,
        ModelCallError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        code = (
            error.code
            if isinstance(error, (ContractError, ModelCallError))
            else str(error)
        )
        if model_completed and output is not None:
            try:
                write_exclusive_json(
                    output / "failure.json",
                    {
                        "schema_version": 1,
                        "status": "failed_after_model_response",
                        "reason_code": code,
                        "reconciliation_required": True,
                        "retry_allowed": False,
                    },
                )
            except (OSError, ValueError):
                pass
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
