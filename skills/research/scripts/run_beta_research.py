"""One-command, fail-closed local Ultra/Academic source dossier.

This is a usable source-discovery path, not a qualified synthesis engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
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

from hermes_research_report.beta_coverage import assess_beta_coverage
from hermes_research_report.beta_evidence_independence import (
    assess_evidence_independence,
)
from hermes_research_report.beta_instrument_portfolio import (
    assess_instrument_portfolio,
)
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.beta_research_gates import (
    assess_research_gate_vector,
    gate_row,
)
from hermes_research_report.beta_saturation import assess_thematic_saturation
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.report import _md
from hermes_research_report.runtime_snapshot import runtime_guarded, verify_runtime
from hermes_research_report.turn_trace import ENV as TURN_TRACE_ENV
from hermes_research_report.turn_trace import register_child_run

SCRIPTS = Path(__file__).resolve().parent
_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")
DEFAULT_ADAPTIVE_COVERAGE_BATCHES = 3


def _adaptive_source_lines(batches: list[dict]) -> list[str]:
    lines = []
    labels = {
        "direct": "предварительная прямая опора",
        "context_only": "полезный контекст",
        "irrelevant": "не отвечает данному вопросу",
        "unclear_quote_unanchored": "неподтвержденная интерпретация",
    }
    for batch in batches:
        screens = batch.get("source_assessments", [])
        if not screens:
            continue  # Older receipts retain their original summary-only scope.
        if not verify_receipt_hash(batch) or [
            s.get("receipt_hash") for s in screens
        ] != batch.get("screen_receipt_hashes"):
            raise ValueError("adaptive_report_screens_unbound")
        for screen in screens:
            if (
                not verify_receipt_hash(screen)
                or screen.get("frame_receipt_hash") != batch.get("frame_receipt_hash")
                or screen.get("atom_id") != batch.get("atom_id")
                or screen.get("claim_truth_verified") is not False
            ):
                raise ValueError("adaptive_report_screen_invalid")
            quote = screen.get("quote") or "нет проверенной цитаты"
            words = list(re.finditer(r"\S+", quote))
            if len(words) > 25:
                quote = quote[: words[24].end()] + " … (начало фрагмента)"
            label = labels.get(screen["relation_effective"], "оценка не завершена")
            lines.append(
                f"- {_md(screen['atom_id'])}: {_md(screen['title'])} "
                f"({_md(screen['source_id'])}) — {label}. {_md(screen['reason'])} "
                f"Прочитанный диапазон: {screen['shown_char_start']}:{screen['shown_char_end']} "
                f"из {screen['source_chars_total']} знаков сохраненного текста. "
                f"Фрагмент: «{_md(quote)}». Истинность и независимость не подтверждены."
            )
    return lines


def _next_coverage_atom(
    frame: dict, progress: dict, attempts: dict[str, int]
) -> dict | None:
    """Re-rank open questions after each observed batch, without claiming saturation."""
    if (
        not verify_receipt_hash(frame)
        or not verify_receipt_hash(progress)
        or progress.get("frame_receipt_hash") != frame.get("receipt_hash")
    ):
        raise ValueError("adaptive_priority_progress_unbound")
    indexed = {row["atom_id"]: row for row in progress["atoms"]}
    candidates = [
        atom
        for atom in frame["atoms"]
        if "web" in atom["required_families"]
        and not indexed[atom["atom_id"]]["evidence_floor_met"]
    ]
    return min(
        candidates,
        key=lambda atom: (
            indexed[atom["atom_id"]]["query_count"] > 0,
            attempts.get(atom["atom_id"], 0),
            indexed[atom["atom_id"]]["query_count"],
            {"central": 0, "peripheral": 1, "marginal": 2}[atom["importance"]],
            {"negative": 0, "latent": 1, "positive": 2}[atom["space"]],
            atom["atom_id"],
        ),
        default=None,
    )


def _accumulate_adaptive_observations(
    accumulated: list[dict[str, Any]], value: object
) -> None:
    if type(value) is not list or any(type(row) is not dict for row in value):
        raise ValueError("adaptive_coverage_observations_invalid")
    if len(value) < len(accumulated) or value[: len(accumulated)] != accumulated:
        raise ValueError("adaptive_coverage_history_changed")
    accumulated[:] = value


def _planning_child(
    command: list[str], *, timeout: float
) -> tuple[int, dict[str, Any]]:
    """Return a saved planning failure with its run ID for one offline replay."""
    verify_runtime()
    if timeout <= 0:
        raise SearchRunError("profile_planning_deadline_exceeded")
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise SearchRunError("profile_planning_outcome_unknown") from None
    try:
        value = json.loads(
            completed.stdout if completed.returncode == 0 else completed.stderr
        )
    except json.JSONDecodeError:
        raise SearchRunError("profile_planning_response_invalid") from None
    if type(value) is not dict or completed.returncode not in (0, 2):
        raise SearchRunError("profile_planning_response_invalid")
    return completed.returncode, value


def _recover_incomplete_adaptive_cost(
    output_root: Path, adaptive_id: str
) -> float | None:
    try:
        planning = _receipt(
            output_root / f"{adaptive_id}-domain-web-plan/run.json",
            "BetaDomainWebPlanningRun",
            adaptive_id,
        )
        execution = _receipt(
            output_root / f"{adaptive_id}-execution/execution.json",
            "BetaAutomaticSourceExecution",
            adaptive_id,
        )
        costs = [
            planning.get("reported_model_cost_usd"),
            execution.get("reported_total_cost_usd"),
        ]
        for index in range(1, 21):
            suffix = "" if index == 1 else f"-{index:02d}"
            screen_dir = output_root / f"{adaptive_id}-domain-web-screen{suffix}"
            screen_run_path = screen_dir / "screen-run.json"
            if screen_run_path.is_file():
                screen = _receipt(
                    screen_run_path,
                    "BetaAdaptiveCoverageScreenRun",
                    f"{adaptive_id}-S{index:02d}",
                )
                if screen.get("batch_run_id") != adaptive_id:
                    return None
                costs.append(screen.get("reported_model_cost_usd"))
            elif screen_dir.exists():
                return None
        if any(
            type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0
            for cost in costs
        ):
            return None
        return round(sum(float(cost) for cost in costs), 8)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _verify_structure_files(directory: Path, structure: dict[str, Any]) -> None:
    pages = structure.get("pages")
    if type(pages) is not list or len(pages) != structure.get("page_count"):
        raise ValueError("profile_structure_files_invalid")
    for page in pages:
        if type(page) is not dict:
            raise ValueError("profile_structure_files_invalid")
        for name_key, hash_key in (
            ("text_file", "text_sha256"),
            ("table_file", "table_sha256"),
            ("image_file", "image_sha256"),
        ):
            name = page.get(name_key)
            if type(name) is not str or "/" in name or "\\" in name:
                raise ValueError("profile_structure_files_invalid")
            payload = read_private_bytes(directory / name, maximum=5_000_000)
            if hashlib.sha256(payload).hexdigest() != page.get(hash_key):
                raise ValueError("profile_structure_files_invalid")


def assemble_source_dossier(
    *,
    plan: dict[str, Any],
    planning: dict[str, Any],
    execution: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
    protocol: dict[str, Any] | None,
    screening: dict[str, Any] | None = None,
    screening_attempted: bool = False,
    challenge: dict[str, Any] | None = None,
    challenge_attempted: bool = False,
    sensitivity: dict[str, Any] | None = None,
    sensitivity_attempted: bool = False,
    fulltext: dict[str, Any] | None = None,
    fulltext_attempted: bool = False,
    structure: dict[str, Any] | None = None,
    structure_attempted: bool = False,
    analysis: dict[str, Any] | None = None,
    analysis_attempted: bool = False,
    study_graph: dict[str, Any] | None = None,
    study_graph_attempted: bool = False,
    domain_first_requested: bool = False,
    decomposition: dict[str, Any] | None = None,
    coverage_frame: dict[str, Any] | None = None,
    coverage_progress: dict[str, Any] | None = None,
    coverage_mapping: dict[str, Any] | None = None,
    coverage_query_progress: dict[str, Any] | None = None,
    coverage_query_observation: dict[str, Any] | None = None,
    coverage_cumulative_progress: dict[str, Any] | None = None,
    adaptive_batches: list[dict[str, Any]] | None = None,
    adaptive_incomplete_batches: list[dict[str, Any]] | None = None,
    adaptive_attempted: bool = False,
    adaptive_cost_usd: float | None = None,
    preflight_cost_usd: float | None = None,
    domain_run_id: str | None = None,
    coverage_run_id: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    verified = verify_beta_mode_plan(plan)
    mode = verified["mode"]
    if mode not in {"ultra", "academic"}:
        raise ValueError("profile_mode_invalid")
    if domain_first_requested:
        if mode != "ultra":
            raise ValueError("profile_domain_first_mode_invalid")
        if decomposition is not None and domain_run_id != decomposition.get("run_id"):
            raise ValueError("profile_domain_run_not_bound")
        if coverage_frame is not None and coverage_run_id != coverage_frame.get(
            "run_id"
        ):
            raise ValueError("profile_coverage_run_not_bound")
        if decomposition is not None and (
            not verify_receipt_hash(decomposition)
            or decomposition.get("contract") != "BetaDomainDecomposition"
            or decomposition.get("question") != verified["question"]
            or decomposition.get("profile") != mode
        ):
            raise ValueError("profile_decomposition_not_bound")
        if coverage_frame is not None and (
            decomposition is None
            or not verify_receipt_hash(coverage_frame)
            or coverage_frame.get("contract") != "BetaCoverageFrame"
            or coverage_frame.get("decomposition_receipt_hash")
            != decomposition["receipt_hash"]
            or coverage_frame.get("question") != verified["question"]
        ):
            raise ValueError("profile_coverage_not_bound")
        if coverage_progress is not None and (
            coverage_frame is None
            or not verify_receipt_hash(coverage_progress)
            or coverage_progress.get("contract") != "BetaCoverageProgressAssessment"
            or coverage_progress.get("frame_receipt_hash")
            != coverage_frame["receipt_hash"]
            or coverage_progress.get("evidence_floor_count") != 0
        ):
            raise ValueError("profile_coverage_progress_not_bound")
        if coverage_mapping is not None and (
            coverage_frame is None
            or not verify_receipt_hash(coverage_mapping)
            or coverage_mapping.get("contract") != "BetaCoverageQueryAtomMapping"
            or coverage_mapping.get("frame_receipt_hash")
            != coverage_frame["receipt_hash"]
            or coverage_mapping.get("plan_receipt_hash") != verified["receipt_hash"]
        ):
            raise ValueError("profile_coverage_mapping_not_bound")
        if coverage_query_progress is not None and (
            coverage_frame is None
            or not verify_receipt_hash(coverage_query_progress)
            or coverage_query_progress.get("frame_receipt_hash")
            != coverage_frame["receipt_hash"]
        ):
            raise ValueError("profile_coverage_observation_not_bound")
        if coverage_query_observation is not None and (
            coverage_mapping is None
            or coverage_query_progress is None
            or not verify_receipt_hash(coverage_query_observation)
            or coverage_query_observation.get("contract")
            != "BetaCoverageMappedQueryObservation"
            or coverage_query_observation.get("mapping_receipt_hash")
            != coverage_mapping["receipt_hash"]
            or coverage_query_observation.get("progress_receipt_hash")
            != coverage_query_progress["receipt_hash"]
        ):
            raise ValueError("profile_coverage_observation_not_bound")
        if coverage_cumulative_progress is not None and (
            coverage_frame is None
            or not verify_receipt_hash(coverage_cumulative_progress)
            or coverage_cumulative_progress.get("frame_receipt_hash")
            != coverage_frame["receipt_hash"]
        ):
            raise ValueError("profile_coverage_cumulative_not_bound")
        if adaptive_batches is not None and any(
            type(row) is not dict
            or not verify_receipt_hash(row)
            or row.get("contract") != "BetaAdaptiveCoverageBatchRun"
            or coverage_frame is None
            or row.get("frame_receipt_hash") != coverage_frame["receipt_hash"]
            for row in adaptive_batches
        ):
            raise ValueError("profile_adaptive_batch_not_bound")
    elif any(
        value is not None
        for value in (
            decomposition,
            coverage_frame,
            coverage_progress,
            coverage_mapping,
            coverage_query_progress,
            coverage_query_observation,
            coverage_cumulative_progress,
            adaptive_batches,
            adaptive_cost_usd,
            preflight_cost_usd,
            domain_run_id,
            coverage_run_id,
        )
    ):
        raise ValueError("profile_unrequested_preflight_invalid")
    if (
        not verify_receipt_hash(planning)
        or planning.get("contract") != "BetaAutonomousPlanningRun"
        or planning.get("plan_receipt_hash") != verified["receipt_hash"]
        or planning.get("run_id") != verified["run_id"]
        or planning.get("mode") != mode
        or planning.get("release_authorized") is not False
    ):
        raise ValueError("profile_planning_not_bound")
    if mode == "academic":
        if (
            type(protocol) is not dict
            or not verify_receipt_hash(protocol)
            or protocol.get("contract") != "BetaAutonomousAcademicProtocol"
            or protocol.get("run_id") != verified["run_id"]
            or protocol.get("receipt_hash")
            != verified["academic_protocol"]["protocol_ref"]
            or planning.get("academic_protocol_receipt_hash")
            != protocol["receipt_hash"]
        ):
            raise ValueError("profile_protocol_not_bound")
    elif protocol is not None:
        raise ValueError("profile_protocol_not_applicable")
    if execution is not None and (
        not verify_receipt_hash(execution)
        or execution.get("contract") != "BetaAutomaticSourceExecution"
        or execution.get("run_id") != verified["run_id"]
        or execution.get("plan_receipt_hash") != verified["receipt_hash"]
        or execution.get("mode") != mode
        or execution.get("release_authorized") is not False
    ):
        raise ValueError("profile_execution_not_bound")
    if portfolio is not None and (
        execution is None
        or not verify_receipt_hash(portfolio)
        or portfolio.get("contract") != "BetaSourcePortfolio"
        or portfolio.get("run_id") != verified["run_id"]
        or portfolio.get("plan_receipt_hash") != verified["receipt_hash"]
        or portfolio.get("mode") != mode
        or portfolio.get("release_authorized") is not False
        or execution.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
    ):
        raise ValueError("profile_portfolio_not_bound")
    if screening is not None and (
        mode != "academic"
        or protocol is None
        or execution is None
        or portfolio is None
        or not verify_receipt_hash(screening)
        or screening.get("contract") != "BetaAcademicPreliminaryScreen"
        or screening.get("run_id") != verified["run_id"]
        or screening.get("plan_receipt_hash") != verified["receipt_hash"]
        or screening.get("protocol_receipt_hash") != protocol["receipt_hash"]
        or screening.get("execution_receipt_hash") != execution["receipt_hash"]
        or screening.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
        or screening.get("included_study_count") != 0
        or screening.get("release_authorized") is not False
    ):
        raise ValueError("profile_screening_not_bound")
    if screening is not None and (
        type(screening.get("decisions")) is not list
        or len(screening["decisions"]) != screening.get("identified_record_count")
        or any(
            type(row) is not dict
            or type(row.get("record_id")) is not str
            or row.get("verdict") not in {"include_candidate", "exclude", "uncertain"}
            or type(row.get("reason")) is not str
            or any(ord(char) < 32 for char in row["reason"])
            for row in screening["decisions"]
        )
    ):
        raise ValueError("profile_screening_invalid")
    if challenge is not None and (
        mode != "ultra"
        or execution is None
        or portfolio is None
        or not verify_receipt_hash(challenge)
        or challenge.get("contract") != "BetaUltraRivalChallenge"
        or challenge.get("run_id") != verified["run_id"]
        or challenge.get("plan_receipt_hash") != verified["receipt_hash"]
        or challenge.get("execution_receipt_hash") != execution["receipt_hash"]
        or challenge.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
        or challenge.get("accepted_claim_count") != 0
        or challenge.get("release_authorized") is not False
    ):
        raise ValueError("profile_challenge_not_bound")
    if sensitivity is not None and (
        mode != "ultra"
        or challenge is None
        or not verify_receipt_hash(sensitivity)
        or sensitivity.get("contract") != "BetaUltraSensitivity"
        or sensitivity.get("run_id") != verified["run_id"]
        or sensitivity.get("plan_receipt_hash") != verified["receipt_hash"]
        or sensitivity.get("challenge_receipt_hash") != challenge["receipt_hash"]
        or sensitivity.get("robustness_verified") is not False
        or sensitivity.get("release_authorized") is not False
    ):
        raise ValueError("profile_sensitivity_not_bound")
    if fulltext is not None and (
        mode != "academic"
        or screening is None
        or not verify_receipt_hash(fulltext)
        or fulltext.get("contract") != "BetaArxivFullTextRead"
        or fulltext.get("run_id") != verified["run_id"]
        or fulltext.get("plan_receipt_hash") != verified["receipt_hash"]
        or fulltext.get("screening_receipt_hash") != screening["receipt_hash"]
        or fulltext.get("status") != "parsed_text_candidate"
        or fulltext.get("release_authorized") is not False
        or not any(
            row.get("record_id") == fulltext.get("record_id")
            and row.get("verdict") == "include_candidate"
            for row in screening.get("decisions", [])
            if type(row) is dict
        )
    ):
        raise ValueError("profile_fulltext_not_bound")
    if analysis is not None and (
        mode != "academic"
        or fulltext is None
        or not verify_receipt_hash(analysis)
        or analysis.get("contract") != "BetaAcademicFullTextAnalysis"
        or analysis.get("run_id") != verified["run_id"]
        or analysis.get("plan_receipt_hash") != verified["receipt_hash"]
        or analysis.get("fulltext_receipt_hash") != fulltext["receipt_hash"]
        or type(analysis.get("cards")) is not list
        or analysis.get("reported_statement_count") != len(analysis["cards"])
        or analysis.get("accepted_claim_count") != 0
        or analysis.get("release_authorized") is not False
    ):
        raise ValueError("profile_analysis_not_bound")
    if structure is not None and (
        mode != "academic"
        or fulltext is None
        or not verify_receipt_hash(structure)
        or structure.get("contract") != "BetaAcademicPdfStructure"
        or structure.get("run_id") != verified["run_id"]
        or structure.get("plan_receipt_hash") != verified["receipt_hash"]
        or structure.get("fulltext_receipt_hash") != fulltext["receipt_hash"]
        or structure.get("page_count") != fulltext["page_count"]
        or structure.get("table_values_verified") is not False
        or structure.get("release_authorized") is not False
    ):
        raise ValueError("profile_structure_not_bound")
    if study_graph is not None and (
        mode != "academic"
        or screening is None
        or not verify_receipt_hash(study_graph)
        or study_graph.get("contract") != "BetaAcademicStudyGraph"
        or study_graph.get("run_id") != verified["run_id"]
        or study_graph.get("plan_receipt_hash") != verified["receipt_hash"]
        or study_graph.get("screening_receipt_hash") != screening["receipt_hash"]
        or study_graph.get("fulltext_receipt_hash")
        != (fulltext["receipt_hash"] if fulltext else None)
        or study_graph.get("quantitative_pooling_allowed") is not False
        or study_graph.get("release_authorized") is not False
    ):
        raise ValueError("profile_study_graph_not_bound")
    source_rows = portfolio["leaves"] if portfolio is not None else []
    if type(source_rows) is not list or any(
        type(row) is not dict for row in source_rows
    ):
        raise ValueError("profile_source_rows_invalid")
    observed = {row["leaf_id"]: row for row in source_rows}
    if len(observed) != len(source_rows) or not set(observed).issubset(
        {leaf["leaf_id"] for leaf in verified["leaves"]}
    ):
        raise ValueError("profile_source_rows_duplicate")
    lines = [
        "# Предварительное досье источников",
        "",
        f"Режим: {mode}. Принятых исследовательских выводов: 0. Квалификация режима: нет.",
        f"Вопрос: {verified['question']}",
        "",
    ]
    if domain_first_requested:
        lines.extend(["## Предметный охват до поиска", ""])
        if coverage_frame is None or coverage_progress is None:
            lines.append("Предметная карта не завершена; пробел сохранён и не скрыт.")
        else:
            lines.append(
                f"Предварительная карта: {coverage_progress['facet_count']} аспектов, "
                f"{coverage_progress['branch_count']} ветвей, "
                f"{coverage_progress['atom_count']} вопросов. "
                "Ни один вопрос не закрыт только созданием карты или поисковым адресом."
            )
            lines.append(
                "Структурные пробелы: "
                f"{len(coverage_progress['empty_branch_ids'])} пустых ветвей; "
                f"{len(coverage_progress['required_importance_rank_gaps'])} "
                "недостающих уровней важности."
            )
            lines.append(
                "Независимая предметная полнота и насыщение не удостоверены; "
                "поисковая попытка не равна проверенному свидетельству."
            )
            final_progress = coverage_cumulative_progress or coverage_query_progress
            observed_atoms = (
                {row["atom_id"]: row for row in final_progress["atoms"]}
                if final_progress is not None
                else {}
            )
            for atom in coverage_frame["atoms"]:
                query_count = observed_atoms.get(atom["atom_id"], {}).get(
                    "query_count", 0
                )
                lines.append(
                    f"- {atom['atom_id']} "
                    f"[{coverage_frame['facet_labels'][atom['facet_id']]}; "
                    f"{atom['importance']}/{atom['space']}]: "
                    f"{atom['question']} — открыт; поисковых попыток: {query_count}."
                )
            if adaptive_batches:
                lines.append(
                    f"Адаптивных дополнительных партий: {len(adaptive_batches)}; "
                    "их кандидаты не повышены до проверенных опор."
                )
                lines.extend(_adaptive_source_lines(adaptive_batches))
        lines.append("")
    lines.extend(["## Исполненные поисковые листья", ""])
    for leaf in verified["leaves"]:
        row = observed.get(leaf["leaf_id"])
        if row is None:
            lines.append(
                f"- {leaf['leaf_id']} ({leaf['source_family']}): нет проверенной квитанции."
            )
        else:
            lines.append(
                f"- {leaf['leaf_id']} ({leaf['source_family']}): {row['status']}; "
                f"кандидатов {row['candidate_count']}; область чтения {row['read_scope']}"
                + (
                    f"; причина {row['reason']}"
                    if row["status"] != "candidate" and row.get("reason")
                    else ""
                )
                + "."
            )
    lines.extend(["", "## Невыполненные проверки", ""])
    if mode == "ultra":
        lines.append("Конкурирующие гипотезы и предварительная проверка по аннотациям:")
        judgments = (
            {row["rival_index"]: row for row in challenge["judgments"]}
            if challenge is not None
            else {}
        )
        for index, rival in enumerate(verified["rival_hypotheses"]):
            row = judgments.get(index)
            if row is None:
                lines.append(f"- {rival}: не проверена.")
            else:
                verdict = {
                    "supported": "предварительно поддержана",
                    "contradicted": "предварительно оспорена",
                    "unclear": "неясно",
                }[row["verdict"]]
                lines.append(
                    f"- {rival}: {verdict} ({row['reason']}); "
                    f"опора: {row['source_ref'] or 'нет'}; "
                    f"точный фрагмент: «{row['quote']}»."
                )
        if sensitivity is not None:
            lines.append(
                f"Проверка удаления цитируемого источника: {sensitivity['single_citation_dependent_count']} "
                "предварительных вердиктов требуют повторного анализа; устойчивость не установлена."
            )
        elif sensitivity_attempted:
            lines.append(
                "Проверка устойчивости не завершена; исходные гипотезы и цитаты сохранены."
            )
        lines.append(
            "Вердикты по аннотациям предварительны; не выполнены независимое сопоставление полных работ и анализ устойчивости."
        )
    else:
        lines.append(
            f"Протокол запечатан до получения источников: {protocol['receipt_hash']}."
        )
        if screening is None:
            lines.append("Предварительный отбор названий и аннотаций не завершён.")
        else:
            lines.append(
                "Предварительный отбор названий и аннотаций: "
                f"{screening['identified_record_count']} записей; "
                f"{screening['include_candidate_count']} кандидатов к полному тексту, "
                f"{screening['exclude_count']} исключены, "
                f"{screening['uncertain_count']} неясны."
            )
            titles = {row["record_id"]: row["title"] for row in screening["records"]}
            screen_labels = {
                "include_candidate": "кандидат к полному тексту",
                "exclude": "исключена по аннотации",
                "uncertain": "неясно",
            }
            lines.extend(
                f"- {titles.get(row['record_id'], 'Название недоступно')} "
                f"({row['record_id']}): {screen_labels[row['verdict']]}; "
                f"{row['reason']}"
                for row in screening["decisions"]
            )
        if fulltext is not None:
            lines.append(
                f"Полный PDF кандидата {fulltext['record_id']} сохранён и текст извлечён: "
                f"{fulltext['page_count']} страниц, {fulltext['text_chars']} знаков. "
                "Полнота формул, таблиц, рисунков и отсканированных страниц ещё не удостоверена."
            )
        elif fulltext_attempted:
            lines.append(
                "Попытка получить полный PDF не завершилась проверенным текстом; предварительный отбор по аннотации сохранён."
            )
        if structure is not None:
            lines.append(
                f"Постраничная структура: текст обнаружен на {structure['pages_with_text']}/{structure['page_count']} страницах; "
                f"выделено {structure['table_grid_count']} табличных сеток. "
                "Ячейки сохранены с координатами, но значения и расчёты не перепроверены."
            )
            visual_pages = structure.get("pages_requiring_visual_review", [])
            numeric_counts = structure.get("numeric_inventory_counts")
            if numeric_counts:
                lines.append(
                    f"В тексте найдены численность с долей: {numeric_counts['count_percent_records']}; "
                    f"доверительные интервалы: {numeric_counts['confidence_interval_records']}; "
                    f"явные пары среднего и SD: {numeric_counts['mean_sd_records']}. "
                    "Это перечень распознанных записей, не проверка всех существенных результатов; "
                    "знаменатель, восстановленный из доли, не является независимым подтверждением."
                )
                lines.append(
                    f"Записей с ±: {numeric_counts.get('location_dispersion_pairs', 0)}; "
                    "без определения в источнике величина после ± не считается SD или стандартной ошибкой."
                )
            if visual_pages:
                lines.append(
                    "Поврежденные символы или неподтвержденная структура таблиц на страницах: "
                    + ", ".join(str(p) for p in visual_pages)
                    + ". Исходный текст сохранен; отсутствующие знаки не восстановлены догадкой."
                )
        elif structure_attempted:
            lines.append(
                "Постраничный разбор таблиц и изображений не завершён; текстовый анализ остаётся доступным с этой оговоркой."
            )
        if analysis is not None:
            if "chunks_total" in analysis:
                lines.append(
                    "Охват текстового слоя: "
                    f"{analysis['text_chars_processed']}/{analysis['text_chars_total']} знаков, "
                    f"{analysis['chunks_analyzed']}/{analysis['chunks_total']} частей. "
                    "Необработанный остаток не считается прочитанным."
                )
            kind_labels = {
                "method": "метод",
                "empirical_observation": "эмпирическое наблюдение",
                "statistical_result": "сообщённый статистический результат",
                "hypothesis": "гипотеза",
                "opinion": "мнение авторов",
                "theory": "теоретическое положение",
                "limitation": "ограничение",
            }
            lines.append(
                "Положения из извлечённого текста PDF; это сообщения авторов, не независимые выводы системы:"
            )
            for card in analysis["cards"]:
                if card.get("evidence_grade") == "short_quote_context_insufficient":
                    grade = (
                        "фрагмент найден, но цитата слишком коротка для проверки всего положения; "
                        "расположение и визуальные элементы не проверены"
                    )
                elif (
                    card["quote"] is not None
                    and card["claim_type"] == "statistical_result"
                ):
                    grade = "точный фрагмент найден; числа, таблицы и метод расчёта не перепроверены"
                elif card["quote"] is not None:
                    grade = "точный фрагмент найден, но расположение и визуальные элементы не проверены"
                else:
                    grade = "цитата модели не совпала с текстом; интерпретация не привязана точно"
                quote = card["quote"]
                if quote is not None and len(quote.split()) > 25:
                    matches = list(re.finditer(r"\S+", quote))
                    quote = quote[: matches[24].end()] + " …"
                    grade += "; показано начало длинного фрагмента"
                lines.append(
                    f"- {kind_labels[card['claim_type']]}: {card['statement']} "
                    f"Опора: {grade}. "
                    f"Цитата: «{quote or 'нет проверенной цитаты'}». "
                    f"Ограничение: {card['uncertainty']}"
                )
        elif analysis_attempted:
            lines.append(
                "Содержательный разбор извлечённого текста не завершён; сам текст и его ограничения сохранены."
            )
        if study_graph is not None:
            lines.append(
                f"Карта публикаций: {study_graph['identified_record_count']} записей, "
                f"{len(study_graph['identity_groups'])} консервативных групп идентичности, "
                f"{study_graph['fulltext_read_count']} прочитанный PDF, "
                "формально включённых исследований: 0. Численное объединение результатов запрещено."
            )
        elif study_graph_attempted:
            lines.append(
                "Связи версий и исследований не завершены; объединение результатов не допускается."
            )
        remaining = ["оценка риска ошибки", "межисследовательский научный синтез"]
        if fulltext is None:
            remaining.insert(0, "отбор и разбор полного текста")
        if study_graph is None:
            remaining.insert(0, "карта исследований")
        lines.append("Не выполнены: " + ", ".join(remaining) + ".")
    lines.append(
        "Метаданные и аннотации не являются полным текстом или доказательством независимости исследований."
    )
    status = (
        "partial_source_dossier"
        if execution is not None
        and execution.get("status") == "partial_analysis_required"
        and portfolio is not None
        and source_rows
        else "source_execution_blocked"
    )
    cost = planning.get("reported_model_cost_usd")
    source_cost = (
        execution.get("reported_total_cost_usd") if execution is not None else None
    )
    screening_cost = (
        screening.get("reported_incremental_cost_usd") if screening is not None else 0
    )
    challenge_cost = (
        challenge.get("reported_incremental_cost_usd") if challenge is not None else 0
    )
    analysis_cost = (
        analysis.get("reported_incremental_cost_usd") if analysis is not None else 0
    )
    if (
        type(cost) not in (int, float)
        or cost < 0
        or type(screening_cost) not in (int, float)
        or screening_cost < 0
        or type(challenge_cost) not in (int, float)
        or challenge_cost < 0
        or type(analysis_cost) not in (int, float)
        or analysis_cost < 0
        or (
            source_cost is not None
            and (type(source_cost) not in (int, float) or source_cost < 0)
        )
        or (
            preflight_cost_usd is not None
            and (type(preflight_cost_usd) not in (int, float) or preflight_cost_usd < 0)
        )
        or (
            adaptive_cost_usd is not None
            and (type(adaptive_cost_usd) not in (int, float) or adaptive_cost_usd < 0)
        )
    ):
        raise ValueError("profile_cost_invalid")
    cost_complete = (
        source_cost is not None
        and (not domain_first_requested or preflight_cost_usd is not None)
        and (not adaptive_attempted or adaptive_cost_usd is not None)
        and (not screening_attempted or screening is not None)
        and (not challenge_attempted or challenge is not None)
        and (not analysis_attempted or analysis is not None)
    )
    total_cost = (
        round(
            float(cost)
            + float(source_cost)
            + float(screening_cost)
            + float(challenge_cost)
            + float(analysis_cost)
            + float(preflight_cost_usd or 0)
            + float(adaptive_cost_usd or 0),
            8,
        )
        if cost_complete
        else None
    )
    workflow_gaps = []
    if domain_first_requested:
        if decomposition is None:
            workflow_gaps.append("domain_decomposition")
        if coverage_frame is None or coverage_progress is None:
            workflow_gaps.append("coverage_frame")
        if coverage_mapping is None:
            workflow_gaps.append("coverage_query_mapping")
        if coverage_query_progress is None or coverage_query_observation is None:
            workflow_gaps.append("coverage_query_observation")
        if adaptive_attempted and (
            not adaptive_batches or coverage_cumulative_progress is None
        ):
            workflow_gaps.append("adaptive_coverage")
    if (
        execution is None
        or portfolio is None
        or execution.get("status") != "partial_analysis_required"
    ):
        workflow_gaps.append("source_execution")
    elif len(source_rows) != len(verified["leaves"]):
        workflow_gaps.append("source_leaf_coverage")
    if mode == "ultra":
        if challenge is None:
            workflow_gaps.append("rival_challenge")
        if sensitivity is None:
            workflow_gaps.append("source_sensitivity")
    else:
        if screening is None:
            workflow_gaps.append("preliminary_screening")
        elif screening["include_candidate_count"] > 0:
            if fulltext is None:
                workflow_gaps.append("candidate_fulltext")
            if structure is None:
                workflow_gaps.append("page_structure")
            if analysis is None:
                workflow_gaps.append("fulltext_analysis")
            elif (
                type(analysis.get("text_chars_total")) is not int
                or analysis.get("text_chars_processed")
                != analysis.get("text_chars_total")
                or analysis.get("text_chars_total") != fulltext["text_chars"]
            ):
                workflow_gaps.append("fulltext_coverage")
        if study_graph is None:
            workflow_gaps.append("study_graph")
    if not cost_complete:
        workflow_gaps.append("cost_observation")
    elif (
        total_cost is not None
        and total_cost > verified["limits"]["max_estimated_cost_usd"]
    ):
        workflow_gaps.append("cost_limit")
    instrument_portfolio = None
    independence = None
    saturation = None
    if coverage_frame is not None:
        instrument_portfolio = assess_instrument_portfolio(
            coverage_frame,
            executable_families={leaf["source_family"] for leaf in verified["leaves"]},
        )
        qualification_progress = (
            coverage_cumulative_progress or coverage_query_progress or coverage_progress
        )
        if qualification_progress is not None:
            evidence_candidates = [
                row
                for batch in adaptive_batches or []
                for row in batch.get("evidence_candidates", [])
                if type(row) is dict
            ]
            independence = assess_evidence_independence(
                coverage_frame, qualification_progress, evidence_candidates
            )
            saturation = assess_thematic_saturation(
                qualification_progress, independence
            )
    gate_rows = [
        gate_row(
            "G0",
            "pass",
            [verified, planning],
            "Исходный вопрос, профиль, пределы и план связаны квитанциями.",
        ),
        gate_row(
            "G1",
            "pass"
            if (mode == "ultra" and decomposition is not None)
            or (mode == "academic" and protocol is not None)
            else "partial",
            [decomposition]
            if mode == "ultra" and decomposition is not None
            else [protocol]
            if mode == "academic" and protocol is not None
            else [],
            "Предметная декомпозиция и операционализация сохранены."
            if mode == "ultra" and decomposition is not None
            else "Академический протокол запечатан до поиска."
            if mode == "academic" and protocol is not None
            else "Декомпозиция или протокол отсутствуют.",
        ),
        gate_row(
            "G2",
            "pass"
            if instrument_portfolio is not None
            and instrument_portfolio["atoms_with_all_required_routes"]
            == instrument_portfolio["atom_count"]
            else "partial",
            [instrument_portfolio] if instrument_portfolio is not None else [],
            "Все требуемые семейства имеют исполняемый маршрут."
            if instrument_portfolio is not None
            and instrument_portfolio["atoms_with_all_required_routes"]
            == instrument_portfolio["atom_count"]
            else "Инструментальный портфель покрывает не все требуемые семейства.",
        ),
        gate_row(
            "G3",
            "partial",
            [portfolio] if portfolio is not None else [],
            "Происхождение захватов проверяется, но независимость первичных корней не установлена.",
        ),
        gate_row(
            "G4",
            "pass"
            if mode == "academic"
            and fulltext is not None
            and analysis is not None
            and analysis.get("text_chars_processed") == analysis.get("text_chars_total")
            else "partial",
            [
                receipt
                for receipt in (fulltext, structure, analysis)
                if receipt is not None
            ],
            "Полный текст выбранной версии обработан целиком."
            if mode == "academic"
            and fulltext is not None
            and analysis is not None
            and analysis.get("text_chars_processed") == analysis.get("text_chars_total")
            else "Чтение ограничено метаданными, аннотациями или неполным текстом.",
        ),
        gate_row(
            "G5",
            "pass"
            if (mode == "ultra" and challenge is not None and sensitivity is not None)
            or (mode == "academic" and analysis is not None and study_graph is not None)
            else "partial",
            [
                receipt
                for receipt in (challenge, sensitivity, analysis, study_graph)
                if receipt is not None
            ],
            "Тезисы, альтернативы и ограничения прошли профильную проверку."
            if (mode == "ultra" and challenge is not None and sensitivity is not None)
            or (mode == "academic" and analysis is not None and study_graph is not None)
            else "Проверка тезисов или контрдоказательств завершена частично.",
        ),
        gate_row(
            "G6",
            "pass"
            if independence is not None
            and independence["all_atoms_meet_independence"] is True
            else "partial",
            [independence] if independence is not None else [],
            "Требуемая независимость корней подтверждена по всем атомам."
            if independence is not None
            and independence["all_atoms_meet_independence"] is True
            else "Независимость достаточного числа опор не подтверждена.",
        ),
        gate_row(
            "G7",
            "not_applicable"
            if mode == "academic"
            else "pass"
            if saturation is not None and saturation["saturation_verified"] is True
            else "partial",
            [saturation] if saturation is not None else [],
            "Тематическое насыщение подтверждено."
            if saturation is not None and saturation["saturation_verified"] is True
            else "Насыщение темы не применяется к разбору одной названной публикации."
            if mode == "academic"
            else "Открытые клетки, независимые корни или калибровка остатка не завершены.",
        ),
        gate_row(
            "G8",
            "pass" if cost_complete and not workflow_gaps else "partial",
            [receipt for receipt in (planning, execution) if receipt is not None],
            "Исполнение и стоимость воспроизводимо зафиксированы."
            if cost_complete and not workflow_gaps
            else "Исполнение либо стоимость зафиксированы не полностью.",
        ),
    ]
    research_gates = assess_research_gate_vector(verified["run_id"], gate_rows)
    lines.extend(
        [
            "",
            "## Исполнение маршрута и надёжность результата",
            "",
            "Запланированный маршрут выполнен; научная надёжность каждого положения указана отдельно."
            if not workflow_gaps
            else "Маршрут завершён частично; недостающие обязательные шаги: "
            + ", ".join(workflow_gaps)
            + ".",
            "Завершённость маршрута не означает подтверждения тезисов или допуска к публичному выпуску.",
            "",
            "## Исследовательская квалификация G0–G8",
            "",
            ", ".join(
                f"{row['gate']}={row['status']}" for row in research_gates["gates"]
            )
            + ".",
            "Полная исследовательская квалификация подтверждена."
            if research_gates["research_qualification_complete"]
            else "Частичный результат доступен; полная исследовательская квалификация не заявлена.",
        ]
    )
    markdown = ("\n".join(lines) + "\n").encode("utf-8")
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaAutonomousProfileDossier",
            "execution_contract": {
                "kind": "standalone_local_research",
                "beads_work_executed": False,
                "dolt_commit_executed": False,
                "external_delivery_executed": False,
            },
            "run_id": verified["run_id"],
            "mode": mode,
            "status": status,
            "plan_receipt_hash": verified["receipt_hash"],
            "planning_run_receipt_hash": planning["receipt_hash"],
            "domain_first_requested": domain_first_requested,
            "domain_decomposition_receipt_hash": decomposition["receipt_hash"]
            if decomposition
            else None,
            "coverage_frame_receipt_hash": coverage_frame["receipt_hash"]
            if coverage_frame
            else None,
            "coverage_progress_receipt_hash": coverage_progress["receipt_hash"]
            if coverage_progress
            else None,
            "coverage_mapping_receipt_hash": coverage_mapping["receipt_hash"]
            if coverage_mapping
            else None,
            "coverage_query_progress_receipt_hash": coverage_query_progress[
                "receipt_hash"
            ]
            if coverage_query_progress
            else None,
            "coverage_query_observation_receipt_hash": coverage_query_observation[
                "receipt_hash"
            ]
            if coverage_query_observation
            else None,
            "coverage_cumulative_progress_receipt_hash": coverage_cumulative_progress[
                "receipt_hash"
            ]
            if coverage_cumulative_progress
            else None,
            "instrument_portfolio": instrument_portfolio,
            "evidence_independence": independence,
            "thematic_saturation": saturation,
            "research_gate_vector": research_gates,
            "research_qualification_complete": research_gates[
                "research_qualification_complete"
            ],
            "adaptive_batch_receipt_hashes": [
                row["receipt_hash"] for row in adaptive_batches or []
            ],
            "adaptive_incomplete_batches": adaptive_incomplete_batches or [],
            "adaptive_attempted": adaptive_attempted,
            "adaptive_cost_usd": adaptive_cost_usd,
            "preflight_model_cost_usd": preflight_cost_usd,
            "domain_run_id": domain_run_id,
            "coverage_run_id": coverage_run_id,
            "execution_receipt_hash": execution["receipt_hash"] if execution else None,
            "portfolio_receipt_hash": portfolio["receipt_hash"] if portfolio else None,
            "academic_protocol_receipt_hash": protocol["receipt_hash"]
            if protocol
            else None,
            "screening_receipt_hash": screening["receipt_hash"] if screening else None,
            "challenge_receipt_hash": challenge["receipt_hash"] if challenge else None,
            "sensitivity_receipt_hash": sensitivity["receipt_hash"]
            if sensitivity
            else None,
            "sensitivity_attempted": sensitivity_attempted,
            "fulltext_receipt_hash": fulltext["receipt_hash"] if fulltext else None,
            "fulltext_attempted": fulltext_attempted,
            "structure_receipt_hash": structure["receipt_hash"] if structure else None,
            "structure_attempted": structure_attempted,
            "analysis_receipt_hash": analysis["receipt_hash"] if analysis else None,
            "analysis_attempted": analysis_attempted,
            "study_graph_receipt_hash": study_graph["receipt_hash"]
            if study_graph
            else None,
            "study_graph_attempted": study_graph_attempted,
            "observed_leaf_count": len(source_rows),
            "candidate_leaf_count": sum(
                row["status"] == "candidate" for row in source_rows
            ),
            "workflow_execution_complete": not workflow_gaps,
            "workflow_gaps": workflow_gaps,
            "accepted_claim_count": 0,
            "markdown_sha256": hashlib.sha256(markdown).hexdigest(),
            "reported_total_cost_usd": total_cost,
            "cost_observation_complete": cost_complete,
            "final_acceptance_external": True,
            "internal_human_gate_required": False,
            "mode_qualified": False,
            "release_authorized": False,
            "external_delivery_authorized": False,
        }
    )
    return receipt, markdown


def _run_control_phase(
    *,
    output_root: Path,
    output: Path,
    run_id: str,
    frame: dict,
    domain: dict,
    content: dict,
    content_dir: Path,
    hermes: Path,
    extras: list[Path],
    query_count: int,
    budget: float,
    deadline: float,
) -> dict:
    """Bound the optional control phase to the enclosing run's remaining resources."""
    if query_count == 0:
        return {"status": "disabled", "partial_result_preserved": True}
    if (
        not content.get("scope_complete")
        or not content.get("model_semantic_review_complete")
        or budget < 0.02
        or deadline - time.monotonic() < 1
    ):
        return {
            "status": "deferred",
            "reason": "content_or_resources_incomplete",
            "partial_result_preserved": True,
        }
    content_paths = [
        p
        for p in content_dir.glob("content-run*.json")
        if load_json(p)[0].get("receipt_hash") == content["receipt_hash"]
    ]
    if not content_paths:
        raise ValueError("control_content_receipt_missing")
    write_exclusive_json(output / "control-frame.json", frame)
    write_exclusive_json(output / "control-domain.json", domain)
    command = [
        sys.executable,
        str(Path(__file__).with_name("run_beta_stage_two.py")),
        "--artifacts-root",
        str(output_root),
        "--content",
        str(content_paths[0]),
        "--frame",
        str(output / "control-frame.json"),
        "--decomposition",
        str(output / "control-domain.json"),
        "--output",
        str(output_root / f"{run_id}-controls"),
        "--hermes",
        str(hermes),
        "--control-queries",
        str(query_count),
        "--budget-usd",
        str(min(2.0, budget)),
        "--wall-seconds",
        str(min(7200, max(1, int(deadline - time.monotonic())))),
        "--public-query-ack",
    ]
    for extra in extras:
        command.extend(["--source-receipt", str(extra)])
    code, result = _planning_child(command, timeout=deadline - time.monotonic())
    if code:
        raise ValueError("control_phase_failed")
    return {"status": "completed", **result}


