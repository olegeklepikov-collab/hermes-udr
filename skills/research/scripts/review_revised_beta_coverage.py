"""Challenge a revised coverage map before any source-search batch."""

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
    from .review_beta_coverage import persist_coverage_review
except ImportError:
    from file_io import load_json, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model
    from review_beta_coverage import persist_coverage_review

from hermes_research_report.beta_coverage_planner import build_coverage_review_prompt
from hermes_research_report.canonical import verify_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
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
        if type(frame) is not dict or not verify_receipt_hash(frame):
            raise ValueError("coverage_review_frame_invalid")
        run_id = frame["run_id"]
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{run_id}-coverage-route-repair/frame.json"
        ):
            raise ValueError("coverage_revised_review_paths_invalid")
        generator, _ = load_json(args.frame.parent / "route-run.json")
        route, _ = load_json(args.frame.parent / "route.json")
        revision, _ = load_json(args.frame.parent / "revision.json")
        if (
            type(generator) is not dict
            or type(route) is not dict
            or type(revision) is not dict
            or not all(
                verify_receipt_hash(item) for item in (generator, route, revision)
            )
            or generator.get("contract") != "BetaCoverageRouteRepairRun"
            or generator.get("revised_frame_receipt_hash") != frame["receipt_hash"]
            or generator.get("route_receipt_hash") != route["receipt_hash"]
            or route.get("revision_receipt_hash") != revision["receipt_hash"]
        ):
            raise ValueError("coverage_revised_review_lineage_invalid")
        output = args.output_root / f"{run_id}-coverage-route-review"
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": run_id,
                "wall_seconds": 120,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=build_coverage_review_prompt(frame),
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "adversarial_revised_coverage_review",
                "frame_receipt_hash": frame["receipt_hash"],
                "route_receipt_hash": route["receipt_hash"],
            },
        )
        model_completed = True
        review, _ = persist_coverage_review(
            output=output,
            frame=frame,
            generator=generator,
            raw=raw,
            usage=usage,
            trace=trace,
            reconciled=False,
        )
        print(
            json.dumps(
                {
                    "status": review["verdict"],
                    "run_id": run_id,
                    "issue_count": review["issue_count"],
                    "model_cost_usd": usage["estimated_cost_usd"],
                    "independence_verified": False,
                    "source_calls": 0,
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
