"""Plan one source-discovery batch tied to an open coverage atom."""

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

from hermes_research_report.beta_coverage_query import (
    build_coverage_query_prompt,
    parse_coverage_query_reply,
    select_coverage_atom,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def persist_coverage_source_plan(
    *,
    output: Path,
    frame: dict,
    review: dict,
    atom_id: str,
    batch_number: int,
    raw: str,
    usage: dict,
    trace: dict,
    reconciled: bool,
) -> tuple[dict, dict]:
    plan, batch = parse_coverage_query_reply(
        raw,
        frame=frame,
        atom_id=atom_id,
        batch_number=batch_number,
        review=review,
    )
    run = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageSourcePlanningRun",
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
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--batch", type=int, default=1)
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
        if type(frame) is not dict or type(review) is not dict:
            raise ValueError("coverage_source_inputs_invalid")
        run_id = frame["run_id"]
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{run_id}-coverage-route-repair/frame.json"
            or args.review
            != args.output_root / f"{run_id}-coverage-route-review/review.json"
            or not verify_receipt_hash(frame)
            or not verify_receipt_hash(review)
            or review.get("frame_receipt_hash") != frame["receipt_hash"]
            or not 1 <= args.batch <= 99
        ):
            raise ValueError("coverage_source_paths_invalid")
        if args.observations is None:
            observations = []
            if args.batch != 1:
                raise ValueError("coverage_source_previous_observations_required")
        else:
            if (
                args.observations
                != args.output_root / f"{run_id}-coverage-observations.json"
            ):
                raise ValueError("coverage_source_observations_path_invalid")
            observations, _ = load_json(args.observations)
        atom = select_coverage_atom(frame, observations)
        batch_run_id = f"{run_id}-B{args.batch:02d}"
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
            prompt=build_coverage_query_prompt(atom),
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "coverage_atom_source_query_plan",
                "frame_receipt_hash": frame["receipt_hash"],
                "review_receipt_hash": review["receipt_hash"],
                "atom_id": atom["atom_id"],
            },
        )
        model_completed = True
        persist_coverage_source_plan(
            output=output,
            frame=frame,
            review=review,
            atom_id=atom["atom_id"],
            batch_number=args.batch,
            raw=raw,
            usage=usage,
            trace=trace,
            reconciled=False,
        )
        print(
            json.dumps(
                {
                    "status": "source_batch_ready",
                    "run_id": run_id,
                    "batch_run_id": batch_run_id,
                    "atom_id": atom["atom_id"],
                    "subplan_mode": "deep_source_discovery_only",
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
