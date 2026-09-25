"""Run one bounded tool-free Hermes model draft from exact saved source text."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import (
        fsync_directory,
        load_json,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from .model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model
except ImportError:
    from file_io import (
        fsync_directory,
        load_json,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model

from hermes_research_report.beta_model import (
    build_beta_model_prompt,
    validate_beta_model_candidate,
)
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.report import ReportInputError, build_report


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def select_draft_source(plan: dict, portfolio: dict, capture: dict) -> tuple[dict, dict]:
    """Choose one receipted text candidate; retain every unreviewed plan leaf."""
    if not all(verify_receipt_hash(value) for value in (plan, portfolio, capture)):
        raise ValueError("source_selection_invalid")
    rows, selected = capture.get("leaves"), portfolio.get("leaves")
    if type(rows) is not list or type(selected) is not list:
        raise ValueError("source_selection_invalid")
    planned = [leaf["leaf_id"] for leaf in plan["leaves"]]
    if len(rows) > 1 and plan["mode"] != "search":
        raise ValueError("unprofiled_multi_source_capture")
    by_leaf = {}
    for row in rows:
        if (
            type(row) is not dict
            or type(row.get("leaf_id")) is not str
            or row["leaf_id"] not in planned
            or row["leaf_id"] in by_leaf
        ):
            raise ValueError("source_selection_invalid")
        by_leaf[row["leaf_id"]] = row
    portfolio_by_leaf = {}
    for item in selected:
        if (
            type(item) is not dict
            or type(item.get("leaf_id")) is not str
            or item["leaf_id"] not in planned
            or item["leaf_id"] in portfolio_by_leaf
        ):
            raise ValueError("source_selection_invalid")
        portfolio_by_leaf[item["leaf_id"]] = item
    eligible = []
    for leaf_id in planned:
        row, item = by_leaf.get(leaf_id), portfolio_by_leaf.get(leaf_id)
        if row is None or item is None:
            continue
        if row.get("status") == "extracted_candidate":
            if not (
                row.get("read_scope") == "extracted_text_only"
                and item.get("status") == "candidate"
                and item.get("read_scope") == "extracted_text_only"
                and item.get("receipt_hash") == capture["receipt_hash"]
                and type(row.get("source_id")) is str
                and row.get("content_file") == f"{row['source_id']}.txt"
            ):
                raise ValueError("source_not_reviewable")
            eligible.append(leaf_id)
        elif item.get("status") == "candidate" and item.get("receipt_hash") == capture["receipt_hash"]:
            raise ValueError("source_selection_invalid")
    if (
        capture.get("successful_sources") != len(eligible)
        or not eligible
        or len({by_leaf[leaf_id]["source_id"] for leaf_id in eligible}) != len(eligible)
    ):
        raise ValueError("source_selection_invalid")
    if plan["mode"] == "search":
        if (
            set(by_leaf) != set(planned)
            or set(portfolio_by_leaf) != set(planned)
            or portfolio.get("candidate_leaf_ids") != eligible
            or portfolio.get("missing_or_failed_leaf_ids") != sorted(set(planned) - set(eligible))
            or capture.get("selected_leaf_id") is not None
        ):
            raise ValueError("source_selection_invalid")
    elif capture.get("selected_leaf_id") != eligible[0]:
        raise ValueError("source_selection_invalid")
    chosen = by_leaf[eligible[0]]
    receipt = with_receipt_hash({
        "schema_version": 1,
        "contract": "BetaDraftSourceSelection",
        "run_id": plan["run_id"],
        "plan_receipt_hash": plan["receipt_hash"],
        "portfolio_receipt_hash": portfolio["receipt_hash"],
        "capture_receipt_hash": capture["receipt_hash"],
        "selection_rule": "first_eligible_in_plan_order",
        "selected_leaf_id": eligible[0],
        "selected_source_id": chosen["source_id"],
        "eligible_leaf_ids": eligible,
        "unreviewed_candidate_leaf_ids": eligible[1:],
        "missing_or_failed_leaf_ids": sorted(set(planned) - set(eligible)),
        "read_scope": "one_extracted_candidate_only",
        "full_plan_coverage_verified": False,
        "release_authorized": False,
    })
    return chosen, receipt


def _preflight(
    plan_file: Path, portfolio_file: Path, capture_file: Path
) -> tuple[dict, dict, dict, str, str, str, str]:
    plan_value, _ = load_json(plan_file)
    plan = verify_beta_mode_plan(plan_value)
    if plan["schema_version"] != 2:
        raise ValueError("legacy_plan_execution_disabled")
    if any("concept_groups" not in leaf for leaf in plan["leaves"]):
        raise ValueError("concept_groups_required")
    portfolio_value, _ = load_json(portfolio_file)
    capture_value, _ = load_json(capture_file)
    if type(portfolio_value) is not dict or type(capture_value) is not dict:
        raise ValueError("source_receipt_invalid")
    portfolio, capture = portfolio_value, capture_value
    if (
        not verify_receipt_hash(portfolio)
        or not verify_receipt_hash(capture)
        or portfolio.get("contract") != "BetaSourcePortfolio"
        or portfolio.get("plan_receipt_hash") != plan["receipt_hash"]
        or portfolio.get("run_id") != plan["run_id"]
        or portfolio.get("mode") != plan["mode"]
        or portfolio.get("status") != "partial_analysis_required"
        or portfolio.get("mode_qualified") is not False
        or portfolio.get("release_authorized") is not False
        or capture.get("contract") != "BetaSourceAcquisition"
        or capture.get("plan_receipt_hash") != plan["receipt_hash"]
        or capture.get("run_id") != plan["run_id"]
        or capture.get("mode") != plan["mode"]
        or capture.get("release_authorized") is not False
    ):
        raise ValueError("source_receipts_not_bound")
    row, _selection = select_draft_source(plan, portfolio, capture)
    leaf_id, source_id, content_file = (
        row.get("leaf_id"),
        row.get("source_id"),
        row.get("content_file"),
    )
    if (
        type(leaf_id) is not str
        or type(source_id) is not str
        or content_file != f"{source_id}.txt"
        or row.get("status") != "extracted_candidate"
        or row.get("read_scope") != "extracted_text_only"
    ):
        raise ValueError("source_not_reviewable")
    payload = read_private_bytes(capture_file.parent / str(content_file))
    if _sha(payload) != row.get("content_sha256"):
        raise ValueError("source_content_hash_mismatch")
    text = payload.decode("utf-8")
    title = row.get("title")
    url = row.get("url")
    if type(title) is not str or type(url) is not str:
        raise ValueError("source_metadata_invalid")
    prompt = build_beta_model_prompt(plan, source_id=source_id, title=title, text=text)
    return plan, portfolio, capture, source_id, title, text, prompt


def finalize_beta_model(
    *,
    plan: dict,
    portfolio: dict,
    capture: dict,
    source_id: str,
    title: str,
    text: str,
    prompt: str,
    raw: str,
    usage: dict,
    trace: object,
    output: Path,
) -> dict:
    candidate = validate_beta_model_candidate(
        raw,
        plan=plan,
        source_id=source_id,
        title=title,
        source_text=text,
        prompt=prompt,
        usage=usage,
        trace=trace,
        provider=PROVIDER,
        model=MODEL,
    )
    if (
        portfolio["reported_provider_cost_usd"] + candidate["estimated_cost_usd"]
        > plan["limits"]["max_estimated_cost_usd"]
    ):
        raise ValueError("cumulative_cost_limit_exceeded")
    source_row, selection = select_draft_source(plan, portfolio, capture)
    if source_row["source_id"] != source_id:
        raise ValueError("source_selection_invalid")
    direct = candidate["status"] == "verification_required"
    claims = (
        [
            {
                "id": "CLM-" + _sha(candidate["claim"].encode())[:16].upper(),
                "text": candidate["claim"],
                "kind": "observation",
                "evidence": [{"source_id": source_id, "quote": candidate["quote"]}],
                "limitations": [candidate["uncertainty"]],
            }
        ]
        if direct
        else []
    )
    report = build_report(
        {
            "question": plan["question"],
            "sources": [
                {
                    "id": source_id,
                    "url": source_row["url"],
                    "title": title,
                    "text": text,
                    "accessed_at": capture["observed_at"],
                }
            ],
            "claims": claims,
            "limitations": [
                "Источник не поддерживает прямой ответ."
                if not direct
                else "Тезис требует следующей автоматической смысловой проверки.",
                candidate["uncertainty"],
                "Извлечённый текст не удостоверяет исходные сетевые байты страницы.",
                "Черновик рассматривает только один выбранный источник; непроверенные листья: "
                + ", ".join(
                    selection["unreviewed_candidate_leaf_ids"]
                    + selection["missing_or_failed_leaf_ids"]
                )
                if selection["unreviewed_candidate_leaf_ids"] or selection["missing_or_failed_leaf_ids"]
                else "Черновик рассматривает только один выбранный источник; полный охват плана не установлен.",
            ]
            + (
                [
                    (
                        "Модель прочитала только фрагмент "
                        f"{candidate['model_view_char_start']}:{candidate['model_view_char_end']} "
                        f"из {candidate['source_chars_total']} знаков; остальной текст не оценён."
                    )
                ]
                if candidate.get("model_source_scope") == "excerpt_only"
                else []
            ),
            "stop_reason": "checkpoint" if direct else "insufficient_evidence",
            "profile": {
                "domain": "academic" if plan["mode"] == "academic" else "general",
                "depth": plan["mode"] if plan["mode"] != "academic" else "deep",
                "risk": "medium",
            },
            "response_format": "structured",
        }
    )
    if (
        report.get("status") != "partial"
        or report.get("release_authorized") is not False
        or report.get("semantic_support_unverified") is not True
    ):
        raise ValueError("model_report_not_partial")
    report_bytes = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
    write_exclusive_bytes(output / "model-report.json", report_bytes)
    write_exclusive_json(output / "source-selection.json", selection)
    body = dict(candidate)
    body.pop("receipt_hash")
    body["report_sha256"] = _sha(report_bytes)
    body["portfolio_receipt_hash"] = portfolio["receipt_hash"]
    body["source_selection_receipt_hash"] = selection["receipt_hash"]
    body["selected_leaf_id"] = selection["selected_leaf_id"]
    body["unreviewed_candidate_leaf_ids"] = selection["unreviewed_candidate_leaf_ids"]
    body["missing_or_failed_leaf_ids"] = selection["missing_or_failed_leaf_ids"]
    body["full_plan_coverage_verified"] = False
    candidate = with_receipt_hash(body)
    write_exclusive_json(output / "model-candidate.json", candidate)
    fsync_directory(output)
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--web-capture", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output_created = False
    try:
        plan, portfolio, capture, source_id, title, text, prompt = _preflight(
            args.plan, args.portfolio, args.web_capture
        )
        if args.output.name != f"{plan['run_id']}-model":
            raise ValueError("output_run_id_mismatch")
        _row, selection = select_draft_source(plan, portfolio, capture)
        raw, usage, trace = run_tool_free_model(
            plan=plan,
            prompt=prompt,
            hermes=args.hermes,
            output=args.output,
            attempt_binding={
                "portfolio_receipt_hash": portfolio["receipt_hash"],
                "source_receipt_hash": capture["receipt_hash"],
                "source_id": source_id,
                "selected_leaf_id": selection["selected_leaf_id"],
                "source_selection_receipt_hash": selection["receipt_hash"],
            },
        )
        output_created = True
        candidate = finalize_beta_model(
            plan=plan,
            portfolio=portfolio,
            capture=capture,
            source_id=source_id,
            title=title,
            text=text,
            prompt=prompt,
            raw=raw,
            usage=usage,
            trace=trace,
            output=args.output,
        )
        print(
            json.dumps(
                {
                    "status": candidate["status"],
                    "run_id": candidate["run_id"],
                    "mode": candidate["mode"],
                    "exact_quote_verified": candidate["exact_quote_verified"],
                    "source_relation": candidate["source_relation"],
                    "semantic_support_verified": False,
                    "mode_qualified": False,
                    "release_authorized": False,
                    "total_tokens": candidate["total_tokens"],
                    "estimated_cost_usd": candidate["estimated_cost_usd"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        ContractError,
        ImportError,
        ModelCallError,
        ReportInputError,
        OSError,
        ValueError,
    ) as error:
        code = (
            error.code
            if isinstance(error, (ContractError, ModelCallError, ReportInputError))
            else str(error)
            if isinstance(error, ValueError)
            and str(error).replace("_", "").isalnum()
            and len(str(error)) < 80
            else "model_input_or_storage_failed"
        )
        if output_created:
            try:
                write_exclusive_json(
                    args.output / "failure.json",
                    {
                        "schema_version": 1,
                        "status": "failed_or_unknown",
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
