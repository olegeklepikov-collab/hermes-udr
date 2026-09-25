"""Reparse a saved semantic-check attempt without another model call."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .draft_beta_model import _preflight
    from .file_io import load_json, read_private_bytes, write_exclusive_json
    from .verify_beta_semantic import finalize_semantic_check
except ImportError:
    from draft_beta_model import _preflight
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from verify_beta_semantic import finalize_semantic_check

from hermes_research_report.beta_semantic import build_semantic_prompt
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--web-capture", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--attempt-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan, portfolio, capture, source_id, _title, text, _draft_prompt = _preflight(
            args.plan, args.portfolio, args.web_capture
        )
        output = args.attempt_dir
        if (
            args.draft.name != f"{plan['run_id']}-model"
            or args.draft.is_symlink()
            or output.name != f"{plan['run_id']}-verify"
            or not output.is_absolute()
            or output.is_symlink()
            or not output.is_dir()
            or stat.S_IMODE(output.stat().st_mode) & 0o077
            or (output / "semantic-check.json").exists()
            or (output.parent / f"{plan['run_id']}-result").exists()
        ):
            raise ValueError("semantic_reconciliation_not_allowed")
        candidate_value, _ = load_json(args.draft / "model-candidate.json")
        attempt_value, _ = load_json(output / "attempt.json")
        failure_value, _ = load_json(output / "failure.json")
        usage_value, _ = load_json(output / "model-usage.json")
        trace_value, _ = load_json(output / "model-trace.json")
        if any(
            type(value) is not dict
            for value in (
                candidate_value,
                attempt_value,
                failure_value,
                usage_value,
                trace_value,
            )
        ):
            raise ValueError("semantic_saved_record_invalid")
        candidate, attempt, failure, usage, trace = (
            candidate_value,
            attempt_value,
            failure_value,
            usage_value,
            trace_value,
        )
        if (
            not verify_receipt_hash(candidate)
            or candidate.get("status") != "verification_required"
            or candidate.get("source_id") != source_id
            or candidate.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
            or candidate.get("release_authorized") is not False
            or attempt.get("run_id") != plan["run_id"]
            or attempt.get("plan_receipt_hash") != plan["receipt_hash"]
            or attempt.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
            or attempt.get("source_receipt_hash") != capture["receipt_hash"]
            or attempt.get("candidate_receipt_hash") != candidate["receipt_hash"]
            or attempt.get("draft_session_id") != candidate["session_id"]
            or attempt.get("retry_allowed") is not False
            or failure.get("status") != "failed_or_unknown"
            or failure.get("reconciliation_required") is not True
            or failure.get("retry_allowed") is not False
        ):
            raise ValueError("semantic_saved_attempt_not_bound")
        prompt = build_semantic_prompt(plan, candidate, source_text=text)
        raw = (
            read_private_bytes(output / "model.raw.json", maximum=6000)
            .decode("utf-8")
            .rstrip("\n")
        )
        messages = trace.get("messages")
        if type(messages) is not list or len(messages) != 2:
            raise ValueError("semantic_saved_trace_invalid")
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
            user_content != prompt
            or type(user_content) is not str
            or hashlib.sha256(user_content.encode()).hexdigest()
            != attempt.get("prompt_sha256")
            or type(assistant_content) is not str
            or assistant_content.strip() != raw
        ):
            raise ValueError("semantic_saved_trace_invalid")
        check = finalize_semantic_check(
            plan=plan,
            portfolio=portfolio,
            candidate=candidate,
            source_text=text,
            prompt=prompt,
            raw=raw,
            usage=usage,
            trace=trace,
            output=output,
        )
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaSemanticReconciliation",
                "run_id": plan["run_id"],
                "previous_failure_reason": failure.get("reason_code"),
                "semantic_check_receipt_hash": check["receipt_hash"],
                "additional_model_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "reconciliation.json", receipt)
        print(
            json.dumps(
                {
                    "status": check["status"],
                    "verdict": check["verdict"],
                    "run_id": plan["run_id"],
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
            else "semantic_reconciliation_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
