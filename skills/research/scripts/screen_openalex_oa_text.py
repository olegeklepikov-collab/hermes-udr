"""One tool-free relevance screen of a saved, unverified article-text candidate."""

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
        fsync_directory,
        load_json,
        read_private_bytes,
        write_exclusive_json,
    )
    from .model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model
except ImportError:
    from file_io import (
        fsync_directory,
        load_json,
        read_private_bytes,
        write_exclusive_json,
    )
    from model_call import MODEL, PROVIDER, ModelCallError, run_tool_free_model

from hermes_research_report.academic_oa_text import article_source_id
from hermes_research_report.beta_model import (
    MAX_CONTEXT_CHARS,
    build_beta_model_prompt,
    validate_beta_model_candidate,
)
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError

_WORK_SHORT = re.compile(r"^W[0-9]+$")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _preflight(
    plan_file: Path, metadata_file: Path, article_file: Path
) -> tuple[dict, dict, dict, str, str, str, str, float]:
    plan_value, _ = load_json(plan_file)
    plan = verify_beta_mode_plan(plan_value)
    metadata_value, _ = load_json(metadata_file)
    article_value, _ = load_json(article_file)
    if type(metadata_value) is not dict or type(article_value) is not dict:
        raise ValueError("oa_screen_receipts_invalid")
    metadata, article = metadata_value, article_value
    leaf_id, work_id = article.get("leaf_id"), article.get("work_id")
    short = (
        work_id.removeprefix("https://openalex.org/") if type(work_id) is str else ""
    )
    if (
        plan["schema_version"] != 2
        or plan["mode"] not in {"deep", "ultra", "academic"}
        or plan["status"] != "ready_to_execute"
        or plan["limits"]["model_calls"] < 1
        or type(leaf_id) is not str
        or not _WORK_SHORT.fullmatch(short)
        or metadata_file.name != "capture.json"
        or article_file.name != "capture.json"
        or metadata_file.parent.name != f"{plan['run_id']}-{leaf_id}-openalex"
        or article_file.parent.name != f"{plan['run_id']}-{leaf_id}-{short}-oa-text"
        or metadata_file.parent.is_symlink()
        or article_file.parent.is_symlink()
        or not verify_receipt_hash(metadata)
        or not verify_receipt_hash(article)
        or metadata.get("contract") != "BetaOpenAlexMetadataAcquisition"
        or article.get("contract") != "BetaOpenAlexArticleTextAcquisition"
        or article.get("status") != "article_text_candidate"
        or metadata.get("run_id") != plan["run_id"]
        or article.get("run_id") != plan["run_id"]
        or article.get("mode") != plan["mode"]
        or metadata.get("plan_receipt_hash") != plan["receipt_hash"]
        or article.get("plan_receipt_hash") != plan["receipt_hash"]
        or article.get("metadata_receipt_hash") != metadata["receipt_hash"]
        or article.get("release_authorized") is not False
        or article.get("full_text_coverage_verified") is not False
        or article.get("source_origin_independence_verified") is not False
    ):
        raise ValueError("oa_screen_receipts_not_bound")
    works = metadata.get("works")
    matching = (
        [
            work
            for work in works
            if type(work) is dict and work.get("work_id") == work_id
        ]
        if type(works) is list
        else []
    )
    if (
        len(matching) != 1
        or matching[0].get("doi") != article.get("doi")
        or matching[0].get("title") != article.get("title")
    ):
        raise ValueError("oa_screen_work_not_bound")
    text_name = article.get("text_file")
    raw_name = article.get("raw_response_file")
    if (
        text_name != f"{leaf_id}.oa-text.txt"
        or raw_name != f"{leaf_id}.oa-extract.raw.json"
    ):
        raise ValueError("oa_screen_files_invalid")
    text_bytes = read_private_bytes(article_file.parent / text_name)
    raw_bytes = read_private_bytes(article_file.parent / raw_name)
    if (
        len(text_bytes) != article.get("text_bytes")
        or _sha(text_bytes) != article.get("text_sha256")
        or len(raw_bytes) != article.get("raw_response_bytes")
        or _sha(raw_bytes) != article.get("raw_response_sha256")
    ):
        raise ValueError("oa_screen_files_tampered")
    source_id = article_source_id(work_id, _sha(text_bytes))
    if article.get("source_id") not in (None, source_id):
        raise ValueError("oa_screen_source_id_invalid")
    text = text_bytes.decode("utf-8")
    excerpt = text[:MAX_CONTEXT_CHARS]
    prompt = build_beta_model_prompt(
        plan, source_id=source_id, title=article["title"], text=excerpt
    )
    cost = metadata.get("reported_cost_usd")
    if (
        type(cost) not in (int, float)
        or not 0 <= cost <= plan["limits"]["max_estimated_cost_usd"]
    ):
        raise ValueError("oa_screen_provider_cost_invalid")
    return plan, metadata, article, source_id, text, excerpt, prompt, float(cost)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--metadata-capture", type=Path, required=True)
    parser.add_argument("--article-capture", type=Path, required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    model_completed = False
    try:
        plan, metadata, article, source_id, text, excerpt, prompt, cost = _preflight(
            args.plan, args.metadata_capture, args.article_capture
        )
        short = article["work_id"].removeprefix("https://openalex.org/")
        if args.output.name != f"{plan['run_id']}-{article['leaf_id']}-{short}-screen":
            raise ValueError("oa_screen_output_name_invalid")
        raw, usage, trace = run_tool_free_model(
            plan=plan,
            prompt=prompt,
            hermes=args.hermes,
            output=args.output,
            attempt_binding={
                "metadata_receipt_hash": metadata["receipt_hash"],
                "article_receipt_hash": article["receipt_hash"],
                "source_id": source_id,
                "excerpt_sha256": _sha(excerpt.encode("utf-8")),
            },
        )
        model_completed = True
        candidate = validate_beta_model_candidate(
            raw,
            plan=plan,
            source_id=source_id,
            title=article["title"],
            source_text=excerpt,
            prompt=prompt,
            usage=usage,
            trace=trace,
            provider=PROVIDER,
            model=MODEL,
        )
        total_cost = round(cost + candidate["estimated_cost_usd"], 8)
        if total_cost > plan["limits"]["max_estimated_cost_usd"]:
            raise ValueError("oa_screen_cumulative_cost_exceeded")
        write_exclusive_json(args.output / "model-candidate.json", candidate)
        screen = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaOpenAlexArticleScreen",
                "status": candidate["status"],
                "run_id": plan["run_id"],
                "mode": plan["mode"],
                "plan_receipt_hash": plan["receipt_hash"],
                "metadata_receipt_hash": metadata["receipt_hash"],
                "article_receipt_hash": article["receipt_hash"],
                "candidate_receipt_hash": candidate["receipt_hash"],
                "source_id": source_id,
                "source_id_origin": "article_receipt"
                if article.get("source_id")
                else "derived_from_historical_receipt",
                "whole_text_sha256": _sha(text.encode("utf-8")),
                "excerpt_start": 0,
                "excerpt_end": len(excerpt),
                "excerpt_sha256": _sha(excerpt.encode("utf-8")),
                "source_relation": candidate["source_relation"],
                "draft_claim_present": candidate["status"] == "verification_required",
                "accepted_claim_count": 0,
                "reported_total_cost_usd": total_cost,
                "full_text_coverage_verified": False,
                "source_origin_independence_verified": False,
                "semantic_support_verified": False,
                "mode_qualified": False,
                "release_authorized": False,
            }
        )
        write_exclusive_json(args.output / "screen.json", screen)
        fsync_directory(args.output)
        print(
            json.dumps(
                {
                    "status": screen["status"],
                    "source_relation": screen["source_relation"],
                    "accepted_claim_count": 0,
                    "run_id": plan["run_id"],
                    "reported_total_cost_usd": total_cost,
                    "mode_qualified": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, ModelCallError, OSError, ValueError, UnicodeError) as error:
        code = (
            error.code
            if isinstance(error, (ContractError, ModelCallError))
            else str(error)
            if isinstance(error, ValueError)
            and str(error).replace("_", "").isalnum()
            and len(str(error)) < 80
            else "oa_screen_failed"
        )
        if model_completed:
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
