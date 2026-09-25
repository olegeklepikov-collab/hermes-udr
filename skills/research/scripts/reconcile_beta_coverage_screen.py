"""Recover one paid full-text coverage screen after PDF line-break alignment."""

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
    from .screen_beta_coverage_candidate import persist_coverage_screen_result
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import MODEL, PROVIDER
    from screen_beta_coverage_candidate import persist_coverage_screen_result

from hermes_research_report.beta_coverage_screen import build_coverage_screen_prompt
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
            or (output / "screen.json").exists()
        ):
            raise ValueError("coverage_screen_reconciliation_not_allowed")
        attempt, _ = load_json(output / "attempt.json")
        failure, _ = load_json(output / "failure.json")
        usage, _ = load_json(output / "model-usage.json")
        trace, _ = load_json(output / "model-trace.json")
        if any(type(value) is not dict for value in (attempt, failure, usage, trace)):
            raise ValueError("coverage_screen_saved_record_invalid")
        attempt = cast(dict[str, Any], attempt)
        failure = cast(dict[str, Any], failure)
        usage = cast(dict[str, Any], usage)
        trace = cast(dict[str, Any], trace)
        run_id = attempt.get("run_id")
        source_id = attempt.get("source_id")
        if (
            type(run_id) is not str
            or not run_id.endswith("-B03-S02")
            or type(source_id) is not str
            or output.name != f"{run_id}-{source_id}-screen"
        ):
            raise ValueError("coverage_screen_saved_attempt_not_bound")
        batch_run_id = run_id.removesuffix("-S02")
        frame_run_id = batch_run_id.removesuffix("-B03")
        frame, _ = load_json(
            output.parent / f"{frame_run_id}-coverage-route-repair/frame.json"
        )
        batch, _ = load_json(
            output.parent / f"{batch_run_id}-coverage-source-plan/batch-plan.json"
        )
        capture_dir = output.parent / f"{batch_run_id}-LEAF-003-keenable"
        capture, _ = load_json(capture_dir / "capture.json")
        if any(
            type(value) is not dict or not verify_receipt_hash(value)
            for value in (frame, batch, capture)
        ):
            raise ValueError("coverage_screen_lineage_invalid")
        frame = cast(dict[str, Any], frame)
        batch = cast(dict[str, Any], batch)
        capture = cast(dict[str, Any], capture)
        atoms = [atom for atom in frame["atoms"] if atom["atom_id"] == batch["atom_id"]]
        attempts = capture["leaves"][0].get("candidate_attempts", [])
        candidates = [
            row
            for row in attempts
            if type(row) is dict and row.get("source_id") == source_id
        ]
        if len(atoms) != 1 or len(candidates) != 1:
            raise ValueError("coverage_screen_source_invalid")
        candidate = candidates[0]
        source_raw = read_private_bytes(
            capture_dir / f"{source_id}.txt", maximum=50_000
        )
        if hashlib.sha256(source_raw).hexdigest() != candidate.get("content_sha256"):
            raise ValueError("coverage_screen_source_invalid")
        text = source_raw.decode("utf-8")
        prompt = build_coverage_screen_prompt(
            atom=atoms[0],
            title=candidate["title"],
            source_id=source_id,
            text=text,
            full_text=True,
        )
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
            attempt.get("purpose") != "coverage_source_relevance_screen"
            or attempt.get("frame_receipt_hash") != frame["receipt_hash"]
            or attempt.get("batch_plan_receipt_hash") != batch["receipt_hash"]
            or attempt.get("capture_receipt_hash") != capture["receipt_hash"]
            or attempt.get("source_text_sha256")
            != hashlib.sha256(source_raw).hexdigest()
            or attempt.get("screen_scope")
            != "all_retained_extracted_text_visuals_unverified"
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
            raise ValueError("coverage_screen_saved_attempt_not_bound")
        validate_tool_free_observation(
            max_estimated_cost_usd=0.01,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
            max_total_tokens=attempt["max_total_tokens"],
        )
        screen, run = persist_coverage_screen_result(
            output=output,
            raw=raw,
            atom=atoms[0],
            title=candidate["title"],
            source_id=source_id,
            text=text,
            frame=frame,
            capture=capture,
            usage=usage,
            trace=trace,
            reconciled=True,
            full_text=True,
        )
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageScreenReconciliation",
                "run_id": frame_run_id,
                "source_id": source_id,
                "previous_failure_reason": failure.get("reason_code"),
                "screen_receipt_hash": screen["receipt_hash"],
                "screen_run_receipt_hash": run["receipt_hash"],
                "quote_origin": screen["quote_origin"],
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "reconciliation.json", receipt)
        print(
            json.dumps(
                {
                    "status": "screen_reconciled",
                    "relation_effective": screen["relation_effective"],
                    "quote_origin": screen["quote_origin"],
                    "additional_model_calls": 0,
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
