"""Plan a keyless DataCite metadata probe for a still-open coverage atom."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, write_exclusive_json
    from .model_call import ModelCallError, run_tool_free_model
except ImportError:
    from file_io import load_json, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model

from hermes_research_report.beta_dataset_query import (
    build_dataset_query_prompt,
    parse_dataset_query_reply,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def persist_dataset_batch(
    *,
    output: Path,
    frame: dict,
    previous: dict,
    raw: str,
    usage: dict,
    trace: dict,
    reconciled: bool,
) -> tuple[dict, dict]:
    plan, batch = parse_dataset_query_reply(
        raw, frame=frame, atom_id=previous["atom_id"], previous=previous
    )
    run = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageDatasetPlanningRun",
            "run_id": frame["run_id"],
            "batch_run_id": batch["batch_run_id"],
            "batch_plan_receipt_hash": batch["receipt_hash"],
            "subplan_receipt_hash": plan["receipt_hash"],
            "model_session_id": usage["session_id"],
            "reported_model_cost_usd": usage["estimated_cost_usd"],
            "model_trace_message_count": len(trace["messages"]),
            "reconciled_without_new_model_call": reconciled,
            "additional_model_calls": 0 if reconciled else 1,
            "source_calls": 0,
            "release_authorized": False,
        }
    )
    for name, value in (
        ("plan.json", plan),
        ("batch-plan.json", batch),
        ("planning-run.json", run),
    ):
        write_exclusive_json(output / name, value)
    return plan, batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--previous-observation", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--public-query-ack", action="store_true")
    args = parser.parse_args(argv)
    if not args.public_query_ack:
        print(
            json.dumps({"status": "error", "code": "public_query_ack_required"}),
            file=sys.stderr,
        )
        return 2
    output: Path | None = None
    model_completed = False
    try:
        frame, _ = load_json(args.frame)
        previous, _ = load_json(args.previous_observation)
        if any(
            type(value) is not dict or not verify_receipt_hash(value)
            for value in (frame, previous)
        ):
            raise ValueError("dataset_batch_inputs_invalid")
        frame = cast(dict[str, Any], frame)
        previous = cast(dict[str, Any], previous)
        run_id = frame["run_id"]
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{run_id}-coverage-route-repair/frame.json"
            or args.previous_observation
            != args.output_root
            / f"{run_id}-B03-coverage-observed/batch-observation.json"
        ):
            raise ValueError("dataset_batch_paths_invalid")
        atom_rows = [
            atom for atom in frame["atoms"] if atom["atom_id"] == previous["atom_id"]
        ]
        if len(atom_rows) != 1:
            raise ValueError("dataset_batch_atom_invalid")
        batch_run_id = f"{run_id}-B04"
        output = args.output_root / f"{batch_run_id}-coverage-dataset-plan"
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": batch_run_id,
                "wall_seconds": 60,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=build_dataset_query_prompt(atom_rows[0]),
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "coverage_dataset_metadata_query_plan",
                "frame_receipt_hash": frame["receipt_hash"],
                "prior_observation_receipt_hash": previous["receipt_hash"],
                "atom_id": previous["atom_id"],
            },
        )
        model_completed = True
        _plan, batch = persist_dataset_batch(
            output=output,
            frame=frame,
            previous=previous,
            raw=raw,
            usage=usage,
            trace=trace,
            reconciled=False,
        )
        print(
            json.dumps(
                {
                    "status": "dataset_metadata_batch_ready",
                    "batch_run_id": batch_run_id,
                    "atom_id": batch["atom_id"],
                    "leaf_count": 2,
                    "dataset_content_read": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        ContractError,
        ModelCallError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
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
