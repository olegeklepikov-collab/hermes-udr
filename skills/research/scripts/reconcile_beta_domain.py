"""Recover a saved paid domain decomposition without recontacting the model."""

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
    from .plan_beta_domain import persist_domain_result
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import MODEL, PROVIDER
    from plan_beta_domain import persist_domain_result

from hermes_research_report.beta_domain_decomposition import (
    build_domain_decomposition_prompt,
)
from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.beta_modes import validate_public_question
from hermes_research_report.canonical import sha256_json, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--profile", choices=("search", "deep", "ultra", "academic"), required=True
    )
    args = parser.parse_args(argv)
    try:
        output = args.output
        question = validate_public_question(args.question)
        if (
            not output.is_absolute()
            or output.is_symlink()
            or not output.is_dir()
            or stat.S_IMODE(output.stat().st_mode) & 0o077
            or (output / "decomposition.json").exists()
        ):
            raise ValueError("domain_reconciliation_not_allowed")
        attempt, _ = load_json(output / "attempt.json")
        failure, _ = load_json(output / "failure.json")
        usage, _ = load_json(output / "model-usage.json")
        trace, _ = load_json(output / "model-trace.json")
        if any(type(value) is not dict for value in (attempt, failure, usage, trace)):
            raise ValueError("domain_saved_record_invalid")
        attempt = cast(dict[str, Any], attempt)
        failure = cast(dict[str, Any], failure)
        usage = cast(dict[str, Any], usage)
        trace = cast(dict[str, Any], trace)
        run_id = attempt.get("run_id")
        if type(run_id) is not str or output.name != f"{run_id}-domain-planning":
            raise ValueError("domain_saved_attempt_not_bound")
        budget = {
            "schema_version": 1,
            "run_id": run_id,
            "wall_seconds": 120,
            "max_estimated_cost_usd": attempt.get("max_estimated_cost_usd"),
            "model_calls": 1,
        }
        prompt_hashes = {
            hashlib.sha256(
                build_domain_decomposition_prompt(
                    question=question,
                    profile=args.profile,
                    legacy_rule_instruction=legacy,
                    legacy_coverage_instruction=legacy_coverage,
                ).encode()
            ).hexdigest()
            for legacy in (False, True)
            for legacy_coverage in (False, True)
        }
        raw = (
            read_private_bytes(output / "model.raw.json", maximum=1_048_576)
            .decode("utf-8")
            .rstrip("\n")
        )
        messages = trace.get("messages")
        if (
            attempt.get("purpose") != "domain_construct_decomposition"
            or attempt.get("profile") != args.profile
            or attempt.get("question_sha256")
            != hashlib.sha256(question.encode()).hexdigest()
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
            raise ValueError("domain_saved_attempt_not_bound")
        validate_tool_free_observation(
            max_estimated_cost_usd=attempt["max_estimated_cost_usd"],
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
            max_total_tokens=attempt["max_total_tokens"],
            preserve_completed_cost_overrun=True,
        )
        decomposition, run = persist_domain_result(
            output=output,
            raw=raw,
            question=question,
            profile=args.profile,
            run_id=run_id,
            usage=usage,
            trace=trace,
            reconciled=True,
            cost_limit_usd=attempt["max_estimated_cost_usd"],
        )
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaDomainPlanningReconciliation",
                "run_id": run_id,
                "prior_failure_reason": failure.get("reason_code"),
                "decomposition_receipt_hash": decomposition["receipt_hash"],
                "planning_run_receipt_hash": run["receipt_hash"],
                "constructs_with_missing_operational_rule": decomposition[
                    "constructs_with_missing_operational_rule"
                ],
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "reconciliation.json", receipt)
        print(
            json.dumps(
                {
                    "status": "provisional_domain_reconciled",
                    "run_id": run_id,
                    "domain_count": len(decomposition["domains"]),
                    "aspect_count": len(decomposition["aspects"]),
                    "construct_count": len(decomposition["constructs"]),
                    "constructs_with_missing_operational_rule": decomposition[
                        "constructs_with_missing_operational_rule"
                    ],
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
