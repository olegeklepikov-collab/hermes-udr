"""Recover saved paid PDF-text chunks and aggregate them without new calls."""

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
    from .analyze_beta_fulltext import (
        aggregate_chunk_analyses,
        build_chunk_prompt,
        chunk_ranges,
        validate_fulltext_cards,
    )
    from .file_io import load_json, read_private_bytes, write_exclusive_json
    from .model_call import MODEL, PROVIDER, run_tool_free_model
except ImportError:
    from analyze_beta_fulltext import (
        aggregate_chunk_analyses,
        build_chunk_prompt,
        chunk_ranges,
        validate_fulltext_cards,
    )
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import MODEL, PROVIDER, run_tool_free_model

from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--fulltext", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--hermes", type=Path)
    args = parser.parse_args(argv)
    try:
        plan_value, _ = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        fulltext_value, _ = load_json(args.fulltext)
        if (
            type(fulltext_value) is not dict
            or not verify_receipt_hash(fulltext_value)
            or fulltext_value.get("contract") != "BetaArxivFullTextRead"
            or fulltext_value.get("plan_receipt_hash") != plan["receipt_hash"]
            or plan["mode"] != "academic"
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or args.plan != args.output_root / f"{plan['run_id']}-planning/plan.json"
        ):
            raise ValueError("fulltext_chunks_inputs_invalid")
        fulltext = fulltext_value
        paper = read_private_bytes(
            args.fulltext.parent / "paper.md", maximum=25_000_000
        )
        if hashlib.sha256(paper).hexdigest() != fulltext["text_sha256"]:
            raise ValueError("fulltext_chunks_source_mismatch")
        text = paper.decode("utf-8")
        ranges = chunk_ranges(text)
        output = args.output_root / f"{plan['run_id']}-academic-fulltext-analysis"
        if (
            not output.is_dir()
            or output.is_symlink()
            or stat.S_IMODE(output.stat().st_mode) & 0o077
            or (output / "analysis.json").exists()
        ):
            raise ValueError("fulltext_chunks_reconciliation_not_allowed")
        aggregate_attempt, _ = load_json(output / "attempt.json")
        if (
            type(aggregate_attempt) is not dict
            or aggregate_attempt.get("plan_receipt_hash") != plan["receipt_hash"]
            or aggregate_attempt.get("fulltext_receipt_hash")
            != fulltext["receipt_hash"]
            or aggregate_attempt.get("source_text_sha256")
            != hashlib.sha256(paper).hexdigest()
            or aggregate_attempt.get("chunks_total") != len(ranges)
            or aggregate_attempt.get("retry_allowed") is not False
        ):
            raise ValueError("fulltext_chunks_aggregate_attempt_invalid")
        results = []
        reconciled = []
        historical_quote_limit_regraded = []
        additional_model_calls = 0
        for index, (start, end) in enumerate(ranges, 1):
            chunk = text[start:end]
            directory = (
                args.output_root
                / f"{plan['run_id']}-academic-fulltext-chunk-{index:03d}"
            )
            if directory.is_symlink():
                raise ValueError("fulltext_chunk_missing")
            if not directory.exists():
                if args.hermes is None:
                    raise ValueError("fulltext_chunk_missing")
                spent = sum(row["reported_incremental_cost_usd"] for row in results)
                if (
                    len(results) >= plan["limits"]["model_calls"] - 1
                    or spent + 0.005 > plan["limits"]["max_estimated_cost_usd"]
                ):
                    raise ValueError("fulltext_chunk_budget_exhausted")
                raw, usage, trace = run_tool_free_model(
                    plan=plan,
                    prompt=build_chunk_prompt(
                        plan, fulltext, chunk, index=index, total=len(ranges)
                    ),
                    hermes=args.hermes,
                    output=directory,
                    attempt_binding={
                        "fulltext_receipt_hash": fulltext["receipt_hash"],
                        "source_scope": "parsed_pdf_text_layout_unverified",
                        "chunk_index": index,
                        "chunk_text_sha256": hashlib.sha256(chunk.encode()).hexdigest(),
                    },
                )
                additional_model_calls += 1
                try:
                    result = validate_fulltext_cards(
                        raw,
                        plan=plan,
                        fulltext=fulltext,
                        text=chunk,
                        usage=usage,
                        trace=trace,
                    )
                except (ContractError, ValueError) as error:
                    write_exclusive_json(
                        directory / "failure.json",
                        {
                            "schema_version": 1,
                            "status": "failed_after_model_response",
                            "reason_code": error.code
                            if isinstance(error, ContractError)
                            else str(error),
                            "reconciliation_required": True,
                            "retry_allowed": False,
                        },
                    )
                    raise
                write_exclusive_json(directory / "analysis.json", result)
                results.append(result)
                continue
            if not directory.is_dir():
                raise ValueError("fulltext_chunk_missing")
            original = (
                directory / "analysis.json"
                if (directory / "analysis.json").exists()
                else directory / "analysis-reconciled.json"
            )
            if original.exists():
                result, _ = load_json(original)
                if (
                    type(result) is not dict
                    or not verify_receipt_hash(result)
                    or result.get("plan_receipt_hash") != plan["receipt_hash"]
                    or result.get("fulltext_receipt_hash") != fulltext["receipt_hash"]
                    or result.get("source_text_sha256")
                    != hashlib.sha256(chunk.encode()).hexdigest()
                ):
                    raise ValueError("fulltext_chunk_original_invalid")
                results.append(result)
                continue
            attempt, _ = load_json(directory / "attempt.json")
            usage, _ = load_json(directory / "model-usage.json")
            trace, _ = load_json(directory / "model-trace.json")
            if any(type(row) is not dict for row in (attempt, usage, trace)):
                raise ValueError("fulltext_chunk_saved_invalid")
            attempt = cast(dict[str, Any], attempt)
            usage = cast(dict[str, Any], usage)
            trace = cast(dict[str, Any], trace)
            prompt = build_chunk_prompt(
                plan, fulltext, chunk, index=index, total=len(ranges)
            )
            historical_prompt = prompt.replace("5–40 слов", "5–20 слов")
            prompt_used = (
                historical_prompt
                if attempt.get("prompt_sha256")
                == hashlib.sha256(historical_prompt.encode()).hexdigest()
                else prompt
            )
            raw_bytes = read_private_bytes(
                directory / "model.raw.json", maximum=1_048_576
            )
            if not raw_bytes.endswith(b"\n") or raw_bytes.endswith(b"\n\n"):
                raise ValueError("fulltext_chunk_raw_invalid")
            raw = raw_bytes[:-1].decode("utf-8")
            messages = trace.get("messages")
            if (
                attempt.get("run_id") != plan["run_id"]
                or attempt.get("plan_receipt_hash") != plan["receipt_hash"]
                or attempt.get("fulltext_receipt_hash") != fulltext["receipt_hash"]
                or attempt.get("chunk_index") != index
                or attempt.get("chunk_text_sha256")
                != hashlib.sha256(chunk.encode()).hexdigest()
                or attempt.get("prompt_sha256")
                != hashlib.sha256(prompt_used.encode()).hexdigest()
                or attempt.get("provider") != PROVIDER
                or attempt.get("model") != MODEL
                or attempt.get("retry_allowed") is not False
                or type(messages) is not list
                or len(messages) != 2
                or type(messages[0]) is not dict
                or type(messages[1]) is not dict
                or messages[0].get("content") != prompt_used
                or messages[1].get("content", "").strip() != raw
            ):
                raise ValueError("fulltext_chunk_lineage_invalid")
            validate_tool_free_observation(
                plan=plan,
                usage=usage,
                trace=trace,
                provider=PROVIDER,
                model=MODEL,
                max_total_tokens=attempt["max_total_tokens"],
            )
            result = validate_fulltext_cards(
                raw, plan=plan, fulltext=fulltext, text=chunk, usage=usage, trace=trace
            )
            write_exclusive_json(directory / "analysis-reconciled.json", result)
            results.append(result)
            reconciled.append(index)
            if prompt_used == historical_prompt and historical_prompt != prompt:
                historical_quote_limit_regraded.append(index)
        aggregate = aggregate_chunk_analyses(
            plan=plan, fulltext=fulltext, text=text, ranges=ranges, results=results
        )
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaAcademicFullTextChunkReconciliation",
                "run_id": plan["run_id"],
                "plan_receipt_hash": plan["receipt_hash"],
                "fulltext_receipt_hash": fulltext["receipt_hash"],
                "analysis_receipt_hash": aggregate["receipt_hash"],
                "reconciled_chunk_indexes": reconciled,
                "historical_quote_limit_20_to_40_regraded": historical_quote_limit_regraded,
                "chunks_analyzed": aggregate["chunks_analyzed"],
                "chunks_total": aggregate["chunks_total"],
                "additional_model_calls": additional_model_calls,
                "additional_source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "analysis.json", aggregate)
        write_exclusive_json(output / "reconciliation.json", receipt)
        print(
            json.dumps(
                {
                    "status": "fulltext_chunks_reconciled",
                    "run_id": plan["run_id"],
                    "chunks_analyzed": aggregate["chunks_analyzed"],
                    "chunks_total": aggregate["chunks_total"],
                    "reconciled_chunk_indexes": reconciled,
                    "additional_model_calls": additional_model_calls,
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
