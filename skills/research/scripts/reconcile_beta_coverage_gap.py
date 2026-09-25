"""Regrade one saved gap-detection reply without a second model call."""

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

from hermes_research_report.beta_coverage import assess_beta_coverage
from hermes_research_report.beta_coverage_discovery import (
    build_coverage_discovery_prompt,
    parse_coverage_discovery,
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
            or (output / "gap-screen-v2.json").exists()
        ):
            raise ValueError("coverage_gap_reconciliation_not_allowed")
        attempt, _ = load_json(output / "attempt.json")
        usage, _ = load_json(output / "model-usage.json")
        trace, _ = load_json(output / "model-trace.json")
        if any(type(value) is not dict for value in (attempt, usage, trace)):
            raise ValueError("coverage_gap_saved_record_invalid")
        attempt = cast(dict[str, Any], attempt)
        usage = cast(dict[str, Any], usage)
        trace = cast(dict[str, Any], trace)
        run_id = attempt.get("run_id")
        source_id = attempt.get("source_id")
        if (
            type(run_id) is not str
            or not run_id.endswith("-B03-S04")
            or type(source_id) is not str
            or output.name != f"{run_id}-{source_id}-gap"
        ):
            raise ValueError("coverage_gap_saved_attempt_not_bound")
        batch_run_id = run_id.removesuffix("-S04")
        frame_run_id = batch_run_id.removesuffix("-B03")
        frame, _ = load_json(
            output.parent / f"{frame_run_id}-coverage-route-repair/frame.json"
        )
        capture_dir = output.parent / f"{batch_run_id}-LEAF-003-keenable"
        capture, _ = load_json(capture_dir / "capture.json")
        observations, _ = load_json(
            output.parent / f"{batch_run_id}-coverage-observed/observations.json"
        )
        prior, _ = load_json(output / "gap-screen.json")
        if (
            type(frame) is not dict
            or type(capture) is not dict
            or type(prior) is not dict
            or type(observations) is not list
            or not all(verify_receipt_hash(item) for item in (frame, capture, prior))
            or prior.get("frame_receipt_hash") != frame["receipt_hash"]
            or prior.get("capture_receipt_hash") != capture["receipt_hash"]
        ):
            raise ValueError("coverage_gap_lineage_invalid")
        frame = cast(dict[str, Any], frame)
        capture = cast(dict[str, Any], capture)
        raw_source = read_private_bytes(
            capture_dir / f"{source_id}.txt", maximum=50_000
        )
        if hashlib.sha256(raw_source).hexdigest() != attempt.get("source_text_sha256"):
            raise ValueError("coverage_gap_source_invalid")
        text = raw_source.decode("utf-8")
        candidates = [
            row
            for row in capture["leaves"][0].get("candidate_attempts", [])
            if type(row) is dict and row.get("source_id") == source_id
        ]
        if len(candidates) != 1:
            raise ValueError("coverage_gap_source_invalid")
        title = candidates[0]["title"]
        prompt = build_coverage_discovery_prompt(
            frame=frame,
            source_id=source_id,
            title=title,
            text=text,
            legacy_status_prompt=True,
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
            attempt.get("purpose") != "coverage_source_backed_gap_detection"
            or attempt.get("frame_receipt_hash") != frame["receipt_hash"]
            or attempt.get("capture_receipt_hash") != capture["receipt_hash"]
            or attempt.get("bootstrap_budget_hash") != sha256_json(budget)
            or attempt.get("prompt_sha256")
            != hashlib.sha256(prompt.encode()).hexdigest()
            or attempt.get("provider") != PROVIDER
            or attempt.get("model") != MODEL
            or attempt.get("retry_allowed") is not False
            or type(messages) is not list
            or len(messages) != 2
            or messages[0].get("content") != prompt
            or messages[1].get("content", "").strip() != raw
            or prior.get("status_model_proposed") != "mapped"
            or prior.get("mapped_atom_ids_model_proposed") != []
        ):
            raise ValueError("coverage_gap_saved_attempt_not_bound")
        validate_tool_free_observation(
            max_estimated_cost_usd=0.01,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
            max_total_tokens=attempt["max_total_tokens"],
        )
        revised = parse_coverage_discovery(
            raw,
            frame=frame,
            source_id=source_id,
            title=title,
            text=text,
            capture=capture,
            batch=3,
        )
        progress = assess_beta_coverage(
            frame,
            observations,
            budget_exhausted=False,
            discovery_signals=[revised["discovery_signal"]]
            if revised["discovery_signal"]
            else [],
        )
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageGapReconciliation",
                "run_id": frame_run_id,
                "source_id": source_id,
                "prior_screen_receipt_hash": prior["receipt_hash"],
                "revised_screen_receipt_hash": revised["receipt_hash"],
                "coverage_assessment_receipt_hash": progress["receipt_hash"],
                "unresolved_mapping": revised["unresolved_mapping"],
                "saturation_decision_blocked": True,
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "gap-screen-v2.json", revised)
        write_exclusive_json(output / "coverage-v2.json", progress)
        write_exclusive_json(output / "reconciliation.json", receipt)
        print(
            json.dumps(
                {
                    "status": revised["status_effective"],
                    "unresolved_mapping": revised["unresolved_mapping"],
                    "saturation_decision_blocked": True,
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
