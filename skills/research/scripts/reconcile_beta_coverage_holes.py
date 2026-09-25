"""Recover a saved hole-fill response without a second model call."""

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
    from .file_io import load_json, read_private_bytes, write_exclusive_json
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json

from hermes_research_report.beta_coverage_holes import fill_coverage_holes
from hermes_research_report.canonical import with_receipt_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--decomposition", type=Path, required=True)
    parser.add_argument("--saved-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        decomposition, _ = load_json(args.decomposition)
        directory = args.saved_dir
        if (
            type(frame) is not dict
            or type(decomposition) is not dict
            or not directory.is_absolute()
            or directory.is_symlink()
            or not directory.is_dir()
            or stat.S_IMODE(directory.stat().st_mode) & 0o077
            or directory.name != f"{frame['run_id']}-hole-fill"
        ):
            raise ValueError("coverage_holes_reconciliation_paths_invalid")
        attempt, _ = load_json(directory / "attempt.json")
        usage, _ = load_json(directory / "model-usage.json")
        trace, _ = load_json(directory / "model-trace.json")
        failure, _ = load_json(directory / "failure.json")
        if (
            type(attempt) is not dict
            or attempt.get("parent_frame_receipt_hash") != frame["receipt_hash"]
            or attempt.get("decomposition_receipt_hash")
            != decomposition["receipt_hash"]
            or attempt.get("purpose") != "coverage_structural_hole_fill"
            or type(usage) is not dict
            or type(trace) is not dict
            or type(failure) is not dict
            or failure.get("reconciliation_required") is not True
        ):
            raise ValueError("coverage_holes_reconciliation_lineage_invalid")
        raw = read_private_bytes(directory / "model.raw.json", maximum=1_048_576)
        revised, receipt = fill_coverage_holes(
            raw.decode("utf-8").rstrip("\n"),
            frame=frame,
            decomposition=decomposition,
        )
        run = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageHoleFillRun",
                "run_id": frame["run_id"],
                "fill_receipt_hash": receipt["receipt_hash"],
                "revised_frame_receipt_hash": revised["receipt_hash"],
                "raw_response_sha256": hashlib.sha256(raw.rstrip(b"\n")).hexdigest(),
                "reported_model_cost_usd": usage["estimated_cost_usd"],
                "model_session_id": usage["session_id"],
                "model_trace_message_count": len(trace["messages"]),
                "reconciled_without_new_model_call": True,
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(directory / "frame.json", revised)
        write_exclusive_json(directory / "fill.json", receipt)
        write_exclusive_json(directory / "run.json", run)
        print(
            json.dumps(
                {
                    "status": "provisional_holes_reconciled",
                    "run_id": frame["run_id"],
                    "added_atom_count": len(receipt["added_atom_ids"]),
                    "normalized_model_spaces": receipt["normalized_model_spaces"],
                    "additional_model_calls": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        print(json.dumps({"status": "error", "code": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
