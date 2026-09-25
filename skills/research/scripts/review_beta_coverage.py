"""Challenge a provisional coverage frame in a separate tool-free model session."""

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
    build_coverage_review_prompt,
    parse_coverage_review,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def persist_coverage_review(
    *,
    output: Path,
    frame: dict,
    generator: dict,
    raw: str,
    usage: dict,
    trace: dict,
    reconciled: bool,
) -> tuple[dict, dict]:
    if usage["session_id"] == generator.get("model_session_id"):
        raise ValueError("coverage_review_session_not_separate")
    review = parse_coverage_review(raw, frame=frame)
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageReviewRun",
            "run_id": frame["run_id"],
            "frame_receipt_hash": frame["receipt_hash"],
            "generator_session_id": generator["model_session_id"],
            "review_session_id": usage["session_id"],
            "review_receipt_hash": review["receipt_hash"],
            "reported_model_cost_usd": usage["estimated_cost_usd"],
            "model_trace_message_count": len(trace["messages"]),
            "reconciled_without_new_model_call": reconciled,
            "additional_model_calls": 0 if reconciled else 1,
            "same_model_family_as_generator": True,
            "independence_verified": False,
            "source_calls": 0,
            "release_authorized": False,
        }
    )
    write_exclusive_json(output / "review.json", review)
    write_exclusive_json(output / "review-run.json", receipt)
    return review, receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
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
        if type(frame) is not dict or not verify_receipt_hash(frame):
            raise ValueError("coverage_review_frame_invalid")
        run_id = frame["run_id"]
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame != args.output_root / f"{run_id}-coverage-planning/frame.json"
        ):
            raise ValueError("coverage_review_paths_invalid")
        generator, _ = load_json(args.frame.parent / "planning-run.json")
        if (
            type(generator) is not dict
            or not verify_receipt_hash(generator)
            or generator.get("contract") != "BetaCoveragePlanningRun"
            or generator.get("frame_receipt_hash") != frame["receipt_hash"]
            or generator.get("release_authorized") is not False
        ):
            raise ValueError("coverage_generator_not_bound")
        output = args.output_root / f"{run_id}-coverage-review"
        assert output is not None
        budget: dict[str, object] = {
            "schema_version": 1,
            "run_id": run_id,
            "wall_seconds": 60,
            "max_estimated_cost_usd": 0.01,
            "model_calls": 1,
        }
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget=budget,
            prompt=build_coverage_review_prompt(frame),
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "adversarial_coverage_review",
                "frame_receipt_hash": frame["receipt_hash"],
            },
        )
        model_completed = True
        review, _ = persist_coverage_review(
            output=output,
            frame=frame,
            generator=generator,
            raw=raw,
            usage=usage,
            trace=trace,
            reconciled=False,
        )
        print(
            json.dumps(
                {
                    "status": review["verdict"],
                    "run_id": run_id,
                    "issue_count": review["issue_count"],
                    "output": str(output),
                    "model_cost_usd": usage["estimated_cost_usd"],
                    "independence_verified": False,
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
            if isinstance(error, ValueError)
            else "coverage_review_failed"
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
