"""Plan a web/scholarly discovery challenge for an empirical domain atom."""

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
    from .plan_beta_coverage_source import persist_coverage_source_plan
except ImportError:
    from file_io import load_json, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model
    from plan_beta_coverage_source import persist_coverage_source_plan

from hermes_research_report.beta_domain_source import build_domain_pair_prompt
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--decomposition", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--atom-id", required=True)
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
        decomposition, _ = load_json(args.decomposition)
        review, _ = load_json(args.review)
        if (
            type(frame) is not dict
            or type(decomposition) is not dict
            or type(review) is not dict
            or not all(
                verify_receipt_hash(row) for row in (frame, decomposition, review)
            )
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{frame['run_id']}-hole-fill/frame.json"
            or args.review
            != args.output_root / f"{frame['run_id']}-hole-review/review.json"
        ):
            raise ValueError("domain_pair_paths_invalid")
        prompt = build_domain_pair_prompt(
            frame, decomposition, review, atom_id=args.atom_id
        )
        batch_run_id = f"{frame['run_id']}-B01"
        output = args.output_root / f"{batch_run_id}-coverage-source-plan"
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": batch_run_id,
                "wall_seconds": 60,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=prompt,
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "domain_empirical_source_pair",
                "frame_receipt_hash": frame["receipt_hash"],
                "decomposition_receipt_hash": decomposition["receipt_hash"],
                "review_receipt_hash": review["receipt_hash"],
                "atom_id": args.atom_id,
            },
        )
        model_completed = True
        plan, batch = persist_coverage_source_plan(
            output=output,
            frame=frame,
            review=review,
            atom_id=args.atom_id,
            batch_number=1,
            raw=raw,
            usage=usage,
            trace=trace,
            reconciled=False,
        )
        atom = next(row for row in frame["atoms"] if row["atom_id"] == args.atom_id)
        route = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaDomainEmpiricalSourceRoute",
                "run_id": batch_run_id,
                "atom_id": args.atom_id,
                "frame_receipt_hash": frame["receipt_hash"],
                "decomposition_receipt_hash": decomposition["receipt_hash"],
                "review_receipt_hash": review["receipt_hash"],
                "batch_plan_receipt_hash": batch["receipt_hash"],
                "plan_receipt_hash": plan["receipt_hash"],
                "required_families_from_atom": atom["required_families"],
                "scholarly_index_is_optional_challenge": "scholarly_index"
                not in atom["required_families"],
                "academic_absence_does_not_block_partial_result": True,
                "parent_profile_qualified": False,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "domain-route.json", route)
        print(
            json.dumps(
                {
                    "status": "domain_empirical_pair_ready",
                    "run_id": batch_run_id,
                    "atom_id": args.atom_id,
                    "scholarly_index_is_optional_challenge": route[
                        "scholarly_index_is_optional_challenge"
                    ],
                    "model_cost_usd": usage["estimated_cost_usd"],
                    "parent_profile_qualified": False,
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
