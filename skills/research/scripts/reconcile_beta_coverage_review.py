"""Reparse one saved paid coverage review; never call the model again."""

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
    from .review_beta_coverage import persist_coverage_review
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import MODEL, PROVIDER
    from review_beta_coverage import persist_coverage_review

from hermes_research_report.beta_coverage_planner import build_coverage_review_prompt
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
                (output / name).exists() for name in ("review.json", "review-run.json")
            )
        ):
            raise ValueError("coverage_review_reconciliation_not_allowed")
        attempt, _ = load_json(output / "attempt.json")
        failure, _ = load_json(output / "failure.json")
        usage, _ = load_json(output / "model-usage.json")
        trace, _ = load_json(output / "model-trace.json")
        if any(type(value) is not dict for value in (attempt, failure, usage, trace)):
            raise ValueError("coverage_review_saved_record_invalid")
        attempt = cast(dict[str, Any], attempt)
        failure = cast(dict[str, Any], failure)
        usage = cast(dict[str, Any], usage)
        trace = cast(dict[str, Any], trace)
        run_id = attempt.get("run_id")
        if type(run_id) is not str or output.name != f"{run_id}-coverage-review":
            raise ValueError("coverage_review_saved_attempt_not_bound")
        planning = output.parent / f"{run_id}-coverage-planning"
        frame, _ = load_json(planning / "frame.json")
        generator, _ = load_json(planning / "planning-run.json")
        if (
            type(frame) is not dict
            or not verify_receipt_hash(frame)
            or type(generator) is not dict
            or not verify_receipt_hash(generator)
            or generator.get("contract") != "BetaCoveragePlanningRun"
            or generator.get("frame_receipt_hash") != frame["receipt_hash"]
            or frame.get("run_id") != run_id
        ):
            raise ValueError("coverage_review_generator_not_bound")
        frame = cast(dict[str, Any], frame)
        generator = cast(dict[str, Any], generator)
        budget = {
            "schema_version": 1,
            "run_id": run_id,
            "wall_seconds": 60,
            "max_estimated_cost_usd": 0.01,
            "model_calls": 1,
        }
        prompt_hashes = {
            hashlib.sha256(build_coverage_review_prompt(frame).encode()).hexdigest(),
            hashlib.sha256(
                build_coverage_review_prompt(frame, space_enum_explicit=False).encode()
            ).hexdigest(),
        }
        raw = (
            read_private_bytes(output / "model.raw.json", maximum=1_048_576)
            .decode("utf-8")
            .rstrip("\n")
        )
        messages = trace.get("messages")
        if (
            attempt.get("purpose") != "adversarial_coverage_review"
            or attempt.get("frame_receipt_hash") != frame["receipt_hash"]
            or attempt.get("bootstrap_budget_hash") != sha256_json(budget)
            or attempt.get("prompt_sha256") not in prompt_hashes
            or attempt.get("provider") != PROVIDER
            or attempt.get("model") != MODEL
            or attempt.get("retry_allowed") is not False
            or failure.get("reconciliation_required") is not True
            or failure.get("retry_allowed") is not False
            or type(messages) is not list
            or len(messages) != 2
            or hashlib.sha256(messages[0].get("content", "").encode()).hexdigest()
            != attempt.get("prompt_sha256")
            or messages[1].get("content", "").strip() != raw
        ):
            raise ValueError("coverage_review_saved_attempt_not_bound")
        validate_tool_free_observation(
            max_estimated_cost_usd=0.01,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
        )
        review, run = persist_coverage_review(
            output=output,
            frame=frame,
            generator=generator,
            raw=raw,
            usage=usage,
            trace=trace,
            reconciled=True,
        )
        reconciliation = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageReviewReconciliation",
                "run_id": run_id,
                "previous_failure_reason": failure.get("reason_code"),
                "review_receipt_hash": review["receipt_hash"],
                "review_run_receipt_hash": run["receipt_hash"],
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "reconciliation.json", reconciliation)
        print(
            json.dumps(
                {
                    "status": review["verdict"],
                    "run_id": run_id,
                    "issue_count": review["issue_count"],
                    "additional_model_calls": 0,
                    "independence_verified": False,
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