def _academic_documents(
    root: Path,
    run_id: str,
    screening: dict | None,
    fulltext: dict | None,
    fulltext_file: Path | None,
) -> list[dict]:
    documents = []
    if fulltext is not None and fulltext_file is not None:
        documents.append(
            {
                "document_id": "primary",
                "url": fulltext["record_id"],
                "title": fulltext["title"],
                "path": str(fulltext_file.parent / "paper.pdf"),
                "read_scope": "full_text",
                "provenance_receipt_hash": fulltext["receipt_hash"],
            }
        )
    if screening is None:
        return documents
    decisions = {d["record_id"]: d for d in screening["decisions"]}
    for record in screening["records"]:
        if (
            record["provider"] != "openalex"
            or decisions[record["record_id"]]["verdict"] == "exclude"
        ):
            continue
        capture, _ = load_json(
            root / f"{run_id}-{record['leaf_id']}-openalex/capture.json"
        )
        if (
            not verify_receipt_hash(capture)
            or capture["receipt_hash"] != record["capture_receipt_hash"]
        ):
            raise ValueError("academic_document_capture_unbound")
        work = next(w for w in capture["works"] if w["work_id"] == record["record_id"])
        location = work.get("open_access_location") or {}
        doc = {
            "document_id": "work-"
            + hashlib.sha256(record["record_id"].encode()).hexdigest()[:12],
            "url": work.get("doi") or record["record_id"],
            "title": work["title"],
            "provenance_receipt_hash": capture["receipt_hash"],
        }
        if location.get("is_oa_reported") and location.get("pdf_url"):
            documents.append(
                {
                    **doc,
                    "pdf_url": location["pdf_url"],
                    "read_scope": "full_text",
                    "oa_status_basis": "metadata_reported_not_independently_verified",
                    "fallback_abstract": work.get("abstract_text"),
                }
            )
        elif work.get("abstract_text"):
            documents.append(
                {**doc, "text": work["abstract_text"], "read_scope": "abstract_only"}
            )
    return documents


