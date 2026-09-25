"""Produce one provisional domain/construct map before coverage or source calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import write_exclusive_json
    from .model_call import ModelCallError, run_tool_free_model
except ImportError:
    from file_io import write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model

from hermes_research_report.beta_domain_decomposition import (
    build_domain_decomposition_prompt,
    parse_domain_decomposition,
)
from hermes_research_report.beta_modes import validate_public_question
from hermes_research_report.canonical import with_receipt_hash
from hermes_research_report.errors import ContractError


def persist_domain_result(
    *,
    output: Path,
    raw: str,
    question: str,
    profile: str,
    run_id: str,
    usage: dict,
    trace: dict,
    reconciled: bool,
    cost_limit_usd: float = 0.01,
) -> tuple[dict, dict]:
    decomposition = parse_domain_decomposition(
        raw, question=question, profile=profile, run_id=run_id
    )
    run = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaDomainPlanningRun",
            "run_id": run_id,
            "profile": profile,
            "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "decomposition_receipt_hash": decomposition["receipt_hash"],
            "model_session_id": usage["session_id"],
            "reported_model_cost_usd": usage["estimated_cost_usd"],
            "cost_limit_usd": cost_limit_usd,
            "cost_limit_exceeded": usage["estimated_cost_usd"] > cost_limit_usd,
            "cost_overrun_usd": max(
                0.0, round(usage["estimated_cost_usd"] - cost_limit_usd, 8)
            ),
            "budget_overrun_authorizes_more_calls": False,
            "model_trace_message_count": len(trace["messages"]),
            "reconciled_without_new_model_call": reconciled,
            "additional_model_calls": 0 if reconciled else 1,
            "source_calls": 0,
            "release_authorized": False,
        }
    )
    write_exclusive_json(output / "decomposition.json", decomposition)
    write_exclusive_json(output / "planning-run.json", run)
    return decomposition, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--profile", choices=("search", "deep", "ultra", "academic"), required=True
    )
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--public-query-ack", action="store_true")
    parser.add_argument("--planning-cost-limit-usd", type=float, default=0.01)
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
        question = validate_public_question(args.question)
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
        ):
            raise ValueError("domain_output_root_invalid")
        run_id = (
            f"BETA-DOM-{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(4).upper()}"
        )
        output = args.output_root / f"{run_id}-domain-planning"
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": run_id,
                "wall_seconds": 120,
                "max_estimated_cost_usd": args.planning_cost_limit_usd,
                "model_calls": 1,
            },
            prompt=build_domain_decomposition_prompt(
                question=question, profile=args.profile
            ),
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "domain_construct_decomposition",
                "profile": args.profile,
                "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            },
            preserve_completed_cost_overrun=True,
        )
        model_completed = True
        result, _ = persist_domain_result(
            output=output,
            raw=raw,
            question=question,
            profile=args.profile,
            run_id=run_id,
            usage=usage,
            trace=trace,
            reconciled=False,
            cost_limit_usd=args.planning_cost_limit_usd,
        )
        print(
            json.dumps(
                {
                    "status": "provisional_domain_decomposition",
                    "run_id": run_id,
                    "domain_count": len(result["domains"]),
                    "aspect_count": len(result["aspects"]),
                    "construct_count": len(result["constructs"]),
                    "academic_absence_blocks_nonacademic_answer": False,
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
        print(
            json.dumps({"status": "error", "code": code, "run_id": run_id}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
