"""Isolated semantic challenge of one exact article-text draft."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .execute_beta_sources import _publisher_readback
    from .file_io import (
        fsync_directory,
        load_json,
        read_private_bytes,
        write_exclusive_json,
    )
    from .model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model
    from .screen_openalex_oa_text import _preflight as _article_preflight
except ImportError:
    from execute_beta_sources import _publisher_readback
    from file_io import (
        fsync_directory,
        load_json,
        read_private_bytes,
        write_exclusive_json,
    )
    from model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model
    from screen_openalex_oa_text import _preflight as _article_preflight

from hermes_research_report.beta_semantic import (
    build_semantic_prompt,
    validate_semantic_verification,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def _preflight(
    plan_file: Path,
    metadata_file: Path,
    article_file: Path,
    publisher_file: Path,
    screen_dir: Path,
    execution_file: Path,
) -> tuple[dict, dict, dict, dict, dict, dict, dict, str, str, float]:
    (
        plan,
        metadata,
        article,
        source_id,
        _text,
        excerpt,
        _draft_prompt,
        _metadata_cost,
    ) = _article_preflight(plan_file, metadata_file, article_file)
    if plan["limits"]["model_calls"] < 2:
        raise ValueError("article_semantic_call_not_budgeted")
    short = article["work_id"].removeprefix("https://openalex.org/")
    leaf_id = article["leaf_id"]
    if (
        publisher_file.name != "capture.json"
        or publisher_file.parent.name
        != f"{plan['run_id']}-{leaf_id}-{short}-publisher-raw"
        or publisher_file.parent.is_symlink()
        or screen_dir.name != f"{plan['run_id']}-{leaf_id}-{short}-screen"
        or screen_dir.is_symlink()
        or execution_file.name != "execution.json"
        or execution_file.parent.name != f"{plan['run_id']}-execution"
        or execution_file.parent.is_symlink()
    ):
        raise ValueError("article_semantic_paths_invalid")
    publisher = _publisher_readback(publisher_file, plan, metadata, article)
    if (
        publisher.get("status") != "publisher_html_candidate"
        or publisher.get("redirect_chain_verified") is not True
        or publisher.get("publisher_extracted_text_overlap_verified") is not True
        or publisher.get("publisher_license_corroborated") is not True
    ):
        raise ValueError("article_publisher_not_attested")
    screen_value, _ = load_json(screen_dir / "screen.json")
    candidate_value, _ = load_json(screen_dir / "model-candidate.json")
    execution_value, _ = load_json(execution_file)
    if any(
        type(value) is not dict
        for value in (screen_value, candidate_value, execution_value)
    ):
        raise ValueError("article_semantic_receipts_invalid")
    screen, candidate, execution = screen_value, candidate_value, execution_value
    if (
        not all(verify_receipt_hash(value) for value in (screen, candidate, execution))
        or screen.get("contract") != "BetaOpenAlexArticleScreen"
        or screen.get("status") != "verification_required"
        or screen.get("plan_receipt_hash") != plan["receipt_hash"]
        or screen.get("metadata_receipt_hash") != metadata["receipt_hash"]
        or screen.get("article_receipt_hash") != article["receipt_hash"]
        or screen.get("source_id") != source_id
        or screen.get("accepted_claim_count") != 0
        or screen.get("candidate_receipt_hash") != candidate["receipt_hash"]
        or screen.get("release_authorized") is not False
        or candidate.get("status") != "verification_required"
        or candidate.get("source_id") != source_id
        or candidate.get("plan_receipt_hash") != plan["receipt_hash"]
        or candidate.get("source_text_sha256") != screen["excerpt_sha256"]
        or candidate.get("exact_quote_verified") is not True
        or candidate.get("observed_tool_calls") != 0
        or candidate.get("release_authorized") is not False
        or execution.get("contract") != "BetaAutomaticSourceExecution"
        or execution.get("run_id") != plan["run_id"]
        or execution.get("plan_receipt_hash") != plan["receipt_hash"]
        or execution.get("accepted_claim_count") != 0
        or execution.get("release_authorized") is not False
        or not any(
            type(item) is dict and item.get("receipt_hash") == screen["receipt_hash"]
            for item in execution.get("article_screens", [])
        )
        or not any(
            type(item) is dict and item.get("receipt_hash") == publisher["receipt_hash"]
            for item in execution.get("publisher_raw_attempts", [])
        )
    ):
        raise ValueError("article_semantic_not_bound")
    cost = execution.get("reported_total_cost_usd")
    if (
        type(cost) not in (int, float)
        or not 0 <= cost <= plan["limits"]["max_estimated_cost_usd"]
    ):
        raise ValueError("article_semantic_prior_cost_invalid")
    prompt = build_semantic_prompt(
        plan, candidate, source_text=excerpt, source_scope="excerpt"
    )
    return (
        plan,
        metadata,
        article,
        publisher,
        screen,
        candidate,
        execution,
        excerpt,
        prompt,
        float(cost),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--metadata-capture", type=Path, required=True)
    parser.add_argument("--article-capture", type=Path, required=True)
    parser.add_argument("--publisher-capture", type=Path, required=True)
    parser.add_argument("--screen-dir", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reconcile-saved", action="store_true")
    args = parser.parse_args(argv)
    model_completed = False
    try:
        (
            plan,
            _metadata,
            article,
            publisher,
            screen,
            candidate,
            execution,
            excerpt,
            prompt,
            prior_cost,
        ) = _preflight(
            args.plan,
            args.metadata_capture,
            args.article_capture,
            args.publisher_capture,
            args.screen_dir,
            args.execution,
        )
        short = article["work_id"].removeprefix("https://openalex.org/")
        if args.output.name != f"{plan['run_id']}-{article['leaf_id']}-{short}-verify":
            raise ValueError("article_semantic_output_name_invalid")
        if args.reconcile_saved:
            if (
                args.output.is_symlink()
                or not args.output.is_dir()
                or (args.output / "semantic-check.json").exists()
            ):
                raise ValueError("article_semantic_reconciliation_not_allowed")
            attempt_value, _ = load_json(args.output / "attempt.json")
            failure_value, _ = load_json(args.output / "failure.json")
            usage_value, _ = load_json(args.output / "model-usage.json")
            trace_value, _ = load_json(args.output / "model-trace.json")
            if any(
                type(value) is not dict
                for value in (attempt_value, failure_value, usage_value, trace_value)
            ):
                raise ValueError("article_semantic_saved_invalid")
            attempt, failure, usage, trace = (
                attempt_value,
                failure_value,
                usage_value,
                trace_value,
            )
            raw = (
                read_private_bytes(args.output / "model.raw.json", maximum=6000)
                .decode("utf-8")
                .rstrip("\n")
            )
            if (
                attempt.get("run_id") != plan["run_id"]
                or attempt.get("plan_receipt_hash") != plan["receipt_hash"]
                or attempt.get("execution_receipt_hash") != execution["receipt_hash"]
                or attempt.get("publisher_receipt_hash") != publisher["receipt_hash"]
                or attempt.get("screen_receipt_hash") != screen["receipt_hash"]
                or attempt.get("candidate_receipt_hash") != candidate["receipt_hash"]
                or attempt.get("prompt_sha256")
                != hashlib.sha256(prompt.encode()).hexdigest()
                or attempt.get("provider") != PROVIDER
                or attempt.get("model") != MODEL
                or attempt.get("retry_allowed") is not False
                or failure.get("reason_code") != "semantic_response_schema_invalid"
                or failure.get("reconciliation_required") is not True
                or failure.get("retry_allowed") is not False
            ):
                raise ValueError("article_semantic_saved_not_bound")
            messages = trace.get("messages")
            if (
                type(messages) is not list
                or len(messages) != 2
                or type(messages[0]) is not dict
                or type(messages[1]) is not dict
                or messages[0].get("content") != prompt
                or messages[1].get("content", "").strip() != raw
            ):
                raise ValueError("article_semantic_trace_invalid")
        else:
            raw, usage, trace = run_tool_free_model(
                plan=plan,
                prompt=prompt,
                hermes=args.hermes,
                output=args.output,
                attempt_binding={
                    "execution_receipt_hash": execution["receipt_hash"],
                    "publisher_receipt_hash": publisher["receipt_hash"],
                    "screen_receipt_hash": screen["receipt_hash"],
                    "candidate_receipt_hash": candidate["receipt_hash"],
                    "draft_session_id": candidate["session_id"],
                },
            )
            model_completed = True
        check = validate_semantic_verification(
            raw,
            plan=plan,
            candidate=candidate,
            source_text=excerpt,
            prompt=prompt,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
            source_scope="excerpt",
        )
        total_cost = round(prior_cost + check["estimated_cost_usd"], 8)
        if total_cost > plan["limits"]["max_estimated_cost_usd"]:
            raise ValueError("article_semantic_cumulative_cost_exceeded")
        body = dict(check)
        body.pop("receipt_hash")
        body.update(
            {
                "execution_receipt_hash": execution["receipt_hash"],
                "publisher_receipt_hash": publisher["receipt_hash"],
                "screen_receipt_hash": screen["receipt_hash"],
                "source_scope": "excerpt_first_12000",
                "reported_total_cost_usd": total_cost,
                "accepted_claim_count": 0,
                "provisional_claim_count": 1 if check["verdict"] == "supported" else 0,
                "reconciled_without_new_model_call": args.reconcile_saved,
                "additional_model_calls": 0 if args.reconcile_saved else 1,
            }
        )
        check = with_receipt_hash(body)
        write_exclusive_json(args.output / "semantic-check.json", check)
        fsync_directory(args.output)
        print(
            json.dumps(
                {
                    "status": check["status"],
                    "verdict": check["verdict"],
                    "run_id": plan["run_id"],
                    "accepted_claim_count": 0,
                    "provisional_claim_count": check["provisional_claim_count"],
                    "reported_total_cost_usd": total_cost,
                    "mode_qualified": False,
                    "release_authorized": False,
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
            else "article_semantic_failed"
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