def _remaining_academic_calls(root: Path, run_id: str, maximum: int) -> int:
    sessions = {}
    for directory in root.glob(run_id + "*"):
        for path in directory.rglob("model-usage.json"):
            usage, _ = load_json(path)
            count = usage.get("api_calls")
            if type(count) is not int or count < 0:
                return 0
            sessions[usage.get("session_id") or str(path)] = count
    return max(0, maximum - sum(sessions.values()))


@runtime_guarded
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("ultra", "academic"), required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--planning-dir", type=Path)
    parser.add_argument("--domain-first", action="store_true")
    parser.add_argument("--decomposition", type=Path)
    parser.add_argument("--coverage-frame", type=Path)
    parser.add_argument("--adaptive-coverage-batches", type=int)
    parser.add_argument("--public-query-ack", action="store_true")
    parser.add_argument("--content-budget-usd", type=float, default=0.15)
    parser.add_argument("--academic-documents", type=Path)
    parser.add_argument("--academic-datasets", type=Path)
    parser.add_argument("--academic-appraisal-budget-usd", type=float, default=0.15)
    parser.add_argument("--control-queries", type=int, default=4)
    parser.add_argument("--control-budget-usd", type=float, default=0.10)
    parser.add_argument(
        "--content-source-receipt", type=Path, action="append", default=[]
    )
    args = parser.parse_args(argv)
    if not args.public_query_ack:
        print(
            json.dumps({"status": "error", "code": "public_query_ack_required"}),
            file=sys.stderr,
        )
        return 2
    plan: dict[str, Any] | None = None
    planning: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    portfolio: dict[str, Any] | None = None
    protocol: dict[str, Any] | None = None
    screening: dict[str, Any] | None = None
    screening_attempted = False
    challenge: dict[str, Any] | None = None
    challenge_attempted = False
    sensitivity: dict[str, Any] | None = None
    sensitivity_attempted = False
    fulltext: dict[str, Any] | None = None
    fulltext_attempted = False
    structure: dict[str, Any] | None = None
    structure_attempted = False
    analysis: dict[str, Any] | None = None
    analysis_attempted = False
    study_graph: dict[str, Any] | None = None
    study_graph_attempted = False
    decomposition: dict[str, Any] | None = None
    coverage_frame: dict[str, Any] | None = None
    coverage_progress: dict[str, Any] | None = None
    coverage_mapping: dict[str, Any] | None = None
    coverage_query_progress: dict[str, Any] | None = None
    coverage_query_observation: dict[str, Any] | None = None
    coverage_cumulative_progress: dict[str, Any] | None = None
    adaptive_batches: list[dict[str, Any]] = []
    adaptive_incomplete_batches: list[dict[str, Any]] = []
    adaptive_attempted = False
    adaptive_cost_usd: float | None = None
    domain_run_id: str | None = None
    coverage_run_id: str | None = None
    preflight_cost_usd: float | None = 0.0 if args.domain_first else None
    output: Path | None = None
    try:
        if (
            not math.isfinite(args.academic_appraisal_budget_usd)
            or not 0 <= args.academic_appraisal_budget_usd <= 10
            or (args.academic_documents is not None and args.mode != "academic")
        ):
            raise ValueError("academic_appraisal_options_invalid")
        if (
            args.control_queries not in (0, *range(2, 65))
            or not math.isfinite(args.control_budget_usd)
            or not 0 <= args.control_budget_usd <= 2
        ):
            raise ValueError("control_limits_invalid")
        if (
            not math.isfinite(args.content_budget_usd)
            or not 0 <= args.content_budget_usd <= 5
        ):
            raise ValueError("content_budget_invalid")
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
        ):
            raise ValueError("output_root_invalid")
        if args.domain_first and args.mode != "ultra":
            raise ValueError("domain_first_only_ultra")
        adaptive_limit = (
            args.adaptive_coverage_batches
            if args.adaptive_coverage_batches is not None
            else DEFAULT_ADAPTIVE_COVERAGE_BATCHES
            if args.domain_first
            else 0
        )
        if not 0 <= adaptive_limit <= 20 or (adaptive_limit and not args.domain_first):
            raise ValueError("adaptive_coverage_budget_invalid")
        if args.coverage_frame is not None and (
            not args.domain_first or args.decomposition is None
        ):
            raise ValueError("coverage_reuse_mode_invalid")
        if args.decomposition is not None:
            if not args.domain_first:
                raise ValueError("domain_reuse_mode_invalid")
            reused, _ = load_json(args.decomposition)
            if (
                type(reused) is not dict
                or not verify_receipt_hash(reused)
                or reused.get("contract") != "BetaDomainDecomposition"
                or reused.get("question") != args.question.strip()
                or reused.get("profile") != args.mode
                or args.decomposition
                != args.output_root
                / f"{reused['run_id']}-domain-planning/decomposition.json"
            ):
                raise ValueError("domain_reuse_not_bound")
            decomposition = reused
            domain_run_id = reused["run_id"]
            domain_run = _receipt(
                args.output_root / f"{domain_run_id}-domain-planning/planning-run.json",
                "BetaDomainPlanningRun",
                domain_run_id,
            )
            if domain_run.get("decomposition_receipt_hash") != reused["receipt_hash"]:
                raise ValueError("domain_reuse_not_bound")
            preflight_cost_usd = float(domain_run["reported_model_cost_usd"])
        elif args.domain_first and args.planning_dir is not None:
            raise ValueError("domain_reuse_required")
        elif args.domain_first and args.planning_dir is None:
            try:
                domain_code, domain_created = _planning_child(
                    [
                        sys.executable,
                        str(SCRIPTS / "plan_beta_domain.py"),
                        "--question",
                        args.question,
                        "--profile",
                        args.mode,
                        "--hermes",
                        str(args.hermes),
                        "--output-root",
                        str(args.output_root),
                        "--public-query-ack",
                    ],
                    timeout=125,
                )
                if domain_code == 2 and type(domain_created.get("run_id")) is str:
                    saved_id = domain_created["run_id"]
                    if re.fullmatch(
                        r"BETA-DOM-[0-9]{8}-[0-9]{6}-[A-F0-9]{8}", saved_id
                    ):
                        saved = args.output_root / f"{saved_id}-domain-planning"
                        if all(
                            (saved / name).is_file()
                            for name in (
                                "failure.json",
                                "model.raw.json",
                                "model-usage.json",
                                "model-trace.json",
                            )
                        ):
                            recovered_code, recovered = _child(
                                [
                                    sys.executable,
                                    str(SCRIPTS / "reconcile_beta_domain.py"),
                                    "--output",
                                    str(saved),
                                    "--question",
                                    args.question,
                                    "--profile",
                                    args.mode,
                                ],
                                timeout=30,
                            )
                            if (
                                recovered_code == 0
                                and recovered.get("run_id") == saved_id
                            ):
                                domain_code, domain_created = 0, recovered
                if domain_code == 0 and type(domain_created.get("run_id")) is str:
                    domain_run_id = domain_created["run_id"]
                    domain_dir = args.output_root / f"{domain_run_id}-domain-planning"
                    decomposition = _receipt(
                        domain_dir / "decomposition.json",
                        "BetaDomainDecomposition",
                        domain_run_id,
                    )
                    domain_run = _receipt(
                        domain_dir / "planning-run.json",
                        "BetaDomainPlanningRun",
                        domain_run_id,
                    )
                    preflight_cost_usd = float(domain_run["reported_model_cost_usd"])
            except (SearchRunError, OSError, ValueError):
                preflight_cost_usd = None
        if args.planning_dir is None:
            planning_command = [
                sys.executable,
                str(SCRIPTS / "plan_beta_from_question.py"),
                "--mode",
                args.mode,
                "--question",
                args.question,
                "--hermes",
                str(args.hermes),
                "--output-root",
                str(args.output_root),
                "--public-query-ack",
            ]
            if decomposition is not None and domain_run_id is not None:
                planning_command.extend(
                    (
                        "--decomposition",
                        str(
                            args.output_root
                            / f"{domain_run_id}-domain-planning/decomposition.json"
                        ),
                    )
                )
            plan_code, created = _planning_child(
                planning_command,
                timeout=75,
            )
            if plan_code == 2 and type(created.get("run_id")) is str:
                saved_id = created["run_id"]
                if re.fullmatch(r"BETA-AUTO-[0-9]{8}-[0-9]{6}-[A-F0-9]{8}", saved_id):
                    saved = args.output_root / f"{saved_id}-planning"
                    if all(
                        (saved / name).is_file()
                        for name in (
                            "failure.json",
                            "model.raw.json",
                            "model-usage.json",
                            "model-trace.json",
                        )
                    ):
                        recovery_command = [
                            sys.executable,
                            str(SCRIPTS / "reconcile_beta_plan.py"),
                            "--output",
                            str(saved),
                            "--question",
                            args.question,
                            "--mode",
                            args.mode,
                        ]
                        if decomposition is not None and domain_run_id is not None:
                            recovery_command.extend(
                                (
                                    "--decomposition",
                                    str(
                                        args.output_root
                                        / f"{domain_run_id}-domain-planning/decomposition.json"
                                    ),
                                )
                            )
                        recovered_code, recovered = _child(recovery_command, timeout=30)
                        if recovered_code == 0 and recovered.get("run_id") == saved_id:
                            plan_code = 0
                            created = {
                                "status": "ready_to_execute",
                                "run_id": saved_id,
                                "output": str(saved),
                            }
            if (
                plan_code != 0
                or created.get("status") != "ready_to_execute"
                or type(created.get("run_id")) is not str
            ):
                raise ValueError("profile_planning_blocked")
            run_id = created["run_id"]
            plan_dir = args.output_root / f"{run_id}-planning"
            if created.get("output") != str(plan_dir):
                raise ValueError("profile_planning_path_invalid")
        else:
            plan_dir = args.planning_dir
            if (
                not plan_dir.is_absolute()
                or plan_dir.is_symlink()
                or not plan_dir.is_dir()
                or plan_dir.parent != args.output_root
                or not plan_dir.name.endswith("-planning")
            ):
                raise ValueError("profile_planning_path_invalid")
            run_id = plan_dir.name.removesuffix("-planning")
            if not re.fullmatch(r"^[A-Z][A-Z0-9-]{2,63}$", run_id):
                raise ValueError("profile_planning_path_invalid")
        plan = verify_beta_mode_plan(
            _receipt(plan_dir / "plan.json", "BetaModeExecutionPlan", run_id)
        )
        planning = _receipt(
            plan_dir / "planning-run.json", "BetaAutonomousPlanningRun", run_id
        )
        if (
            plan["mode"] != args.mode
            or plan["question"] != args.question.strip()
            or plan["status"] != "ready_to_execute"
        ):
            raise ValueError("profile_plan_not_executable")
        if (
            decomposition is not None
            and planning.get("decomposition_receipt_hash")
            != decomposition["receipt_hash"]
        ):
            raise ValueError("profile_planning_decomposition_not_bound")
        if args.coverage_frame is not None and decomposition is not None:
            reused_frame, _ = load_json(args.coverage_frame)
            if (
                type(reused_frame) is not dict
                or not verify_receipt_hash(reused_frame)
                or reused_frame.get("contract") != "BetaCoverageFrame"
                or reused_frame.get("decomposition_receipt_hash")
                != decomposition["receipt_hash"]
                or reused_frame.get("question") != args.question.strip()
                or reused_frame.get("profile") != args.mode
                or args.coverage_frame
                != args.output_root
                / f"{reused_frame['run_id']}-coverage-planning/frame.json"
            ):
                raise ValueError("coverage_reuse_not_bound")
            coverage_frame = reused_frame
            coverage_run_id = reused_frame["run_id"]
            coverage_run = _receipt(
                args.output_root
                / f"{coverage_run_id}-coverage-planning/planning-run.json",
                "BetaCoveragePlanningRun",
                coverage_run_id,
            )
            if coverage_run.get("frame_receipt_hash") != reused_frame["receipt_hash"]:
                raise ValueError("coverage_reuse_not_bound")
            coverage_progress = assess_beta_coverage(
                coverage_frame, [], budget_exhausted=False
            )
            progress_path = (
                args.output_root / f"{coverage_run_id}-coverage-initial-progress.json"
            )
            if progress_path.exists():
                recorded, _ = load_json(progress_path)
                if recorded != coverage_progress:
                    raise ValueError("coverage_reuse_progress_changed")
            else:
                write_exclusive_json(progress_path, coverage_progress)
            if preflight_cost_usd is not None:
                preflight_cost_usd = round(
                    preflight_cost_usd + float(coverage_run["reported_model_cost_usd"]),
                    8,
                )
        elif args.domain_first and decomposition is not None:
            try:
                coverage_code, coverage_created = _planning_child(
                    [
                        sys.executable,
                        str(SCRIPTS / "plan_beta_coverage.py"),
                        "--question",
                        args.question,
                        "--profile",
                        args.mode,
                        "--decomposition",
                        str(
                            args.output_root
                            / f"{domain_run_id}-domain-planning/decomposition.json"
                        ),
                        "--hermes",
                        str(args.hermes),
                        "--output-root",
                        str(args.output_root),
                        "--public-query-ack",
                    ],
                    timeout=360,
                )
                if coverage_code == 2 and type(coverage_created.get("run_id")) is str:
                    saved_id = coverage_created["run_id"]
                    if re.fullmatch(
                        r"BETA-COV-[0-9]{8}-[0-9]{6}-[A-F0-9]{8}", saved_id
                    ):
                        saved = args.output_root / f"{saved_id}-coverage-planning"
                        if all(
                            (saved / name).is_file()
                            for name in (
                                "failure.json",
                                "model.raw.json",
                                "model-usage.json",
                                "model-trace.json",
                            )
                        ):
                            recovered_code, recovered = _child(
                                [
                                    sys.executable,
                                    str(SCRIPTS / "reconcile_beta_coverage.py"),
                                    "--output",
                                    str(saved),
                                    "--question",
                                    args.question,
                                    "--profile",
                                    args.mode,
                                    "--decomposition",
                                    str(
                                        args.output_root
                                        / f"{domain_run_id}-domain-planning/decomposition.json"
                                    ),
                                ],
                                timeout=30,
                            )
                            if (
                                recovered_code == 0
                                and recovered.get("run_id") == saved_id
                            ):
                                coverage_code, coverage_created = 0, recovered
                if coverage_code == 0 and type(coverage_created.get("run_id")) is str:
                    coverage_run_id = coverage_created["run_id"]
                    coverage_dir = (
                        args.output_root / f"{coverage_run_id}-coverage-planning"
                    )
                    frame_value, _ = load_json(coverage_dir / "frame.json")
                    if type(frame_value) is not dict or not verify_receipt_hash(
                        frame_value
                    ):
                        raise ValueError("profile_coverage_frame_invalid")
                    coverage_frame = frame_value
                    coverage_run = _receipt(
                        coverage_dir / "planning-run.json",
                        "BetaCoveragePlanningRun",
                        coverage_run_id,
                    )
                    coverage_progress = assess_beta_coverage(
                        coverage_frame, [], budget_exhausted=False
                    )
                    write_exclusive_json(
                        args.output_root
                        / f"{coverage_run_id}-coverage-initial-progress.json",
                        coverage_progress,
                    )
                    if preflight_cost_usd is not None:
                        preflight_cost_usd = round(
                            preflight_cost_usd
                            + float(coverage_run["reported_model_cost_usd"]),
                            8,
                        )
            except (SearchRunError, OSError, ValueError):
                preflight_cost_usd = None
        if args.domain_first and coverage_frame is not None:
            try:
                mapping_dir = args.output_root / f"{run_id}-coverage-map-plan"
                frame_path = (
                    args.output_root / f"{coverage_run_id}-coverage-planning/frame.json"
                )
                try:
                    mapping_code, _ = _child(
                        [
                            sys.executable,
                            str(SCRIPTS / "map_beta_coverage_plan.py"),
                            "--frame",
                            str(frame_path),
                            "--plan",
                            str(plan_dir / "plan.json"),
                            "--hermes",
                            str(args.hermes),
                            "--output-root",
                            str(args.output_root),
                        ],
                        timeout=75,
                    )
                except SearchRunError:
                    mapping_code = 2
                    if all(
                        (mapping_dir / name).is_file()
                        for name in (
                            "failure.json",
                            "model.raw.json",
                            "model-usage.json",
                            "model-trace.json",
                        )
                    ):
                        mapping_code, _ = _child(
                            [
                                sys.executable,
                                str(SCRIPTS / "reconcile_beta_coverage_mapping.py"),
                                "--frame",
                                str(frame_path),
                                "--plan",
                                str(plan_dir / "plan.json"),
                                "--output",
                                str(mapping_dir),
                            ],
                            timeout=30,
                        )
                if mapping_code == 0:
                    coverage_mapping = _receipt(
                        mapping_dir / "mapping.json",
                        "BetaCoverageQueryAtomMapping",
                        run_id,
                    )
                    mapping_run = _receipt(
                        mapping_dir / "run.json",
                        "BetaCoverageQueryMappingRun",
                        run_id,
                    )
                    if (
                        mapping_run.get("mapping_receipt_hash")
                        != coverage_mapping["receipt_hash"]
                    ):
                        raise ValueError("profile_mapping_run_not_bound")
                    if preflight_cost_usd is not None:
                        preflight_cost_usd = round(
                            preflight_cost_usd
                            + float(mapping_run["reported_model_cost_usd"]),
                            8,
                        )
            except (SearchRunError, OSError, ValueError):
                preflight_cost_usd = None
        if args.mode == "academic":
            protocol_value, _ = load_json(plan_dir / "academic-protocol.json")
            if type(protocol_value) is not dict:
                raise ValueError("profile_protocol_invalid")
            protocol = protocol_value
        output = args.output_root / f"{run_id}-{args.mode}-overall"
        new_private_directory(output)
        write_exclusive_json(
            output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "run_id": run_id,
                "mode": args.mode,
                "plan_receipt_hash": plan["receipt_hash"],
                "retry_allowed": False,
            },
        )
        deadline = time.monotonic() + float(plan["limits"]["wall_seconds"])
        try:
            _child(
                [
                    sys.executable,
                    str(SCRIPTS / "execute_beta_sources.py"),
                    "--plan",
                    str(plan_dir / "plan.json"),
                    "--output-root",
                    str(args.output_root),
                    "--public-query-ack",
                ],
                timeout=deadline - time.monotonic(),
            )
        except SearchRunError:
            pass
        execution_file = args.output_root / f"{run_id}-execution/execution.json"
        portfolio_file = args.output_root / f"{run_id}-execution/portfolio.json"
        if execution_file.is_file():
            execution = _receipt(execution_file, "BetaAutomaticSourceExecution", run_id)
        if execution is not None and portfolio_file.is_file():
            portfolio = _receipt(portfolio_file, "BetaSourcePortfolio", run_id)
        if (
            args.domain_first
            and coverage_frame is not None
            and coverage_mapping is not None
            and portfolio is not None
        ):
            try:
                observed_code, _ = _child(
                    [
                        sys.executable,
                        str(SCRIPTS / "observe_beta_plan_coverage.py"),
                        "--frame",
                        str(
                            args.output_root
                            / f"{coverage_run_id}-coverage-planning/frame.json"
                        ),
                        "--plan",
                        str(plan_dir / "plan.json"),
                        "--mapping",
                        str(
                            args.output_root
                            / f"{run_id}-coverage-map-plan/mapping.json"
                        ),
                        "--portfolio",
                        str(portfolio_file),
                        "--output-root",
                        str(args.output_root),
                    ],
                    timeout=30,
                )
                if observed_code == 0:
                    observed_dir = args.output_root / f"{run_id}-coverage-observed"
                    coverage_query_progress = _receipt(
                        observed_dir / "progress.json",
                        "BetaCoverageProgressAssessment",
                        coverage_run_id,
                    )
                    coverage_query_observation = _receipt(
                        observed_dir / "observation.json",
                        "BetaCoverageMappedQueryObservation",
                        run_id,
                    )
            except (SearchRunError, OSError, ValueError):
                pass
        if (
            args.mode == "academic"
            and execution is not None
            and execution.get("status") == "partial_analysis_required"
            and portfolio is not None
        ):
            screening_attempted = True
            try:
                screen_code, _ = _child(
                    [
                        sys.executable,
                        str(SCRIPTS / "screen_beta_academic.py"),
                        "--plan",
                        str(plan_dir / "plan.json"),
                        "--protocol",
                        str(plan_dir / "academic-protocol.json"),
                        "--execution",
                        str(execution_file),
                        "--portfolio",
                        str(portfolio_file),
                        "--hermes",
                        str(args.hermes),
                        "--output-root",
                        str(args.output_root),
                    ],
                    timeout=deadline - time.monotonic(),
                )
                if screen_code == 0:
                    screening = _receipt(
                        args.output_root / f"{run_id}-academic-screen/screening.json",
                        "BetaAcademicPreliminaryScreen",
                        run_id,
                    )
            except SearchRunError:
                pass
        if (
            args.mode == "ultra"
            and execution is not None
            and execution.get("status") == "partial_analysis_required"
            and portfolio is not None
        ):
            challenge_attempted = True
            try:
                challenge_code, _ = _child(
                    [
                        sys.executable,
                        str(SCRIPTS / "challenge_beta_ultra.py"),
                        "--plan",
                        str(plan_dir / "plan.json"),
                        "--execution",
                        str(execution_file),
                        "--portfolio",
                        str(portfolio_file),
                        "--hermes",
                        str(args.hermes),
                        "--output-root",
                        str(args.output_root),
                    ],
                    timeout=deadline - time.monotonic(),
                )
                if challenge_code == 0:
                    challenge = _receipt(
                        args.output_root / f"{run_id}-ultra-challenge/challenge.json",
                        "BetaUltraRivalChallenge",
                        run_id,
                    )
            except SearchRunError:
                pass
        if (
            args.mode == "ultra"
            and challenge is not None
            and execution is not None
            and portfolio is not None
        ):
            sensitivity_attempted = True
            try:
                sensitivity_code, _ = _child(
                    [
                        sys.executable,
                        str(SCRIPTS / "assess_beta_ultra_sensitivity.py"),
                        "--plan",
                        str(plan_dir / "plan.json"),
                        "--execution",
                        str(execution_file),
                        "--portfolio",
                        str(portfolio_file),
                        "--challenge",
                        str(
                            args.output_root
                            / f"{run_id}-ultra-challenge/challenge.json"
                        ),
                        "--output-root",
                        str(args.output_root),
                    ],
                    timeout=deadline - time.monotonic(),
                )
                if sensitivity_code == 0:
                    sensitivity = _receipt(
                        args.output_root / f"{run_id}.ultra-sensitivity.json",
                        "BetaUltraSensitivity",
                        run_id,
                    )
            except SearchRunError:
                pass
        if args.mode == "academic" and screening is not None:
            selected = [
                row
                for row in screening["decisions"]
                if row["verdict"] == "include_candidate"
            ]
            records = {row["record_id"]: row for row in screening["records"]}
            arxiv_selected = [
                row
                for row in selected
                if records[row["record_id"]]["provider"] == "arxiv"
            ]
            if arxiv_selected:
                fulltext_attempted = True
                chosen = arxiv_selected[0]["record_id"]
                leaf_id = records[chosen]["leaf_id"]
                try:
                    fulltext_code, _ = _child(
                        [
                            sys.executable,
                            str(SCRIPTS / "acquire_arxiv_fulltext.py"),
                            "--plan",
                            str(plan_dir / "plan.json"),
                            "--arxiv-capture",
                            str(
                                args.output_root
                                / f"{run_id}-{leaf_id}-arxiv/capture.json"
                            ),
                            "--screening",
                            str(
                                args.output_root
                                / f"{run_id}-academic-screen/screening.json"
                            ),
                            "--record-id",
                            chosen,
                            "--output-root",
                            str(args.output_root),
                        ],
                        timeout=deadline - time.monotonic(),
                    )
                    if fulltext_code == 0:
                        stem = chosen.rsplit("/", 1)[-1]
                        fulltext_file = (
                            args.output_root
                            / f"{run_id}-{leaf_id}-{stem}-fulltext/capture.json"
                        )
                        fulltext = _receipt(
                            fulltext_file,
                            "BetaArxivFullTextRead",
                            run_id,
                        )
                        pdf = read_private_bytes(
                            fulltext_file.parent / "paper.pdf", maximum=50_000_000
                        )
                        parsed = read_private_bytes(
                            fulltext_file.parent / "paper.md", maximum=25_000_000
                        )
                        if (
                            hashlib.sha256(pdf).hexdigest() != fulltext["pdf_sha256"]
                            or hashlib.sha256(parsed).hexdigest()
                            != fulltext["text_sha256"]
                            or len(pdf) != fulltext["pdf_bytes"]
                        ):
                            raise ValueError("profile_fulltext_bytes_not_bound")
                except SearchRunError:
                    pass
        if args.mode == "academic" and fulltext is not None:
            structure_attempted = True
            try:
                structure_code, _ = _child(
                    [
                        sys.executable,
                        str(SCRIPTS / "verify_beta_pdf_structure.py"),
                        "--plan",
                        str(plan_dir / "plan.json"),
                        "--fulltext",
                        str(fulltext_file),
                        "--output-root",
                        str(args.output_root),
                    ],
                    timeout=deadline - time.monotonic(),
                )
                if structure_code == 0:
                    structure_dir = (
                        args.output_root / f"{run_id}-academic-pdf-structure"
                    )
                    structure = _receipt(
                        structure_dir / "structure.json",
                        "BetaAcademicPdfStructure",
                        run_id,
                    )
                    _verify_structure_files(structure_dir, structure)
            except (SearchRunError, OSError, ValueError):
                structure = None
        if args.mode == "academic" and fulltext is not None:
            analysis_attempted = True
            try:
                analysis_code, _ = _child(
                    [
                        sys.executable,
                        str(SCRIPTS / "analyze_beta_fulltext.py"),
                        "--plan",
                        str(plan_dir / "plan.json"),
                        "--fulltext",
                        str(fulltext_file),
                        "--hermes",
                        str(args.hermes),
                        "--output-root",
                        str(args.output_root),
                    ],
                    timeout=deadline - time.monotonic(),
                )
                if analysis_code == 0:
                    analysis = _receipt(
                        args.output_root
                        / f"{run_id}-academic-fulltext-analysis/analysis.json",
                        "BetaAcademicFullTextAnalysis",
                        run_id,
                    )
            except SearchRunError:
                pass
        if args.mode == "academic" and screening is not None:
            study_graph_attempted = True
            graph_command = [
                sys.executable,
                str(SCRIPTS / "assess_beta_academic_study_graph.py"),
                "--plan",
                str(plan_dir / "plan.json"),
                "--execution",
                str(execution_file),
                "--portfolio",
                str(portfolio_file),
                "--screening",
                str(args.output_root / f"{run_id}-academic-screen/screening.json"),
                "--output-root",
                str(args.output_root),
            ]
            if fulltext is not None:
                graph_command.extend(("--fulltext", str(fulltext_file)))
            if structure is not None:
                graph_command.extend(
                    ("--structure", str(structure_dir / "structure.json"))
                )
            if analysis is not None:
                graph_command.extend(
                    (
                        "--analysis",
                        str(
                            args.output_root
                            / f"{run_id}-academic-fulltext-analysis/analysis.json"
                        ),
                    )
                )
            try:
                graph_code, _ = _child(
                    graph_command, timeout=deadline - time.monotonic()
                )
                if graph_code == 0:
                    study_graph = _receipt(
                        args.output_root / f"{run_id}.academic-study-graph.json",
                        "BetaAcademicStudyGraph",
                        run_id,
                    )
            except SearchRunError:
                pass
        if (
            args.domain_first
            and adaptive_limit
            and coverage_frame is not None
            and decomposition is not None
            and coverage_query_observation is not None
        ):
            initial_observations, _ = load_json(
                args.output_root / f"{run_id}-coverage-observed/observations.json"
            )
            if type(initial_observations) is not list:
                raise ValueError("coverage_initial_observations_invalid")
            adaptive_observations: list[dict[str, Any]] = []
            atom_attempts: dict[str, int] = {}
            for batch_number in range(1, adaptive_limit + 1):
                current_progress = assess_beta_coverage(
                    coverage_frame,
                    [*initial_observations, *adaptive_observations],
                    budget_exhausted=False,
                )
                atom = _next_coverage_atom(
                    coverage_frame, current_progress, atom_attempts
                )
                if atom is None:
                    break
                atom_attempts[atom["atom_id"]] = (
                    atom_attempts.get(atom["atom_id"], 0) + 1
                )
                adaptive_attempted = True
                try:
                    adaptive_id = f"{run_id}-C{batch_number:02d}"
                    if os.environ.get(TURN_TRACE_ENV) is not None:
                        register_child_run(run_id, adaptive_id)
                        for screen_number in range(1, 4):
                            register_child_run(
                                run_id, f"{adaptive_id}-S{screen_number:02d}"
                            )
                    adaptive_command = [
                        sys.executable,
                        str(SCRIPTS / "advance_beta_coverage.py"),
                        "--frame",
                        str(
                            args.output_root
                            / f"{coverage_run_id}-coverage-planning/frame.json"
                        ),
                        "--decomposition",
                        str(
                            args.output_root
                            / f"{domain_run_id}-domain-planning/decomposition.json"
                        ),
                        "--atom-id",
                        atom["atom_id"],
                        "--batch",
                        str(batch_number),
                        "--parent-run-id",
                        run_id,
                        "--hermes",
                        str(args.hermes),
                        "--output-root",
                        str(args.output_root),
                        "--public-query-ack",
                    ]
                    try:
                        adaptive_code, _ = _child(
                            adaptive_command,
                            timeout=min(360, deadline - time.monotonic()),
                        )
                    except SearchRunError:
                        saved = (
                            args.output_root
                            / f"{run_id}-C{batch_number:02d}-domain-web-plan"
                        )
                        if (
                            not all(
                                (saved / name).is_file()
                                for name in (
                                    "failure.json",
                                    "model.raw.json",
                                    "model-usage.json",
                                    "model-trace.json",
                                )
                            )
                            or (saved / "plan.json").exists()
                        ):
                            raise
                        adaptive_code, _ = _child(
                            [*adaptive_command, "--resume-saved"],
                            timeout=min(360, deadline - time.monotonic()),
                        )
                    if adaptive_code != 0:
                        break
                    observed_dir = (
                        args.output_root / f"{adaptive_id}-domain-web-observed"
                    )
                    batch_receipt = _receipt(
                        observed_dir / "run.json",
                        "BetaAdaptiveCoverageBatchRun",
                        adaptive_id,
                    )
                    if (
                        batch_receipt["atom_id"] != atom["atom_id"]
                        or batch_receipt["frame_receipt_hash"]
                        != coverage_frame["receipt_hash"]
                    ):
                        raise ValueError("adaptive_coverage_batch_not_bound")
                    adaptive_observations_value, _ = load_json(
                        observed_dir / "observations.json"
                    )
                    _accumulate_adaptive_observations(
                        adaptive_observations, adaptive_observations_value
                    )
                    source_cost = batch_receipt["reported_source_cost_usd"]
                    model_cost = batch_receipt["reported_model_cost_usd"]
                    if (
                        type(source_cost) not in (int, float)
                        or type(model_cost) not in (int, float)
                        or source_cost < 0
                        or model_cost < 0
                    ):
                        raise ValueError("adaptive_coverage_cost_unknown")
                    adaptive_cost_usd = round(
                        (adaptive_cost_usd or 0) + source_cost + model_cost, 8
                    )
                    adaptive_batches.append(batch_receipt)
                except (
                    SearchRunError,
                    OSError,
                    ValueError,
                    KeyError,
                    TypeError,
                ) as error:
                    adaptive_id = f"{run_id}-C{batch_number:02d}"
                    recovered_cost = _recover_incomplete_adaptive_cost(
                        args.output_root, adaptive_id
                    )
                    reason = str(error)
                    adaptive_incomplete_batches.append(
                        {
                            "run_id": adaptive_id,
                            "batch_number": batch_number,
                            "atom_id": atom["atom_id"],
                            "reason_code": reason
                            if _CODE.fullmatch(reason)
                            else "adaptive_batch_incomplete",
                            "observed_cost_usd": recovered_cost,
                            "observations_promoted": False,
                        }
                    )
                    adaptive_cost_usd = (
                        round((adaptive_cost_usd or 0) + recovered_cost, 8)
                        if recovered_cost is not None
                        else None
                    )
                    break
            if adaptive_batches:
                initial_observations, _ = load_json(
                    args.output_root / f"{run_id}-coverage-observed/observations.json"
                )
                if type(initial_observations) is not list:
                    raise ValueError("coverage_initial_observations_invalid")
                coverage_cumulative_progress = assess_beta_coverage(
                    coverage_frame,
                    [*initial_observations, *adaptive_observations],
                    budget_exhausted=False,
                )
                write_exclusive_json(
                    args.output_root / f"{run_id}-coverage-cumulative-progress.json",
                    coverage_cumulative_progress,
                )
        result, markdown = assemble_source_dossier(
            plan=plan,
            planning=planning,
            execution=execution,
            portfolio=portfolio,
            protocol=protocol,
            screening=screening,
            screening_attempted=screening_attempted,
            challenge=challenge,
            challenge_attempted=challenge_attempted,
            sensitivity=sensitivity,
            sensitivity_attempted=sensitivity_attempted,
            fulltext=fulltext,
            fulltext_attempted=fulltext_attempted,
            structure=structure,
            structure_attempted=structure_attempted,
            analysis=analysis,
            analysis_attempted=analysis_attempted,
            study_graph=study_graph,
            study_graph_attempted=study_graph_attempted,
            domain_first_requested=args.domain_first,
            decomposition=decomposition,
            coverage_frame=coverage_frame,
            coverage_progress=coverage_progress,
            coverage_mapping=coverage_mapping,
            coverage_query_progress=coverage_query_progress,
            coverage_query_observation=coverage_query_observation,
            coverage_cumulative_progress=coverage_cumulative_progress,
            adaptive_batches=adaptive_batches if args.domain_first else None,
            adaptive_incomplete_batches=adaptive_incomplete_batches
            if args.domain_first
            else None,
            adaptive_attempted=adaptive_attempted,
            adaptive_cost_usd=adaptive_cost_usd,
            preflight_cost_usd=preflight_cost_usd,
            domain_run_id=domain_run_id,
            coverage_run_id=coverage_run_id,
        )
        write_exclusive_bytes(output / "result.md", markdown)
        write_exclusive_json(output / "outcome.json", result)
        content = None
        controls = {"status": "not_applicable"}
        content_result_path = output / "result.md"
        academic_appraisal = {"status": "not_applicable"}
        if args.mode == "academic":
            try:
                try:
                    from .appraise_beta_papers import run_appraisals
                except ImportError:
                    from appraise_beta_papers import run_appraisals
                if args.academic_documents:
                    supplied, _ = load_json(args.academic_documents)
                    documents = supplied["documents"]
                else:
                    documents = _academic_documents(
                        args.output_root,
                        run_id,
                        screening,
                        fulltext,
                        fulltext_file if fulltext is not None else None,
                    )
                prior_cost = result.get("reported_total_cost_usd")
                available = (
                    min(
                        args.academic_appraisal_budget_usd,
                        max(0.0, plan["limits"]["max_estimated_cost_usd"] - prior_cost),
                    )
                    if type(prior_cost) in (int, float)
                    else 0
                )
                if documents and available > 0 and time.monotonic() < deadline:
                    remaining_calls = _remaining_academic_calls(
                        args.output_root, run_id, plan["limits"]["model_calls"]
                    )
                    appraised = run_appraisals(
                        documents=documents,
                        question=args.question,
                        output=args.output_root / f"{run_id}-paper-appraisal",
                        hermes=args.hermes,
                        budget=available,
                        deadline=deadline,
                        batch_chars=80000,
                        max_model_calls=remaining_calls,
                        datasets=load_json(args.academic_datasets)[0]["datasets"]
                        if args.academic_datasets
                        else [],
                    )
                    academic_appraisal = {
                        "status": "completed"
                        if appraised["receipt"]["all_text_batches_appraised"]
                        else "partial",
                        "receipt_hash": appraised["receipt"]["receipt_hash"],
                        "receipt_file": appraised["receipt_file"],
                        "report": appraised["report"],
                        "model_cost_usd": appraised["receipt"]["model_cost_usd"],
                        "model_calls_observed": appraised["receipt"][
                            "model_calls_observed"
                        ],
                    }
                    content_result_path = Path(appraised["report"])
                else:
                    academic_appraisal = {
                        "status": "deferred",
                        "reason": "no_documents_or_remaining_resources",
                    }
            except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
                academic_appraisal = {
                    "status": "partial",
                    "reason": str(error)[:160],
                    "source_result_preserved": True,
                }
            write_exclusive_json(
                output / "academic-appraisal-composition.json",
                with_receipt_hash(
                    {
                        "contract": "AcademicAppraisalComposition",
                        "source_outcome_receipt_hash": result["receipt_hash"],
                        "appraisal": academic_appraisal,
                        "release_authorized": False,
                    }
                ),
            )
        if args.domain_first and coverage_frame is not None:
            try:
                try:
                    from .complete_beta_content import complete_content
                except ImportError:
                    from complete_beta_content import complete_content
                previous_cost = result.get("reported_total_cost_usd")
                remaining = (
                    max(0.0, plan["limits"]["max_estimated_cost_usd"] - previous_cost)
                    if type(previous_cost) in (int, float)
                    and math.isfinite(previous_cost)
                    else 0.0
                )
                content_dir = args.output_root / f"{run_id}-content"
                content = complete_content(
                    root=args.output_root,
                    run_id=run_id,
                    frame=coverage_frame,
                    hermes=args.hermes,
                    output=content_dir,
                    extras=args.content_source_receipt,
                    budget=min(args.content_budget_usd, remaining),
                    deadline=deadline,
                )
                content_result_path = content_dir / "result.md"
                write_exclusive_json(
                    output / "content-composition.json",
                    with_receipt_hash(
                        {
                            "contract": "BetaSourceContentComposition",
                            "run_id": run_id,
                            "source_outcome_receipt_hash": result["receipt_hash"],
                            "content_receipt_hash": content["receipt_hash"],
                            "reported_total_cost_usd": previous_cost
                            + content["reported_model_cost_usd"]
                            if type(previous_cost) in (int, float)
                            and content["reported_model_cost_usd"] is not None
                            else None,
                            "content_scope_complete": content["scope_complete"],
                            "release_authorized": False,
                        }
                    ),
                )
                if decomposition is not None:
                    content_cost = content["reported_model_cost_usd"]
                    try:
                        controls = _run_control_phase(
                            output_root=args.output_root,
                            output=output,
                            run_id=run_id,
                            frame=coverage_frame,
                            domain=decomposition,
                            content=content,
                            content_dir=content_dir,
                            hermes=args.hermes,
                            extras=args.content_source_receipt,
                            query_count=args.control_queries,
                            budget=min(
                                args.control_budget_usd,
                                max(0.0, remaining - content_cost),
                            )
                            if type(content_cost) in (int, float)
                            else 0.0,
                            deadline=deadline,
                        )
                        if controls.get("refined_report"):
                            content_result_path = Path(controls["refined_report"])
                    except (OSError, ValueError, SearchRunError) as error:
                        controls = {
                            "status": "incomplete",
                            "reason": str(error)[:200],
                            "partial_result_preserved": True,
                        }
                    write_exclusive_json(
                        output / "control-composition.json",
                        with_receipt_hash(
                            {
                                "contract": "BetaControlComposition",
                                "run_id": run_id,
                                "content_receipt_hash": content["receipt_hash"],
                                "controls": controls,
                                "reported_total_cost_usd": previous_cost
                                + content_cost
                                + controls["cost"]
                                if all(
                                    type(v) in (int, float)
                                    for v in (
                                        previous_cost,
                                        content_cost,
                                        controls.get("cost"),
                                    )
                                )
                                else None,
                                "release_authorized": False,
                            }
                        ),
                    )
            except (OSError, ValueError, KeyError, TypeError) as error:
                write_exclusive_json(
                    output / "content-failure.json",
                    {
                        "reason": str(error)[:200],
                        "source_result_preserved": True,
                        "retry_allowed": False,
                    },
                )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "mode": args.mode,
                    "run_id": run_id,
                    "result": str(content_result_path),
                    "content_scope_complete": content["scope_complete"]
                    if content
                    else False,
                    "controls": controls,
                    "academic_appraisal": academic_appraisal,
                    "content_answer_count": content["addressed_atom_count"]
                    if content
                    else 0,
                    "workflow_execution_complete": result[
                        "workflow_execution_complete"
                    ],
                    "workflow_gaps": result["workflow_gaps"],
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
            code = "profile_run_failed"
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
