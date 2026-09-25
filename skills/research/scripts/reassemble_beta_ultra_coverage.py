"""Bind saved domain-first Ultra coverage to an existing partial dossier."""

from __future__ import annotations

import argparse
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
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from .run_beta_research import assemble_source_dossier
    from .run_beta_search import _receipt
except ImportError:
    from file_io import (
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from run_beta_research import assemble_source_dossier
    from run_beta_search import _receipt

from hermes_research_report.beta_coverage import assess_beta_coverage
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--domain-run-id", required=True)
    parser.add_argument("--coverage-run-id", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.output_root
        run_id, domain_id, coverage_id = (
            args.run_id,
            args.domain_run_id,
            args.coverage_run_id,
        )
        if (
            not root.is_absolute()
            or root.is_symlink()
            or not root.is_dir()
            or stat.S_IMODE(root.stat().st_mode) & 0o077
            or not re.fullmatch(r"BETA-AUTO-[0-9]{8}-[0-9]{6}-[A-F0-9]{8}", run_id)
            or not re.fullmatch(r"BETA-DOM-[0-9]{8}-[0-9]{6}-[A-F0-9]{8}", domain_id)
            or not re.fullmatch(r"BETA-COV-[0-9]{8}-[0-9]{6}-[A-F0-9]{8}", coverage_id)
        ):
            raise ValueError("ultra_coverage_reassembly_root_invalid")
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
            root / f"{run_id}-ultra-overall/outcome.json",
            "BetaAutonomousProfileDossier",
            run_id,
        )
        decomposition = _receipt(
            root / f"{domain_id}-domain-planning/decomposition.json",
            "BetaDomainDecomposition",
            domain_id,
        )
        domain_run = _receipt(
            root / f"{domain_id}-domain-planning/planning-run.json",
            "BetaDomainPlanningRun",
            domain_id,
        )
        frame_value, _ = load_json(root / f"{coverage_id}-coverage-planning/frame.json")
        coverage_run = _receipt(
            root / f"{coverage_id}-coverage-planning/planning-run.json",
            "BetaCoveragePlanningRun",
            coverage_id,
        )
        if (
            plan["mode"] != "ultra"
            or type(frame_value) is not dict
            or not verify_receipt_hash(frame_value)
            or frame_value.get("contract") != "BetaCoverageFrame"
            or frame_value.get("decomposition_receipt_hash")
            != decomposition["receipt_hash"]
            or coverage_run.get("frame_receipt_hash") != frame_value["receipt_hash"]
            or domain_run.get("decomposition_receipt_hash")
            != decomposition["receipt_hash"]
            or planning.get("decomposition_receipt_hash")
            != decomposition["receipt_hash"]
            or prior.get("domain_first_requested") is not True
            or prior.get("domain_decomposition_receipt_hash")
            != decomposition["receipt_hash"]
            or prior.get("coverage_frame_receipt_hash") is not None
            or "coverage_frame" not in prior.get("workflow_gaps", [])
            or prior.get("accepted_claim_count") != 0
        ):
            raise ValueError("ultra_coverage_reassembly_lineage_invalid")
        frame = frame_value
        progress = assess_beta_coverage(frame, [], budget_exhausted=False)
        progress_path = root / f"{coverage_id}-coverage-initial-progress.json"
        if progress_path.exists():
            stored, _ = load_json(progress_path)
            if stored != progress:
                raise ValueError("ultra_coverage_progress_changed")
        else:
            write_exclusive_json(progress_path, progress)
        execution = _receipt(
            root / f"{run_id}-execution/execution.json",
            "BetaAutomaticSourceExecution",
            run_id,
        )
        portfolio = _receipt(
            root / f"{run_id}-execution/portfolio.json", "BetaSourcePortfolio", run_id
        )
        challenge = _receipt(
            root / f"{run_id}-ultra-challenge/challenge.json",
            "BetaUltraRivalChallenge",
            run_id,
        )
        sensitivity = _receipt(
            root / f"{run_id}.ultra-sensitivity.json", "BetaUltraSensitivity", run_id
        )
        dossier, markdown = assemble_source_dossier(
            plan=plan,
            planning=planning,
            execution=execution,
            portfolio=portfolio,
            protocol=None,
            challenge=challenge,
            challenge_attempted=True,
            sensitivity=sensitivity,
            sensitivity_attempted=True,
            domain_first_requested=True,
            decomposition=decomposition,
            coverage_frame=frame,
            coverage_progress=progress,
            preflight_cost_usd=round(
                domain_run["reported_model_cost_usd"]
                + coverage_run["reported_model_cost_usd"],
                8,
            ),
            domain_run_id=domain_id,
            coverage_run_id=coverage_id,
        )
        body = {key: value for key, value in dossier.items() if key != "receipt_hash"}
        body.update(
            {
                "prior_partial_receipt_hash": prior["receipt_hash"],
                "reassembled_without_new_calls": True,
                "additional_model_calls": 0,
                "additional_source_calls": 0,
            }
        )
        dossier = with_receipt_hash(body)
        output = root / f"{run_id}-ultra-reassembled-overall"
        new_private_directory(output)
        write_exclusive_bytes(output / "result.md", markdown)
        write_exclusive_json(output / "outcome.json", dossier)
        print(
            json.dumps(
                {
                    "status": dossier["status"],
                    "run_id": run_id,
                    "workflow_execution_complete": dossier[
                        "workflow_execution_complete"
                    ],
                    "workflow_gaps": dossier["workflow_gaps"],
                    "additional_model_calls": 0,
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
