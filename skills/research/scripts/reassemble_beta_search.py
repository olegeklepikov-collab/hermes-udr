"""Assemble a graded Search result after replaying a saved paid draft."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from .run_beta_search import _receipt
except ImportError:
    from file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from run_beta_search import _receipt

from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.output_root
        run_id = args.run_id
        if (
            not root.is_absolute()
            or root.is_symlink()
            or not root.is_dir()
            or stat.S_IMODE(root.stat().st_mode) & 0o077
            or not re.fullmatch(r"^BETA-AUTO-[0-9]{8}-[0-9]{6}-[A-F0-9]{8}$", run_id)
        ):
            raise ValueError("search_reassembly_root_invalid")
        plan = verify_beta_mode_plan(
            _receipt(
                root / f"{run_id}-planning/plan.json", "BetaModeExecutionPlan", run_id
            )
        )
        planning = _receipt(
            root / f"{run_id}-planning/planning-run.json",
            "BetaAutonomousPlanningRun",
            run_id,
        )
        prior = _receipt(
            root / f"{run_id}-overall/outcome.json", "BetaAutonomousSearchRun", run_id
        )
        execution = _receipt(
            root / f"{run_id}-execution/execution.json",
            "BetaAutomaticSourceExecution",
            run_id,
        )
        portfolio = _receipt(
            root / f"{run_id}-execution/portfolio.json", "BetaSourcePortfolio", run_id
        )
        candidate = _receipt(
            root / f"{run_id}-model/model-candidate.json", "BetaModelCandidate", run_id
        )
        semantic = _receipt(
            root / f"{run_id}-verify/semantic-check.json",
            "BetaSemanticModelCheck",
            run_id,
        )
        result = _receipt(
            root / f"{run_id}-result/result.json", "BetaLocalSearchResult", run_id
        )
        reconciliation, _ = load_json(root / f"{run_id}-model/reconciliation.json")
        markdown = read_private_bytes(
            root / f"{run_id}-result/result.md", maximum=250_000
        )
        if (
            plan["mode"] != "search"
            or prior["status"] != "blocked"
            or prior["reason_code"]
            not in {"search_draft_incomplete", "model_response_schema_invalid"}
            or prior["plan_receipt_hash"] != plan["receipt_hash"]
            or planning["plan_receipt_hash"] != plan["receipt_hash"]
            or portfolio["plan_receipt_hash"] != plan["receipt_hash"]
            or execution["plan_receipt_hash"] != plan["receipt_hash"]
            or execution["source_calls_completed"] < 1
            or candidate["plan_receipt_hash"] != plan["receipt_hash"]
            or candidate["portfolio_receipt_hash"] != portfolio["receipt_hash"]
            or semantic["candidate_receipt_hash"] != candidate["receipt_hash"]
            or result["candidate_receipt_hash"] != candidate["receipt_hash"]
            or result["semantic_check_receipt_hash"] != semantic["receipt_hash"]
            or result["portfolio_receipt_hash"] != portfolio["receipt_hash"]
            or result["claim_count"] not in (0, 1)
            or type(reconciliation) is not dict
            or reconciliation.get("candidate_receipt_hash") != candidate["receipt_hash"]
            or reconciliation.get("additional_model_calls") != 0
            or hashlib.sha256(markdown).hexdigest() != result["markdown_sha256"]
        ):
            raise ValueError("search_reassembly_lineage_invalid")
        total_cost = (
            planning["reported_model_cost_usd"] + result["reported_total_cost_usd"]
        )
        if total_cost > plan["limits"]["max_estimated_cost_usd"] + 0.01:
            raise ValueError("search_reassembly_budget_exceeded")
        stages = [
            {
                "stage": "planning",
                "status": "complete",
                "receipt_hash": planning["receipt_hash"],
            },
            {
                "stage": "sources",
                "status": portfolio["status"],
                "receipt_hash": portfolio["receipt_hash"],
            },
            {
                "stage": "draft",
                "status": candidate["status"],
                "receipt_hash": candidate["receipt_hash"],
            },
            {
                "stage": "semantic_check",
                "status": semantic["status"],
                "receipt_hash": semantic["receipt_hash"],
            },
            {
                "stage": "result",
                "status": result["status"],
                "receipt_hash": result["receipt_hash"],
            },
        ]
        outcome = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaAutonomousSearchRun",
                "run_id": run_id,
                "status": result["status"],
                "reason_code": None,
                "plan_receipt_hash": plan["receipt_hash"],
                "planning_run_receipt_hash": planning["receipt_hash"],
                "result_receipt_hash": result["receipt_hash"],
                "local_result_sha256": result["markdown_sha256"],
                "stages": stages,
                "reported_planning_cost_usd": planning["reported_model_cost_usd"],
                "reported_research_cost_usd": result["reported_total_cost_usd"],
                "reported_total_cost_usd": total_cost,
                "prior_partial_receipt_hash": prior["receipt_hash"],
                "saved_draft_recovered_without_repeat": True,
                "additional_draft_model_calls": 0,
                "semantic_check_model_calls_after_recovery": 1,
                "internal_human_gate_required": False,
                "final_acceptance_external": True,
                "mode_qualified": False,
                "release_authorized": False,
                "external_delivery_authorized": False,
            }
        )
        output = root / f"{run_id}-search-reassembled-overall"
        new_private_directory(output)
        write_exclusive_bytes(output / "result.md", markdown)
        write_exclusive_json(output / "outcome.json", outcome)
        print(
            json.dumps(
                {
                    "status": outcome["status"],
                    "run_id": run_id,
                    "claim_count": result["claim_count"],
                    "additional_draft_model_calls": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        ContractError,
        OSError,
        ValueError,
        UnicodeError,
        KeyError,
        TypeError,
    ) as error:
        code = error.code if isinstance(error, ContractError) else str(error)
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
