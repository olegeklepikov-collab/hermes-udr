"""Assemble one unreleased Deep checkpoint from an attested publisher excerpt."""

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
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from .verify_openalex_oa_semantic import _preflight
except ImportError:
    from file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from verify_openalex_oa_semantic import _preflight

from hermes_research_report.beta_fact_map import build_beta_deep_fact_map
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.report import ReportInputError, build_report


def assemble_deep_partial(
    *,
    plan: dict,
    article: dict,
    publisher: dict,
    screen: dict,
    candidate: dict,
    execution: dict,
    origin_graph: dict,
    semantic_check: dict,
    excerpt: str,
    crosswork: dict | None = None,
) -> dict:
    if (
        plan["mode"] != "deep"
        or not verify_receipt_hash(semantic_check)
        or semantic_check.get("contract") != "BetaSemanticModelCheck"
        or semantic_check.get("run_id") != plan["run_id"]
        or semantic_check.get("plan_receipt_hash") != plan["receipt_hash"]
        or semantic_check.get("candidate_receipt_hash") != candidate["receipt_hash"]
        or semantic_check.get("screen_receipt_hash") != screen["receipt_hash"]
        or semantic_check.get("publisher_receipt_hash") != publisher["receipt_hash"]
        or semantic_check.get("execution_receipt_hash") != execution["receipt_hash"]
        or semantic_check.get("source_scope") != "excerpt_first_12000"
        or semantic_check.get("accepted_claim_count") != 0
        or semantic_check.get("independent_primary_support_verified") is not False
        or semantic_check.get("release_authorized") is not False
        or semantic_check.get("verdict")
        not in {"supported", "overstated", "contradicted", "unclear"}
        or publisher.get("status") != "publisher_html_candidate"
        or publisher.get("publisher_extracted_text_overlap_verified") is not True
        or publisher.get("full_text_coverage_verified") is not False
        or candidate.get("source_text_sha256")
        != hashlib.sha256(excerpt.encode()).hexdigest()
        or candidate.get("quote") not in excerpt
        or not verify_receipt_hash(origin_graph)
        or origin_graph.get("contract") != "BetaWorkOriginGraph"
        or origin_graph.get("run_id") != plan["run_id"]
        or origin_graph.get("plan_receipt_hash") != plan["receipt_hash"]
        or origin_graph.get("execution_receipt_hash") != execution["receipt_hash"]
        or origin_graph.get("work_id") != article.get("work_id")
        or origin_graph.get("doi") != article.get("doi")
        or origin_graph.get("independent_second_work_verified") is not False
        or origin_graph.get("independent_primary_work_count_verified") != 0
        or origin_graph.get("release_authorized") is not False
    ):
        raise ValueError("deep_result_receipts_not_bound")
    supported = semantic_check["verdict"] == "supported"
    expected_status = (
        "provisional_support"
        if supported
        else "verification_inconclusive"
        if semantic_check["verdict"] == "unclear"
        else "claim_rejected"
    )
    if semantic_check.get("status") != expected_status:
        raise ValueError("deep_result_verdict_invalid")
    if crosswork is not None and (
        not verify_receipt_hash(crosswork)
        or crosswork.get("contract") != "BetaDeepCrossWorkComparison"
        or crosswork.get("run_id") != plan["run_id"]
        or crosswork.get("plan_receipt_hash") != plan["receipt_hash"]
        or crosswork.get("execution_receipt_hash") != execution["receipt_hash"]
        or crosswork.get("origin_graph_receipt_hash") != origin_graph["receipt_hash"]
        or crosswork.get("primary_candidate_receipt_hash") != candidate["receipt_hash"]
        or crosswork.get("primary_semantic_receipt_hash")
        != semantic_check["receipt_hash"]
        or crosswork.get("primary_semantic_verdict", "supported")
        != semantic_check["verdict"]
        or crosswork.get("independent_primary_study_verified") is not False
        or crosswork.get("accepted_claim_count") != 0
        or crosswork.get("release_authorized") is not False
        or (
            crosswork.get("verdict_origin") == "policy_downgrade_unanchored_quote"
            and (
                crosswork.get("model_verdict") not in {"corroborates", "challenges"}
                or crosswork.get("verdict") != "unclear"
                or crosswork.get("quote") is not None
            )
        )
        or crosswork.get("secondary_source_ref") == article.get("work_id")
        or (
            crosswork.get("secondary_source_ref") is not None
            and (
                crosswork.get("secondary_source_scope") != "abstract_only"
                or type(crosswork.get("secondary_abstract")) is not str
                or hashlib.sha256(crosswork["secondary_abstract"].encode()).hexdigest()
                != crosswork.get("secondary_abstract_sha256")
                or (
                    crosswork.get("quote") is not None
                    and crosswork["quote"] not in crosswork["secondary_abstract"]
                )
            )
        )
    ):
        raise ValueError("deep_result_crosswork_not_bound")
    cost = (
        crosswork.get("reported_total_cost_usd")
        if crosswork is not None
        else semantic_check.get("reported_total_cost_usd")
    )
    if (
        type(cost) not in (int, float)
        or not 0 <= cost <= plan["limits"]["max_estimated_cost_usd"]
    ):
        raise ValueError("deep_result_cost_invalid")
    fact_map = build_beta_deep_fact_map(
        plan=plan,
        execution=execution,
        origin_graph=origin_graph,
        article=article,
        publisher=publisher,
        screen=screen,
        candidate=candidate,
        semantic_check=semantic_check,
        excerpt=excerpt,
    )
    claims = (
        [
            {
                "id": "CLM-"
                + hashlib.sha256(candidate["claim"].encode()).hexdigest()[:16].upper(),
                "text": candidate["claim"],
                "kind": "observation",
                "evidence": [
                    {"source_id": candidate["source_id"], "quote": candidate["quote"]}
                ],
                "limitations": [
                    candidate["uncertainty"],
                    "Опора ограничена одним издательским материалом и проверенным фрагментом; независимой второй работы нет.",
                ],
            }
        ]
        if supported
        else []
    )
    report = build_report(
        {
            "question": plan["question"],
            "sources": [
                {
                    "id": candidate["source_id"],
                    "url": publisher["final_url_without_query"],
                    "title": article["title"],
                    "text": excerpt,
                    "accessed_at": publisher["observed_at"],
                }
            ],
            "claims": claims,
            "limitations": [
                "Смысловая проверка выполнена отдельным сеансом того же поставщика модели и не является независимой научной опорой.",
                "Проверены издательская страница и связь извлечённого текста с ней; полнота приложений и иных версий статьи не установлена.",
                "Другая запись сопоставлена только по аннотации; научная независимость, полнотекстовое сравнение и анализ покрытия не установлены; режим Deep не квалифицирован."
                if crosswork is not None
                and crosswork.get("secondary_source_ref") is not None
                else "Второй независимой работы и сопоставления конкурирующих результатов нет; режим Deep не квалифицирован.",
            ]
            + (
                [
                    "Исходная цитата модели не совпала с текстом; точный фрагмент выбрала система по предметным группам плана, его смысл отдельно проверен."
                ]
                if candidate.get("quote_origin") == "source_retrieval_policy_v1"
                else []
            ),
            "stop_reason": "checkpoint" if supported else "insufficient_evidence",
            "profile": {"domain": "general", "depth": "deep", "risk": "medium"},
            "response_format": "full",
        }
    )
    if (
        report.get("status") != "partial"
        or report.get("release_authorized") is not False
        or type(report.get("markdown")) is not str
    ):
        raise ValueError("deep_report_not_partial")
    banner = (
        "Статус: предварительный тезис, не принятый как вывод Deep. "
        "Принятых тезисов: 0.\n\n"
        if supported
        else "Статус: модельный тезис сохранён как непроверенная гипотеза; принятых тезисов: 0.\n\n"
    )
    hypothesis_appendix = ""
    if not supported and candidate.get("claim"):
        hypothesis_appendix = (
            "\n## Непринятый модельный тезис\n\n"
            f"{candidate['claim']}\n\n"
            f"Точный фрагмент проверенного отрывка: «{candidate['quote']}». "
            f"Смысловая проверка: { {'overstated': 'формулировка сильнее доказательств', 'contradicted': 'тезис противоречит материалу', 'unclear': 'смысловая опора не установлена'}[semantic_check['verdict']] }; {semantic_check.get('rationale', 'требуется дополнительная проверка')}. "
            "Это гипотеза или отклонённое предположение, не вывод исследования.\n"
        )
    appendix = ""
    if crosswork is not None and crosswork.get("secondary_source_ref") is not None:
        verdict_labels = {
            "corroborates": "предварительно согласуется",
            "challenges": "предварительно возражает",
            "context_only": "даёт только контекст",
            "unclear": "связь неясна",
        }
        verdict = crosswork.get("verdict")
        if verdict not in verdict_labels:
            raise ValueError("deep_result_crosswork_verdict_invalid")
        quote = crosswork.get("quote")
        appendix = (
            "\n## Другая запись — только аннотация\n\n"
            f"{crosswork['secondary_title']} ({crosswork['secondary_source_ref']}). "
            f"Сопоставление: {verdict_labels[verdict]}. "
            f"{crosswork['reason']}\n\n"
            + (
                f"Точный фрагмент аннотации: «{quote}».\n\n"
                if quote
                else "Цитата модели не получила точной привязки либо не требовалась.\n\n"
            )
            + "Содержательная независимость работы, её методы и полный текст не проверены.\n"
            + (
                "Модель предположила согласие или возражение, но её цитата не привязана к аннотации; итоговая связь неясна.\n"
                if crosswork.get("verdict_origin")
                == "policy_downgrade_unanchored_quote"
                else ""
            )
            + (
                "Первичная смысловая опора тезиса неясна; сопоставление по аннотации не повышает его до вывода.\n"
                if not supported
                else ""
            )
            + (
                "Сопоставление восстановлено из сохранённого ответа без нового вызова модели.\n"
                if crosswork.get("reconciled_without_new_model_call") is True
                else ""
            )
        )
    report = {
        **report,
        "markdown": banner + report["markdown"] + hypothesis_appendix + appendix,
    }
    markdown = report["markdown"].encode("utf-8")
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaLocalDeepPartialResult",
            "status": "provisional_crosswork_partial"
            if supported
            and crosswork is not None
            and crosswork.get("secondary_source_ref") is not None
            else "provisional_single_work"
            if supported
            else "hypothesis_unresolved"
            if semantic_check["verdict"] == "unclear"
            else "insufficient_evidence",
            "run_id": plan["run_id"],
            "plan_receipt_hash": plan["receipt_hash"],
            "execution_receipt_hash": execution["receipt_hash"],
            "origin_graph_receipt_hash": origin_graph["receipt_hash"],
            "publisher_receipt_hash": publisher["receipt_hash"],
            "screen_receipt_hash": screen["receipt_hash"],
            "semantic_check_receipt_hash": semantic_check["receipt_hash"],
            "crosswork_receipt_hash": crosswork["receipt_hash"] if crosswork else None,
            "fact_map_receipt_hash": fact_map["receipt_hash"],
            "fact_map": fact_map,
            "markdown_sha256": hashlib.sha256(markdown).hexdigest(),
            "provisional_claim_count": len(claims),
            "visible_unaccepted_hypothesis_count": int(
                not supported and bool(candidate.get("claim"))
            ),
            "accepted_claim_count": 0,
            "reported_total_cost_usd": cost,
            "open_obligations": [
                "second_independent_work",
                "full_text_cross_work_challenge"
                if crosswork is not None
                and crosswork.get("secondary_source_ref") is not None
                else "cross_work_fact_map_and_challenge",
                "full_article_version_and_supplements",
                "mode_e2e_qualification",
            ],
            "report": report,
            "final_acceptance_external": True,
            "mode_qualified": False,
            "release_authorized": False,
            "external_delivery_authorized": False,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--metadata-capture", type=Path, required=True)
    parser.add_argument("--article-capture", type=Path, required=True)
    parser.add_argument("--publisher-capture", type=Path, required=True)
    parser.add_argument("--screen-dir", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--origin-graph", type=Path, required=True)
    parser.add_argument("--semantic-check", type=Path, required=True)
    parser.add_argument("--crosswork", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        (
            plan,
            _metadata,
            article,
            publisher,
            screen,
            candidate,
            execution,
            excerpt,
            _prompt,
            _cost,
        ) = _preflight(
            args.plan,
            args.metadata_capture,
            args.article_capture,
            args.publisher_capture,
            args.screen_dir,
            args.execution,
        )
        short = article["work_id"].removeprefix("https://openalex.org/")
        revision = (
            1
            if args.output.name == f"{plan['run_id']}-deep-result-reconciled"
            else 2
            if args.output.name == f"{plan['run_id']}-deep-result-reconciled-v2"
            else 0
        )
        if (
            args.semantic_check.name != "semantic-check.json"
            or args.semantic_check.parent.name
            != f"{plan['run_id']}-{article['leaf_id']}-{short}-verify"
            or args.semantic_check.parent.is_symlink()
            or args.origin_graph.name != f"{plan['run_id']}.origin-graph.json"
            or args.origin_graph.is_symlink()
            or (args.output.name != f"{plan['run_id']}-deep-result" and revision == 0)
        ):
            raise ValueError("deep_result_paths_invalid")
        check_value, _ = load_json(args.semantic_check)
        origin_value, _ = load_json(args.origin_graph)
        crosswork_value = None
        if args.crosswork is not None:
            if (
                args.crosswork.name != "comparison.json"
                or args.crosswork.parent.name != f"{plan['run_id']}-deep-crosswork"
                or args.crosswork.parent.is_symlink()
            ):
                raise ValueError("deep_result_crosswork_path_invalid")
            crosswork_value, _ = load_json(args.crosswork)
        if type(check_value) is not dict or type(origin_value) is not dict:
            raise ValueError("deep_semantic_check_invalid")
        if crosswork_value is not None and type(crosswork_value) is not dict:
            raise ValueError("deep_crosswork_receipt_invalid")
        result = assemble_deep_partial(
            plan=plan,
            article=article,
            publisher=publisher,
            screen=screen,
            candidate=candidate,
            execution=execution,
            origin_graph=origin_value,
            semantic_check=check_value,
            excerpt=excerpt,
            crosswork=crosswork_value,
        )
        if revision:
            if (
                crosswork_value is None
                or crosswork_value.get("reconciled_without_new_model_call") is not True
            ):
                raise ValueError("deep_reconciled_result_requires_saved_comparison")
            prior_name = (
                f"{plan['run_id']}-deep-result"
                if revision == 1
                else f"{plan['run_id']}-deep-result-reconciled"
            )
            prior_value, _ = load_json(args.output.parent / prior_name / "result.json")
            if (
                type(prior_value) is not dict
                or not verify_receipt_hash(prior_value)
                or prior_value.get("contract") != "BetaLocalDeepPartialResult"
                or prior_value.get("plan_receipt_hash") != plan["receipt_hash"]
                or prior_value.get("execution_receipt_hash")
                != execution["receipt_hash"]
                or prior_value.get("crosswork_receipt_hash")
                != (None if revision == 1 else crosswork_value["receipt_hash"])
                or prior_value.get("release_authorized") is not False
            ):
                raise ValueError("deep_prior_result_not_bound")
            body = dict(result)
            body.pop("receipt_hash")
            body.update(
                {
                    "supersedes_result_receipt_hash": prior_value["receipt_hash"],
                    "reconciled_without_new_model_call": True,
                    "additional_model_calls": 0,
                    "result_revision": revision,
                }
            )
            result = with_receipt_hash(body)
        new_private_directory(args.output)
        write_exclusive_bytes(
            args.output / "result.md", result["report"]["markdown"].encode("utf-8")
        )
        write_exclusive_json(args.output / "fact-map.json", result["fact_map"])
        write_exclusive_json(args.output / "result.json", result)
        fsync_directory(args.output)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "run_id": result["run_id"],
                    "provisional_claim_count": result["provisional_claim_count"],
                    "accepted_claim_count": 0,
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
            else "deep_result_assembly_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
