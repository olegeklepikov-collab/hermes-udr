"""Map a sealed source plan to a provisional atomic coverage frame."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, write_exclusive_json
    from .model_call import ModelCallError, run_tool_free_model
except ImportError:
    from file_io import load_json, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model

from hermes_research_report.beta_coverage_mapping import (
    build_query_atom_mapping_prompt,
    parse_query_atom_mapping,
)
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    output: Path | None = None
    model_completed = False
    try:
        frame, _ = load_json(args.frame)
        plan_value, _ = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        if (
            type(frame) is not dict
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{frame['run_id']}-coverage-planning/frame.json"
            or args.plan != args.output_root / f"{plan['run_id']}-planning/plan.json"
        ):
            raise ValueError("coverage_mapping_paths_invalid")
        prompt = build_query_atom_mapping_prompt(frame, plan)
        output = args.output_root / f"{plan['run_id']}-coverage-map-plan"
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": plan["run_id"],
                "wall_seconds": 60,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=prompt,
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "coverage_query_intent_mapping",
                "frame_receipt_hash": frame["receipt_hash"],
                "sealed_plan_receipt_hash": plan["receipt_hash"],
            },
        )
        model_completed = True
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
                "model_trace_message_count": len(trace["messages"]),
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "mapping.json", mapping)
        write_exclusive_json(output / "run.json", run)
        print(
            json.dumps(
                {
                    "status": "coverage_query_mapping_provisional",
                    "run_id": plan["run_id"],
                    "mapped_atom_count": len(mapping["mapped_atom_ids"]),
                    "unmapped_leaf_count": len(mapping["unmapped_leaf_ids"]),
                    "model_cost_usd": usage["estimated_cost_usd"],
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, ModelCallError, OSError, ValueError, KeyError) as error:
        code = (
            error.code
            if isinstance(error, (ContractError, ModelCallError))
            else str(error)
        )
        if model_completed and output is not None:
            try:
                write_exclusive_json(
                    output / "failure.json",
                    {
                        "schema_version": 1,
                        "status": "failed_after_model_response",
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
