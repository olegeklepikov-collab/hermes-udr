"""Restore a missing revision receipt from one already paid route-selection run."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path
from typing import Any, cast

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, read_private_bytes, write_exclusive_json
    from .model_call import MODEL, PROVIDER
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from model_call import MODEL, PROVIDER

from hermes_research_report.beta_coverage_repair import (
    build_route_repair_prompt,
    parse_route_repair,
)
from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = args.output
        if (
            not output.is_absolute()
            or output.is_symlink()
            or not output.is_dir()
            or stat.S_IMODE(output.stat().st_mode) & 0o077
            or (output / "revision.json").exists()
        ):
            raise ValueError("coverage_route_reconciliation_not_allowed")
        prepared, _ = load_json(output / "prepared.json")
        saved_frame, _ = load_json(output / "frame.json")
        saved_proposal, _ = load_json(output / "proposal.json")
        saved_route, _ = load_json(output / "route.json")
        saved_run, _ = load_json(output / "route-run.json")
        attempt, _ = load_json(output / "attempt.json")
        usage, _ = load_json(output / "model-usage.json")
        trace, _ = load_json(output / "model-trace.json")
        if any(
            type(item) is not dict
            for item in (
                prepared,
                saved_frame,
                saved_proposal,
                saved_route,
                saved_run,
                attempt,
                usage,
                trace,
            )
        ):
            raise ValueError("coverage_route_saved_record_invalid")
        prepared = cast(dict[str, Any], prepared)
        saved_frame = cast(dict[str, Any], saved_frame)
        saved_proposal = cast(dict[str, Any], saved_proposal)
        saved_route = cast(dict[str, Any], saved_route)
        saved_run = cast(dict[str, Any], saved_run)
        attempt = cast(dict[str, Any], attempt)
        usage = cast(dict[str, Any], usage)
        trace = cast(dict[str, Any], trace)
        run_id = prepared.get("run_id")
        if type(run_id) is not str or output.name != f"{run_id}-coverage-route-repair":
            raise ValueError("coverage_route_saved_attempt_not_bound")
        parent_frame, _ = load_json(
            output.parent / f"{run_id}-coverage-planning/frame.json"
        )
        review, _ = load_json(output.parent / f"{run_id}-coverage-review/review.json")
        if type(parent_frame) is not dict or type(review) is not dict:
            raise ValueError("coverage_route_lineage_invalid")
        raw = (
            read_private_bytes(output / "model.raw.json", maximum=1_048_576)
            .decode("utf-8")
            .rstrip("\n")
        )
        prompt = build_route_repair_prompt(prepared)
        messages = trace.get("messages")
        if (
            attempt.get("purpose") != "coverage_instrument_strategy_repair"
            or attempt.get("prepared_receipt_hash") != prepared["receipt_hash"]
            or attempt.get("prompt_sha256")
            != hashlib.sha256(prompt.encode()).hexdigest()
            or attempt.get("provider") != PROVIDER
            or attempt.get("model") != MODEL
            or attempt.get("retry_allowed") is not False
            or saved_run.get("prepared_receipt_hash") != prepared["receipt_hash"]
            or saved_run.get("route_receipt_hash") != saved_route["receipt_hash"]
            or saved_run.get("revised_frame_receipt_hash")
            != saved_frame["receipt_hash"]
            or type(messages) is not list
            or len(messages) != 2
            or messages[0].get("content") != prompt
            or messages[1].get("content", "").strip() != raw
            or not all(
                verify_receipt_hash(item)
                for item in (
                    prepared,
                    saved_frame,
                    saved_proposal,
                    saved_route,
                    saved_run,
                )
            )
        ):
            raise ValueError("coverage_route_saved_attempt_not_bound")
        validate_tool_free_observation(
            max_estimated_cost_usd=0.01,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
            max_total_tokens=attempt["max_total_tokens"],
        )
        frame, proposal, revision, route = parse_route_repair(
            raw, prepared=prepared, frame=parent_frame, review=review
        )
        if (
            frame["receipt_hash"] != saved_frame["receipt_hash"]
            or proposal["receipt_hash"] != saved_proposal["receipt_hash"]
            or route["receipt_hash"] != saved_route["receipt_hash"]
            or route["revision_receipt_hash"] != revision["receipt_hash"]
        ):
            raise ValueError("coverage_route_replay_mismatch")
        write_exclusive_json(output / "revision.json", revision)
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaCoverageRouteReconciliation",
                "run_id": run_id,
                "revision_receipt_hash": revision["receipt_hash"],
                "additional_model_calls": 0,
                "source_calls": 0,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "reconciliation.json", receipt)
        print(
            json.dumps(
                {"status": "reconciled", "additional_model_calls": 0, "run_id": run_id}
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
