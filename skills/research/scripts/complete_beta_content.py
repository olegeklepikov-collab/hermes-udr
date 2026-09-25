"""Produce a source-bound provisional answer or explicit gap for every frame atom."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
    from .model_call import (
        MODEL,
        PROVIDER,
        prompt_binding_matches,
        run_tool_free_model,
        vision_binding_matches,
    )
except ImportError:
    from file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from model_call import (
        MODEL,
        PROVIDER,
        prompt_binding_matches,
        run_tool_free_model,
        vision_binding_matches,
    )
from hermes_research_report.beta_atomic_answer import (
    QUOTE_FORMAT_NOTE,
    apply_content_review,
    build_atomic_answer_prompt,
    build_content_review_prompt,
    parse_atomic_answer,
    render_atomic_answers,
    select_atom_sources,
)
from hermes_research_report.beta_coverage import assess_beta_coverage
from hermes_research_report.beta_model import validate_tool_free_observation
from hermes_research_report.beta_source_lineage import assess_source_lineage
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash


def _read_receipt(path: Path) -> dict:
    value, _ = load_json(path)
    if type(value) is not dict or not verify_receipt_hash(value):
        raise ValueError("content_receipt_invalid")
    return value


def collect_sources(
    root: Path,
    run_id: str,
    frame: dict,
    extras: list[Path],
    frame_revision: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    if not re.fullmatch(r"BETA-AUTO-[0-9]{8}-[0-9]{6}-[A-F0-9]{8}", run_id):
        raise ValueError("content_run_id_invalid")
    sources = {}
    gaps = []
    plan = _read_receipt(root / f"{run_id}-planning/plan.json")
    if plan.get("question") != frame.get("question"):
        raise ValueError("content_frame_question_unbound")
    source_frame_hashes = {frame["receipt_hash"]}
    if frame_revision is not None:
        if (
            not verify_receipt_hash(frame_revision)
            or frame_revision.get("contract") != "BetaCoverageHoleFill"
            or frame_revision.get("revised_frame_receipt_hash") != frame["receipt_hash"]
            or frame_revision.get("decomposition_receipt_hash")
            != frame.get("decomposition_receipt_hash")
        ):
            raise ValueError("content_frame_revision_unbound")
        source_frame_hashes.add(frame_revision["parent_frame_receipt_hash"])

    def add(source_id, title, url, text, receipt_hash, scope, mapped, family):
        digest = hashlib.sha256(text.encode()).hexdigest()
        key = "SRC-" + hashlib.sha256((url + digest).encode()).hexdigest()[:16].upper()
        if key in sources:
            sources[key]["mapped_atom_ids"] = sorted(
                set(sources[key]["mapped_atom_ids"]) | set(mapped)
            )
            return
        sources[key] = {
            "source_id": key,
            "original_source_id": source_id,
            "title": title or url,
            "url": url,
            "text": text,
            "text_sha256": digest,
            "receipt_hash": receipt_hash,
            "read_scope": scope,
            "mapped_atom_ids": mapped,
            "declared_family": family,
        }

    for path in sorted(root.glob(f"{run_id}*/capture.json")):
        capture = _read_receipt(path)
        if capture.get("contract") != "BetaSourceAcquisition":
            if (
                capture.get("plan_receipt_hash") != plan["receipt_hash"]
                or capture.get("run_id") != run_id
            ):
                raise ValueError("content_nonweb_plan_unbound")
            filename = capture.get("text_file")
            if filename and capture.get("text_sha256"):
                if Path(filename).name != filename:
                    raise ValueError("content_article_path_invalid")
                raw = read_private_bytes(path.parent / filename, maximum=5_000_000)
                if hashlib.sha256(raw).hexdigest() != capture["text_sha256"]:
                    raise ValueError("content_article_hash_invalid")
                add(
                    capture.get("source_id"),
                    capture.get("title"),
                    capture.get("final_url_without_query") or capture.get("doi"),
                    raw.decode(),
                    capture["receipt_hash"],
                    "retained_article_text_completeness_unverified",
                    [],
                    "scholarly_index",
                )
            elif capture.get("contract") in {
                "BetaOpenAlexMetadataAcquisition",
                "BetaArxivMetadataAcquisition",
            }:
                filename = capture["response_file"]
                if Path(filename).name != filename:
                    raise ValueError("content_metadata_path_invalid")
                raw = read_private_bytes(path.parent / filename, maximum=5_000_000)
                if hashlib.sha256(raw).hexdigest() != capture["response_sha256"]:
                    raise ValueError("content_metadata_hash_invalid")
                for record in capture.get("works", capture.get("preprints", [])):
                    abstract = (
                        record.get("abstract_text")
                        or record.get("abstract")
                        or record.get("summary")
                    )
                    url = (
                        record.get("doi")
                        or record.get("work_id")
                        or record.get("abs_url")
                        or record.get("versioned_url")
                        or record.get("id")
                    )
                    if type(abstract) is str and abstract.strip() and type(url) is str:
                        add(
                            url,
                            record.get("title"),
                            url,
                            abstract,
                            capture["receipt_hash"],
                            "abstract_only",
                            [],
                            capture["source_family"],
                        )
                if not capture.get("candidate_count"):
                    gaps.append(
                        {
                            "source": path.parent.name,
                            "reason": capture.get("reason", "no_candidates"),
                        }
                    )
            elif capture.get("contract") == "BetaDataCiteDatasetMetadataAcquisition":
                gaps.append(
                    {
                        "source": path.parent.name,
                        "reason": "DataCite returned metadata only; no dataset file read by this route.",
                        "candidate_count": capture.get("candidate_count", 0),
                    }
                )
            continue
        batch_id = capture["run_id"]
        mapped = []
        if batch_id != run_id:
            if not re.fullmatch(re.escape(run_id) + r"-C[0-9]{2}", batch_id):
                raise ValueError("content_capture_run_unbound")
            batch = _read_receipt(root / f"{batch_id}-domain-web-plan/batch.json")
            if (
                batch.get("frame_receipt_hash") not in source_frame_hashes
                or batch.get("subplan_receipt_hash") != capture["plan_receipt_hash"]
            ):
                raise ValueError("content_capture_frame_unbound")
            mapped = [batch["atom_id"]]
        elif capture.get("plan_receipt_hash") != plan["receipt_hash"]:
            raise ValueError("content_capture_plan_unbound")
        for leaf in capture["leaves"]:
            for row in leaf.get("candidate_attempts", []):
                identifier = row.get("source_id")
                if (
                    type(identifier) is not str
                    or not re.fullmatch(r"SRC-[A-F0-9]{16}", identifier)
                    or not row.get("content_sha256")
                ):
                    gaps.append(
                        {
                            "source": row.get("requested_url"),
                            "reason": row.get("status", "no_retained_text"),
                        }
                    )
                    continue
                try:
                    raw = read_private_bytes(
                        path.parent / f"{identifier}.txt", maximum=2_000_000
                    )
                    if hashlib.sha256(raw).hexdigest() != row["content_sha256"]:
                        raise ValueError("content_source_changed")
                    add(
                        identifier,
                        row.get("title"),
                        row.get("url") or row["requested_url"],
                        raw.decode(),
                        capture["receipt_hash"],
                        "retained_extracted_text_visuals_unverified",
                        mapped,
                        leaf.get("declared_source_family", "web"),
                    )
                except (OSError, ValueError) as error:
                    gaps.append({"source": identifier, "reason": str(error)[:160]})
    for path in extras:
        source = _read_receipt(path)
        if source.get("contract") != "BetaPublicContentRead":
            raise ValueError("content_extra_contract_invalid")
        if source.get("status") != "content_read":
            gaps.append(
                {"source": source.get("requested_url"), "reason": source.get("reason")}
            )
            continue
        filename = source["text_file"]
        if Path(filename).name != filename:
            raise ValueError("content_extra_path_invalid")
        raw = read_private_bytes(path.parent / filename, maximum=50_000_000)
        if hashlib.sha256(raw).hexdigest() != source["text_sha256"]:
            raise ValueError("content_extra_hash_invalid")
        add(
            source["source_id"],
            source["title"],
            source["url"],
            raw.decode(),
            source["receipt_hash"],
            source["read_scope"],
            source.get("mapped_atom_ids", []),
            source["declared_family"],
        )
    return list(sources.values()), gaps


def call_or_recover(
    prompt: str,
    output: Path,
    hermes: Path,
    run_id: str,
    budget: float,
    *,
    wall_seconds: int = 180,
    image_path: Path | None = None,
) -> tuple[str, float]:
    if output.exists():
        attempt, _ = load_json(output / "attempt.json")
        usage, _ = load_json(output / "model-usage.json")
        trace, _ = load_json(output / "model-trace.json")
        raw = (
            read_private_bytes(output / "model.raw.json", maximum=1_048_576)
            .decode()
            .rstrip("\n")
        )
        if attempt.get("prompt_sha256") != hashlib.sha256(prompt.encode()).hexdigest():
            legacy = prompt.replace(QUOTE_FORMAT_NOTE, "", 1)
            if (
                attempt.get("prompt_sha256")
                == hashlib.sha256(legacy.encode()).hexdigest()
            ):
                prompt = legacy
        if (
            attempt.get("prompt_sha256") != hashlib.sha256(prompt.encode()).hexdigest()
            or not (
                vision_binding_matches(
                    output,
                    trace,
                    prompt,
                    hashlib.sha256(
                        read_private_bytes(image_path, maximum=8_000_000)
                    ).hexdigest(),
                    raw,
                )
                if image_path
                else prompt_binding_matches(trace["messages"][0].get("content"), prompt)
            )
            or trace["messages"][-1].get("content", "").strip() != raw
        ):
            raise ValueError("content_recovery_prompt_changed")
        validate_tool_free_observation(
            max_estimated_cost_usd=min(0.02, budget),
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
            max_total_tokens=attempt["max_total_tokens"],
            preserve_completed_cost_overrun=True,
        )
    else:
        raw, usage, _ = run_tool_free_model(
            prompt=prompt,
            hermes=hermes,
            output=output,
            attempt_binding={"purpose": "atomic_content_synthesis"},
            bootstrap_budget={
                "schema_version": 1,
                "run_id": run_id,
                "wall_seconds": wall_seconds,
                "max_estimated_cost_usd": min(0.02, budget),
                "model_calls": 1,
            },
            preserve_completed_cost_overrun=True,
            **({"image_path": image_path} if image_path is not None else {}),
        )
    return raw, float(usage["estimated_cost_usd"])


def complete_content(
    *,
    root: Path,
    run_id: str,
    frame: dict,
    hermes: Path,
    output: Path,
    extras: list[Path],
    budget: float,
    source_limit: int = 5,
    text_limit: int = 40000,
    deadline: float | None = None,
    frame_revision: dict | None = None,
    reuse_answers_from: Path | None = None,
    resume_frozen_corpus: bool = False,
    corpus_override: dict | None = None,
    target_atom_ids: list[str] | None = None,
) -> dict:
    assess_beta_coverage(frame, [], budget_exhausted=False)
    if (
        type(budget) not in (float, int)
        or not math.isfinite(budget)
        or budget < 0
        or budget > 5
    ):
        raise ValueError("content_budget_invalid")
    if corpus_override is None:
        sources, corpus_gaps = collect_sources(
            root, run_id, frame, extras, frame_revision
        )
    else:
        if (
            not verify_receipt_hash(corpus_override)
            or corpus_override.get("run_id") != run_id
            or corpus_override.get("frame_receipt_hash") != frame["receipt_hash"]
        ):
            raise ValueError("content_override_corpus_unbound")
        sources, corpus_gaps = (
            corpus_override["sources"],
            corpus_override.get("gaps", []),
        )
    selected_atoms = frame["atoms"]
    if target_atom_ids is not None:
        if (
            not target_atom_ids
            or len(set(target_atom_ids)) != len(target_atom_ids)
            or not set(target_atom_ids).issubset({a["atom_id"] for a in selected_atoms})
        ):
            raise ValueError("content_target_atoms_invalid")
        selected_atoms = [a for a in selected_atoms if a["atom_id"] in target_atom_ids]
    deferred_new_sources = []
    if not output.exists():
        new_private_directory(output)
        write_exclusive_json(
            output / "corpus.json",
            with_receipt_hash(
                {
                    "contract": "BetaRetainedContentCorpus",
                    "run_id": run_id,
                    "frame_receipt_hash": frame["receipt_hash"],
                    "sources": sources,
                    "gaps": corpus_gaps,
                }
            ),
        )
    else:
        prior = json.loads(
            read_private_bytes(output / "corpus.json", maximum=50_000_000)
        )
        if (
            not verify_receipt_hash(prior)
            or prior["frame_receipt_hash"] != frame["receipt_hash"]
        ):
            raise ValueError("content_resume_corpus_changed")
        if prior["sources"] != sources:
            current = {row["source_id"]: row for row in sources}
            if not resume_frozen_corpus or any(
                current.get(row["source_id"]) != row for row in prior["sources"]
            ):
                raise ValueError("content_resume_corpus_changed")
            known = {row["source_id"] for row in prior["sources"]}
            deferred_new_sources = [
                {key: row[key] for key in ("source_id", "title", "url", "read_scope")}
                for row in sources
                if row["source_id"] not in known
            ]
            sources = prior["sources"]
            corpus_gaps = prior["gaps"]
    answers = []
    gaps = []
    spent = 0.0
    cost_known = True
    reused_atoms = []
    for index, atom in enumerate(selected_atoms, 1):
        selected = select_atom_sources(atom, sources, maximum=source_limit)
        if (
            not selected
            or not cost_known
            or spent >= budget
            or (deadline is not None and time.monotonic() >= deadline)
        ):
            gaps.append(
                {
                    "atom_id": atom["atom_id"],
                    "reason": "Исчерпан бюджет времени или расходов, либо расход предыдущей попытки неизвестен."
                    if selected
                    else "В полученном корпусе нет доступного сохраненного текста.",
                }
            )
            continue
        directory = output / f"atom-{index:03d}"
        prompt = build_atomic_answer_prompt(atom, selected, text_limit=text_limit)
        if reuse_answers_from is not None and not directory.exists():
            prior_directory = reuse_answers_from / f"atom-{index:03d}"
            names = (
                "attempt.json",
                "model-usage.json",
                "model-trace.json",
                "model.raw.json",
            )
            if all((prior_directory / name).is_file() for name in names):
                attempt, _ = load_json(prior_directory / "attempt.json")
                allowed_prompts = {
                    hashlib.sha256(value.encode()).hexdigest()
                    for value in (prompt, prompt.replace(QUOTE_FORMAT_NOTE, "", 1))
                }
                if attempt.get("prompt_sha256") in allowed_prompts:
                    new_private_directory(directory)
                    for name in names:
                        write_exclusive_bytes(
                            directory / name,
                            read_private_bytes(
                                prior_directory / name, maximum=5_000_000
                            ),
                        )
                    reused_atoms.append(atom["atom_id"])
        cost = None
        try:
            raw, cost = call_or_recover(
                prompt,
                directory,
                hermes,
                f"{run_id}-A{index:02d}",
                min(0.02, budget - spent),
                wall_seconds=max(1, min(180, int(deadline - time.monotonic())))
                if deadline is not None
                else 180,
            )
            spent += cost
            answer = parse_atomic_answer(raw, atom, selected, text_limit=text_limit)
            if not (directory / "answer.json").exists():
                write_exclusive_json(directory / "answer.json", answer)
            else:
                saved = _read_receipt(directory / "answer.json")
                if answer != saved:
                    raise ValueError("content_answer_reparse_changed")
            answers.append(answer)
        except (OSError, ValueError, KeyError, TypeError) as error:
            if cost is None:
                cost_known = False
            gaps.append(
                {
                    "atom_id": atom["atom_id"],
                    "reason": "Содержательная оценка не завершена: " + str(error)[:180],
                }
            )
    review_complete = False
    if (
        answers
        and cost_known
        and spent < budget
        and (deadline is None or time.monotonic() < deadline)
    ):
        review_cost = None
        try:
            review_prompt = build_content_review_prompt(answers, sources)
            review_directory = output / "review"
            if review_directory.exists():
                prior_attempt, _ = load_json(review_directory / "attempt.json")
                if (
                    prior_attempt.get("prompt_sha256")
                    != hashlib.sha256(review_prompt.encode()).hexdigest()
                ):
                    review_directory = output / (
                        "review-"
                        + hashlib.sha256(review_prompt.encode()).hexdigest()[:12]
                    )
            previously_counted_reviews = set()
            for usage_path in output.glob("review*/model-usage.json"):
                if usage_path.parent == review_directory:
                    continue
                prior_usage, _ = load_json(usage_path)
                prior_cost = prior_usage.get("estimated_cost_usd")
                if (
                    type(prior_cost) not in (float, int)
                    or not math.isfinite(prior_cost)
                    or prior_cost < 0
                ):
                    raise ValueError("content_prior_review_cost_unknown")
                spent += prior_cost
                previously_counted_reviews.add(usage_path.parent)
            if spent >= budget:
                review_cost = 0.0
                raise ValueError("content_review_budget_exhausted")
            raw, review_cost = call_or_recover(
                review_prompt,
                review_directory,
                hermes,
                f"{run_id}-REVIEW",
                min(0.02, budget - spent),
                wall_seconds=max(1, min(180, int(deadline - time.monotonic())))
                if deadline is not None
                else 180,
            )
            spent += review_cost
            answers = apply_content_review(raw, answers)
            missing_reviews = [
                answer for answer in answers if not answer.get("model_review")
            ]
            if (
                missing_reviews
                and spent < budget
                and (deadline is None or time.monotonic() < deadline)
            ):
                missing_prompt = build_content_review_prompt(missing_reviews, sources)
                missing_dir = output / (
                    "review-missing-"
                    + hashlib.sha256(missing_prompt.encode()).hexdigest()[:12]
                )
                review_cost = None
                missing_raw, missing_cost = call_or_recover(
                    missing_prompt,
                    missing_dir,
                    hermes,
                    f"{run_id}-REVIEW-MISSING",
                    min(0.02, budget - spent),
                    wall_seconds=max(1, min(180, int(deadline - time.monotonic())))
                    if deadline is not None
                    else 180,
                )
                review_cost = missing_cost
                if missing_dir not in previously_counted_reviews:
                    spent += missing_cost
                filled = {
                    a["atom_id"]: a
                    for a in apply_content_review(missing_raw, missing_reviews)
                }
                answers = [filled.get(a["atom_id"], a) for a in answers]
            review_complete = all(answer.get("model_review") for answer in answers)
            if not review_complete:
                gaps.append(
                    {
                        "atom_id": "REVIEW",
                        "reason": "Отдельные вопросы остались без смысловой проверки; остальные оценки сохранены.",
                    }
                )
        except (OSError, ValueError, KeyError, TypeError) as error:
            if review_cost is None:
                cost_known = False
            gaps.append(
                {
                    "atom_id": "REVIEW",
                    "reason": "Отдельная смысловая проверка не завершена: "
                    + str(error)[:160],
                }
            )
    outcome = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaAtomicContentRun",
            "run_id": run_id,
            "question": frame["question"],
            "frame_receipt_hash": frame["receipt_hash"],
            "source_count": len(sources),
            "corpus_gaps": corpus_gaps,
            "new_sources_outside_frozen_review": deferred_new_sources,
            "atom_count": len(selected_atoms),
            "frame_atom_count": len(frame["atoms"]),
            "target_atom_ids": [a["atom_id"] for a in selected_atoms],
            "answers": answers,
            "technical_gaps": gaps,
            "addressed_atom_count": len(answers),
            "source_anchored_answer_count": sum(
                a["anchored_premise_count"] > 0 for a in answers
            ),
            "reported_model_cost_usd": spent if cost_known else None,
            "known_model_cost_usd": spent,
            "budget_usd": budget,
            "cost_observation_complete": cost_known,
            "scope_complete": len(answers) == len(selected_atoms),
            "model_semantic_review_complete": review_complete,
            "observed_budget_overrun_usd": max(0.0, spent - budget),
            "semantic_review_independent": False,
            "reused_atom_ids": reused_atoms,
            "frame_revision_receipt_hash": frame_revision["receipt_hash"]
            if frame_revision
            else None,
            "full_research_coverage_verified": False,
            "saturation_verified": False,
            "release_authorized": False,
        }
    )
    markdown = render_atomic_answers(frame["question"], answers, gaps)
    if deferred_new_sources:
        markdown += "\n## Дополнительные материалы вне проверенного снимка\n\n"
        markdown += "Исходные оплаченные ответы восстановлены без замены их корпуса. Следующие новые записи не использованы в этих ответах:\n\n"
        for source in deferred_new_sources:
            markdown += "- " + source["source_id"] + ": " + source["url"] + "\n"
    outcome = with_receipt_hash(
        {
            **{key: value for key, value in outcome.items() if key != "receipt_hash"},
            "markdown_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
        }
    )
    if not (output / "content-run.json").exists():
        write_exclusive_json(output / "content-run.json", outcome)
        write_exclusive_bytes(output / "result.md", markdown.encode())
    elif (
        _read_receipt(output / "content-run.json")["receipt_hash"]
        != outcome["receipt_hash"]
    ):
        revision = outcome["receipt_hash"][:16]
        receipt_path = output / f"content-run-{revision}.json"
        report_path = output / f"result-{revision}.md"
        if receipt_path.exists():
            if _read_receipt(receipt_path) != outcome:
                raise ValueError("content_saved_revision_changed")
        else:
            write_exclusive_json(receipt_path, outcome)
        if report_path.exists():
            if read_private_bytes(report_path, maximum=50_000_000) != markdown.encode():
                raise ValueError("content_saved_report_changed")
        else:
            write_exclusive_bytes(report_path, markdown.encode())
    lineage = assess_source_lineage(_read_receipt(output / "corpus.json"), outcome)
    lineage_path = output / f"lineage-{lineage['receipt_hash'][:16]}.json"
    if not lineage_path.exists():
        write_exclusive_json(lineage_path, lineage)
    return outcome


def reconcile_content_review(output: Path) -> tuple[dict, Path]:
    """Finalize an already paid review from an immutable corpus, without new calls."""
    corpus = json.loads(read_private_bytes(output / "corpus.json", maximum=50_000_000))
    if not verify_receipt_hash(corpus):
        raise ValueError("content_review_corpus_invalid")
    answers = [
        _read_receipt(path) for path in sorted(output.glob("atom-*/answer.json"))
    ]
    prompt = build_content_review_prompt(answers, corpus["sources"])
    matching = []
    for path in output.glob("review*/attempt.json"):
        attempt, _ = load_json(path)
        if attempt.get("prompt_sha256") == hashlib.sha256(prompt.encode()).hexdigest():
            matching.append(path.parent)
    if len(matching) != 1:
        raise ValueError("content_saved_review_not_unique")
    raw, _cost = call_or_recover(
        prompt, matching[0], Path("/not-used"), corpus["run_id"] + "-REVIEW", 0.02
    )
    reviewed = apply_content_review(raw, answers)
    cost = 0.0
    for path in output.glob("*/model-usage.json"):
        usage, _ = load_json(path)
        value = usage.get("estimated_cost_usd")
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("content_cost_unknown")
        cost += value
    prior = max(output.glob("content-run*.json"), key=lambda p: p.stat().st_mtime)
    previous = _read_receipt(prior)
    if {a["atom_id"] for a in reviewed} != {a["atom_id"] for a in previous["answers"]}:
        raise ValueError("content_review_answer_inventory_changed")
    body = {key: value for key, value in previous.items() if key != "receipt_hash"}
    body.update(
        answers=reviewed,
        model_semantic_review_complete=True,
        parent_content_receipt_hash=previous["receipt_hash"],
        additional_model_calls=0,
        reported_model_cost_usd=cost,
        known_model_cost_usd=cost,
        technical_gaps=[
            row for row in previous["technical_gaps"] if row["atom_id"] != "REVIEW"
        ],
    )
    receipt = with_receipt_hash(body)
    suffix = receipt["receipt_hash"][:16]
    write_exclusive_json(output / f"content-run-review-{suffix}.json", receipt)
    destination = output / f"result-review-{suffix}.md"
    write_exclusive_bytes(
        destination,
        render_atomic_answers(
            previous.get("question", "Исследование: результаты по вопросам карты"),
            reviewed,
            receipt["technical_gaps"],
        ).encode(),
    )
    return receipt, destination


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, action="append", default=[])
    parser.add_argument("--budget-usd", type=float, default=0.2)
    parser.add_argument("--max-sources-per-atom", type=int, default=5)
    parser.add_argument("--source-char-limit", type=int, default=40000)
    parser.add_argument("--public-query-ack", action="store_true")
    parser.add_argument("--frame-revision", type=Path)
    parser.add_argument("--reuse-answers-from", type=Path)
    parser.add_argument("--resume-frozen-corpus", action="store_true")
    args = parser.parse_args(argv)
    if not args.public_query_ack:
        parser.error("public_query_ack_required")
    result = complete_content(
        root=args.artifacts_root,
        run_id=args.run_id,
        frame=_read_receipt(args.frame),
        hermes=args.hermes,
        output=args.output,
        extras=args.source_receipt,
        budget=args.budget_usd,
        source_limit=args.max_sources_per_atom,
        text_limit=args.source_char_limit,
        frame_revision=_read_receipt(args.frame_revision)
        if args.frame_revision
        else None,
        reuse_answers_from=args.reuse_answers_from,
        resume_frozen_corpus=args.resume_frozen_corpus,
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "scope_complete",
                    "atom_count",
                    "addressed_atom_count",
                    "source_count",
                    "source_anchored_answer_count",
                    "reported_model_cost_usd",
                )
            }
        )
    )
    return 0 if result["scope_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
