"""Assemble one local provisional Search result from bound saved evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .draft_beta_model import _preflight, select_draft_source
    from .file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
except ImportError:
    from draft_beta_model import _preflight, select_draft_source
    from file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )

from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.report import ReportInputError, _md, build_report


def assemble_search_result(
    *,
    plan: dict,
    portfolio: dict,
    capture: dict,
    candidate: dict,
    semantic_check: dict | None,
    source_text: str,
) -> dict:
    if plan["mode"] != "search":
        raise ValueError("search_only_result")
    row, selection = select_draft_source(plan, portfolio, capture)
    if (
        candidate.get("source_id") != row["source_id"]
        or (
            candidate.get("source_selection_receipt_hash") != selection["receipt_hash"]
            if len(capture["leaves"]) > 1
            else candidate.get("source_selection_receipt_hash")
            not in (None, selection["receipt_hash"])
        )
    ):
        raise ValueError("search_source_selection_not_bound")
    scope_parts = ["Один источник выбран для черновика."]
    if selection["unreviewed_candidate_leaf_ids"]:
        scope_parts.append(
            "Другие пригодные листья не проверены: "
            + ", ".join(selection["unreviewed_candidate_leaf_ids"])
            + "."
        )
    if selection["missing_or_failed_leaf_ids"]:
        scope_parts.append(
            "Непокрытые или отклонённые листья: "
            + ", ".join(selection["missing_or_failed_leaf_ids"])
            + "."
        )
    scope_parts.append("Полный охват плана не установлен.")
    scope_limit = " ".join(scope_parts)
    model_scope_limit = (
        f"Модель прочитала только фрагмент "
        f"{candidate['model_view_char_start']}:{candidate['model_view_char_end']} "
        f"из {candidate['source_chars_total']} знаков сохранённого источника; "
        "остальной текст не оценён."
        if candidate.get("model_source_scope") == "excerpt_only"
        else None
    )
    if candidate.get("status") == "source_insufficient":
        if (
            semantic_check is not None
            or not verify_receipt_hash(candidate)
            or candidate.get("plan_receipt_hash") != plan["receipt_hash"]
            or candidate.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
            or candidate.get("source_id") != row.get("source_id")
            or candidate.get("source_text_sha256")
            != hashlib.sha256(source_text.encode()).hexdigest()
            or candidate.get("source_relation") not in {"context_only", "irrelevant"}
            or candidate.get("claim") != ""
            or candidate.get("quote") != ""
            or candidate.get("release_authorized") is not False
        ):
            raise ValueError("search_negative_result_not_bound")
        total_cost = (
            portfolio["reported_provider_cost_usd"] + candidate["estimated_cost_usd"]
        )
        if total_cost > plan["limits"]["max_estimated_cost_usd"]:
            raise ValueError("search_result_cost_not_bound")
        report = build_report(
            {
                "question": plan["question"],
                "sources": [
                    {
                        "id": row["source_id"],
                        "url": row["url"],
                        "title": row["title"],
                        "text": source_text,
                        "accessed_at": capture["observed_at"],
                    }
                ],
                "claims": [],
                "limitations": [
                    candidate["uncertainty"],
                    "Источник не даёт прямого ответа; содержательный тезис не выдан.",
                    scope_limit,
                ]
                + ([model_scope_limit] if model_scope_limit else []),
                "stop_reason": "insufficient_evidence",
                "profile": {"domain": "general", "depth": "search", "risk": "low"},
                "response_format": "full",
            }
        )
        if (
            report.get("status") != "partial"
            or report.get("release_authorized") is not False
        ):
            raise ValueError("search_report_not_provisional")
        return with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaLocalSearchResult",
                "status": "insufficient_evidence",
                "run_id": plan["run_id"],
                "plan_receipt_hash": plan["receipt_hash"],
                "portfolio_receipt_hash": portfolio["receipt_hash"],
                "candidate_receipt_hash": candidate["receipt_hash"],
                "source_selection_receipt_hash": selection["receipt_hash"],
                "semantic_check_receipt_hash": None,
                "source_text_sha256": candidate["source_text_sha256"],
                "markdown_sha256": hashlib.sha256(
                    report["markdown"].encode()
                ).hexdigest(),
                "claim_count": 0,
                "reported_total_cost_usd": total_cost,
                "report": report,
                "final_acceptance_external": True,
                "independent_primary_support_verified": False,
                "mode_qualified": False,
                "release_authorized": False,
                "external_delivery_authorized": False,
            }
        )
    if semantic_check is None:
        raise ValueError("search_semantic_check_required")
    if (
        not verify_receipt_hash(candidate)
        or not verify_receipt_hash(semantic_check)
        or candidate.get("status") != "verification_required"
        or candidate.get("plan_receipt_hash") != plan["receipt_hash"]
        or candidate.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
        or candidate.get("source_text_sha256")
        != hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        or candidate.get("release_authorized") is not False
        or semantic_check.get("candidate_receipt_hash") != candidate["receipt_hash"]
        or semantic_check.get("plan_receipt_hash") != plan["receipt_hash"]
        or semantic_check.get("run_id") != plan["run_id"]
        or semantic_check.get("mode") != "search"
        or semantic_check.get("model_check_only") is not True
        or semantic_check.get("independent_primary_support_verified") is not False
        or semantic_check.get("release_authorized") is not False
        or semantic_check.get("verdict")
        not in {"supported", "overstated", "contradicted", "unclear"}
    ):
        raise ValueError("search_result_receipts_not_bound")
    quote_start = candidate.get("quote_char_start")
    quote_end = candidate.get("quote_char_end")
    quote = candidate.get("quote")
    if (
        row.get("source_id") != candidate.get("source_id")
        or type(quote) is not str
        or type(quote_start) is not int
        or type(quote_end) is not int
        or source_text[quote_start:quote_end] != quote
        or quote_end != quote_start + len(quote)
    ):
        raise ValueError("search_result_quote_not_exact")
    support = semantic_check["verdict"] == "supported"
    expected_status = (
        "provisional_support"
        if support
        else "verification_inconclusive"
        if semantic_check["verdict"] == "unclear"
        else "claim_rejected"
    )
    if semantic_check.get("status") != expected_status:
        raise ValueError("search_result_verdict_invalid")
    total_cost = semantic_check.get("reported_total_cost_usd")
    if (
        type(total_cost) not in (int, float)
        or abs(
            total_cost
            - portfolio["reported_provider_cost_usd"]
            - candidate["estimated_cost_usd"]
            - semantic_check["estimated_cost_usd"]
        )
        > 0.000000001
        or total_cost > plan["limits"]["max_estimated_cost_usd"]
    ):
        raise ValueError("search_result_cost_not_bound")
    claims = (
        [
            {
                "id": "CLM-"
                + hashlib.sha256(candidate["claim"].encode()).hexdigest()[:16].upper(),
                "text": candidate["claim"],
                "kind": "observation",
                "evidence": [
                    {"source_id": row["source_id"], "quote": candidate["quote"]}
                ],
                "limitations": [candidate["uncertainty"]],
            }
        ]
        if support
        else []
    )
    report = build_report(
        {
            "question": plan["question"],
            "sources": [
                {
                    "id": row["source_id"],
                    "url": row["url"],
                    "title": row["title"],
                    "text": source_text,
                    "accessed_at": capture["observed_at"],
                }
            ],
            "claims": claims,
            "limitations": [
                "Проверка смысла выполнена отдельным сеансом той же модели; это предварительная поддержка, не независимая опора."
                if support
                else "Автоматическая проверка не подтвердила тезис; он сохранён отдельно и не считается установленным выводом.",
                "Исходные байты страницы и независимость происхождения не удостоверены.",
                scope_limit,
            ]
            + ([model_scope_limit] if model_scope_limit else []),
            "stop_reason": "checkpoint" if support else "insufficient_evidence",
            "profile": {"domain": "general", "depth": "search", "risk": "low"},
            "response_format": "full",
        }
    )
    if (
        report.get("status") != "partial"
        or report.get("release_authorized") is not False
        or report.get("semantic_support_unverified") is not True
        or type(report.get("markdown")) is not str
    ):
        raise ValueError("search_report_not_provisional")
    if not support:
        report["unaccepted_interpretations"] = [
            {
                "text": candidate["claim"],
                "source_id": row["source_id"],
                "quote": candidate["quote"],
                "verdict": semantic_check["verdict"],
                "rationale": semantic_check.get("rationale"),
                "accepted": False,
            }
        ]
        report["markdown"] = report["markdown"].replace(
            "Тезисы не переданы; содержательный ответ отсутствует.",
            "Подтвержденных тезисов нет; непроверенная интерпретация сохранена ниже.",
        )
        report["markdown"] += (
            "\n## Неподтвержденная интерпретация\n\n"
            + _md(candidate["claim"])
            + "\n\nСтатус проверки: "
            + {
                "overstated": "формулировка сильнее доказательств",
                "contradicted": "тезис противоречит материалу",
                "unclear": "смысловая опора не установлена",
            }[semantic_check["verdict"]]
            + ". Основание: "
            + _md(semantic_check.get("rationale", "не установлено"))
            + "\n\nФрагмент источника: «"
            + _md(candidate["quote"])
            + "».\n\n"
            + "Точное совпадение цитаты не подтверждает интерпретацию. "
            "Это сохраненное предположение, а не принятый вывод.\n"
        )
    markdown_bytes = report["markdown"].encode("utf-8")
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaLocalSearchResult",
            "status": "provisional_answer" if support else "insufficient_evidence",
            "run_id": plan["run_id"],
            "plan_receipt_hash": plan["receipt_hash"],
            "portfolio_receipt_hash": portfolio["receipt_hash"],
            "candidate_receipt_hash": candidate["receipt_hash"],
            "source_selection_receipt_hash": selection["receipt_hash"],
            "semantic_check_receipt_hash": semantic_check["receipt_hash"],
            "source_text_sha256": candidate["source_text_sha256"],
            "markdown_sha256": hashlib.sha256(markdown_bytes).hexdigest(),
            "claim_count": len(claims),
            "visible_unaccepted_interpretation_count": int(not support),
            "reported_total_cost_usd": total_cost,
            "report": report,
            "final_acceptance_external": True,
            "independent_primary_support_verified": False,
            "mode_qualified": False,
            "release_authorized": False,
            "external_delivery_authorized": False,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--web-capture", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--semantic-check", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan, portfolio, capture, _source_id, _title, source_text, _prompt = _preflight(
            args.plan, args.portfolio, args.web_capture
        )
        if args.output.name != f"{plan['run_id']}-result":
            raise ValueError("search_result_output_mismatch")
        candidate_value, _ = load_json(args.draft)
        check_value = None
        if args.semantic_check is not None:
            check_value, _ = load_json(args.semantic_check)
        if type(candidate_value) is not dict or (
            check_value is not None and type(check_value) is not dict
        ):
            raise ValueError("search_result_input_invalid")
        result = assemble_search_result(
            plan=plan,
            portfolio=portfolio,
            capture=capture,
            candidate=candidate_value,
            semantic_check=check_value,
            source_text=source_text,
        )
        new_private_directory(args.output)
        write_exclusive_bytes(
            args.output / "result.md", result["report"]["markdown"].encode("utf-8")
        )
        write_exclusive_json(args.output / "result.json", result)
        fsync_directory(args.output)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "run_id": result["run_id"],
                    "claim_count": result["claim_count"],
                    "final_acceptance_external": True,
                    "mode_qualified": False,
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
            else "search_result_assembly_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
