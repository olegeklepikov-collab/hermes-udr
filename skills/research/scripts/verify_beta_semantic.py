"""Isolated model challenge of one saved exact-quote candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .draft_beta_model import _preflight
    from .file_io import fsync_directory, load_json, write_exclusive_json
    from .model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model
except ImportError:
    from draft_beta_model import _preflight
    from file_io import fsync_directory, load_json, write_exclusive_json
    from model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model

from hermes_research_report.beta_semantic import (
    build_semantic_prompt,
    validate_semantic_verification,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def finalize_semantic_check(
    *,
    plan: dict,
    portfolio: dict,
    candidate: dict,
    source_text: str,
    prompt: str,
    raw: str,
    usage: dict,
    trace: object,
    output: Path,
) -> dict:
    check = validate_semantic_verification(
        raw,
        plan=plan,
        candidate=candidate,
        source_text=source_text,
        prompt=prompt,
        usage=usage,
        trace=trace,
        provider=PROVIDER,
        model=MODEL,
    )
    total_cost = (
        portfolio["reported_provider_cost_usd"]
        + candidate["estimated_cost_usd"]
        + check["estimated_cost_usd"]
    )
    if total_cost > plan["limits"]["max_estimated_cost_usd"]:
        raise ValueError("cumulative_cost_limit_exceeded")
    body = dict(check)
    body.pop("receipt_hash")
    body["reported_total_cost_usd"] = total_cost
    check = with_receipt_hash(body)
    write_exclusive_json(output / "semantic-check.json", check)
    fsync_directory(output)
    return check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--web-capture", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    model_completed = False
    try:
        plan, portfolio, capture, source_id, _title, text, _prompt = _preflight(
            args.plan, args.portfolio, args.web_capture
        )
        if plan["limits"]["model_calls"] < 2:
            raise ValueError("semantic_model_call_not_budgeted")
        if (
            args.draft.name != f"{plan['run_id']}-model"
            or args.draft.is_symlink()
            or args.output.name != f"{plan['run_id']}-verify"
        ):
            raise ValueError("semantic_paths_invalid")
        candidate_value, _ = load_json(args.draft / "model-candidate.json")
        if type(candidate_value) is not dict:
            raise ValueError("semantic_candidate_invalid")
        candidate = candidate_value
        if (
            not verify_receipt_hash(candidate)
            or candidate.get("source_id") != source_id
            or candidate.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
            or candidate.get("status") != "verification_required"
            or candidate.get("observed_tool_calls") != 0
            or candidate.get("release_authorized") is not False
        ):
            raise ValueError("semantic_candidate_not_bound")
        prompt = build_semantic_prompt(plan, candidate, source_text=text)
        raw, usage, trace = run_tool_free_model(
            plan=plan,
            prompt=prompt,
            hermes=args.hermes,
            output=args.output,
            attempt_binding={
                "portfolio_receipt_hash": portfolio["receipt_hash"],
                "source_receipt_hash": capture["receipt_hash"],
                "candidate_receipt_hash": candidate["receipt_hash"],
                "draft_session_id": candidate["session_id"],
            },
        )
        model_completed = True
        check = finalize_semantic_check(
            plan=plan,
            portfolio=portfolio,
            candidate=candidate,
            source_text=text,
            prompt=prompt,
            raw=raw,
            usage=usage,
            trace=trace,
            output=args.output,
        )
        print(
            json.dumps(
                {
                    "status": check["status"],
                    "verdict": check["verdict"],
                    "run_id": check["run_id"],
                    "model_check_only": True,
                    "semantic_support_verified": False,
                    "release_authorized": False,
                    "total_tokens": check["total_tokens"],
                    "reported_total_cost_usd": check["reported_total_cost_usd"],
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
            else "semantic_verification_failed"
        )
        if model_completed:
            try:
                write_exclusive_json(
                    args.output / "failure.json",
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
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
