"""Select instrument families for a preserved coverage-revision draft."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, read_private_bytes, write_exclusive_json
    from .model_call import ModelCallError, run_tool_free_model
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model

from hermes_research_report.beta_coverage_repair import (
    build_route_repair_prompt,
    parse_route_repair,
    prepare_coverage_repair,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", type=Path, required=True)
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
        revision_dir = args.revision
        draft, _ = load_json(revision_dir / "revision-draft.json")
        reconciliation, _ = load_json(revision_dir / "reconciliation.json")
        if (
            type(draft) is not dict
            or type(reconciliation) is not dict
            or not verify_receipt_hash(draft)
            or not verify_receipt_hash(reconciliation)
            or reconciliation.get("outcome_receipt_hash") != draft["receipt_hash"]
            or reconciliation.get("outcome_status") != "unvalidated_revision_draft"
            or draft.get("ready_for_source_calls") is not False
        ):
            raise ValueError("coverage_route_draft_invalid")
        run_id = draft["run_id"]
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or revision_dir != args.output_root / f"{run_id}-coverage-revision-02"
        ):
            raise ValueError("coverage_route_paths_invalid")
        frame, _ = load_json(
            args.output_root / f"{run_id}-coverage-planning/frame.json"
        )
        review, _ = load_json(
            args.output_root / f"{run_id}-coverage-review/review.json"
        )
        if type(frame) is not dict or type(review) is not dict:
            raise ValueError("coverage_route_lineage_invalid")
        raw_revision = (
            read_private_bytes(revision_dir / "model.raw.json", maximum=1_048_576)
            .decode("utf-8")
            .rstrip("\n")
        )
        if (
            hashlib.sha256(raw_revision.encode()).hexdigest()
            != draft["raw_response_sha256"]
        ):
            raise ValueError("coverage_route_raw_mismatch")
        prepared = prepare_coverage_repair(raw_revision, frame=frame, review=review)
        prompt = build_route_repair_prompt(prepared)
        output = args.output_root / f"{run_id}-coverage-route-repair"
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": run_id,
                "wall_seconds": 120,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=prompt,
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "coverage_instrument_strategy_repair",
                "prepared_receipt_hash": prepared["receipt_hash"],
                "revision_draft_receipt_hash": draft["receipt_hash"],
            },
        )
        model_completed = True
        revised, proposal, revision, route = parse_route_repair(
            raw, prepared=prepared, frame=frame, review=review
        )
        run = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageRouteRepairRun",
                "run_id": run_id,
                "prepared_receipt_hash": prepared["receipt_hash"],
                "route_receipt_hash": route["receipt_hash"],
                "revised_frame_receipt_hash": revised["receipt_hash"],
                "model_session_id": usage["session_id"],
                "reported_model_cost_usd": usage["estimated_cost_usd"],
                "model_trace_message_count": len(trace["messages"]),
                "source_calls": 0,
                "independence_verified": False,
                "release_authorized": False,
            }
        )
        for name, value in (
            ("prepared.json", prepared),
            ("frame.json", revised),
            ("proposal.json", proposal),
            ("revision.json", revision),
            ("route.json", route),
            ("route-run.json", run),
        ):
            write_exclusive_json(output / name, value)
        print(
            json.dumps(
                {
                    "status": "provisional_revised_frame",
                    "run_id": run_id,
                    "facet_count": len(revised["facets"]),
                    "atom_count": len(revised["atoms"]),
                    "source_calls": 0,
                    "independence_verified": False,
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
