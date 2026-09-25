"""Run one bounded domain-grounded adaptive web batch for an open atom."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import stat
import subprocess
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
    from .model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model
except ImportError:
    from file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_json,
    )
    from model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model

from hermes_research_report.beta_coverage_screen import (
    build_coverage_screen_prompt,
    parse_coverage_screen,
)
from hermes_research_report.beta_domain_source import (
    append_domain_search_feedback,
    build_domain_search_feedback,
    build_domain_web_prompt,
    observe_domain_web_batch,
    parse_domain_web_query,
)
from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError

SCRIPTS = Path(__file__).resolve().parent


def _screen_first_retained_candidate(
    *,
    frame: dict[str, Any],
    capture: dict[str, Any],
    atom_id: str,
    batch_run_id: str,
    hermes: Path,
    output_root: Path,
    candidate_index: int = 0,
    cost_limit: float = 0.01,
) -> tuple[list[dict[str, Any]], float | None, bool]:
    leaves = capture.get("leaves")
    atom_rows = [row for row in frame["atoms"] if row["atom_id"] == atom_id]
    if type(leaves) is not list or len(leaves) != 1 or len(atom_rows) != 1:
        raise ValueError("adaptive_screen_inputs_invalid")
    attempts = leaves[0].get("candidate_attempts")
    if type(attempts) is not list:
        raise ValueError("adaptive_screen_inputs_invalid")
    retained = [
        row
        for row in attempts
        if type(row) is dict
        and row.get("status") in {"screened_out", "extracted_candidate"}
        and type(row.get("source_id")) is str
        and type(row.get("content_sha256")) is str
    ]
    if not retained:
        return [], 0.0, False
    candidate = retained[candidate_index]
    source_id = candidate["source_id"]
    payload = read_private_bytes(
        output_root / batch_run_id / f"{source_id}.txt", maximum=200_000
    )
    if hashlib.sha256(payload).hexdigest() != candidate["content_sha256"]:
        raise ValueError("adaptive_screen_source_changed")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return [], 0.0, False
    title = candidate.get("title")
    if type(title) is not str or not title or len(text) < 40:
        return [], 0.0, False
    prompt = build_coverage_screen_prompt(
        atom=atom_rows[0],
        title=title,
        source_id=source_id,
        text=text,
        full_text=True,
    )
    screen_id = f"{batch_run_id}-S{candidate_index + 1:02d}"
    suffix = "" if candidate_index == 0 else f"-{candidate_index + 1:02d}"
    directory = output_root / f"{batch_run_id}-domain-web-screen{suffix}"
    try:
        raw, usage, trace = run_tool_free_model(
            prompt=prompt,
            hermes=hermes,
            output=directory,
            attempt_binding={
                "purpose": "adaptive_coverage_candidate_screen",
                "frame_receipt_hash": frame["receipt_hash"],
                "capture_receipt_hash": capture["receipt_hash"],
                "atom_id": atom_id,
                "source_id": source_id,
                "source_text_sha256": candidate["content_sha256"],
            },
            bootstrap_budget={
                "schema_version": 1,
                "run_id": screen_id,
                "wall_seconds": 60,
                "max_estimated_cost_usd": cost_limit,
                "model_calls": 1,
            },
        )
        screen = parse_coverage_screen(
            raw,
            atom=atom_rows[0],
            title=title,
            source_id=source_id,
            text=text,
            frame=frame,
            capture=capture,
            full_text=True,
        )
        run = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaAdaptiveCoverageScreenRun",
                "run_id": screen_id,
                "batch_run_id": batch_run_id,
                "screen_receipt_hash": screen["receipt_hash"],
                "reported_model_cost_usd": usage["estimated_cost_usd"],
                "model_session_id": usage["session_id"],
                "model_trace_message_count": len(trace["messages"]),
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(directory / "screen.json", screen)
        write_exclusive_json(directory / "screen-run.json", run)
        return [screen], float(usage["estimated_cost_usd"]), True
    except (ContractError, ModelCallError, OSError, ValueError, KeyError, TypeError):
        usage_path = directory / "model-usage.json"
        if usage_path.is_file():
            usage, _ = load_json(usage_path)
            cost = usage.get("estimated_cost_usd") if type(usage) is dict else None
            if (
                isinstance(cost, (int, float))
                and not isinstance(cost, bool)
                and math.isfinite(cost)
                and cost >= 0
            ):
                return [], float(cost), True
        return [], None, True


def _screen_retained_candidates(
    *,
    frame: dict[str, Any],
    capture: dict[str, Any],
    atom_id: str,
    batch_run_id: str,
    hermes: Path,
    output_root: Path,
    maximum: int = 3,
) -> tuple[list[dict[str, Any]], float | None, bool]:
    """Inspect later candidates too, within the original total screening budget."""
    if type(maximum) is not int or not 1 <= maximum <= 20:
        raise ValueError("adaptive_screen_limit_invalid")
    retained = [
        row
        for row in capture["leaves"][0].get("candidate_attempts", [])
        if type(row) is dict
        and row.get("status") in {"screened_out", "extracted_candidate"}
        and type(row.get("source_id")) is str
        and type(row.get("content_sha256")) is str
    ]
    count = min(maximum, len(retained))
    screens: list[dict[str, Any]] = []
    total = 0.0
    attempted = False
    outcomes: list[dict[str, Any]] = []

    def finish(cost: float | None, stop: str):
        write_exclusive_json(
            output_root / f"{batch_run_id}-screening-summary.json",
            with_receipt_hash(
                {
                    "schema_version": 1,
                    "contract": "BetaAdaptiveCandidateScreeningSummary",
                    "run_id": batch_run_id,
                    "frame_receipt_hash": frame["receipt_hash"],
                    "capture_receipt_hash": capture["receipt_hash"],
                    "atom_id": atom_id,
                    "retained_candidate_count": len(retained),
                    "maximum_candidates": maximum,
                    "outcomes": outcomes,
                    "screen_receipt_hashes": [row["receipt_hash"] for row in screens],
                    "unvisited_source_ids": [
                        row["source_id"] for row in retained[len(outcomes) :]
                    ],
                    "reported_model_cost_usd": cost,
                    "budget_usd": 0.01,
                    "stop_reason": stop,
                    "source_calls": 0,
                    "release_authorized": False,
                }
            ),
        )
        return screens, cost, attempted

    for index in range(count):
        try:
            found, cost, called = _screen_first_retained_candidate(
                frame=frame,
                capture=capture,
                atom_id=atom_id,
                batch_run_id=batch_run_id,
                hermes=hermes,
                output_root=output_root,
                candidate_index=index,
                cost_limit=(0.01 - total) / (count - index),
            )
        except (OSError, ValueError, UnicodeError) as error:
            suffix = "" if index == 0 else f"-{index + 1:02d}"
            if (output_root / f"{batch_run_id}-domain-web-screen{suffix}").exists():
                # Failure after dispatch is not a free input rejection.
                attempted = True
                outcomes.append(
                    {
                        "source_id": retained[index]["source_id"],
                        "status": "outcome_unknown",
                        "model_attempted": True,
                        "observed_cost_usd": None,
                    }
                )
                return finish(None, "cost_unknown")
            # A damaged/unreadable source is not a reason to drop other sources.
            write_exclusive_json(
                output_root / f"{batch_run_id}-screen-input-{index + 1:02d}.json",
                {
                    "source_id": retained[index]["source_id"],
                    "status": "input_unavailable",
                    "error_type": type(error).__name__,
                    "source_excluded_globally": False,
                },
            )
            outcomes.append(
                {
                    "source_id": retained[index]["source_id"],
                    "status": "input_unavailable",
                }
            )
            continue
        screens.extend(found)
        attempted = attempted or called
        outcomes.append(
            {
                "source_id": retained[index]["source_id"],
                "status": "assessed" if found else "unresolved",
                "model_attempted": called,
                "observed_cost_usd": cost,
            }
        )
        if cost is None or not math.isfinite(cost):
            return finish(None, "cost_unknown")
        total += cost
        if total >= 0.01:
            return finish(total, "budget_reached")
    return finish(
        total,
        "candidate_limit" if count < len(retained) else "selected_candidates_processed",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--decomposition", type=Path, required=True)
    parser.add_argument("--atom-id", required=True)
    parser.add_argument("--batch", type=int, required=True)
    parser.add_argument("--parent-run-id")
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--public-query-ack", action="store_true")
    parser.add_argument("--resume-saved", action="store_true")
    parser.add_argument(
        "--max-screen-candidates", type=int, choices=range(1, 21), default=3
    )
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
        if (
            type(frame) is not dict
            or type(decomposition) is not dict
            or not all(verify_receipt_hash(row) for row in (frame, decomposition))
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{frame['run_id']}-coverage-planning/frame.json"
            or args.decomposition
            != args.output_root
            / f"{decomposition['run_id']}-domain-planning/decomposition.json"
            or not 1 <= args.batch <= 99
        ):
            raise ValueError("adaptive_coverage_paths_invalid")
        parent_plan = None
        if args.parent_run_id is not None:
            plan_value, _ = load_json(
                args.output_root / f"{args.parent_run_id}-planning/plan.json"
            )
            parent_plan = verify_beta_mode_plan(plan_value)
            if (
                parent_plan["run_id"] != args.parent_run_id
                or parent_plan["mode"] != "ultra"
                or parent_plan["question"] != frame["question"]
            ):
                raise ValueError("adaptive_parent_plan_invalid")
        prefix = args.parent_run_id or frame["run_id"]
        suffix = "C" if args.parent_run_id else "D"
        previous = None
        if args.batch > 1:
            previous, _ = load_json(
                args.output_root
                / f"{prefix}-{suffix}{args.batch - 1:02d}-domain-web-observed/observations.json"
            )
        prompt = build_domain_web_prompt(
            frame, decomposition, None, atom_id=args.atom_id
        )
        batch_run_id = f"{prefix}-{suffix}{args.batch:02d}"
        output = args.output_root / f"{batch_run_id}-domain-web-plan"
        assert output is not None
        feedback = None
        if args.batch > 1 and not args.resume_saved:
            history = []
            for number in range(1, args.batch):
                prior_id = f"{prefix}-{suffix}{number:02d}"
                prior_plan, _ = load_json(
                    args.output_root / f"{prior_id}-domain-web-plan/plan.json"
                )
                prior_batch, _ = load_json(
                    args.output_root / f"{prior_id}-domain-web-plan/batch.json"
                )
                prior_observed, _ = load_json(
                    args.output_root / f"{prior_id}-domain-web-observed/run.json"
                )
                history.append(
                    {
                        "plan": prior_plan,
                        "batch": prior_batch,
                        "observed": prior_observed,
                    }
                )
            feedback = build_domain_search_feedback(frame, args.atom_id, history)
            prompt = append_domain_search_feedback(prompt, feedback)
        if args.resume_saved:
            if (
                not output.is_dir()
                or output.is_symlink()
                or stat.S_IMODE(output.stat().st_mode) & 0o077
                or (output / "plan.json").exists()
            ):
                raise ValueError("adaptive_recovery_target_invalid")
            attempt, _ = load_json(output / "attempt.json")
            failure, _ = load_json(output / "failure.json")
            usage, _ = load_json(output / "model-usage.json")
            trace, _ = load_json(output / "model-trace.json")
            raw = (
                read_private_bytes(output / "model.raw.json", maximum=1_048_576)
                .decode("utf-8")
                .rstrip("\n")
            )
            if any(type(row) is not dict for row in (attempt, failure, usage, trace)):
                raise ValueError("adaptive_recovery_record_invalid")
            attempt = cast(dict[str, Any], attempt)
            if attempt.get("search_feedback_receipt_hash") is not None:
                feedback = attempt.get("search_feedback")
                if (
                    type(feedback) is not dict
                    or not verify_receipt_hash(feedback)
                    or feedback.get("receipt_hash")
                    != attempt["search_feedback_receipt_hash"]
                    or feedback.get("frame_receipt_hash") != frame["receipt_hash"]
                    or feedback.get("atom_id") != args.atom_id
                ):
                    raise ValueError("adaptive_feedback_recovery_unbound")
                prompt = append_domain_search_feedback(prompt, feedback)
            failure = cast(dict[str, Any], failure)
            usage = cast(dict[str, Any], usage)
            trace = cast(dict[str, Any], trace)
            if (
                attempt.get("purpose") != "adaptive_domain_coverage_query"
                or attempt.get("frame_receipt_hash") != frame["receipt_hash"]
                or attempt.get("decomposition_receipt_hash")
                != decomposition["receipt_hash"]
                or attempt.get("atom_id") != args.atom_id
                or attempt.get("batch_number") != args.batch
                or attempt.get("parent_plan_receipt_hash")
                != (parent_plan["receipt_hash"] if parent_plan else None)
                or attempt.get("prompt_sha256")
                != hashlib.sha256(prompt.encode()).hexdigest()
                or attempt.get("provider") != PROVIDER
                or attempt.get("model") != MODEL
                or attempt.get("retry_allowed") is not False
                or failure.get("reconciliation_required") is not True
                or failure.get("retry_allowed") is not False
                or type(trace.get("messages")) is not list
                or len(trace["messages"]) != 2
                or trace["messages"][0].get("content") != prompt
                or trace["messages"][1].get("content", "").strip() != raw
            ):
                raise ValueError("adaptive_recovery_lineage_invalid")
            validate_tool_free_observation(
                max_estimated_cost_usd=0.01,
                usage=usage,
                trace=trace,
                provider=PROVIDER,
                model=MODEL,
                max_total_tokens=attempt["max_total_tokens"],
            )
        else:
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
                    "purpose": "adaptive_domain_coverage_query",
                    "frame_receipt_hash": frame["receipt_hash"],
                    "decomposition_receipt_hash": decomposition["receipt_hash"],
                    "atom_id": args.atom_id,
                    "batch_number": args.batch,
                    "search_feedback_receipt_hash": feedback["receipt_hash"]
                    if feedback
                    else None,
                    "search_feedback": feedback,
                    "parent_plan_receipt_hash": parent_plan["receipt_hash"]
                    if parent_plan
                    else None,
                },
            )
        model_completed = True
        if feedback is not None and not args.resume_saved:
            write_exclusive_json(output / "search-feedback.json", feedback)
        plan, batch = parse_domain_web_query(
            raw,
            frame=frame,
            decomposition=decomposition,
            review=None,
            atom_id=args.atom_id,
            batch_number=args.batch,
            batch_run_id=batch_run_id,
        )
        run = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaDomainWebPlanningRun",
                "run_id": batch_run_id,
                "batch_receipt_hash": batch["receipt_hash"],
                "plan_receipt_hash": plan["receipt_hash"],
                "model_session_id": usage["session_id"],
                "reported_model_cost_usd": usage["estimated_cost_usd"],
                "model_trace_message_count": len(trace["messages"]),
                "reconciled_without_new_model_call": args.resume_saved,
                "additional_model_calls": 0 if args.resume_saved else 1,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "plan.json", plan)
        write_exclusive_json(output / "batch.json", batch)
        write_exclusive_json(output / "run.json", run)
        child = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "execute_beta_sources.py"),
                "--read-all-candidates",
                "--plan",
                str(output / "plan.json"),
                "--output-root",
                str(args.output_root),
                "--public-query-ack",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=plan["limits"]["wall_seconds"] + 10,
        )
        if child.returncode not in (0, 3):
            raise ValueError("adaptive_source_execution_incomplete")
        execution, _ = load_json(
            args.output_root / f"{batch_run_id}-execution/execution.json"
        )
        portfolio, _ = load_json(
            args.output_root / f"{batch_run_id}-execution/portfolio.json"
        )
        capture, _ = load_json(args.output_root / f"{batch_run_id}/capture.json")
        if any(type(row) is not dict for row in (execution, portfolio, capture)):
            raise ValueError("adaptive_source_receipts_invalid")
        execution = cast(dict[str, Any], execution)
        portfolio = cast(dict[str, Any], portfolio)
        capture = cast(dict[str, Any], capture)
        screens, screening_cost, screening_attempted = _screen_retained_candidates(
            frame=frame,
            capture=capture,
            atom_id=args.atom_id,
            batch_run_id=batch_run_id,
            hermes=args.hermes,
            output_root=args.output_root,
            maximum=args.max_screen_candidates,
        )
        screening_summary, _ = load_json(
            args.output_root / f"{batch_run_id}-screening-summary.json"
        )
        if type(screening_summary) is not dict or not verify_receipt_hash(
            screening_summary
        ):
            raise ValueError("adaptive_screening_summary_invalid")
        screening_model_calls = sum(
            row.get("model_attempted") is True for row in screening_summary["outcomes"]
        )
        observations, progress, observed = observe_domain_web_batch(
            frame=frame,
            review=None,
            plan=plan,
            batch=batch,
            execution=execution,
            portfolio=portfolio,
            capture=capture,
            previous_observations=previous,
            screens=screens,
        )
        evidence_candidates = []
        for screen in screens:
            relation = screen["relation_effective"]
            if relation not in {"direct", "context_only"}:
                continue
            evidence_candidates.append(
                {
                    "claim_id": screen["receipt_hash"],
                    "atom_id": args.atom_id,
                    "source_ref": next(
                        (
                            row.get("url")
                            or row.get("requested_url")
                            or screen["source_id"]
                            for row in capture["leaves"][0]["candidate_attempts"]
                            if type(row) is dict
                            and row.get("source_id") == screen["source_id"]
                        ),
                        screen["source_id"],
                    ),
                    "root_type": "unknown",
                    "root_id": screen["source_id"],
                    "role": "unknown",
                    "relation": "supports" if relation == "direct" else "context",
                    "read_scope": "partial_text",
                    "provenance_receipt_hash": capture["receipt_hash"],
                    "provenance_verified": False,
                    "independence_cluster": screen["source_id"],
                    "independence_verified": False,
                }
            )
        observed_dir = args.output_root / f"{batch_run_id}-domain-web-observed"
        new_private_directory(observed_dir)
        write_exclusive_json(observed_dir / "observations.json", observations)
        write_exclusive_json(observed_dir / "coverage.json", progress)
        write_exclusive_json(observed_dir / "batch-observation.json", observed)
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaAdaptiveCoverageBatchRun",
                "run_id": batch_run_id,
                "atom_id": args.atom_id,
                "frame_receipt_hash": frame["receipt_hash"],
                "parent_run_id": args.parent_run_id,
                "parent_plan_receipt_hash": parent_plan["receipt_hash"]
                if parent_plan
                else None,
                "batch_plan_receipt_hash": batch["receipt_hash"],
                "execution_receipt_hash": execution["receipt_hash"],
                "observation_receipt_hash": observed["receipt_hash"],
                "reported_model_cost_usd": round(
                    float(usage["estimated_cost_usd"]) + float(screening_cost or 0),
                    8,
                )
                if screening_cost is not None
                else None,
                "planning_model_cost_usd": usage["estimated_cost_usd"],
                "screening_attempted": screening_attempted,
                "screening_summary_receipt_hash": screening_summary["receipt_hash"],
                "screening_model_calls": screening_model_calls,
                "screening_model_cost_usd": screening_cost,
                "screen_receipt_hashes": [screen["receipt_hash"] for screen in screens],
                "source_assessments": screens,
                "evidence_candidates": evidence_candidates,
                "reconciled_without_new_model_call": args.resume_saved,
                "additional_model_calls": (0 if args.resume_saved else 1)
                + screening_model_calls,
                "reported_source_cost_usd": execution.get("reported_total_cost_usd"),
                "provisionally_direct_source_count": sum(
                    screen["relation_effective"] == "direct" for screen in screens
                ),
                "verified_source_count": 0,
                "saturation_verified": False,
                "release_authorized": False,
            }
        )
        write_exclusive_json(observed_dir / "run.json", receipt)
        print(
            json.dumps(
                {
                    "status": "adaptive_coverage_partial",
                    "run_id": batch_run_id,
                    "atom_id": args.atom_id,
                    "candidate_count": observed["candidate_count"],
                    "verified_source_count": 0,
                    "reported_model_cost_usd": round(
                        float(usage["estimated_cost_usd"]) + float(screening_cost or 0),
                        8,
                    )
                    if screening_cost is not None
                    else None,
                    "screening_attempted": screening_attempted,
                    "screened_candidate_count": len(screens),
                    "additional_model_calls": (0 if args.resume_saved else 1)
                    + screening_model_calls,
                    "reported_source_cost_usd": execution.get(
                        "reported_total_cost_usd"
                    ),
                    "saturation_verified": False,
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
        subprocess.TimeoutExpired,
    ) as error:
        code = (
            error.code
            if isinstance(error, (ContractError, ModelCallError))
            else str(error)
        )
        if (
            model_completed
            and output is not None
            and not (output / "plan.json").exists()
        ):
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
