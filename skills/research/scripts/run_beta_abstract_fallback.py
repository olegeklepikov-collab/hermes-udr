"""Return a graded Deep observation when only a retained abstract is readable."""

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
    from .file_io import (
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from .model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model
    from .screen_beta_academic import _records
except ImportError:
    from file_io import (
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model
    from screen_beta_academic import _records

from hermes_research_report.beta_model import (
    build_beta_model_prompt,
    validate_beta_model_candidate,
)
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.beta_semantic import (
    build_semantic_prompt,
    validate_semantic_verification,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError

_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


def _receipt(path: Path, contract: str, plan: dict) -> dict:
    value, _ = load_json(path)
    if (
        type(value) is not dict
        or not verify_receipt_hash(value)
        or value.get("contract") != contract
        or value.get("run_id") != plan["run_id"]
        or value.get("plan_receipt_hash") != plan["receipt_hash"]
        or value.get("release_authorized") is not False
    ):
        raise ValueError("abstract_fallback_receipt_not_bound")
    return value


def _select_record(plan: dict, records: list[dict]) -> dict:
    usable = [row for row in records if len(row["abstract"]) >= 40]
    if not usable:
        raise ValueError("abstract_fallback_no_text")
    terms = {
        token.casefold() for token in re.findall(r"[A-Za-z]{4,}", plan["question"])
    } - {
        "which",
        "what",
        "where",
        "when",
        "from",
        "with",
        "form",
        "article",
        "research",
    }
    leaves = {leaf["leaf_id"]: leaf for leaf in plan["leaves"]}

    def score(row: dict) -> tuple[int, int, bool, int]:
        text = (row["title"] + " " + row["abstract"]).casefold()
        groups = leaves[row["leaf_id"]]["concept_groups"]
        matched_groups = sum(
            any(term.casefold() in text for term in group) for group in groups
        )
        return (
            matched_groups,
            sum(term in text for term in terms),
            row["provider"] == "openalex",
            -records.index(row),
        )

    return max(usable, key=score)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    output: Path | None = None
    try:
        plan_value, _ = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        if (
            plan["mode"] != "deep"
            or plan["schema_version"] != 2
            or plan["status"] != "ready_to_execute"
        ):
            raise ValueError("abstract_fallback_plan_invalid")
        execution = _receipt(args.execution, "BetaAutomaticSourceExecution", plan)
        portfolio = _receipt(args.portfolio, "BetaSourcePortfolio", plan)
        if (
            execution.get("portfolio_receipt_hash") != portfolio["receipt_hash"]
            or execution.get("status") != "partial_analysis_required"
        ):
            raise ValueError("abstract_fallback_sources_invalid")
        records = _records(plan, portfolio, args.output_root)
        row = _select_record(plan, records)
        source_text = row["abstract"]
        source_id = (
            "SRC-"
            + hashlib.sha256((row["record_id"] + "\0" + source_text).encode())
            .hexdigest()[:16]
            .upper()
        )
        title = "Аннотация; полный текст не прочитан: " + row["title"]
        used_model_calls = len(execution.get("article_screens", []))
        if used_model_calls >= plan["limits"]["model_calls"]:
            raise ValueError("abstract_fallback_model_budget_exhausted")
        prompt = build_beta_model_prompt(
            plan, source_id=source_id, title=title, text=source_text
        )
        draft_dir = args.output_root / f"{plan['run_id']}-abstract-draft"
        raw, usage, trace = run_tool_free_model(
            plan=plan,
            prompt=prompt,
            hermes=args.hermes,
            output=draft_dir,
            attempt_binding={
                "execution_receipt_hash": execution["receipt_hash"],
                "portfolio_receipt_hash": portfolio["receipt_hash"],
                "source_capture_receipt_hash": row["capture_receipt_hash"],
                "source_ref": row["record_id"],
                "source_scope": "abstract_only",
            },
        )
        candidate = validate_beta_model_candidate(
            raw,
            plan=plan,
            source_id=source_id,
            title=title,
            source_text=source_text,
            prompt=prompt,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
        )
        write_exclusive_json(draft_dir / "candidate.json", candidate)
        semantic = None
        if (
            candidate["status"] == "verification_required"
            and used_model_calls + 2 <= plan["limits"]["model_calls"]
        ):
            check_prompt = build_semantic_prompt(
                plan, candidate, source_text=source_text, source_scope="excerpt"
            )
            check_dir = args.output_root / f"{plan['run_id']}-abstract-verify"
            check_raw, check_usage, check_trace = run_tool_free_model(
                plan=plan,
                prompt=check_prompt,
                hermes=args.hermes,
                output=check_dir,
                attempt_binding={
                    "candidate_receipt_hash": candidate["receipt_hash"],
                    "source_scope": "abstract_only",
                },
            )
            semantic = validate_semantic_verification(
                check_raw,
                plan=plan,
                candidate=candidate,
                source_text=source_text,
                prompt=check_prompt,
                usage=check_usage,
                trace=check_trace,
                provider=PROVIDER,
                model=MODEL,
                source_scope="excerpt",
            )
            write_exclusive_json(check_dir / "semantic-check.json", semantic)
        cost = execution.get("reported_total_cost_usd")
        if type(cost) not in (int, float):
            raise ValueError("abstract_fallback_cost_unknown")
        total_cost = round(
            cost
            + candidate["estimated_cost_usd"]
            + (semantic["estimated_cost_usd"] if semantic else 0),
            8,
        )
        if total_cost > plan["limits"]["max_estimated_cost_usd"]:
            raise ValueError("abstract_fallback_cost_exceeded")
        direct = candidate["status"] == "verification_required"
        verdict = semantic["verdict"] if semantic else "not_checked"
        lines = [
            "# Частичное исследовательское наблюдение",
            "",
            f"Вопрос: {plan['question']}",
            "Уровень опоры: только аннотация. Полный текст, методы, данные и ограничения работы не прочитаны.",
            f"Источник: {row['title']} ({row['record_id']}).",
            "",
        ]
        if direct:
            lines.extend(
                [
                    f"Предварительный тезис: {candidate['claim']}",
                    f"Точный фрагмент аннотации: «{candidate['quote']}».",
                    f"Смысловая проверка по аннотации: {verdict}.",
                    f"Ограничение: {candidate['uncertainty']}",
                ]
            )
        else:
            lines.extend(
                [
                    "По прочитанной аннотации прямой тезис не выведен.",
                    f"Причина: {candidate['uncertainty']}",
                ]
            )
        lines.append(
            "Это не вывод о полном исследовании; статус работы и независимая опора остаются открытыми."
        )
        markdown = ("\n".join(lines) + "\n").encode("utf-8")
        output = args.output_root / f"{plan['run_id']}-abstract-result"
        new_private_directory(output)
        result = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaDeepAbstractFallback",
                "run_id": plan["run_id"],
                "status": "abstract_hypothesis" if direct else "abstract_context_only",
                "plan_receipt_hash": plan["receipt_hash"],
                "execution_receipt_hash": execution["receipt_hash"],
                "portfolio_receipt_hash": portfolio["receipt_hash"],
                "source_capture_receipt_hash": row["capture_receipt_hash"],
                "source_ref": row["record_id"],
                "source_id": source_id,
                "source_scope": "abstract_only",
                "draft_receipt_hash": candidate["receipt_hash"],
                "semantic_check_receipt_hash": semantic["receipt_hash"]
                if semantic
                else None,
                "semantic_verdict": verdict,
                "markdown_sha256": hashlib.sha256(markdown).hexdigest(),
                "provisional_claim_count": int(direct),
                "accepted_claim_count": 0,
                "reported_total_cost_usd": total_cost,
                "mode_qualified": False,
                "release_authorized": False,
                "external_delivery_authorized": False,
            }
        )
        write_exclusive_bytes(output / "result.md", markdown)
        write_exclusive_json(output / "result.json", result)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "run_id": plan["run_id"],
                    "provisional_claim_count": result["provisional_claim_count"],
                    "accepted_claim_count": 0,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, ModelCallError, OSError, ValueError) as error:
        code = (
            error.code
            if isinstance(error, (ContractError, ModelCallError))
            else str(error)
        )
        if not _CODE.fullmatch(code):
            code = "abstract_fallback_failed"
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
