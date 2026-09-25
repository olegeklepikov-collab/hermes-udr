"""Expose a saved paid revision as a graded draft when its contract fails."""

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
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import MODEL, PROVIDER

from hermes_research_report.beta_coverage_planner import (
    build_coverage_revision_prompt,
    parse_coverage_revision,
)
from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.canonical import (
    sha256_json,
    verify_receipt_hash,
    with_receipt_hash,
)
from hermes_research_report.errors import ContractError


def _draft(raw: str, *, frame: dict, review: dict, reason: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = None
    facets = value.get("facets") if type(value) is dict else None
    atoms = value.get("atoms") if type(value) is dict else None
    candidate_facets = (
        [
            row.get("name")
            for row in facets
            if type(row) is dict and type(row.get("name")) is str
        ]
        if type(facets) is list
        else []
    )
    candidate_questions = (
        [
            row.get("question")
            for row in atoms
            if type(row) is dict and type(row.get("question")) is str
        ]
        if type(atoms) is list
        else []
    )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageRevisionDraft",
            "run_id": frame["run_id"],
            "parent_frame_receipt_hash": frame["receipt_hash"],
            "review_receipt_hash": review["receipt_hash"],
            "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "candidate_facet_names": candidate_facets,
            "candidate_questions": candidate_questions,
            "reported_facet_count": len(candidate_facets),
            "reported_question_count": len(candidate_questions),
            "contract_error": reason,
            "source_strategy_verified": False,
            "semantic_atomicity_verified": False,
            "ready_for_source_calls": False,
            "release_authorized": False,
        }
    )


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
                (output / name).exists()
                for name in ("frame.json", "revision-draft.json", "reconciliation.json")
            )
        ):
            raise ValueError("coverage_revision_reconciliation_not_allowed")
        attempt, _ = load_json(output / "attempt.json")
        failure, _ = load_json(output / "failure.json")
        usage, _ = load_json(output / "model-usage.json")
        trace, _ = load_json(output / "model-trace.json")
        if any(type(item) is not dict for item in (attempt, failure, usage, trace)):
            raise ValueError("coverage_revision_saved_record_invalid")
        attempt = cast(dict[str, Any], attempt)
        failure = cast(dict[str, Any], failure)
        usage = cast(dict[str, Any], usage)
        trace = cast(dict[str, Any], trace)
        run_id = attempt.get("run_id")
        if type(run_id) is not str or output.name != f"{run_id}-coverage-revision-02":
            raise ValueError("coverage_revision_saved_attempt_not_bound")
        planning = output.parent / f"{run_id}-coverage-planning"
        checking = output.parent / f"{run_id}-coverage-review"
        frame, _ = load_json(planning / "frame.json")
        review, _ = load_json(checking / "review.json")
        if (
            type(frame) is not dict
            or type(review) is not dict
            or not verify_receipt_hash(frame)
            or not verify_receipt_hash(review)
        ):
            raise ValueError("coverage_revision_lineage_invalid")
        frame = cast(dict[str, Any], frame)
        review = cast(dict[str, Any], review)
        prompt = build_coverage_revision_prompt(frame, review)
        budget = {
            "schema_version": 1,
            "run_id": run_id,
            "wall_seconds": 120,
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
            attempt.get("purpose") != "coverage_frame_revision"
            or attempt.get("parent_frame_receipt_hash") != frame["receipt_hash"]
            or attempt.get("review_receipt_hash") != review["receipt_hash"]
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
            raise ValueError("coverage_revision_saved_attempt_not_bound")
        validate_tool_free_observation(
            max_estimated_cost_usd=0.01,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
            max_total_tokens=30_000,
        )
        declared_limit = attempt.get("max_total_tokens")
        observed_tokens = usage.get("total_tokens")
        if type(declared_limit) is not int or type(observed_tokens) is not int:
            raise ValueError("coverage_revision_token_receipt_invalid")
        try:
            revised, proposal, revision = parse_coverage_revision(
                raw, frame=frame, review=review
            )
        except ValueError as error:
            reason = str(error)
            draft = _draft(raw, frame=frame, review=review, reason=reason)
            write_exclusive_json(output / "revision-draft.json", draft)
            outcome_hash = draft["receipt_hash"]
            status = "unvalidated_revision_draft"
        else:
            for name, value in (
                ("frame.json", revised),
                ("proposal.json", proposal),
                ("revision.json", revision),
            ):
                write_exclusive_json(output / name, value)
            outcome_hash = revision["receipt_hash"]
            status = "revised_provisional_frame"
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageRevisionReconciliation",
                "run_id": run_id,
                "previous_failure_reason": failure.get("reason_code"),
                "outcome_status": status,
                "outcome_receipt_hash": outcome_hash,
                "declared_token_limit": declared_limit,
                "observed_total_tokens": observed_tokens,
                "token_limit_violated": observed_tokens > declared_limit,
                "reported_model_cost_usd": usage["estimated_cost_usd"],
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "reconciliation.json", receipt)
        print(
            json.dumps(
                {
                    "status": status,
                    "run_id": run_id,
                    "token_limit_violated": receipt["token_limit_violated"],
                    "additional_model_calls": 0,
                    "source_calls": 0,
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
