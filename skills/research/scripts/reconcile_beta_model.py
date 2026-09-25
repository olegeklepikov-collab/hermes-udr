"""Reparse one saved model attempt without another provider call."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .draft_beta_model import MODEL, PROVIDER, _preflight, finalize_beta_model, select_draft_source
    from .file_io import (
        fsync_directory,
        load_json,
        read_private_bytes,
        write_exclusive_json,
    )
except ImportError:
    from draft_beta_model import MODEL, PROVIDER, _preflight, finalize_beta_model, select_draft_source
    from file_io import (
        fsync_directory,
        load_json,
        read_private_bytes,
        write_exclusive_json,
    )

from hermes_research_report.errors import ContractError
from hermes_research_report.report import ReportInputError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--web-capture", type=Path, required=True)
    parser.add_argument("--attempt-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan, portfolio, capture, source_id, title, text, prompt = _preflight(
            args.plan, args.portfolio, args.web_capture
        )
        output = args.attempt_dir
        if (
            not output.is_absolute()
            or output.is_symlink()
            or not output.is_dir()
            or output.name != f"{plan['run_id']}-model"
            or (output / "model-candidate.json").exists()
            or (output / "model-report.json").exists()
        ):
            raise ValueError("model_reconciliation_target_invalid")
        attempt_value, attempt_sha = load_json(output / "attempt.json")
        if type(attempt_value) is not dict:
            raise ValueError("model_attempt_invalid")
        attempt = attempt_value
        _row, selection = select_draft_source(plan, portfolio, capture)
        historical_prompt = prompt.replace("5–40 слов", "5–20 слов")
        prompt_used = (
            historical_prompt
            if attempt.get("prompt_sha256")
            == hashlib.sha256(historical_prompt.encode("utf-8")).hexdigest()
            else prompt
        )
        if (
            attempt.get("status") != "started_unknown_until_reconciled"
            or attempt.get("run_id") != plan["run_id"]
            or attempt.get("plan_receipt_hash") != plan["receipt_hash"]
            or attempt.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
            or attempt.get("source_receipt_hash") != capture["receipt_hash"]
            or attempt.get("source_id") != source_id
            or attempt.get("selected_leaf_id") not in (None, selection["selected_leaf_id"])
            or attempt.get("source_selection_receipt_hash") not in (None, selection["receipt_hash"])
            or (len(capture["leaves"]) > 1 and attempt.get("source_selection_receipt_hash") != selection["receipt_hash"])
            or attempt.get("prompt_sha256")
            != hashlib.sha256(prompt_used.encode("utf-8")).hexdigest()
            or attempt.get("provider") != PROVIDER
            or attempt.get("model") != MODEL
            or attempt.get("retry_allowed") is not False
        ):
            raise ValueError("model_attempt_not_bound")
        raw_bytes = read_private_bytes(output / "model.raw.json", maximum=25_000)
        if not raw_bytes.endswith(b"\n") or raw_bytes.endswith(b"\n\n"):
            raise ValueError("model_raw_normalization_invalid")
        raw = raw_bytes[:-1].decode("utf-8")
        usage_value, usage_sha = load_json(output / "model-usage.json")
        trace_value, trace_sha = load_json(output / "model-trace.json")
        if type(usage_value) is not dict or type(trace_value) is not dict:
            raise ValueError("model_observation_invalid")
        failure_sha = None
        failure_file = output / "failure.json"
        if failure_file.exists():
            failure_value, failure_sha = load_json(failure_file)
            if (
                type(failure_value) is not dict
                or failure_value.get("status") != "failed_or_unknown"
                or failure_value.get("retry_allowed") is not False
            ):
                raise ValueError("model_failure_record_invalid")
        candidate = finalize_beta_model(
            plan=plan,
            portfolio=portfolio,
            capture=capture,
            source_id=source_id,
            title=title,
            text=text,
            prompt=prompt_used,
            raw=raw,
            usage=usage_value,
            trace=trace_value,
            output=output,
        )
        write_exclusive_json(
            output / "reconciliation.json",
            {
                "schema_version": 1,
                "status": "saved_attempt_reparsed",
                "run_id": plan["run_id"],
                "attempt_file_sha256": attempt_sha,
                "model_raw_file_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "usage_file_sha256": usage_sha,
                "trace_file_sha256": trace_sha,
                "prior_failure_file_sha256": failure_sha,
                "candidate_receipt_hash": candidate["receipt_hash"],
                "historical_quote_limit_20_to_40_regraded": prompt_used
                == historical_prompt
                and historical_prompt != prompt,
                "additional_model_calls": 0,
                "release_authorized": False,
            },
        )
        fsync_directory(output)
        print(
            json.dumps(
                {
                    "status": candidate["status"],
                    "run_id": candidate["run_id"],
                    "source_relation": candidate["source_relation"],
                    "uncertainty_origin": candidate["uncertainty_origin"],
                    "additional_model_calls": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, ReportInputError, OSError, ValueError) as error:
        code = (
            error.code
            if isinstance(error, (ContractError, ReportInputError))
            else str(error)
            if isinstance(error, ValueError)
            and str(error).replace("_", "").isalnum()
            and len(str(error)) < 80
            else "model_reconciliation_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
