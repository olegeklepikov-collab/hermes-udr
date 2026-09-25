"""Reparse one saved paid coverage proposal without another model call."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path
from typing import Any, cast

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, read_private_bytes, write_exclusive_json
    from .model_call import MODEL, PROVIDER
    from .plan_beta_coverage import persist_coverage_result
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import MODEL, PROVIDER
    from plan_beta_coverage import persist_coverage_result

from hermes_research_report.beta_coverage_planner import build_coverage_prompt
from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.beta_modes import validate_public_question
from hermes_research_report.canonical import sha256_json, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--profile", choices=("search", "deep", "ultra", "academic"), required=True
    )
    parser.add_argument("--question", required=True)
    parser.add_argument("--decomposition", type=Path)
    args = parser.parse_args(argv)
    try:
        question = validate_public_question(args.question)
        decomposition = None
        if args.decomposition is not None:
            decomposition, _ = load_json(args.decomposition)
        output = args.output
        if (
            not output.is_absolute()
            or output.is_symlink()
            or not output.is_dir()
            or stat.S_IMODE(output.stat().st_mode) & 0o077
            or any(
                (output / name).exists()
                for name in ("frame.json", "proposal.json", "planning-run.json")
            )
        ):
            raise ValueError("coverage_reconciliation_not_allowed")
        attempt, _ = load_json(output / "attempt.json")
        failure, _ = load_json(output / "failure.json")
        usage, _ = load_json(output / "model-usage.json")
        trace, _ = load_json(output / "model-trace.json")
        if any(type(value) is not dict for value in (attempt, failure, usage, trace)):
            raise ValueError("coverage_saved_record_invalid")
        attempt = cast(dict[str, Any], attempt)
        failure = cast(dict[str, Any], failure)
        usage = cast(dict[str, Any], usage)
        trace = cast(dict[str, Any], trace)
        run_id = attempt.get("run_id")
        budget_cost = attempt.get("max_estimated_cost_usd")
        if type(budget_cost) not in (int, float) or budget_cost not in (0.01, 0.02):
            raise ValueError("coverage_saved_budget_invalid")
        candidates: list[dict[str, object]] = [
            {
                "schema_version": 1,
                "run_id": run_id,
                "wall_seconds": seconds,
                "max_estimated_cost_usd": budget_cost,
                "model_calls": 1,
            }
            for seconds in (60, 180)
        ]
        matched_budgets = [
            candidate
            for candidate in candidates
            if sha256_json(candidate) == attempt.get("bootstrap_budget_hash")
        ]
        if len(matched_budgets) != 1:
            raise ValueError("coverage_saved_budget_invalid")
        budget = matched_budgets[0]
        prompt = build_coverage_prompt(
            question=question, profile=args.profile, decomposition=decomposition
        )
        raw = (
            read_private_bytes(output / "model.raw.json", maximum=1_048_576)
            .decode("utf-8")
            .rstrip("\n")
        )
        messages = trace.get("messages")
        if (
            type(run_id) is not str
            or output.name != f"{run_id}-coverage-planning"
            or attempt.get("purpose") != "provisional_coverage_frame"
            or attempt.get("profile") != args.profile
            or attempt.get("question_sha256")
            != hashlib.sha256(question.encode()).hexdigest()
            or attempt.get("decomposition_receipt_hash")
            != (
                decomposition.get("receipt_hash")
                if type(decomposition) is dict
                else None
            )
            or attempt.get("bootstrap_budget_hash") != sha256_json(budget)
            or attempt.get("prompt_sha256")
            != hashlib.sha256(prompt.encode()).hexdigest()
            or attempt.get("provider") != PROVIDER
            or attempt.get("model") != MODEL
            or attempt.get("retry_allowed") is not False
            or failure.get("reconciliation_required") is not True
            or failure.get("retry_allowed") is not False
            or type(messages) is not list
            or len(messages) != 2
            or messages[0].get("content") != prompt
            or messages[1].get("content", "").strip() != raw
        ):
            raise ValueError("coverage_saved_attempt_not_bound")
        validate_tool_free_observation(
            max_estimated_cost_usd=float(budget_cost),
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
        )
        frame, run = persist_coverage_result(
            output=output,
            run_id=run_id,
            profile=args.profile,
            question=question,
            raw=raw,
            usage=usage,
            trace=trace,
            decomposition=decomposition,
            reconciled=True,
        )
        reconciliation = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoveragePlanningReconciliation",
                "run_id": run_id,
                "previous_failure_reason": failure.get("reason_code"),
                "frame_receipt_hash": frame["receipt_hash"],
                "planning_run_receipt_hash": run["receipt_hash"],
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "reconciliation.json", reconciliation)
        print(
            json.dumps(
                {
                    "status": "provisional_frame_reconciled",
                    "run_id": run_id,
                    "facet_count": len(frame["facets"]),
                    "atom_count": len(frame["atoms"]),
                    "additional_model_calls": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        ContractError,
        OSError,
        ValueError,
        UnicodeError,
        KeyError,
        TypeError,
    ) as error:
        code = error.code if isinstance(error, ContractError) else str(error)
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
