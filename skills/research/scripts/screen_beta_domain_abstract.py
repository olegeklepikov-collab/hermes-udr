"""Screen one OpenAlex abstract as an abstract, never as a read paper."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, write_exclusive_json
    from .model_call import ModelCallError, run_tool_free_model
    from .screen_beta_coverage_candidate import persist_coverage_screen_result
except ImportError:
    from file_io import load_json, write_exclusive_json
    from model_call import ModelCallError, run_tool_free_model
    from screen_beta_coverage_candidate import persist_coverage_screen_result

from hermes_research_report.beta_coverage_screen import build_coverage_screen_prompt
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--batch-plan", type=Path, required=True)
    parser.add_argument("--metadata-capture", type=Path, required=True)
    parser.add_argument("--work-id", required=True)
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
        batch, _ = load_json(args.batch_plan)
        capture, _ = load_json(args.metadata_capture)
        if (
            type(frame) is not dict
            or type(batch) is not dict
            or type(capture) is not dict
            or not all(verify_receipt_hash(row) for row in (frame, batch, capture))
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{frame['run_id']}-hole-fill/frame.json"
            or args.batch_plan
            != args.output_root
            / f"{batch['batch_run_id']}-coverage-source-plan/batch-plan.json"
            or args.metadata_capture
            != args.output_root
            / f"{batch['batch_run_id']}-LEAF-002-openalex/capture.json"
            or batch.get("frame_receipt_hash") != frame["receipt_hash"]
            or capture.get("contract") != "BetaOpenAlexMetadataAcquisition"
            or capture.get("run_id") != batch["batch_run_id"]
        ):
            raise ValueError("domain_abstract_paths_invalid")
        works = capture.get("works")
        matches = (
            [
                row
                for row in works
                if type(row) is dict and row.get("work_id") == args.work_id
            ]
            if type(works) is list
            else []
        )
        if len(matches) != 1:
            raise ValueError("domain_abstract_work_invalid")
        work = matches[0]
        title, abstract = work.get("title"), work.get("abstract_text")
        if type(title) is not str or type(abstract) is not str or len(abstract) < 40:
            raise ValueError("domain_abstract_text_unavailable")
        atom_rows = [
            row for row in frame["atoms"] if row["atom_id"] == batch["atom_id"]
        ]
        if len(atom_rows) != 1:
            raise ValueError("domain_abstract_atom_invalid")
        source_id = (
            f"SRC-{hashlib.sha256(args.work_id.encode()).hexdigest()[:16].upper()}"
        )
        text = title + "\n" + abstract
        prompt = build_coverage_screen_prompt(
            atom=atom_rows[0],
            title=title,
            source_id=source_id,
            text=text,
        )
        run_id = f"{batch['batch_run_id']}-A01"
        output = args.output_root / f"{run_id}-{source_id}-abstract-screen"
        assert output is not None
        raw, usage, trace = run_tool_free_model(
            bootstrap_budget={
                "schema_version": 1,
                "run_id": run_id,
                "wall_seconds": 60,
                "max_estimated_cost_usd": 0.01,
                "model_calls": 1,
            },
            prompt=prompt,
            hermes=args.hermes,
            output=output,
            attempt_binding={
                "purpose": "domain_metadata_abstract_screen",
                "frame_receipt_hash": frame["receipt_hash"],
                "batch_plan_receipt_hash": batch["receipt_hash"],
                "capture_receipt_hash": capture["receipt_hash"],
                "work_id_sha256": hashlib.sha256(args.work_id.encode()).hexdigest(),
                "abstract_sha256": hashlib.sha256(text.encode()).hexdigest(),
            },
        )
        model_completed = True
        screen, _ = persist_coverage_screen_result(
            output=output,
            raw=raw,
            atom=atom_rows[0],
            title=title,
            source_id=source_id,
            text=text,
            frame=frame,
            capture=capture,
            usage=usage,
            trace=trace,
            reconciled=False,
            full_text=False,
        )
        scope = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaDomainAbstractScreenScope",
                "run_id": run_id,
                "screen_receipt_hash": screen["receipt_hash"],
                "metadata_capture_receipt_hash": capture["receipt_hash"],
                "batch_plan_receipt_hash": batch["receipt_hash"],
                "work_id": args.work_id,
                "doi": work.get("doi"),
                "read_scope": "title_and_metadata_abstract_only",
                "full_text_read": False,
                "methods_and_statistics_verified": False,
                "primary_origin_independence_verified": False,
                "claim_truth_verified": False,
                "abstract_only_hypothesis_allowed": True,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "abstract-scope.json", scope)
        print(
            json.dumps(
                {
                    "status": "abstract_screened",
                    "relation": screen["relation_effective"],
                    "read_scope": "title_and_metadata_abstract_only",
                    "full_text_read": False,
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
