"""Assemble a new Academic dossier from already saved, paid observations."""

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
        fsync_directory,
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from .run_beta_research import _verify_structure_files, assemble_source_dossier
    from .run_beta_search import _receipt
except ImportError:
    from file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from run_beta_research import _verify_structure_files, assemble_source_dossier
    from run_beta_search import _receipt

from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError

_RUN = re.compile(r"^[A-Z][A-Z0-9-]{2,63}$")
_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


def reassemble_academic(root: Path, run_id: str) -> tuple[dict, bytes, str]:
    if (
        not root.is_absolute()
        or root.is_symlink()
        or not root.is_dir()
        or stat.S_IMODE(root.stat().st_mode) & 0o077
        or not _RUN.fullmatch(run_id)
    ):
        raise ValueError("academic_reassembly_root_invalid")
    directory_names = (
        f"{run_id}-planning",
        f"{run_id}-execution",
        f"{run_id}-academic-screen",
        f"{run_id}-academic-pdf-structure",
        f"{run_id}-academic-fulltext-analysis",
        f"{run_id}-academic-overall",
    )
    if any((root / name).is_symlink() for name in directory_names):
        raise ValueError("academic_reassembly_input_symlink")
    plan_dir = root / directory_names[0]
    plan = verify_beta_mode_plan(
        _receipt(plan_dir / "plan.json", "BetaModeExecutionPlan", run_id)
    )
    if plan["mode"] != "academic" or plan["schema_version"] != 2:
        raise ValueError("academic_reassembly_plan_invalid")
    planning = _receipt(
        plan_dir / "planning-run.json", "BetaAutonomousPlanningRun", run_id
    )
    protocol_value, _ = load_json(plan_dir / "academic-protocol.json")
    if (
        type(protocol_value) is not dict
        or not verify_receipt_hash(protocol_value)
        or protocol_value.get("contract") != "BetaAutonomousAcademicProtocol"
        or protocol_value.get("run_id") != run_id
        or protocol_value.get("receipt_hash")
        != plan["academic_protocol"]["protocol_ref"]
    ):
        raise ValueError("academic_reassembly_protocol_invalid")
    protocol = protocol_value
    execution = _receipt(
        root / directory_names[1] / "execution.json",
        "BetaAutomaticSourceExecution",
        run_id,
    )
    portfolio = _receipt(
        root / directory_names[1] / "portfolio.json", "BetaSourcePortfolio", run_id
    )
    screening = _receipt(
        root / directory_names[2] / "screening.json",
        "BetaAcademicPreliminaryScreen",
        run_id,
    )
    prior = _receipt(
        root / directory_names[5] / "outcome.json",
        "BetaAutonomousProfileDossier",
        run_id,
    )
    if (
        prior.get("mode") != "academic"
        or prior.get("plan_receipt_hash") != plan["receipt_hash"]
        or prior.get("screening_receipt_hash") not in (None, screening["receipt_hash"])
        or prior.get("analysis_receipt_hash") is not None
        or prior.get("workflow_execution_complete") is not False
        or prior.get("release_authorized") is not False
    ):
        raise ValueError("academic_reassembly_prior_not_partial")
    selected = [
        row for row in screening["decisions"] if row["verdict"] == "include_candidate"
    ]
    records = {row["record_id"]: row for row in screening["records"]}
    if len(selected) != 1 or records[selected[0]["record_id"]]["provider"] != "arxiv":
        raise ValueError("academic_reassembly_candidate_invalid")
    record_id = selected[0]["record_id"]
    stem = record_id.rsplit("/", 1)[-1]
    leaf_id = records[record_id]["leaf_id"]
    full_dir = root / f"{run_id}-{leaf_id}-{stem}-fulltext"
    if full_dir.is_symlink():
        raise ValueError("academic_reassembly_input_symlink")
    fulltext = _receipt(full_dir / "capture.json", "BetaArxivFullTextRead", run_id)
    pdf = read_private_bytes(full_dir / "paper.pdf", maximum=50_000_000)
    parsed = read_private_bytes(full_dir / "paper.md", maximum=25_000_000)
    if (
        hashlib.sha256(pdf).hexdigest() != fulltext["pdf_sha256"]
        or hashlib.sha256(parsed).hexdigest() != fulltext["text_sha256"]
        or len(pdf) != fulltext["pdf_bytes"]
    ):
        raise ValueError("academic_reassembly_fulltext_bytes_invalid")
    structure_dir = root / directory_names[3]
    structure = _receipt(
        structure_dir / "structure.json", "BetaAcademicPdfStructure", run_id
    )
    _verify_structure_files(structure_dir, structure)
    analysis = _receipt(
        root / directory_names[4] / "analysis.json",
        "BetaAcademicFullTextAnalysis",
        run_id,
    )
    study_graph = _receipt(
        root / f"{run_id}.academic-study-graph.json",
        "BetaAcademicStudyGraph",
        run_id,
    )
    dossier, markdown = assemble_source_dossier(
        plan=plan,
        planning=planning,
        execution=execution,
        portfolio=portfolio,
        protocol=protocol,
        screening=screening,
        screening_attempted=True,
        fulltext=fulltext,
        fulltext_attempted=True,
        structure=structure,
        structure_attempted=True,
        analysis=analysis,
        analysis_attempted=True,
        study_graph=study_graph,
        study_graph_attempted=True,
    )
    if (
        not dossier["workflow_execution_complete"]
        or not dossier["cost_observation_complete"]
    ):
        raise ValueError("academic_reassembly_still_partial")
    body = dict(dossier)
    body.pop("receipt_hash")
    body["prior_partial_receipt_hash"] = prior["receipt_hash"]
    body["reassembled_without_new_calls"] = True
    return with_receipt_hash(body), markdown, prior["receipt_hash"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        dossier, markdown, prior_hash = reassemble_academic(
            args.output_root, args.run_id
        )
        output = args.output_root / f"{args.run_id}-academic-reassembled-overall"
        new_private_directory(output)
        write_exclusive_json(
            output / "attempt.json",
            {
                "schema_version": 1,
                "run_id": args.run_id,
                "prior_partial_receipt_hash": prior_hash,
                "additional_network_calls": 0,
                "additional_model_calls": 0,
                "retry_allowed": False,
            },
        )
        write_exclusive_bytes(output / "result.md", markdown)
        write_exclusive_json(output / "outcome.json", dossier)
        fsync_directory(output)
        print(
            json.dumps(
                {
                    "status": dossier["status"],
                    "run_id": args.run_id,
                    "result": str(output / "result.md"),
                    "workflow_execution_complete": True,
                    "reported_total_cost_usd": dossier["reported_total_cost_usd"],
                    "additional_network_calls": 0,
                    "additional_model_calls": 0,
                    "mode_qualified": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, OSError, ValueError, KeyError, TypeError) as error:
        code = error.code if isinstance(error, ContractError) else str(error)
        if not _CODE.fullmatch(code):
            code = "academic_reassembly_failed"
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
