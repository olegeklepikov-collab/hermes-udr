"""Create one web discovery plan bound to a domain-grounded coverage atom."""

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

from hermes_research_report.beta_domain_source import (
    build_domain_web_prompt,
    parse_domain_web_query,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--decomposition", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--atom-id", required=True)
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
        decomposition, _ = load_json(args.decomposition)
        review, _ = load_json(args.review)
        if (
            type(frame) is not dict
            or type(decomposition) is not dict
            or type(review) is not dict
            or not all(
                verify_receipt_hash(item) for item in (frame, decomposition, review)
            )
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{frame['run_id']}-hole-fill/frame.json"
            or args.review
            != args.output_root / f"{frame['run_id']}-hole-review/review.json"
        ):
            raise ValueError("domain_web_paths_invalid")
        prompt = build_domain_web_prompt(
            frame, decomposition, review, atom_id=args.atom_id
        )
        batch_run_id = f"{frame['run_id']}-D{args.batch:02d}"
        output = args.output_root / f"{batch_run_id}-domain-web-plan"
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": batch_run_id,
                "wall_seconds": 60,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=prompt,
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "domain_grounded_web_query",
                "frame_receipt_hash": frame["receipt_hash"],
                "decomposition_receipt_hash": decomposition["receipt_hash"],
                "review_receipt_hash": review["receipt_hash"],
                "atom_id": args.atom_id,
            },
        )
        model_completed = True
        plan, batch = parse_domain_web_query(
            raw,
            frame=frame,
            decomposition=decomposition,
            review=review,
            atom_id=args.atom_id,
            batch_number=args.batch,
        )
        run = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaDomainWebPlanningRun",
                "run_id": batch_run_id,
                "batch_receipt_hash": batch["receipt_hash"],
                "plan_receipt_hash": plan["receipt_hash"],
                "model_session_id": usage["session_id"],
                "reported_model_cost_usd": usage["estimated_cost_usd"],
                "model_trace_message_count": len(trace["messages"]),
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "plan.json", plan)
        write_exclusive_json(output / "batch.json", batch)
        write_exclusive_json(output / "run.json", run)
        print(
            json.dumps(
                {
                    "status": "domain_web_plan_ready",
                    "run_id": batch_run_id,
                    "atom_id": args.atom_id,
                    "unattempted_required_families": batch[
                        "unattempted_required_families"
                    ],
                    "model_cost_usd": usage["estimated_cost_usd"],
                    "parent_profile_qualified": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, ModelCallError, OSError, ValueError, KeyError) as error:
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
