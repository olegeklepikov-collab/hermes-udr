"""Replan a failed comparison as four domain-specific source leaves."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, write_exclusive_json
    from .model_call import ModelCallError, run_tool_free_model
except ImportError:
    from file_io import load_json, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model

from hermes_research_report.beta_coverage_query import (
    build_cross_domain_query_prompt,
    parse_cross_domain_query_reply,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def persist_cross_domain_plan(
    *,
    output: Path,
    frame: dict,
    review: dict,
    previous: dict,
    raw: str,
    usage: dict,
    trace: dict,
    reconciled: bool,
) -> tuple[dict, dict]:
    plan, batch = parse_cross_domain_query_reply(
        raw,
        frame=frame,
        review=review,
        atom_id=previous["atom_id"],
        previous=previous,
    )
    run = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageCrossDomainPlanningRun",
            "run_id": frame["run_id"],
            "batch_run_id": batch["batch_run_id"],
            "batch_plan_receipt_hash": batch["receipt_hash"],
            "subplan_receipt_hash": plan["receipt_hash"],
            "model_session_id": usage["session_id"],
            "reported_model_cost_usd": usage["estimated_cost_usd"],
            "model_trace_message_count": len(trace["messages"]),
            "reconciled_without_new_model_call": reconciled,
            "additional_model_calls": 0 if reconciled else 1,
            "source_calls": 0,
            "release_authorized": False,
        }
    )
    for name, value in (
        ("plan.json", plan),
        ("batch-plan.json", batch),
        ("planning-run.json", run),
    ):
        write_exclusive_json(output / name, value)
    return plan, batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--previous-observation", type=Path, required=True)
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
        review, _ = load_json(args.review)
        previous, _ = load_json(args.previous_observation)
        if any(
            type(value) is not dict or not verify_receipt_hash(value)
            for value in (frame, review, previous)
        ):
            raise ValueError("coverage_cross_domain_inputs_invalid")
        frame = cast(dict[str, Any], frame)
        review = cast(dict[str, Any], review)
        previous = cast(dict[str, Any], previous)
        run_id = frame["run_id"]
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{run_id}-coverage-route-repair/frame.json"
            or args.review
            != args.output_root / f"{run_id}-coverage-route-review/review.json"
            or args.previous_observation
            != args.output_root
            / f"{run_id}-B02-coverage-observed/batch-observation.json"
            or previous.get("batch_number") != 2
        ):
            raise ValueError("coverage_cross_domain_paths_invalid")
        matching = [
            atom for atom in frame["atoms"] if atom["atom_id"] == previous["atom_id"]
        ]
        if len(matching) != 1:
            raise ValueError("coverage_cross_domain_atom_invalid")
        batch_run_id = f"{run_id}-B03"
        output = args.output_root / f"{batch_run_id}-coverage-source-plan"
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": batch_run_id,
                "wall_seconds": 60,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=build_cross_domain_query_prompt(matching[0], previous),
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "coverage_cross_domain_query_plan",
                "frame_receipt_hash": frame["receipt_hash"],
                "review_receipt_hash": review["receipt_hash"],
                "prior_observation_receipt_hash": previous["receipt_hash"],
                "atom_id": previous["atom_id"],
            },
        )
        model_completed = True
        _plan, batch = persist_cross_domain_plan(
            output=output,
            frame=frame,
            review=review,
            previous=previous,
            raw=raw,
            usage=usage,
            trace=trace,
            reconciled=False,
        )
        print(
            json.dumps(
                {
                    "status": "cross_domain_batch_ready",
                    "batch_run_id": batch_run_id,
                    "atom_id": batch["atom_id"],
                    "leaf_count": 4,
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
