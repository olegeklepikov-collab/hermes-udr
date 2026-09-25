"""Challenge one preserved source against every atom in the sealed frame."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, read_private_bytes, write_exclusive_json
    from .model_call import ModelCallError, run_tool_free_model
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model

from hermes_research_report.beta_coverage import assess_beta_coverage
from hermes_research_report.beta_coverage_discovery import (
    build_coverage_discovery_prompt,
    parse_coverage_discovery,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
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
        capture, _ = load_json(args.capture)
        observations, _ = load_json(args.observations)
        if (
            type(frame) is not dict
            or type(capture) is not dict
            or type(observations) is not list
            or not verify_receipt_hash(frame)
            or not verify_receipt_hash(capture)
        ):
            raise ValueError("coverage_gap_inputs_invalid")
        frame = cast(dict[str, Any], frame)
        capture = cast(dict[str, Any], capture)
        run_id = frame["run_id"]
        batch_run_id = f"{run_id}-B03"
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{run_id}-coverage-route-repair/frame.json"
            or args.capture
            != args.output_root / f"{batch_run_id}-LEAF-003-keenable/capture.json"
            or args.observations
            != args.output_root / f"{batch_run_id}-coverage-observed/observations.json"
        ):
            raise ValueError("coverage_gap_paths_invalid")
        attempts = capture["leaves"][0].get("candidate_attempts", [])
        candidates = [
            row
            for row in attempts
            if type(row) is dict
            and row.get("source_id") == args.source_id
            and row.get("status") in {"screened_out", "extracted_candidate"}
        ]
        if len(candidates) != 1:
            raise ValueError("coverage_gap_source_invalid")
        candidate = candidates[0]
        name = f"{args.source_id}.txt"
        artifacts = capture.get("artifact_hashes")
        matches = (
            [row for row in artifacts if type(row) is dict and row.get("path") == name]
            if type(artifacts) is list
            else []
        )
        if len(matches) != 1:
            raise ValueError("coverage_gap_file_invalid")
        payload = read_private_bytes(args.capture.parent / name, maximum=50_000)
        if (
            len(payload) != matches[0].get("bytes")
            or hashlib.sha256(payload).hexdigest() != matches[0].get("sha256")
            or hashlib.sha256(payload).hexdigest() != candidate.get("content_sha256")
        ):
            raise ValueError("coverage_gap_file_invalid")
        text = payload.decode("utf-8")
        prompt = build_coverage_discovery_prompt(
            frame=frame,
            source_id=args.source_id,
            title=candidate["title"],
            text=text,
        )
        output_run_id = f"{batch_run_id}-S04"
        output = args.output_root / f"{output_run_id}-{args.source_id}-gap"
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": output_run_id,
                "wall_seconds": 120,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=prompt,
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "coverage_source_backed_gap_detection",
                "frame_receipt_hash": frame["receipt_hash"],
                "capture_receipt_hash": capture["receipt_hash"],
                "source_id": args.source_id,
                "source_text_sha256": hashlib.sha256(payload).hexdigest(),
            },
        )
        model_completed = True
        result = parse_coverage_discovery(
            raw,
            frame=frame,
            source_id=args.source_id,
            title=candidate["title"],
            text=text,
            capture=capture,
            batch=3,
        )
        signals = [result["discovery_signal"]] if result["discovery_signal"] else []
        progress = assess_beta_coverage(
            frame, observations, budget_exhausted=False, discovery_signals=signals
        )
        run = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageGapDetectionRun",
                "run_id": run_id,
                "source_id": args.source_id,
                "gap_screen_receipt_hash": result["receipt_hash"],
                "coverage_assessment_receipt_hash": progress["receipt_hash"],
                "model_session_id": usage["session_id"],
                "reported_model_cost_usd": usage["estimated_cost_usd"],
                "model_trace_message_count": len(trace["messages"]),
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "gap-screen.json", result)
        write_exclusive_json(output / "coverage.json", progress)
        write_exclusive_json(output / "gap-run.json", run)
        print(
            json.dumps(
                {
                    "status": result["status_model_proposed"],
                    "status_effective": result["status_effective"],
                    "unresolved_mapping": result["unresolved_mapping"],
                    "source_backed_signal": result["discovery_signal"] is not None,
                    "frame_expansion_required": progress["frame_expansion_required"],
                    "observed_novelty_plateau": progress["observed_novelty_plateau"],
                    "saturation_verified": False,
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
        UnicodeError,
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
