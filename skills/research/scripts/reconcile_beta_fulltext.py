"""Reconcile a saved over-limit full-text response without a second model call."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .analyze_beta_fulltext import build_fulltext_prompt, validate_fulltext_cards
    from .file_io import load_json, read_private_bytes, write_exclusive_json
    from .model_call import MODEL, PROVIDER
except ImportError:
    from analyze_beta_fulltext import build_fulltext_prompt, validate_fulltext_cards
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import MODEL, PROVIDER

from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError

_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--fulltext", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan_value, _ = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        fulltext_value, _ = load_json(args.fulltext)
        if (
            plan["mode"] != "academic"
            or type(fulltext_value) is not dict
            or not verify_receipt_hash(fulltext_value)
            or fulltext_value.get("contract") != "BetaArxivFullTextRead"
            or fulltext_value.get("plan_receipt_hash") != plan["receipt_hash"]
        ):
            raise ValueError("fulltext_reconciliation_source_invalid")
        fulltext = fulltext_value
        if (
            args.plan != args.output_root / f"{plan['run_id']}-planning/plan.json"
            or args.output_root.is_symlink()
            or args.fulltext.is_symlink()
            or args.fulltext.parent.is_symlink()
        ):
            raise ValueError("fulltext_reconciliation_paths_invalid")
        text_bytes = read_private_bytes(
            args.fulltext.parent / "paper.md", maximum=25_000_000
        )
        pdf = read_private_bytes(args.fulltext.parent / "paper.pdf", maximum=50_000_000)
        if (
            hashlib.sha256(text_bytes).hexdigest() != fulltext["text_sha256"]
            or hashlib.sha256(pdf).hexdigest() != fulltext["pdf_sha256"]
        ):
            raise ValueError("fulltext_reconciliation_bytes_invalid")
        text = text_bytes.decode("utf-8")
        prompt = build_fulltext_prompt(plan, fulltext, text)
        output = args.output_root / f"{plan['run_id']}-academic-fulltext-analysis"
        if (
            output.is_symlink()
            or not output.is_dir()
            or (output / "analysis.json").exists()
            or (output / "analysis-reconciled.json").exists()
        ):
            raise ValueError("fulltext_reconciliation_not_allowed")
        attempt_value, _ = load_json(output / "attempt.json")
        failure_value, _ = load_json(output / "failure.json")
        usage_value, _ = load_json(output / "model-usage.json")
        trace_value, _ = load_json(output / "model-trace.json")
        if any(
            type(value) is not dict
            for value in (attempt_value, failure_value, usage_value, trace_value)
        ):
            raise ValueError("fulltext_reconciliation_saved_invalid")
        attempt, failure, usage, trace = (
            attempt_value,
            failure_value,
            usage_value,
            trace_value,
        )
        raw = (
            read_private_bytes(output / "model.raw.json", maximum=6000)
            .decode("utf-8")
            .rstrip("\n")
        )
        if (
            attempt.get("run_id") != plan["run_id"]
            or attempt.get("plan_receipt_hash") != plan["receipt_hash"]
            or attempt.get("fulltext_receipt_hash") != fulltext["receipt_hash"]
            or attempt.get("source_scope") != "parsed_pdf_text_layout_unverified"
            or attempt.get("prompt_sha256")
            != hashlib.sha256(prompt.encode()).hexdigest()
            or attempt.get("provider") != PROVIDER
            or attempt.get("model") != MODEL
            or attempt.get("max_total_tokens") != 10_000
            or attempt.get("retry_allowed") is not False
            or failure.get("reason_code") != "model_budget_or_route_invalid"
            or failure.get("reconciliation_required") is not True
            or failure.get("retry_allowed") is not False
        ):
            raise ValueError("fulltext_reconciliation_attempt_invalid")
        messages = trace.get("messages")
        if (
            type(messages) is not list
            or len(messages) != 2
            or type(messages[0]) is not dict
            or type(messages[1]) is not dict
            or messages[0].get("content") != prompt
            or messages[1].get("content", "").strip() != raw
        ):
            raise ValueError("fulltext_reconciliation_trace_invalid")
        tokens, _cost, _session = validate_tool_free_observation(
            plan=plan,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
            max_total_tokens=30_000,
        )
        if tokens <= 10_000:
            raise ValueError("fulltext_reconciliation_limit_not_exceeded")
        result = validate_fulltext_cards(
            raw, plan=plan, fulltext=fulltext, text=text, usage=usage, trace=trace
        )
        body = dict(result)
        body.pop("receipt_hash")
        body.update(
            {
                "historical_declared_token_limit": 10_000,
                "observed_total_tokens": tokens,
                "historical_token_limit_exceeded": True,
                "reconciled_without_new_model_call": True,
                "additional_model_calls": 0,
                "prior_failure_reason": failure["reason_code"],
            }
        )
        result = with_receipt_hash(body)
        write_exclusive_json(output / "analysis-reconciled.json", result)
        print(
            json.dumps(
                {
                    "status": "author_statements_reconciled",
                    "run_id": plan["run_id"],
                    "reported_statement_count": result["reported_statement_count"],
                    "exact_quote_count": result["exact_quote_count"],
                    "unanchored_count": result["unanchored_count"],
                    "additional_model_calls": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, OSError, ValueError, UnicodeError) as error:
        code = error.code if isinstance(error, ContractError) else str(error)
        if not _CODE.fullmatch(code):
            code = "fulltext_reconciliation_failed"
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
