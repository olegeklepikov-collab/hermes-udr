"""Reconcile an already saved planning answer without another model call."""

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
    from .plan_beta_from_question import persist_planning_result
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import MODEL, PROVIDER
    from plan_beta_from_question import persist_planning_result

from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.beta_modes import validate_public_question
from hermes_research_report.beta_planner import build_planning_prompt
from hermes_research_report.canonical import sha256_json, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("search", "deep", "ultra", "academic"), required=True
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
        ):
            raise ValueError("planning_output_not_private")
        attempt_value, _ = load_json(output / "attempt.json")
        failure_value, _ = load_json(output / "failure.json")
        usage_value, _ = load_json(output / "model-usage.json")
        trace_value, _ = load_json(output / "model-trace.json")
        if any(
            type(value) is not dict
            for value in (attempt_value, failure_value, usage_value, trace_value)
        ):
            raise ValueError("planning_saved_record_invalid")
        attempt, failure, usage, trace = (
            cast(dict[str, Any], value)
            for value in (attempt_value, failure_value, usage_value, trace_value)
        )
        run_id = attempt.get("run_id")
        if type(run_id) is not str or output.name != f"{run_id}-planning":
            raise ValueError("planning_run_id_mismatch")
        budget: dict[str, object] = {
            "schema_version": 1,
            "run_id": run_id,
            "wall_seconds": 60,
            "max_estimated_cost_usd": 0.01,
            "model_calls": 1,
        }
        if (
            attempt.get("mode") != args.mode
            or attempt.get("question_sha256")
            != hashlib.sha256(question.encode()).hexdigest()
            or attempt.get("decomposition_receipt_hash")
            != (
                decomposition.get("receipt_hash")
                if type(decomposition) is dict
                else None
            )
            or attempt.get("bootstrap_budget_hash") != sha256_json(budget)
            or attempt.get("provider") != PROVIDER
            or attempt.get("model") != MODEL
            or attempt.get("model_calls_limit") != 1
            or attempt.get("retry_allowed") is not False
            or failure.get("status") != "failed_or_unknown"
            or failure.get("retry_allowed") is not False
            or failure.get("reconciliation_required") is not True
            or (output / "planning-run.json").exists()
            or any(
                sibling.name.startswith(run_id) and sibling != output
                for sibling in output.parent.iterdir()
            )
        ):
            raise ValueError("planning_reconciliation_not_allowed")
        raw = (
            read_private_bytes(output / "model.raw.json", maximum=1_048_576)
            .decode("utf-8")
            .rstrip("\n")
        )
        messages = trace.get("messages")
        if type(messages) is not list or len(messages) != 2:
            raise ValueError("planning_trace_prompt_invalid")
        user, assistant = messages
        user_content = (
            user.get("content")
            if type(user) is dict and user.get("role") == "user"
            else None
        )
        assistant_content = (
            assistant.get("content")
            if type(assistant) is dict and assistant.get("role") == "assistant"
            else None
        )
        if (
            type(user_content) is not str
            or type(assistant_content) is not str
            or hashlib.sha256(user_content.encode()).hexdigest()
            != attempt.get("prompt_sha256")
            or (
                user_content
                != build_planning_prompt(
                    question=question, mode=args.mode, decomposition=decomposition
                )
                if decomposition is not None
                else not user_content.endswith(
                    f"РЕЖИМ: {args.mode}\nВОПРОС: {question}"
                )
            )
            or assistant_content.strip() != raw
        ):
            raise ValueError("planning_trace_prompt_invalid")
        validate_tool_free_observation(
            max_estimated_cost_usd=0.01,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
        )
        run = persist_planning_result(
            output=output,
            run_id=run_id,
            mode=args.mode,
            question=question,
            raw=raw,
            usage=usage,
            trace=trace,
            budget=budget,
            decomposition_receipt_hash=decomposition["receipt_hash"]
            if type(decomposition) is dict
            else None,
            reconciled=True,
        )
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaPlanningReconciliation",
                "run_id": run_id,
                "previous_failure_reason": failure.get("reason_code"),
                "planning_run_receipt_hash": run["receipt_hash"],
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "reconciliation.json", receipt)
        print(
            json.dumps(
                {
                    "status": "ready_to_execute",
                    "run_id": run_id,
                    "additional_model_calls": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, OSError, ValueError, UnicodeError) as error:
        code = (
            error.code
            if isinstance(error, ContractError)
            else str(error)
            if isinstance(error, ValueError)
            and str(error).replace("_", "").isalnum()
            and len(str(error)) < 80
            else "planning_reconciliation_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
