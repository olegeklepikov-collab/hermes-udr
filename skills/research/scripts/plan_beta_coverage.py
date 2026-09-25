"""Propose and seal a provisional atomic coverage frame before source calls."""

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
    from .file_io import load_json, write_exclusive_json
    from .model_call import ModelCallError, run_tool_free_model
except ImportError:
    from file_io import load_json, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model

from hermes_research_report.beta_coverage import assess_beta_coverage
from hermes_research_report.beta_coverage_holes import (
    build_hole_prompt,
    fill_coverage_holes,
)
from hermes_research_report.beta_coverage_planner import (
    build_coverage_prompt,
    parse_coverage_proposal,
)
from hermes_research_report.beta_modes import validate_public_question
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def persist_coverage_result(
    *,
    output: Path,
    run_id: str,
    profile: str,
    question: str,
    raw: str,
    usage: dict,
    trace: dict,
    decomposition: object | None = None,
    reconciled: bool = False,
    repair: tuple[dict, dict, dict] | None = None,
    repair_failure: dict | None = None,
) -> tuple[dict, dict]:
    frame, proposal = parse_coverage_proposal(
        raw,
        question=question,
        profile=profile,
        run_id=run_id,
        decomposition=decomposition,
    )
    repair_cost = 0.0
    if repair is not None:
        repaired, repair_receipt, repair_usage = repair
        if (
            not verify_receipt_hash(repaired)
            or not verify_receipt_hash(repair_receipt)
            or repair_receipt.get("parent_frame_receipt_hash") != frame["receipt_hash"]
            or repair_receipt.get("revised_frame_receipt_hash")
            != repaired["receipt_hash"]
        ):
            raise ValueError("coverage_repair_parent_mismatch")
        write_exclusive_json(output / "initial-frame.json", frame)
        write_exclusive_json(output / "hole-repair.json", repair_receipt)
        frame = repaired
        repair_cost = float(repair_usage["estimated_cost_usd"])
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoveragePlanningRun",
            "run_id": run_id,
            "profile": profile,
            "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "frame_receipt_hash": frame["receipt_hash"],
            "proposal_receipt_hash": proposal["receipt_hash"],
            "decomposition_receipt_hash": frame.get("decomposition_receipt_hash"),
            "reported_model_cost_usd": (
                None
                if repair_failure and repair_failure["observed_cost_usd"] is None
                else usage["estimated_cost_usd"]
                + repair_cost
                + (repair_failure["observed_cost_usd"] if repair_failure else 0)
            ),
            "hole_repair_failure": repair_failure,
            "hole_repair_receipt_hash": repair[1]["receipt_hash"] if repair else None,
            "initial_frame_receipt_hash": proposal["frame_receipt_hash"],
            "model_session_id": usage["session_id"],
            "model_trace_message_count": len(trace["messages"]),
            "reconciled_without_new_model_call": reconciled,
            "additional_model_calls": 0
            if reconciled
            else int(repair is not None or repair_failure is not None),
            "repair_model_session_id": repair[2]["session_id"] if repair else None,
            "independent_review_status": "not_performed",
            "source_calls": 0,
            "release_authorized": False,
        }
    )
    write_exclusive_json(output / "frame.json", frame)
    write_exclusive_json(output / "proposal.json", proposal)
    write_exclusive_json(output / "planning-run.json", receipt)
    return frame, receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--profile", choices=("search", "deep", "ultra", "academic"), required=True
    )
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
        question = validate_public_question(args.question)
        decomposition = None
        if args.decomposition is not None:
            decomposition, _ = load_json(args.decomposition)
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
        ):
            raise ValueError("coverage_output_root_invalid")
        run_id = (
            f"BETA-COV-{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(4).upper()}"
        )
        output = args.output_root / f"{run_id}-coverage-planning"
        assert output is not None
        budget: dict[str, object] = {
            "schema_version": 1,
            "run_id": run_id,
            "wall_seconds": 180,
            "max_estimated_cost_usd": 0.02,
            "model_calls": 1,
        }
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget=budget,
            prompt=build_coverage_prompt(
                question=question, profile=args.profile, decomposition=decomposition
            ),
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "provisional_coverage_frame",
                "profile": args.profile,
                "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                **(
                    {"decomposition_receipt_hash": decomposition["receipt_hash"]}
                    if type(decomposition) is dict
                    else {}
                ),
            },
        )
        model_completed = True
        repair = None
        repair_failure = None
        preview, _ = parse_coverage_proposal(
            raw,
            question=question,
            profile=args.profile,
            run_id=run_id,
            decomposition=decomposition,
        )
        progress = assess_beta_coverage(preview, [], budget_exhausted=False)
        if decomposition is not None and any(
            progress[key]
            for key in (
                "empty_branch_ids",
                "required_importance_rank_gaps",
                "required_space_gaps",
            )
        ):
            # Preserve the first paid response and record the additional stage separately.
            repair_usage = None
            try:
                repair_raw, repair_usage, _repair_trace = run_tool_free_model(
                    bootstrap_budget={
                        "schema_version": 1,
                        "run_id": run_id + "-HF",
                        "wall_seconds": 120,
                        "max_estimated_cost_usd": 0.01,
                        "model_calls": 1,
                    },
                    prompt=build_hole_prompt(preview, decomposition),
                    hermes=args.hermes,
                    output=output / "hole-repair",
                    attempt_binding={
                        "purpose": "coverage_structural_hole_fill",
                        "parent_frame_receipt_hash": preview["receipt_hash"],
                    },
                    preserve_completed_cost_overrun=True,
                )
                repaired, repair_receipt = fill_coverage_holes(
                    repair_raw,
                    frame=preview,
                    decomposition=decomposition,
                )
                repair = (repaired, repair_receipt, repair_usage)
            except (
                ContractError,
                ModelCallError,
                OSError,
                ValueError,
                KeyError,
            ) as error:
                repair_failure = {
                    "status": "unresolved",
                    "error_type": type(error).__name__,
                    "observed_cost_usd": repair_usage["estimated_cost_usd"]
                    if repair_usage
                    else None,
                    "initial_frame_preserved": True,
                    "retry_allowed": False,
                }
        frame, _receipt = persist_coverage_result(
            output=output,
            run_id=run_id,
            profile=args.profile,
            question=question,
            raw=raw,
            usage=usage,
            trace=trace,
            decomposition=decomposition,
            repair=repair,
            repair_failure=repair_failure,
        )
        print(
            json.dumps(
                {
                    "status": "provisional_frame",
                    "run_id": run_id,
                    "output": str(output),
                    "facet_count": len(frame["facets"]),
                    "atom_count": len(frame["atoms"]),
                    "model_cost_usd": _receipt["reported_model_cost_usd"],
                    "source_calls": 0,
                    "release_authorized": False,
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
            if isinstance(error, ValueError)
            else "coverage_planning_failed"
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
