"""Execute profiled beta source leaves once, then reconcile saved receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_json,
    )
except ImportError:
    from file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_json,
    )

from hermes_research_report.academic_publisher_raw import MAX_HTML_BYTES
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import runtime_guarded, verify_runtime

SCRIPTS = Path(__file__).resolve().parent
_FAMILY_SCRIPTS = {
    "web": ("acquire_beta_sources.py", "keenable"),
    "official": ("acquire_beta_sources.py", "official"),
    "scholarly_index": ("acquire_openalex_metadata.py", "openalex"),
    "preprint_archive": ("acquire_arxiv_metadata.py", "arxiv"),
    "dataset": ("acquire_datacite_metadata.py", "datacite"),
}
_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


def source_steps(plan: object) -> list[tuple[str | None, str, str]]:
    verified = verify_beta_mode_plan(plan)
    if (
        verified["schema_version"] != 2
        or verified["status"] != "ready_to_execute"
        or any("concept_groups" not in leaf for leaf in verified["leaves"])
        or not set(verified["source_families"]).issubset(_FAMILY_SCRIPTS)
    ):
        raise ValueError("source_plan_not_executable")
    run_id = verified["run_id"]
    if verified["mode"] == "search":
        if verified["source_families"] != ["web"]:
            raise ValueError("search_route_invalid")
        return [(None, "acquire_beta_sources.py", run_id)]
    worst_case_sources = 3 * len(verified["leaves"]) + sum(
        leaf["source_family"] == "scholarly_index" for leaf in verified["leaves"]
    )
    if verified["limits"]["max_sources"] < worst_case_sources:
        raise ValueError("source_global_budget_insufficient")
    return [
        (
            leaf["leaf_id"],
            _FAMILY_SCRIPTS[leaf["source_family"]][0],
            f"{run_id}-{leaf['leaf_id']}-{_FAMILY_SCRIPTS[leaf['source_family']][1]}",
        )
        for leaf in verified["leaves"]
    ]


def _child_code(stderr: str) -> str:
    try:
        value = json.loads(stderr.strip())
    except (json.JSONDecodeError, ValueError):
        return "source_child_failed"
    code = value.get("code") if type(value) is dict else None
    return (
        code if type(code) is str and _CODE.fullmatch(code) else "source_child_failed"
    )


def eligible_oa_work(
    metadata: object,
    *,
    excluded_work_ids: frozenset[str] = frozenset(),
    excluded_dois: frozenset[str] = frozenset(),
) -> str | None:
    if type(metadata) is not dict or metadata.get("status") != "partial_candidate":
        return None
    works = metadata.get("works")
    if type(works) is not list:
        return None
    for work in works:
        if type(work) is not dict:
            continue
        location = work.get("open_access_location")
        if (
            work.get("work_id") not in excluded_work_ids
            and work.get("doi") not in excluded_dois
            and type(location) is dict
            and location.get("is_oa_reported") is True
            and location.get("license_reported") in {"cc0", "cc-by"}
            and location.get("version_reported")
            in {"publishedVersion", "acceptedVersion"}
            and type(location.get("pdf_url")) is str
            and type(work.get("doi")) is str
            and type(work.get("work_id")) is str
        ):
            return work["work_id"]
    return None


def _oa_readback(path: Path, plan: dict, metadata: dict, work_id: str) -> dict:
    value, _ = load_json(path)
    if type(value) is not dict or not verify_receipt_hash(value):
        raise ValueError("oa_capture_invalid")
    receipt = value
    if (
        receipt.get("contract") != "BetaOpenAlexArticleTextAcquisition"
        or receipt.get("run_id") != plan["run_id"]
        or receipt.get("plan_receipt_hash") != plan["receipt_hash"]
        or receipt.get("metadata_receipt_hash") != metadata["receipt_hash"]
        or receipt.get("work_id") != work_id
        or receipt.get("release_authorized") is not False
        or receipt.get("source_origin_independence_verified") is not False
        or receipt.get("full_text_coverage_verified") is not False
    ):
        raise ValueError("oa_capture_not_bound")
    for file_key, sha_key, bytes_key in (
        ("raw_response_file", "raw_response_sha256", "raw_response_bytes"),
        ("text_file", "text_sha256", "text_bytes"),
    ):
        name = receipt.get(file_key)
        if name is None:
            if file_key == "text_file" and receipt.get("status") == "blocked":
                continue
            raise ValueError("oa_capture_files_invalid")
        if type(name) is not str or "/" in name or "\\" in name:
            raise ValueError("oa_capture_files_invalid")
        payload = read_private_bytes(path.parent / name)
        if len(payload) != receipt.get(bytes_key) or hashlib.sha256(
            payload
        ).hexdigest() != receipt.get(sha_key):
            raise ValueError("oa_capture_files_invalid")
    return receipt


def _publisher_readback(path: Path, plan: dict, metadata: dict, article: dict) -> dict:
    value, _ = load_json(path)
    if type(value) is not dict or not verify_receipt_hash(value):
        raise ValueError("publisher_capture_invalid")
    receipt = value
    if (
        receipt.get("contract") != "BetaPublisherRawAttestation"
        or receipt.get("run_id") != plan["run_id"]
        or receipt.get("plan_receipt_hash") != plan["receipt_hash"]
        or receipt.get("metadata_receipt_hash") != metadata["receipt_hash"]
        or receipt.get("article_receipt_hash") != article["receipt_hash"]
        or receipt.get("release_authorized") is not False
        or receipt.get("full_text_coverage_verified") is not False
    ):
        raise ValueError("publisher_capture_not_bound")
    hops = receipt.get("redirect_hops")
    if type(hops) is not list or not 1 <= len(hops) <= 6:
        raise ValueError("publisher_capture_files_invalid")
    for hop in hops:
        if type(hop) is not dict:
            raise ValueError("publisher_capture_files_invalid")
        for name_key, sha_key, bytes_key in (
            ("body_file", "response_sha256", "response_bytes"),
            ("headers_file", "headers_sha256", "headers_bytes"),
        ):
            name = hop.get(name_key)
            if type(name) is not str or "/" in name or "\\" in name:
                raise ValueError("publisher_capture_files_invalid")
            payload = read_private_bytes(path.parent / name, maximum=MAX_HTML_BYTES)
            if len(payload) != hop.get(bytes_key) or hashlib.sha256(
                payload
            ).hexdigest() != hop.get(sha_key):
                raise ValueError("publisher_capture_files_invalid")
    raw_name = receipt.get("raw_file")
    if raw_name is not None:
        if type(raw_name) is not str or "/" in raw_name or "\\" in raw_name:
            raise ValueError("publisher_capture_files_invalid")
        raw = read_private_bytes(path.parent / raw_name, maximum=MAX_HTML_BYTES)
        if len(raw) != receipt.get("raw_bytes") or hashlib.sha256(
            raw
        ).hexdigest() != receipt.get("raw_sha256"):
            raise ValueError("publisher_capture_files_invalid")
    elif receipt.get("status") != "blocked":
        raise ValueError("publisher_capture_files_invalid")
    return receipt


def _guarded_child(*args, **kwargs):
    verify_runtime()
    kwargs.setdefault("check", False)
    return subprocess.run(*args, **kwargs)  # noqa: PLW1510 — explicit default above; callers retain overrides.


@runtime_guarded
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--hermes", type=Path)
    parser.add_argument("--public-query-ack", action="store_true")
    parser.add_argument("--read-all-candidates", action="store_true")
    args = parser.parse_args(argv)
    if not args.public_query_ack:
        print(
            json.dumps({"status": "error", "code": "public_query_ack_required"}),
            file=sys.stderr,
        )
        return 2
    output: Path | None = None
    rows: list[dict[str, object]] = []
    captures: list[Path] = []
    article_rows: list[dict[str, object]] = []
    publisher_rows: list[dict[str, object]] = []
    screen_rows: list[dict[str, object]] = []
    article_unknown = False
    selected_work_ids: set[str] = set()
    selected_dois: set[str] = set()
    source_slots_used = 0
    model_cost_used = 0.0
    try:
        plan_value, plan_file_sha = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        steps = source_steps(plan)
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
        ):
            raise ValueError("output_root_invalid")
        output = args.output_root / f"{plan['run_id']}-execution"
        assert output is not None
        new_private_directory(output)
        write_exclusive_json(
            output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "run_id": plan["run_id"],
                "plan_receipt_hash": plan["receipt_hash"],
                "plan_file_sha256": plan_file_sha,
                "scheduled_routes": [
                    {"leaf_id": leaf_id, "script": script, "output_name": name}
                    for leaf_id, script, name in steps
                ],
                "retry_allowed": False,
            },
        )
        deadline = time.monotonic() + float(plan["limits"]["wall_seconds"])
        for leaf_id, script, name in steps:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                rows.append(
                    {
                        "leaf_id": leaf_id,
                        "status": "not_started",
                        "reason": "wall_limit",
                    }
                )
                break
            directory = args.output_root / name
            command = [
                sys.executable,
                str(SCRIPTS / script),
                "--plan",
                str(args.plan),
                "--output",
                str(directory),
                "--public-query-ack",
            ]
            if leaf_id is not None:
                command.extend(("--leaf-id", leaf_id))
            if script == "acquire_beta_sources.py" and (
                args.read_all_candidates or plan["mode"] == "ultra"
            ):
                command.extend(("--max-candidates-per-leaf", "3"))
            try:
                child = _guarded_child(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=remaining,
                )
            except subprocess.TimeoutExpired:
                rows.append(
                    {"leaf_id": leaf_id, "status": "unknown", "reason": "wall_limit"}
                )
                break
            capture = directory / "capture.json"
            if child.returncode not in (0, 3) or not capture.is_file():
                rows.append(
                    {
                        "leaf_id": leaf_id,
                        "status": "unknown" if directory.exists() else "failed",
                        "reason": _child_code(child.stderr),
                    }
                )
                break
            capture_value, _ = load_json(capture)
            if type(capture_value) is not dict or not verify_receipt_hash(
                capture_value
            ):
                raise ValueError("source_capture_invalid")
            capture_contract = capture_value.get("contract")
            slot_field = (
                "extract_calls"
                if capture_contract == "BetaSourceAcquisition"
                else "candidate_count"
                if capture_contract
                in {"BetaOpenAlexMetadataAcquisition", "BetaArxivMetadataAcquisition"}
                or capture_contract == "BetaDataCiteDatasetMetadataAcquisition"
                else None
            )
            slots = capture_value.get(slot_field) if slot_field else None
            if type(slots) is not int or not 0 <= slots <= 3:
                raise ValueError("source_slot_count_invalid")
            source_slots_used += slots
            if source_slots_used > plan["limits"]["max_sources"]:
                raise ValueError("source_global_budget_exceeded")
            captures.append(capture)
            rows.append(
                {"leaf_id": leaf_id, "status": "captured", "capture": str(capture)}
            )
            if (
                script == "acquire_openalex_metadata.py"
                and child.returncode == 0
                and source_slots_used < plan["limits"]["max_sources"]
            ):
                metadata_value, _ = load_json(capture)
                work_id = eligible_oa_work(
                    metadata_value,
                    excluded_work_ids=frozenset(selected_work_ids),
                    excluded_dois=frozenset(selected_dois),
                )
                if work_id is not None and type(metadata_value) is dict:
                    selected_work_ids.add(work_id)
                    selected_work = next(
                        work
                        for work in metadata_value["works"]
                        if type(work) is dict and work.get("work_id") == work_id
                    )
                    selected_dois.add(selected_work["doi"])
                    metadata = metadata_value
                    short = work_id.removeprefix("https://openalex.org/")
                    article_dir = (
                        args.output_root / f"{plan['run_id']}-{leaf_id}-{short}-oa-text"
                    )
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        article_rows.append(
                            {
                                "leaf_id": leaf_id,
                                "work_id": work_id,
                                "status": "not_started",
                                "reason": "wall_limit",
                            }
                        )
                        article_unknown = True
                        break
                    article_command = [
                        sys.executable,
                        str(SCRIPTS / "acquire_openalex_oa_text.py"),
                        "--plan",
                        str(args.plan),
                        "--metadata-capture",
                        str(capture),
                        "--work-id",
                        work_id,
                        "--output",
                        str(article_dir),
                        "--public-query-ack",
                    ]
                    try:
                        article_child = _guarded_child(
                            article_command,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=remaining,
                        )
                    except subprocess.TimeoutExpired:
                        article_rows.append(
                            {
                                "leaf_id": leaf_id,
                                "work_id": work_id,
                                "status": "unknown",
                                "reason": "wall_limit",
                            }
                        )
                        article_unknown = True
                        break
                    article_capture = article_dir / "capture.json"
                    if (
                        article_child.returncode not in (0, 3)
                        or not article_capture.is_file()
                    ):
                        article_rows.append(
                            {
                                "leaf_id": leaf_id,
                                "work_id": work_id,
                                "status": "unknown",
                                "reason": _child_code(article_child.stderr),
                            }
                        )
                        article_unknown = True
                        break
                    article_receipt = _oa_readback(
                        article_capture, plan, metadata, work_id
                    )
                    source_slots_used += 1
                    if source_slots_used > plan["limits"]["max_sources"]:
                        raise ValueError("source_global_budget_exceeded")
                    article_rows.append(
                        {
                            "leaf_id": leaf_id,
                            "work_id": work_id,
                            "status": article_receipt["status"],
                            "receipt_hash": article_receipt["receipt_hash"],
                            "capture": str(article_capture),
                            "full_text_coverage_verified": False,
                        }
                    )
                    publisher_ok = False
                    if article_receipt["status"] == "article_text_candidate":
                        work = next(
                            (
                                item
                                for item in metadata["works"]
                                if type(item) is dict and item.get("work_id") == work_id
                            ),
                            None,
                        )
                        location = (
                            work.get("open_access_location")
                            if type(work) is dict
                            else None
                        )
                        if (
                            type(location) is dict
                            and location.get("license_reported") == "cc-by"
                            and location.get("version_reported") == "publishedVersion"
                        ):
                            publisher_dir = (
                                args.output_root
                                / f"{plan['run_id']}-{leaf_id}-{short}-publisher-raw"
                            )
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                publisher_rows.append(
                                    {
                                        "leaf_id": leaf_id,
                                        "status": "not_started",
                                        "reason": "wall_limit",
                                    }
                                )
                                article_unknown = True
                                break
                            publisher_command = [
                                sys.executable,
                                str(SCRIPTS / "acquire_publisher_raw.py"),
                                "--plan",
                                str(args.plan),
                                "--metadata-capture",
                                str(capture),
                                "--article-capture",
                                str(article_capture),
                                "--output",
                                str(publisher_dir),
                            ]
                            try:
                                publisher_child = _guarded_child(
                                    publisher_command,
                                    capture_output=True,
                                    text=True,
                                    check=False,
                                    timeout=remaining,
                                )
                            except subprocess.TimeoutExpired:
                                publisher_rows.append(
                                    {
                                        "leaf_id": leaf_id,
                                        "status": "unknown",
                                        "reason": "wall_limit",
                                    }
                                )
                                article_unknown = True
                                break
                            publisher_capture = publisher_dir / "capture.json"
                            if (
                                publisher_child.returncode not in (0, 3)
                                or not publisher_capture.is_file()
                            ):
                                publisher_rows.append(
                                    {
                                        "leaf_id": leaf_id,
                                        "status": "unknown",
                                        "reason": _child_code(publisher_child.stderr),
                                    }
                                )
                                article_unknown = True
                                break
                            publisher_receipt = _publisher_readback(
                                publisher_capture, plan, metadata, article_receipt
                            )
                            publisher_ok = (
                                publisher_receipt["status"]
                                == "publisher_html_candidate"
                            )
                            publisher_rows.append(
                                {
                                    "leaf_id": leaf_id,
                                    "work_id": work_id,
                                    "status": publisher_receipt["status"],
                                    "receipt_hash": publisher_receipt["receipt_hash"],
                                    "capture": str(publisher_capture),
                                    "redirect_hops": len(
                                        publisher_receipt["redirect_hops"]
                                    ),
                                    "publisher_extracted_text_overlap_verified": publisher_receipt.get(
                                        "publisher_extracted_text_overlap_verified"
                                    )
                                    is True,
                                    "full_text_coverage_verified": False,
                                }
                            )
                        else:
                            publisher_rows.append(
                                {
                                    "leaf_id": leaf_id,
                                    "work_id": work_id,
                                    "status": "not_eligible_for_raw_profile",
                                }
                            )
                    if (
                        article_receipt["status"] == "article_text_candidate"
                        and publisher_ok
                        and args.hermes is not None
                        and not screen_rows
                        and plan["limits"]["model_calls"] >= 1
                    ):
                        screen_dir = (
                            args.output_root
                            / f"{plan['run_id']}-{leaf_id}-{short}-screen"
                        )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            screen_rows.append(
                                {
                                    "leaf_id": leaf_id,
                                    "status": "not_started",
                                    "reason": "wall_limit",
                                }
                            )
                            article_unknown = True
                            break
                        screen_command = [
                            sys.executable,
                            str(SCRIPTS / "screen_openalex_oa_text.py"),
                            "--plan",
                            str(args.plan),
                            "--metadata-capture",
                            str(capture),
                            "--article-capture",
                            str(article_capture),
                            "--hermes",
                            str(args.hermes),
                            "--output",
                            str(screen_dir),
                        ]
                        try:
                            screen_child = _guarded_child(
                                screen_command,
                                capture_output=True,
                                text=True,
                                check=False,
                                timeout=remaining,
                            )
                        except subprocess.TimeoutExpired:
                            screen_rows.append(
                                {
                                    "leaf_id": leaf_id,
                                    "status": "unknown",
                                    "reason": "wall_limit",
                                }
                            )
                            article_unknown = True
                            break
                        screen_file = screen_dir / "screen.json"
                        if screen_child.returncode != 0 or not screen_file.is_file():
                            screen_rows.append(
                                {
                                    "leaf_id": leaf_id,
                                    "status": "unknown",
                                    "reason": _child_code(screen_child.stderr),
                                }
                            )
                            article_unknown = True
                            break
                        screen_value, _ = load_json(screen_file)
                        if (
                            type(screen_value) is not dict
                            or not verify_receipt_hash(screen_value)
                            or screen_value.get("contract")
                            != "BetaOpenAlexArticleScreen"
                            or screen_value.get("plan_receipt_hash")
                            != plan["receipt_hash"]
                            or screen_value.get("article_receipt_hash")
                            != article_receipt["receipt_hash"]
                            or screen_value.get("accepted_claim_count") != 0
                            or screen_value.get("release_authorized") is not False
                        ):
                            raise ValueError("article_screen_not_bound")
                        screen = screen_value
                        screen_cost = screen.get("reported_total_cost_usd")
                        metadata_cost = metadata.get("reported_cost_usd")
                        if type(screen_cost) not in (int, float) or type(
                            metadata_cost
                        ) not in (int, float):
                            raise ValueError("article_screen_cost_invalid")
                        incremental_cost = float(
                            cast(int | float, screen_cost)
                        ) - float(cast(int | float, metadata_cost))
                        if (
                            type(incremental_cost) not in (int, float)
                            or incremental_cost < 0
                        ):
                            raise ValueError("article_screen_cost_invalid")
                        model_cost_used += incremental_cost
                        screen_rows.append(
                            {
                                "leaf_id": leaf_id,
                                "work_id": work_id,
                                "status": screen["status"],
                                "source_relation": screen["source_relation"],
                                "receipt_hash": screen["receipt_hash"],
                                "capture": str(screen_file),
                                "accepted_claim_count": 0,
                            }
                        )
                elif type(metadata_value) is dict:
                    article_rows.append(
                        {
                            "leaf_id": leaf_id,
                            "status": "not_selected",
                            "reason": "no_unique_eligible_work",
                        }
                    )
        portfolio: dict[str, object] | None = None
        if captures:
            command = [
                sys.executable,
                str(SCRIPTS / "assess_beta_source_portfolio.py"),
                "--plan",
                str(args.plan),
                "--output",
                str(output / "portfolio.json"),
            ]
            for capture in captures:
                command.extend(("--acquisition", str(capture)))
            child = _guarded_child(
                command, capture_output=True, text=True, check=False, timeout=30
            )
            if child.returncode != 0:
                rows.append(
                    {
                        "leaf_id": None,
                        "status": "portfolio_failed",
                        "reason": _child_code(child.stderr),
                    }
                )
            else:
                portfolio_value, _ = load_json(output / "portfolio.json")
                if type(portfolio_value) is not dict:
                    raise ValueError("portfolio_invalid")
                portfolio = portfolio_value
        complete = (
            not article_unknown
            and len(rows) == len(steps)
            and all(row["status"] == "captured" for row in rows)
        )
        if portfolio is not None:
            provider_cost = portfolio.get("reported_provider_cost_usd")
            if type(provider_cost) not in (int, float):
                raise ValueError("portfolio_cost_invalid")
            total_cost = round(
                float(cast(int | float, provider_cost)) + model_cost_used, 8
            )
        else:
            total_cost = None
        if (
            total_cost is not None
            and total_cost > plan["limits"]["max_estimated_cost_usd"]
        ):
            complete = False
        result = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaAutomaticSourceExecution",
                "run_id": plan["run_id"],
                "mode": plan["mode"],
                "plan_receipt_hash": plan["receipt_hash"],
                "status": "partial_analysis_required"
                if complete
                and portfolio is not None
                and portfolio["status"] == "partial_analysis_required"
                else "blocked",
                "steps": rows,
                "article_text_attempts": article_rows,
                "publisher_raw_attempts": publisher_rows,
                "publisher_html_candidate_count": sum(
                    row["status"] == "publisher_html_candidate"
                    for row in publisher_rows
                ),
                "article_screens": screen_rows,
                "accepted_claim_count": 0,
                "reported_model_cost_usd": model_cost_used,
                "reported_total_cost_usd": total_cost,
                "article_text_candidate_count": sum(
                    row["status"] == "article_text_candidate" for row in article_rows
                ),
                "observed_source_slots": source_slots_used,
                "max_source_slots": plan["limits"]["max_sources"],
                "source_slot_count_complete": complete,
                "portfolio_receipt_hash": portfolio["receipt_hash"]
                if portfolio
                else None,
                "source_calls_completed": len(captures),
                "mode_qualified": False,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "execution.json", result)
        fsync_directory(output)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "run_id": plan["run_id"],
                    "output": str(output),
                    "source_calls_completed": len(captures),
                    "observed_source_slots": source_slots_used,
                    "mode_qualified": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0 if result["status"] == "partial_analysis_required" else 3
    except (ContractError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        code = (
            error.code
            if isinstance(error, ContractError)
            else str(error)
            if isinstance(error, ValueError)
            and str(error).replace("_", "").isalnum()
            and len(str(error)) < 80
            else "source_execution_failed"
        )
        if output is not None and output.is_dir():
            try:
                write_exclusive_json(
                    output / "failure.json",
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
