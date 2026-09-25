"""Rebuild a domain-anchored second batch from a saved model reply."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any, cast

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_json,
    )
except ImportError:
    from file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_json,
    )

from hermes_research_report.beta_domain_source import parse_domain_web_query
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--decomposition", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--prior-plan-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
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
            or args.prior_plan_dir.is_symlink()
            or stat.S_IMODE(args.prior_plan_dir.stat().st_mode) & 0o077
        ):
            raise ValueError("domain_replan_paths_invalid")
        run_id = frame["run_id"]
        prior_run_id = f"{run_id}-D01"
        if args.prior_plan_dir != args.output_root / f"{prior_run_id}-domain-web-plan":
            raise ValueError("domain_replan_paths_invalid")
        prior_plan, _ = load_json(args.prior_plan_dir / "plan.json")
        prior_batch, _ = load_json(args.prior_plan_dir / "batch.json")
        prior_run, _ = load_json(args.prior_plan_dir / "run.json")
        execution, _ = load_json(
            args.output_root / f"{prior_run_id}-execution/execution.json"
        )
        capture, _ = load_json(args.output_root / f"{prior_run_id}/capture.json")
        if any(
            type(row) is not dict or not verify_receipt_hash(row)
            for row in (prior_plan, prior_batch, prior_run, execution, capture)
        ):
            raise ValueError("domain_replan_lineage_invalid")
        prior_plan = cast(dict[str, Any], prior_plan)
        prior_batch = cast(dict[str, Any], prior_batch)
        prior_run = cast(dict[str, Any], prior_run)
        execution = cast(dict[str, Any], execution)
        capture = cast(dict[str, Any], capture)
        if (
            prior_batch["frame_receipt_hash"] != frame["receipt_hash"]
            or prior_batch["decomposition_receipt_hash"]
            != decomposition["receipt_hash"]
            or prior_batch["review_receipt_hash"] != review["receipt_hash"]
            or prior_batch["subplan_receipt_hash"] != prior_plan["receipt_hash"]
            or prior_run["batch_receipt_hash"] != prior_batch["receipt_hash"]
            or execution["plan_receipt_hash"] != prior_plan["receipt_hash"]
            or capture["plan_receipt_hash"] != prior_plan["receipt_hash"]
            or capture.get("successful_sources") != 0
        ):
            raise ValueError("domain_replan_lineage_invalid")
        raw = (
            read_private_bytes(
                args.prior_plan_dir / "model.raw.json", maximum=1_048_576
            )
            .decode("utf-8")
            .rstrip("\n")
        )
        if (
            hashlib.sha256(raw.encode()).hexdigest()
            != prior_batch["raw_response_sha256"]
        ):
            raise ValueError("domain_replan_raw_mismatch")
        anchor = " ".join(re.findall(r"\w+", decomposition["domains"][0]["name"])[:3])
        if anchor and anchor.casefold() in prior_plan["leaves"][0]["query"].casefold():
            raise ValueError("domain_replan_anchor_already_present")
        plan, batch = parse_domain_web_query(
            raw,
            frame=frame,
            decomposition=decomposition,
            review=review,
            atom_id=prior_batch["atom_id"],
            batch_number=2,
        )
        if not batch["query_domain_anchor_added"]:
            raise ValueError("domain_replan_anchor_not_added")
        output = args.output_root / f"{run_id}-D02-domain-web-plan"
        new_private_directory(output)
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaDomainWebQueryReplan",
                "run_id": plan["run_id"],
                "prior_batch_receipt_hash": prior_batch["receipt_hash"],
                "prior_execution_receipt_hash": execution["receipt_hash"],
                "prior_capture_receipt_hash": capture["receipt_hash"],
                "batch_receipt_hash": batch["receipt_hash"],
                "plan_receipt_hash": plan["receipt_hash"],
                "reason": "missing_domain_anchor_and_zero_successful_sources",
                "additional_model_calls": 0,
                "source_calls_before_replan": execution["source_calls_completed"],
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "plan.json", plan)
        write_exclusive_json(output / "batch.json", batch)
        write_exclusive_json(output / "replan.json", receipt)
        print(
            json.dumps(
                {
                    "status": "domain_web_replanned",
                    "run_id": plan["run_id"],
                    "atom_id": batch["atom_id"],
                    "query_domain_anchor_added": True,
                    "additional_model_calls": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, UnicodeError, KeyError, TypeError) as error:
        print(json.dumps({"status": "error", "code": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
