"""One bounded autonomous Deep checkpoint from a presealed v2 plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
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
    from .run_beta_search import SearchRunError, _child, _receipt
except ImportError:
    from file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from run_beta_search import SearchRunError, _child, _receipt

from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import runtime_guarded

SCRIPTS = Path(__file__).resolve().parent
_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


def _finish(
    output: Path,
    *,
    plan: dict,
    status: str,
    reason: str | None,
    execution: dict | None,
    semantic: dict | None,
    result: dict | None,
    fallback: dict | None = None,
    unknown_model_cost: bool = False,
) -> dict:
    note = (
        "Недостаточно независимых проверенных работ для вывода Deep. "
        "Принятых тезисов: 0. Причины и сохранённые источники указаны в квитанции.\n"
    )
    if result is None and fallback is None:
        write_exclusive_bytes(output / "result.md", note.encode("utf-8"))
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaAutonomousDeepRun",
            "execution_contract": {
                "kind": "standalone_local_research",
                "beads_work_executed": False,
                "dolt_commit_executed": False,
                "external_delivery_executed": False,
            },
            "status": status,
            "reason_code": reason,
            "run_id": plan["run_id"],
            "plan_receipt_hash": plan["receipt_hash"],
            "execution_receipt_hash": execution["receipt_hash"] if execution else None,
            "semantic_check_receipt_hash": semantic["receipt_hash"]
            if semantic
            else None,
            "result_receipt_hash": result["receipt_hash"] if result else None,
            "abstract_fallback_receipt_hash": fallback["receipt_hash"]
            if fallback
            else None,
            "provisional_claim_count": result["provisional_claim_count"]
            if result
            else fallback["provisional_claim_count"]
            if fallback
            else 0,
            "accepted_claim_count": 0,
            "observed_source_slots": execution["observed_source_slots"]
            if execution
            else None,
            "reported_total_cost_usd": result["reported_total_cost_usd"]
            if result and not unknown_model_cost
            else fallback["reported_total_cost_usd"]
            if fallback and not unknown_model_cost
            else None
            if unknown_model_cost
            else execution.get("reported_total_cost_usd")
            if execution
            else None,
            "cost_observation_complete": not unknown_model_cost
            and (
                result is not None
                or fallback is not None
                or (
                    execution is not None
                    and execution.get("reported_total_cost_usd") is not None
                )
            ),
            "final_acceptance_external": True,
            "internal_human_gate_required": False,
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
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--public-query-ack", action="store_true")
    args = parser.parse_args(argv)
    if not args.public_query_ack:
        print(
            json.dumps({"status": "error", "code": "public_query_ack_required"}),
            file=sys.stderr,
        )
        return 2
    output: Path | None = None
    plan: dict | None = None
    execution: dict | None = None
    semantic: dict | None = None
    try:
        plan_value, _ = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        if (
            plan["schema_version"] != 2
            or plan["mode"] != "deep"
            or plan["status"] != "ready_to_execute"
        ):
            raise ValueError("deep_plan_not_executable")
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
        ):
            raise ValueError("deep_output_root_invalid")
        run_id = plan["run_id"]
        output = args.output_root / f"{run_id}-deep-overall"
        new_private_directory(output)
        write_exclusive_json(
            output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "run_id": run_id,
                "plan_receipt_hash": plan["receipt_hash"],
                "retry_allowed": False,
            },
        )
        deadline = time.monotonic() + float(plan["limits"]["wall_seconds"])

        def left() -> float:
            return deadline - time.monotonic()

        source_code, _source_output = _child(
            [
                sys.executable,
                str(SCRIPTS / "execute_beta_sources.py"),
                "--plan",
                str(args.plan),
                "--output-root",
                str(args.output_root),
                "--hermes",
                str(args.hermes),
                "--public-query-ack",
            ],
            timeout=left(),
        )
        execution_file = args.output_root / f"{run_id}-execution/execution.json"
        execution = _receipt(execution_file, "BetaAutomaticSourceExecution", run_id)
        if execution["plan_receipt_hash"] != plan["receipt_hash"]:
            raise ValueError("deep_execution_not_bound")
        if source_code == 3 or execution["status"] != "partial_analysis_required":
            final = _finish(
                output,
                plan=plan,
                status="insufficient_evidence",
                reason="source_execution_blocked",
                execution=execution,
                semantic=None,
                result=None,
            )
            print(
                json.dumps(
                    {
                        "status": final["status"],
                        "run_id": run_id,
                        "result": str(output / "result.md"),
                        "accepted_claim_count": 0,
                        "release_authorized": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
        screens = execution.get("article_screens")
        publishers = execution.get("publisher_raw_attempts")
        if type(screens) is not list or type(publishers) is not list:
            raise ValueError("deep_execution_analysis_invalid")
        direct = [
            row
            for row in screens
            if type(row) is dict and row.get("status") == "verification_required"
        ]
        if len(direct) != 1:
            fallback: dict | None = None
            unknown_model_cost = False
            try:
                fallback_code, _ = _child(
                    [
                        sys.executable,
                        str(SCRIPTS / "run_beta_abstract_fallback.py"),
                        "--plan",
                        str(args.plan),
                        "--execution",
                        str(execution_file),
                        "--portfolio",
                        str(args.output_root / f"{run_id}-execution/portfolio.json"),
                        "--hermes",
                        str(args.hermes),
                        "--output-root",
                        str(args.output_root),
                    ],
                    timeout=left(),
                )
                if fallback_code == 0:
                    fallback = _receipt(
                        args.output_root / f"{run_id}-abstract-result/result.json",
                        "BetaDeepAbstractFallback",
                        run_id,
                    )
                    if (
                        fallback["execution_receipt_hash"] != execution["receipt_hash"]
                        or fallback["plan_receipt_hash"] != plan["receipt_hash"]
                        or fallback["accepted_claim_count"] != 0
                    ):
                        raise ValueError("deep_abstract_fallback_not_bound")
                    raw_fallback = read_private_bytes(
                        args.output_root / f"{run_id}-abstract-result/result.md"
                    )
                    if (
                        hashlib.sha256(raw_fallback).hexdigest()
                        != fallback["markdown_sha256"]
                    ):
                        raise ValueError("deep_abstract_fallback_text_invalid")
                    write_exclusive_bytes(output / "result.md", raw_fallback)
            except SearchRunError:
                unknown_model_cost = True
            final = _finish(
                output,
                plan=plan,
                status=fallback["status"] if fallback else "insufficient_evidence",
                reason="full_text_unavailable_abstract_only"
                if fallback
                else "no_direct_article_candidate",
                execution=execution,
                semantic=None,
                result=None,
                fallback=fallback,
                unknown_model_cost=unknown_model_cost,
            )
            print(
                json.dumps(
                    {
                        "status": final["status"],
                        "run_id": run_id,
                        "result": str(output / "result.md"),
                        "provisional_claim_count": final["provisional_claim_count"],
                        "accepted_claim_count": 0,
                        "release_authorized": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
        row = direct[0]
        leaf_id, work_id = row.get("leaf_id"), row.get("work_id")
        if (
            type(leaf_id) is not str
            or type(work_id) is not str
            or not re.fullmatch(r"https://openalex\.org/W[0-9]+", work_id)
        ):
            raise ValueError("deep_article_binding_invalid")
        short = work_id.removeprefix("https://openalex.org/")
        expected_screen = (
            args.output_root / f"{run_id}-{leaf_id}-{short}-screen/screen.json"
        )
        if row.get("capture") != str(expected_screen):
            raise ValueError("deep_article_binding_invalid")
        matching_publisher = [
            item
            for item in publishers
            if type(item) is dict
            and item.get("leaf_id") == leaf_id
            and item.get("work_id") == work_id
            and item.get("status") == "publisher_html_candidate"
        ]
        if len(matching_publisher) != 1:
            raise ValueError("deep_publisher_binding_invalid")
        metadata_file = args.output_root / f"{run_id}-{leaf_id}-openalex/capture.json"
        article_file = (
            args.output_root / f"{run_id}-{leaf_id}-{short}-oa-text/capture.json"
        )
        publisher_file = (
            args.output_root / f"{run_id}-{leaf_id}-{short}-publisher-raw/capture.json"
        )
        if matching_publisher[0].get("capture") != str(publisher_file):
            raise ValueError("deep_publisher_binding_invalid")
        origin_file = args.output_root / f"{run_id}.origin-graph.json"
        origin_command = [
            sys.executable,
            str(SCRIPTS / "assess_beta_origin_graph.py"),
            "--plan",
            str(args.plan),
            "--execution",
            str(execution_file),
            "--portfolio",
            str(args.output_root / f"{run_id}-execution/portfolio.json"),
            "--metadata-capture",
            str(metadata_file),
            "--article-capture",
            str(article_file),
            "--publisher-capture",
            str(publisher_file),
            "--output",
            str(origin_file),
        ]
        web_leaves = [leaf for leaf in plan["leaves"] if leaf["source_family"] == "web"]
        if len(web_leaves) == 1:
            web_capture = (
                args.output_root
                / f"{run_id}-{web_leaves[0]['leaf_id']}-keenable/capture.json"
            )
            if web_capture.is_file():
                origin_command.extend(("--web-capture", str(web_capture)))
        origin_code, _origin_output = _child(origin_command, timeout=min(30.0, left()))
        if origin_code != 0:
            raise ValueError("deep_origin_graph_incomplete")
        origin_graph = _receipt(origin_file, "BetaWorkOriginGraph", run_id)
        if (
            origin_graph["plan_receipt_hash"] != plan["receipt_hash"]
            or origin_graph["execution_receipt_hash"] != execution["receipt_hash"]
            or origin_graph["independent_second_work_verified"] is not False
        ):
            raise ValueError("deep_origin_graph_not_bound")
        screen_dir = expected_screen.parent
        verify_dir = args.output_root / f"{run_id}-{leaf_id}-{short}-verify"
        verify_code, _verify_output = _child(
            [
                sys.executable,
                str(SCRIPTS / "verify_openalex_oa_semantic.py"),
                "--plan",
                str(args.plan),
                "--metadata-capture",
                str(metadata_file),
                "--article-capture",
                str(article_file),
                "--publisher-capture",
                str(publisher_file),
                "--screen-dir",
                str(screen_dir),
                "--execution",
                str(execution_file),
                "--hermes",
                str(args.hermes),
                "--output",
                str(verify_dir),
            ],
            timeout=left(),
        )
        if verify_code != 0:
            raise ValueError("deep_semantic_incomplete")
        semantic_file = verify_dir / "semantic-check.json"
        semantic = _receipt(semantic_file, "BetaSemanticModelCheck", run_id)
        crosswork_file: Path | None = None
        crosswork: dict | None = None
        unknown_crosswork_cost = False
        if plan["limits"]["model_calls"] >= 3 and semantic["verdict"] in {
            "supported",
            "unclear",
        }:
            try:
                crosswork_code, _ = _child(
                    [
                        sys.executable,
                        str(SCRIPTS / "compare_beta_deep_works.py"),
                        "--plan",
                        str(args.plan),
                        "--execution",
                        str(execution_file),
                        "--portfolio",
                        str(args.output_root / f"{run_id}-execution/portfolio.json"),
                        "--origin-graph",
                        str(origin_file),
                        "--candidate",
                        str(screen_dir / "model-candidate.json"),
                        "--semantic-check",
                        str(semantic_file),
                        "--hermes",
                        str(args.hermes),
                        "--output-root",
                        str(args.output_root),
                    ],
                    timeout=left(),
                )
                if crosswork_code == 0:
                    crosswork_file = (
                        args.output_root / f"{run_id}-deep-crosswork/comparison.json"
                    )
                    crosswork = _receipt(
                        crosswork_file, "BetaDeepCrossWorkComparison", run_id
                    )
                    if (
                        crosswork["primary_semantic_receipt_hash"]
                        != semantic["receipt_hash"]
                        or crosswork["origin_graph_receipt_hash"]
                        != origin_graph["receipt_hash"]
                    ):
                        raise ValueError("deep_crosswork_not_bound")
            except SearchRunError:
                unknown_crosswork_cost = True
        result_dir = args.output_root / f"{run_id}-deep-result"
        result_command = [
            sys.executable,
            str(SCRIPTS / "assemble_beta_deep_partial.py"),
            "--plan",
            str(args.plan),
            "--metadata-capture",
            str(metadata_file),
            "--article-capture",
            str(article_file),
            "--publisher-capture",
            str(publisher_file),
            "--screen-dir",
            str(screen_dir),
            "--execution",
            str(execution_file),
            "--origin-graph",
            str(origin_file),
            "--semantic-check",
            str(semantic_file),
            "--output",
            str(result_dir),
        ]
        if crosswork_file is not None:
            result_command.extend(("--crosswork", str(crosswork_file)))
        result_code, _result_output = _child(result_command, timeout=min(30.0, left()))
        if result_code != 0:
            raise ValueError("deep_result_incomplete")
        result = _receipt(
            result_dir / "result.json", "BetaLocalDeepPartialResult", run_id
        )
        fact_map = _receipt(result_dir / "fact-map.json", "BetaDeepFactMap", run_id)
        if (
            result["execution_receipt_hash"] != execution["receipt_hash"]
            or result["semantic_check_receipt_hash"] != semantic["receipt_hash"]
            or result["origin_graph_receipt_hash"] != origin_graph["receipt_hash"]
            or result["crosswork_receipt_hash"]
            != (crosswork["receipt_hash"] if crosswork else None)
            or result["fact_map_receipt_hash"] != fact_map["receipt_hash"]
            or result["fact_map"] != fact_map
            or fact_map["accepted_fact_count"] != 0
            or result["accepted_claim_count"] != 0
            or result["reported_total_cost_usd"]
            > plan["limits"]["max_estimated_cost_usd"]
        ):
            raise ValueError("deep_result_not_bound")
        final = _finish(
            output,
            plan=plan,
            status=result["status"],
            reason=None,
            execution=execution,
            semantic=semantic,
            result=result,
            unknown_model_cost=unknown_crosswork_cost,
        )
        print(
            json.dumps(
                {
                    "status": final["status"],
                    "run_id": run_id,
                    "result": str(result_dir / "result.md"),
                    "provisional_claim_count": result["provisional_claim_count"],
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
            code = "deep_run_failed"
        if (
            output is not None
            and plan is not None
            and not (output / "outcome.json").exists()
        ):
            try:
                _finish(
                    output,
                    plan=plan,
                    status="blocked",
                    reason=code,
                    execution=execution,
                    semantic=semantic,
                    result=None,
                )
            except (OSError, ValueError):
                pass
        print(
            json.dumps(
                {
                    "status": "error",
                    "code": code,
                    "run_id": plan["run_id"] if plan else None,
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
