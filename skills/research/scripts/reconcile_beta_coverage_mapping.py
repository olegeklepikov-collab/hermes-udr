"""Reparse one saved query-to-atom mapping answer without another call."""

from __future__ import annotations

import hashlib
import json
import stat
import sys
from argparse import ArgumentParser
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

from hermes_research_report.beta_coverage_mapping import (
    build_query_atom_mapping_prompt,
    parse_query_atom_mapping,
)
from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        plan_value, _ = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        output = args.output
        if (
            type(frame) is not dict
            or not verify_receipt_hash(frame)
            or not output.is_absolute()
            or output.is_symlink()
            or not output.is_dir()
            or stat.S_IMODE(output.stat().st_mode) & 0o077
            or args.frame
            != output.parent / f"{frame['run_id']}-coverage-planning/frame.json"
            or args.plan != output.parent / f"{plan['run_id']}-planning/plan.json"
            or output != output.parent / f"{plan['run_id']}-coverage-map-plan"
            or any((output / name).exists() for name in ("mapping.json", "run.json"))
        ):
            raise ValueError("coverage_mapping_reconcile_paths_invalid")
        attempt, _ = load_json(output / "attempt.json")
        failure, _ = load_json(output / "failure.json")
        usage, _ = load_json(output / "model-usage.json")
        trace, _ = load_json(output / "model-trace.json")
        if any(type(row) is not dict for row in (attempt, failure, usage, trace)):
            raise ValueError("coverage_mapping_reconcile_records_invalid")
        attempt, failure, usage, trace = (
            cast(dict[str, Any], row) for row in (attempt, failure, usage, trace)
        )
        prompt = build_query_atom_mapping_prompt(frame, plan)
        raw = (
            read_private_bytes(output / "model.raw.json", maximum=1_048_576)
            .decode("utf-8")
            .rstrip("\n")
        )
        messages = trace.get("messages")
        if (
            attempt.get("purpose") != "coverage_query_intent_mapping"
            or attempt.get("frame_receipt_hash") != frame["receipt_hash"]
            or attempt.get("sealed_plan_receipt_hash") != plan["receipt_hash"]
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
            raise ValueError("coverage_mapping_reconcile_lineage_invalid")
        validate_tool_free_observation(
            max_estimated_cost_usd=0.01,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
            max_total_tokens=attempt["max_total_tokens"],
        )
        mapping = parse_query_atom_mapping(raw, frame=frame, plan=plan)
        run = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageQueryMappingRun",
                "run_id": plan["run_id"],
                "frame_receipt_hash": frame["receipt_hash"],
                "plan_receipt_hash": plan["receipt_hash"],
                "mapping_receipt_hash": mapping["receipt_hash"],
                "model_session_id": usage["session_id"],
                "reported_model_cost_usd": usage["estimated_cost_usd"],
                "model_trace_message_count": len(messages),
                "reconciled_without_new_model_call": True,
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "mapping.json", mapping)
        write_exclusive_json(output / "run.json", run)
        print(
            json.dumps(
                {
                    "status": "coverage_query_mapping_reconciled",
                    "run_id": plan["run_id"],
                    "mapped_atom_count": len(mapping["mapped_atom_ids"]),
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
