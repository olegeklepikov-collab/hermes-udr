"""Run the existing bounded Deep checkpoint directly from a public question."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import new_private_directory, read_private_bytes, write_exclusive_json
    from .run_beta_search import SearchRunError, _child, _receipt
except ImportError:
    from file_io import new_private_directory, read_private_bytes, write_exclusive_json
    from run_beta_search import SearchRunError, _child, _receipt

from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import runtime_guarded

SCRIPTS = Path(__file__).resolve().parent
_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


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
    try:
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
        ):
            raise ValueError("output_root_invalid")
        plan_code, created = _child(
            [
                sys.executable,
                str(SCRIPTS / "plan_beta_from_question.py"),
                "--mode",
                "deep",
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
        if (
            plan_code != 0
            or created.get("status") != "ready_to_execute"
            or type(created.get("run_id")) is not str
        ):
            raise ValueError("deep_question_planning_blocked")
        run_id = created["run_id"]
        plan_dir = args.output_root / f"{run_id}-planning"
        if created.get("output") != str(plan_dir):
            raise ValueError("deep_question_plan_path_invalid")
        plan = verify_beta_mode_plan(
            _receipt(plan_dir / "plan.json", "BetaModeExecutionPlan", run_id)
        )
        planning = _receipt(
            plan_dir / "planning-run.json", "BetaAutonomousPlanningRun", run_id
        )
        if (
            plan["mode"] != "deep"
            or plan["question"] != args.question.strip()
            or plan["status"] != "ready_to_execute"
            or planning["plan_receipt_hash"] != plan["receipt_hash"]
        ):
            raise ValueError("deep_question_plan_not_bound")
        output = args.output_root / f"{run_id}-deep-question-overall"
        new_private_directory(output)
        write_exclusive_json(
            output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "run_id": run_id,
                "plan_receipt_hash": plan["receipt_hash"],
                "planning_run_receipt_hash": planning["receipt_hash"],
                "retry_allowed": False,
            },
        )
        deep_code, _ = _child(
            [
                sys.executable,
                str(SCRIPTS / "run_beta_deep.py"),
                "--plan",
                str(plan_dir / "plan.json"),
                "--output-root",
                str(args.output_root),
                "--hermes",
                str(args.hermes),
                "--public-query-ack",
            ],
            timeout=float(plan["limits"]["wall_seconds"]) + 5,
        )
        deep = _receipt(
            args.output_root / f"{run_id}-deep-overall/outcome.json",
            "BetaAutonomousDeepRun",
            run_id,
        )
        if (
            deep_code not in (0, 3)
            or deep["plan_receipt_hash"] != plan["receipt_hash"]
            or deep["accepted_claim_count"] != 0
        ):
            raise ValueError("deep_question_result_not_bound")
        if deep["result_receipt_hash"] is not None:
            result = _receipt(
                args.output_root / f"{run_id}-deep-result/result.json",
                "BetaLocalDeepPartialResult",
                run_id,
            )
            if result["receipt_hash"] != deep["result_receipt_hash"]:
                raise ValueError("deep_question_result_not_bound")
            result_path = args.output_root / f"{run_id}-deep-result/result.md"
            raw_result = read_private_bytes(result_path)
            if hashlib.sha256(raw_result).hexdigest() != result["markdown_sha256"]:
                raise ValueError("deep_question_markdown_not_bound")
        else:
            result_path = args.output_root / f"{run_id}-deep-overall/result.md"
            read_private_bytes(result_path)
        planner_cost, deep_cost = (
            planning.get("reported_model_cost_usd"),
            deep.get("reported_total_cost_usd"),
        )
        if (
            type(planner_cost) not in (int, float)
            or planner_cost < 0
            or (
                deep_cost is not None
                and (type(deep_cost) not in (int, float) or deep_cost < 0)
            )
        ):
            raise ValueError("deep_question_cost_invalid")
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaAutonomousDeepQuestionRun",
                "execution_contract": {
                    "kind": "standalone_local_research",
                    "beads_work_executed": False,
                    "dolt_commit_executed": False,
                    "external_delivery_executed": False,
                },
                "run_id": run_id,
                "status": deep["status"],
                "plan_receipt_hash": plan["receipt_hash"],
                "planning_run_receipt_hash": planning["receipt_hash"],
                "deep_run_receipt_hash": deep["receipt_hash"],
                "reported_total_cost_usd": round(planner_cost + deep_cost, 8)
                if deep_cost is not None
                else None,
                "accepted_claim_count": 0,
                "final_acceptance_external": True,
                "internal_human_gate_required": False,
                "mode_qualified": False,
                "release_authorized": False,
                "external_delivery_authorized": False,
            }
        )
        write_exclusive_json(output / "outcome.json", receipt)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "run_id": run_id,
                    "result": str(result_path),
                    "accepted_claim_count": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, SearchRunError, OSError, ValueError) as error:
        code = error.code if isinstance(error, ContractError) else str(error)
        if not _CODE.fullmatch(code):
            code = "deep_question_run_failed"
        print(
            json.dumps({"status": "error", "code": code, "run_id": run_id}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
