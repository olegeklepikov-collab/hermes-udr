"""Create one private beta plan from a public question, without source calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import fsync_directory, load_json, write_exclusive_json
    from .model_call import ModelCallError, run_tool_free_model
except ImportError:
    from file_io import fsync_directory, load_json, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model

from hermes_research_report.beta_planner import (
    build_planning_prompt,
    parse_planning_proposal,
)
from hermes_research_report.canonical import sha256_json, with_receipt_hash
from hermes_research_report.errors import ContractError


def persist_planning_result(
    *,
    output: Path,
    run_id: str,
    mode: str,
    question: str,
    raw: str,
    usage: dict[str, Any],
    trace: dict[str, Any],
    budget: dict[str, object],
    decomposition_receipt_hash: str | None = None,
    reconciled: bool = False,
) -> dict[str, Any]:
    plan, protocol, proposal = parse_planning_proposal(
        raw, question=question, mode=mode, run_id=run_id
    )
    if protocol is not None:
        write_exclusive_json(output / "academic-protocol.json", protocol)
    write_exclusive_json(output / "plan.json", plan)
    write_exclusive_json(output / "proposal.json", proposal)
    run = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaAutonomousPlanningRun",
            "run_id": run_id,
            "mode": mode,
            "bootstrap_budget_hash": sha256_json(budget),
            "plan_receipt_hash": plan["receipt_hash"],
            "proposal_receipt_hash": proposal["receipt_hash"],
            "decomposition_receipt_hash": decomposition_receipt_hash,
            "academic_protocol_receipt_hash": protocol["receipt_hash"]
            if protocol
            else None,
            "model_usage_sha256": sha256_json(usage),
            "model_trace_sha256": sha256_json(trace),
            "reported_model_cost_usd": usage["estimated_cost_usd"],
            "reconciled_without_new_model_call": reconciled,
            "source_calls_before_seal": 0,
            "release_authorized": False,
        }
    )
    write_exclusive_json(output / "planning-run.json", run)
    fsync_directory(output)
    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=("search", "deep", "ultra", "academic"), required=True
    )
    parser.add_argument("--question", required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--decomposition", type=Path)
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
    run_id: str | None = None
    model_completed = False
    try:
        decomposition = None
        if args.decomposition is not None:
            decomposition, _ = load_json(args.decomposition)
        prompt = build_planning_prompt(
            question=args.question, mode=args.mode, decomposition=decomposition
        )
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
        ):
            raise ValueError("output_root_invalid")
        run_id = f"BETA-AUTO-{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(4).upper()}"
        output = args.output_root / f"{run_id}-planning"
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
            prompt=prompt,
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "mode": args.mode,
                "question_sha256": hashlib.sha256(
                    args.question.strip().encode()
                ).hexdigest(),
                **(
                    {"decomposition_receipt_hash": decomposition["receipt_hash"]}
                    if type(decomposition) is dict
                    else {}
                ),
            },
        )
        model_completed = True
        persist_planning_result(
            output=output,
            run_id=run_id,
            mode=args.mode,
            question=args.question,
            raw=raw,
            usage=usage,
            trace=trace,
            budget=budget,
            decomposition_receipt_hash=decomposition["receipt_hash"]
            if type(decomposition) is dict
            else None,
        )
        print(
            json.dumps(
                {
                    "status": "ready_to_execute",
                    "run_id": run_id,
                    "mode": args.mode,
                    "output": str(output),
                    "model_cost_usd": usage["estimated_cost_usd"],
                    "source_calls": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, ModelCallError, OSError, ValueError) as error:
        code = (
            error.code
            if isinstance(error, (ContractError, ModelCallError))
            else str(error)
            if isinstance(error, ValueError)
            and str(error).replace("_", "").isalnum()
            and len(str(error)) < 80
            else "planning_failed"
        )
        if model_completed and output is not None:
            try:
                write_exclusive_json(
                    output / "failure.json",
                    {
                        "schema_version": 1,
                        "status": "failed_or_unknown",
                        "reason_code": code,
                        "reconciliation_required": True,
                        "retry_allowed": False,
                    },
                )
            except (OSError, ValueError):
                pass
        print(
            json.dumps({"status": "error", "code": code, "run_id": run_id}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
