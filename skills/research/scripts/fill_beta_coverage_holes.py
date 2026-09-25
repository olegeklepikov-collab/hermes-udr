"""One bounded model call for missing coverage ranks and empty branches."""

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

from hermes_research_report.beta_coverage_holes import (
    build_hole_prompt,
    fill_coverage_holes,
)
from hermes_research_report.canonical import with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--decomposition", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    output: Path | None = None
    model_completed = False
    try:
        frame, _ = load_json(args.frame)
        decomposition, _ = load_json(args.decomposition)
        if (
            type(frame) is not dict
            or type(decomposition) is not dict
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
        ):
            raise ValueError("coverage_holes_paths_invalid")
        output = args.output_root / f"{frame['run_id']}-hole-fill"
        assert output is not None
        prompt = build_hole_prompt(frame, decomposition)
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": frame["run_id"],
                "wall_seconds": 120,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=prompt,
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "coverage_structural_hole_fill",
                "parent_frame_receipt_hash": frame["receipt_hash"],
                "decomposition_receipt_hash": decomposition["receipt_hash"],
            },
        )
        model_completed = True
        revised, receipt = fill_coverage_holes(
            raw, frame=frame, decomposition=decomposition
        )
        run = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageHoleFillRun",
                "run_id": frame["run_id"],
                "fill_receipt_hash": receipt["receipt_hash"],
                "revised_frame_receipt_hash": revised["receipt_hash"],
                "reported_model_cost_usd": usage["estimated_cost_usd"],
                "model_session_id": usage["session_id"],
                "model_trace_message_count": len(trace["messages"]),
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "frame.json", revised)
        write_exclusive_json(output / "fill.json", receipt)
        write_exclusive_json(output / "run.json", run)
        print(
            json.dumps(
                {
                    "status": "provisional_holes_filled",
                    "run_id": frame["run_id"],
                    "added_atom_count": len(receipt["added_atom_ids"]),
                    "remaining_empty_branches": receipt["remaining_empty_branch_ids"],
                    "remaining_importance_ranks": receipt[
                        "remaining_importance_rank_gaps"
                    ],
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
