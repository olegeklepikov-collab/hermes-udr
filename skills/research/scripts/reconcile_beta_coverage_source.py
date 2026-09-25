"""Recover one saved paid source-query plan without another model call."""

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
    from .plan_beta_coverage_source import persist_coverage_source_plan
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import MODEL, PROVIDER
    from plan_beta_coverage_source import persist_coverage_source_plan

from hermes_research_report.beta_coverage_query import (
    build_coverage_query_prompt,
    select_coverage_atom,
)
from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.canonical import (
    sha256_json,
    verify_receipt_hash,
    with_receipt_hash,
)
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = args.output
        if (
            not output.is_absolute()
            or output.is_symlink()
            or not output.is_dir()
            or stat.S_IMODE(output.stat().st_mode) & 0o077
            or any(
                (output / name).exists() for name in ("plan.json", "batch-plan.json")
            )
        ):
            raise ValueError("coverage_source_reconciliation_not_allowed")
        attempt, _ = load_json(output / "attempt.json")
        failure, _ = load_json(output / "failure.json")
        usage, _ = load_json(output / "model-usage.json")
        trace, _ = load_json(output / "model-trace.json")
        if any(type(item) is not dict for item in (attempt, failure, usage, trace)):
            raise ValueError("coverage_source_saved_record_invalid")
        attempt = cast(dict[str, Any], attempt)
        failure = cast(dict[str, Any], failure)
        usage = cast(dict[str, Any], usage)
        trace = cast(dict[str, Any], trace)
        batch_run_id = attempt.get("run_id")
        if (
            type(batch_run_id) is not str
            or not batch_run_id.endswith("-B01")
            or output.name != f"{batch_run_id}-coverage-source-plan"
        ):
            raise ValueError("coverage_source_saved_attempt_not_bound")
        run_id = batch_run_id.removesuffix("-B01")
        frame, _ = load_json(
            output.parent / f"{run_id}-coverage-route-repair/frame.json"
        )
        review, _ = load_json(
            output.parent / f"{run_id}-coverage-route-review/review.json"
        )
        if (
            type(frame) is not dict
            or type(review) is not dict
            or not verify_receipt_hash(frame)
            or not verify_receipt_hash(review)
            or review.get("frame_receipt_hash") != frame["receipt_hash"]
        ):
            raise ValueError("coverage_source_lineage_invalid")
        frame = cast(dict[str, Any], frame)
        review = cast(dict[str, Any], review)
        atom = select_coverage_atom(frame, [])
        prompt = build_coverage_query_prompt(atom)
        budget = {
            "schema_version": 1,
            "run_id": batch_run_id,
            "wall_seconds": 60,
            "max_estimated_cost_usd": 0.01,
            "model_calls": 1,
        }
        raw = (
            read_private_bytes(output / "model.raw.json", maximum=1_048_576)
            .decode("utf-8")
            .rstrip("\n")
        )
        messages = trace.get("messages")
        if (
            attempt.get("purpose") != "coverage_atom_source_query_plan"
            or attempt.get("frame_receipt_hash") != frame["receipt_hash"]
            or attempt.get("review_receipt_hash") != review["receipt_hash"]
            or attempt.get("atom_id") != atom["atom_id"]
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
            raise ValueError("coverage_source_saved_attempt_not_bound")
        validate_tool_free_observation(
            max_estimated_cost_usd=0.01,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
            max_total_tokens=attempt["max_total_tokens"],
        )
        plan, batch = persist_coverage_source_plan(
            output=output,
            frame=frame,
            review=review,
            atom_id=atom["atom_id"],
            batch_number=1,
            raw=raw,
            usage=usage,
            trace=trace,
            reconciled=True,
        )
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageSourcePlanningReconciliation",
                "run_id": run_id,
                "batch_run_id": batch_run_id,
                "plan_receipt_hash": plan["receipt_hash"],
                "batch_plan_receipt_hash": batch["receipt_hash"],
                "previous_failure_reason": failure.get("reason_code"),
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "reconciliation.json", receipt)
        print(
            json.dumps(
                {
                    "status": "source_batch_reconciled",
                    "batch_run_id": batch_run_id,
                    "atom_id": atom["atom_id"],
                    "additional_model_calls": 0,
                }
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
