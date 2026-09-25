"""Screen one retained extracted web candidate for one coverage question."""

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

from hermes_research_report.beta_coverage_screen import (
    build_coverage_screen_prompt,
    parse_coverage_screen,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def persist_coverage_screen_result(
    *,
    output: Path,
    raw: str,
    atom: dict,
    title: str,
    source_id: str,
    text: str,
    frame: dict,
    capture: dict,
    usage: dict,
    trace: dict,
    reconciled: bool,
    full_text: bool,
    reuse_receipt_hash: str | None = None,
) -> tuple[dict, dict]:
    screen = parse_coverage_screen(
        raw,
        atom=atom,
        title=title,
        source_id=source_id,
        text=text,
        frame=frame,
        capture=capture,
        full_text=full_text,
    )
    run = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageScreenRun",
            "run_id": frame["run_id"],
            "batch_run_id": capture["run_id"],
            "screen_receipt_hash": screen["receipt_hash"],
            "model_session_id": usage["session_id"],
            "reported_model_cost_usd": usage["estimated_cost_usd"],
            "model_trace_message_count": len(trace["messages"]),
            "cross_atom_reuse_receipt_hash": reuse_receipt_hash,
            "reconciled_without_new_model_call": reconciled,
            "additional_model_calls": 0 if reconciled else 1,
            "source_calls": 0,
            "release_authorized": False,
        }
    )
    write_exclusive_json(output / "screen.json", screen)
    write_exclusive_json(output / "screen-run.json", run)
    return screen, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--batch-plan", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--target-atom-id")
    parser.add_argument("--source-reuse", type=Path)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--public-query-ack", action="store_true")
    parser.add_argument("--full-text", action="store_true")
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
        batch, _ = load_json(args.batch_plan)
        capture, _ = load_json(args.capture)
        if any(
            type(value) is not dict or not verify_receipt_hash(value)
            for value in (frame, batch, capture)
        ):
            raise ValueError("coverage_screen_receipts_invalid")
        frame = cast(dict[str, Any], frame)
        batch = cast(dict[str, Any], batch)
        capture = cast(dict[str, Any], capture)
        run_id = frame["run_id"]
        batch_run_id = batch["batch_run_id"]
        domain_batch = batch.get("contract") == "BetaDomainWebBatchPlan"
        expected_frame = (
            args.output_root / f"{run_id}-hole-fill/frame.json"
            if domain_batch
            else args.output_root / f"{run_id}-coverage-route-repair/frame.json"
        )
        expected_batch = (
            args.output_root / f"{batch_run_id}-domain-web-plan/batch.json"
            if domain_batch
            else args.output_root
            / f"{batch_run_id}-coverage-source-plan/batch-plan.json"
        )
        expected_capture = (
            args.output_root / f"{batch_run_id}/capture.json"
            if domain_batch
            else args.output_root / f"{batch_run_id}-LEAF-003-keenable/capture.json"
        )
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame != expected_frame
            or args.batch_plan != expected_batch
            or args.capture != expected_capture
            or batch.get("frame_receipt_hash") != frame["receipt_hash"]
            or capture.get("run_id") != batch_run_id
            or capture.get("contract") != "BetaSourceAcquisition"
        ):
            raise ValueError("coverage_screen_paths_invalid")
        target_atom_id = args.target_atom_id or batch["atom_id"]
        cross_atom = target_atom_id != batch["atom_id"]
        reuse_hash = None
        if cross_atom:
            if not args.full_text or args.source_reuse is None:
                raise ValueError("coverage_cross_atom_scope_invalid")
            expected_reuse = (
                args.output_root
                / f"{batch_run_id}-S02-{args.source_id}-screen/source-reuse-v2.json"
            )
            if args.source_reuse != expected_reuse:
                raise ValueError("coverage_cross_atom_reuse_path_invalid")
            reuse, _ = load_json(args.source_reuse)
            if (
                type(reuse) is not dict
                or not verify_receipt_hash(reuse)
                or reuse.get("frame_receipt_hash") != frame["receipt_hash"]
                or reuse.get("source_id") != args.source_id
                or not any(
                    type(row) is dict and row.get("atom_id") == target_atom_id
                    for row in reuse.get("suggestions", [])
                )
            ):
                raise ValueError("coverage_cross_atom_reuse_invalid")
            reuse_hash = reuse["receipt_hash"]
        elif args.source_reuse is not None:
            raise ValueError("coverage_cross_atom_reuse_unexpected")
        atom_rows = [
            atom for atom in frame["atoms"] if atom["atom_id"] == target_atom_id
        ]
        if len(atom_rows) != 1:
            raise ValueError("coverage_screen_atom_invalid")
        leaves = capture.get("leaves")
        if type(leaves) is not list or len(leaves) != 1:
            raise ValueError("coverage_screen_capture_invalid")
        attempts = leaves[0].get("candidate_attempts", [])
        candidates = [
            row
            for row in attempts
            if type(row) is dict
            and row.get("source_id") == args.source_id
            and row.get("status") in {"screened_out", "extracted_candidate"}
        ]
        if len(candidates) != 1:
            raise ValueError("coverage_screen_source_invalid")
        candidate = candidates[0]
        name = f"{args.source_id}.txt"
        manifests = capture.get("artifact_hashes")
        matches = (
            [row for row in manifests if type(row) is dict and row.get("path") == name]
            if type(manifests) is list
            else []
        )
        if len(matches) != 1:
            raise ValueError("coverage_screen_file_not_bound")
        payload = read_private_bytes(args.capture.parent / name, maximum=50_000)
        if (
            len(payload) != matches[0].get("bytes")
            or hashlib.sha256(payload).hexdigest() != matches[0].get("sha256")
            or hashlib.sha256(payload).hexdigest() != candidate.get("content_sha256")
        ):
            raise ValueError("coverage_screen_file_not_bound")
        text = payload.decode("utf-8")
        title = candidate["title"]
        prompt = build_coverage_screen_prompt(
            atom=atom_rows[0],
            title=title,
            source_id=args.source_id,
            text=text,
            full_text=args.full_text,
        )
        output_run_id = f"{batch_run_id}-S{'03' if cross_atom else '02' if args.full_text else '01'}"
        output_name = (
            f"{output_run_id}-{target_atom_id}-{args.source_id}-screen"
            if cross_atom
            else f"{output_run_id}-{args.source_id}-screen"
        )
        output = args.output_root / output_name
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": output_run_id,
                "wall_seconds": 120 if args.full_text else 60,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=prompt,
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "coverage_cross_atom_relevance_screen"
                if cross_atom
                else "coverage_source_relevance_screen",
                "frame_receipt_hash": frame["receipt_hash"],
                "batch_plan_receipt_hash": batch["receipt_hash"],
                "capture_receipt_hash": capture["receipt_hash"],
                "source_id": args.source_id,
                "source_text_sha256": hashlib.sha256(payload).hexdigest(),
                "target_atom_id": target_atom_id,
                "cross_atom_reuse_receipt_hash": reuse_hash,
                "screen_scope": "all_retained_extracted_text_visuals_unverified"
                if args.full_text
                else "first_12000_chars_only",
            },
        )
        model_completed = True
        screen, _run = persist_coverage_screen_result(
            output=output,
            raw=raw,
            atom=atom_rows[0],
            title=title,
            source_id=args.source_id,
            text=text,
            frame=frame,
            capture=capture,
            usage=usage,
            trace=trace,
            reconciled=False,
            full_text=args.full_text,
            reuse_receipt_hash=reuse_hash,
        )
        print(
            json.dumps(
                {
                    "status": "screened",
                    "relation_model_proposed": screen["relation_model_proposed"],
                    "source_id": args.source_id,
                    "source_semantic_support_verified": False,
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
