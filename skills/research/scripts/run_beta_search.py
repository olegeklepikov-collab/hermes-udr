"""One bounded autonomous local Search run; never deliver or release externally."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import (
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
except ImportError:
    from file_io import (
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )

from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import runtime_guarded, verify_runtime

SCRIPTS = Path(__file__).resolve().parent
_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


class SearchRunError(ValueError):
    pass


def _child(command: list[str], *, timeout: float) -> tuple[int, dict[str, Any]]:
    verify_runtime()
    if timeout <= 0:
        raise SearchRunError("search_wall_limit_exhausted")
    try:
        process = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise SearchRunError("search_child_outcome_unknown") from None
    try:
        result = json.loads(
            (process.stdout if process.returncode in (0, 3) else process.stderr).strip()
        )
    except (json.JSONDecodeError, ValueError):
        raise SearchRunError("search_child_response_invalid") from None
    if type(result) is not dict:
        raise SearchRunError("search_child_response_invalid")
    if process.returncode not in (0, 3):
        code = result.get("code")
        raise SearchRunError(
            code
            if type(code) is str and _CODE.fullmatch(code)
            else "search_child_failed"
        )
    return process.returncode, result


def _receipt(path: Path, contract: str, run_id: str) -> dict[str, Any]:
    value, _ = load_json(path)
    if (
        type(value) is not dict
        or not verify_receipt_hash(value)
        or value.get("contract") != contract
        or value.get("run_id") != run_id
        or value.get("release_authorized") is not False
    ):
        raise SearchRunError("search_saved_receipt_invalid")
    return value


def _finish(
    output: Path,
    *,
    run_id: str,
    plan: dict[str, Any],
    planning: dict[str, Any],
    status: str,
    reason: str | None,
    stages: list[dict[str, object]],
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    planner_cost = planning["reported_model_cost_usd"]
    research_cost = result["reported_total_cost_usd"] if result else None
    note = (
        "Недостаточно проверенных данных для содержательного ответа. "
        "Система сохранила причину остановки и не выдала тезис.\n"
    )
    if result is None:
        write_exclusive_bytes(output / "result.md", note.encode())
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaAutonomousSearchRun",
            "execution_contract": {
                "kind": "standalone_local_research",
                "beads_work_executed": False,
                "dolt_commit_executed": False,
                "external_delivery_executed": False,
            },
            "run_id": run_id,
            "status": status,
            "reason_code": reason,
            "plan_receipt_hash": plan["receipt_hash"],
            "planning_run_receipt_hash": planning["receipt_hash"],
            "result_receipt_hash": result["receipt_hash"] if result else None,
            "local_result_sha256": result["markdown_sha256"]
            if result
            else hashlib.sha256(note.encode()).hexdigest(),
            "stages": stages,
            "reported_planning_cost_usd": planner_cost,
            "reported_research_cost_usd": research_cost,
            "reported_total_cost_usd": planner_cost + research_cost
            if research_cost is not None
            else None,
            "internal_human_gate_required": False,
            "final_acceptance_external": True,
            "mode_qualified": False,
            "release_authorized": False,
            "external_delivery_authorized": False,
        }
    )
    write_exclusive_json(output / "outcome.json", receipt)
    return receipt


@runtime_guarded
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
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
    run_id: str | None = None
    output: Path | None = None
    plan: dict[str, Any] | None = None
    planning: dict[str, Any] | None = None
    stages: list[dict[str, object]] = []
    try:
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
        ):
            raise SearchRunError("output_root_invalid")
        code, created = _child(
            [
                sys.executable,
                str(SCRIPTS / "plan_beta_from_question.py"),
                "--mode",
                "search",
                "--question",
                args.question,
                "--hermes",
                str(args.hermes),
                "--output-root",
                str(args.output_root),
                "--public-query-ack",
            ],
            timeout=75,
        )
        if code != 0 or created.get("status") != "ready_to_execute":
            raise SearchRunError("search_planning_blocked")
        run_id = created.get("run_id")
        if type(run_id) is not str:
            raise SearchRunError("search_planning_binding_invalid")
        plan_dir = args.output_root / f"{run_id}-planning"
        if created.get("output") != str(plan_dir):
            raise SearchRunError("search_planning_binding_invalid")
        plan = _receipt(plan_dir / "plan.json", "BetaModeExecutionPlan", run_id)
        planning = _receipt(
            plan_dir / "planning-run.json", "BetaAutonomousPlanningRun", run_id
        )
        plan = verify_beta_mode_plan(plan)
        if (
            plan["mode"] != "search"
            or plan["status"] != "ready_to_execute"
            or planning["plan_receipt_hash"] != plan["receipt_hash"]
            or planning["reported_model_cost_usd"] > 0.01
        ):
            raise SearchRunError("search_planning_binding_invalid")
        output = args.output_root / f"{run_id}-overall"
        new_private_directory(output)
        write_exclusive_json(
            output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "run_id": run_id,
                "question_sha256": hashlib.sha256(
                    plan["question"].encode()
                ).hexdigest(),
                "plan_receipt_hash": plan["receipt_hash"],
                "planning_run_receipt_hash": planning["receipt_hash"],
                "retry_allowed": False,
            },
        )
        stages.append(
            {
                "stage": "planning",
                "status": "complete",
                "receipt_hash": planning["receipt_hash"],
            }
        )
        deadline = time.monotonic() + float(plan["limits"]["wall_seconds"])

        def left() -> float:
            return deadline - time.monotonic()

        source_code, _ = _child(
            [
                sys.executable,
                str(SCRIPTS / "execute_beta_sources.py"),
                "--plan",
                str(plan_dir / "plan.json"),
                "--output-root",
                str(args.output_root),
                "--public-query-ack",
            ],
            timeout=left(),
        )
        source_dir = args.output_root / f"{run_id}-execution"
        execution = _receipt(
            source_dir / "execution.json", "BetaAutomaticSourceExecution", run_id
        )
        portfolio = _receipt(
            source_dir / "portfolio.json", "BetaSourcePortfolio", run_id
        )
        if (
            execution["plan_receipt_hash"] != plan["receipt_hash"]
            or portfolio["plan_receipt_hash"] != plan["receipt_hash"]
        ):
            raise SearchRunError("search_source_binding_invalid")
        stages.append(
            {
                "stage": "sources",
                "status": portfolio["status"],
                "receipt_hash": portfolio["receipt_hash"],
            }
        )
        if source_code == 3 or portfolio["status"] != "partial_analysis_required":
            final = _finish(
                output,
                run_id=run_id,
                plan=plan,
                planning=planning,
                status="insufficient_evidence",
                reason="source_portfolio_blocked",
                stages=stages,
                result=None,
            )
            print(
                json.dumps(
                    {
                        "status": final["status"],
                        "run_id": run_id,
                        "result": str(output / "result.md"),
                        "claim_count": 0,
                        "release_authorized": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
        capture_file = args.output_root / run_id / "capture.json"
        capture = _receipt(capture_file, "BetaSourceAcquisition", run_id)
        if capture["plan_receipt_hash"] != plan["receipt_hash"]:
            raise SearchRunError("search_source_binding_invalid")
        draft_dir = args.output_root / f"{run_id}-model"
        draft_code, _ = _child(
            [
                sys.executable,
                str(SCRIPTS / "draft_beta_model.py"),
                "--plan",
                str(plan_dir / "plan.json"),
                "--portfolio",
                str(source_dir / "portfolio.json"),
                "--web-capture",
                str(capture_file),
                "--hermes",
                str(args.hermes),
                "--output",
                str(draft_dir),
            ],
            timeout=left(),
        )
        if draft_code != 0:
            raise SearchRunError("search_draft_incomplete")
        candidate = _receipt(
            draft_dir / "model-candidate.json", "BetaModelCandidate", run_id
        )
        stages.append(
            {
                "stage": "draft",
                "status": candidate["status"],
                "receipt_hash": candidate["receipt_hash"],
            }
        )
        if candidate["status"] not in {"verification_required", "source_insufficient"}:
            raise SearchRunError("search_candidate_status_invalid")
        check_file: Path | None = None
        if candidate["status"] == "verification_required":
            verify_dir = args.output_root / f"{run_id}-verify"
            verify_code, _ = _child(
                [
                    sys.executable,
                    str(SCRIPTS / "verify_beta_semantic.py"),
                    "--plan",
                    str(plan_dir / "plan.json"),
                    "--portfolio",
                    str(source_dir / "portfolio.json"),
                    "--web-capture",
                    str(capture_file),
                    "--draft",
                    str(draft_dir),
                    "--hermes",
                    str(args.hermes),
                    "--output",
                    str(verify_dir),
                ],
                timeout=left(),
            )
            if verify_code != 0:
                raise SearchRunError("search_semantic_check_incomplete")
            check_file = verify_dir / "semantic-check.json"
            check = _receipt(check_file, "BetaSemanticModelCheck", run_id)
            stages.append(
                {
                    "stage": "semantic_check",
                    "status": check["status"],
                    "receipt_hash": check["receipt_hash"],
                }
            )
        result_dir = args.output_root / f"{run_id}-result"
        command = [
            sys.executable,
            str(SCRIPTS / "assemble_beta_search.py"),
            "--plan",
            str(plan_dir / "plan.json"),
            "--portfolio",
            str(source_dir / "portfolio.json"),
            "--web-capture",
            str(capture_file),
            "--draft",
            str(draft_dir / "model-candidate.json"),
            "--output",
            str(result_dir),
        ]
        if check_file is not None:
            command.extend(("--semantic-check", str(check_file)))
        assembly_code, _ = _child(command, timeout=min(30.0, left()))
        if assembly_code != 0:
            raise SearchRunError("search_result_incomplete")
        result = _receipt(result_dir / "result.json", "BetaLocalSearchResult", run_id)
        stages.append(
            {
                "stage": "result",
                "status": result["status"],
                "receipt_hash": result["receipt_hash"],
            }
        )
        if (
            planning["reported_model_cost_usd"] + result["reported_total_cost_usd"]
            > plan["limits"]["max_estimated_cost_usd"] + 0.01
        ):
            raise SearchRunError("search_combined_budget_exceeded")
        final = _finish(
            output,
            run_id=run_id,
            plan=plan,
            planning=planning,
            status=result["status"],
            reason=None,
            stages=stages,
            result=result,
        )
        print(
            json.dumps(
                {
                    "status": final["status"],
                    "run_id": run_id,
                    "result": str(result_dir / "result.md"),
                    "claim_count": result["claim_count"],
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, OSError, ValueError) as error:
        code = error.code if isinstance(error, ContractError) else str(error)
        if not _CODE.fullmatch(code):
            code = "search_run_failed"
        if (
            output is not None
            and plan is not None
            and planning is not None
            and run_id is not None
            and not (output / "outcome.json").exists()
        ):
            try:
                _finish(
                    output,
                    run_id=run_id,
                    plan=plan,
                    planning=planning,
                    status="blocked",
                    reason=code,
                    stages=stages,
                    result=None,
                )
            except (OSError, ValueError):
                pass
        print(
            json.dumps({"status": "error", "code": code, "run_id": run_id}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
