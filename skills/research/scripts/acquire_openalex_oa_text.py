"""Acquire one rights-limited publisher-text candidate via configured Hermes."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import signal
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
except ImportError:
    from file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )

from hermes_research_report.academic_oa_text import acquire_openalex_oa_text
from hermes_research_report.academic_openalex import (
    MAX_RECORDS,
    _metadata_rows,
    _strict_json,
)
from hermes_research_report.beta_acquisition import AcquisitionError
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import runtime_guarded

_WORK_SHORT = re.compile(r"^W[0-9]+$")


class AcquisitionDeadline(BaseException):
    """Abort the whole provider call on timeout."""


def _preflight(
    plan_file: Path, metadata_file: Path, work_id: str
) -> tuple[dict, dict, str]:
    plan_value, _ = load_json(plan_file)
    plan = verify_beta_mode_plan(plan_value)
    metadata_value, _ = load_json(metadata_file)
    if type(metadata_value) is not dict:
        raise ValueError("oa_metadata_invalid")
    metadata = metadata_value
    leaf_id = metadata.get("leaf_id")
    if (
        plan["schema_version"] != 2
        or plan["mode"] not in {"deep", "ultra", "academic"}
        or type(leaf_id) is not str
        or metadata_file.name != "capture.json"
        or metadata_file.parent.name != f"{plan['run_id']}-{leaf_id}-openalex"
        or metadata_file.parent.is_symlink()
        or metadata.get("run_id") != plan["run_id"]
        or metadata.get("plan_receipt_hash") != plan["receipt_hash"]
    ):
        raise ValueError("oa_metadata_path_not_bound")
    raw_name = metadata.get("response_file")
    if type(raw_name) is not str or raw_name != f"{leaf_id}.openalex.raw.json":
        raise ValueError("oa_metadata_raw_not_bound")
    raw = read_private_bytes(metadata_file.parent / raw_name)
    if hashlib.sha256(raw).hexdigest() != metadata.get("response_sha256"):
        raise ValueError("oa_metadata_raw_not_bound")
    total, cost, rows = _metadata_rows(_strict_json(raw), MAX_RECORDS)
    if (
        rows != metadata.get("works")
        or total != metadata.get("reported_total")
        or cost != metadata.get("reported_cost_usd")
    ):
        raise ValueError("oa_metadata_raw_not_bound")
    short = work_id.removeprefix("https://openalex.org/")
    if not _WORK_SHORT.fullmatch(short):
        raise ValueError("oa_work_id_invalid")
    return plan, metadata, short


@runtime_guarded
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--metadata-capture", type=Path, required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-query-ack", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.public_query_ack:
            raise AcquisitionError("public_query_ack_required")
        plan, metadata, short = _preflight(
            args.plan, args.metadata_capture, args.work_id
        )
        leaf_id = metadata["leaf_id"]
        if args.output.name != f"{plan['run_id']}-{leaf_id}-{short}-oa-text":
            raise AcquisitionError("oa_output_name_invalid")
        home = Path(os.environ.get("HERMES_HOME", ""))
        if not home.is_absolute() or not home.is_dir() or home.is_symlink():
            raise AcquisitionError("hermes_home_invalid")
        new_private_directory(args.output)
        write_exclusive_json(
            args.output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "run_id": plan["run_id"],
                "leaf_id": leaf_id,
                "work_id": args.work_id,
                "plan_receipt_hash": plan["receipt_hash"],
                "metadata_receipt_hash": metadata["receipt_hash"],
                "metadata_raw_sha256": metadata["response_sha256"],
                "retry_allowed": False,
            },
        )
        from hermes_cli.config import load_config
        from plugins.web.keyless_mcp import _ring_order, provider_tier

        web = load_config().get("web") or {}
        if (
            web.get("extract_backend") != "keenable"
            or web.get("keyless_rescue") is not False
            or provider_tier("keenable") != "free"
            or _ring_order("keenable") != ["keenable"]
        ):
            raise AcquisitionError("oa_web_route_not_bounded")
        importlib.import_module("tools.web_tools")
        from tools.registry import registry

        def extract(urls: list[str]) -> str:
            result = registry.dispatch(
                "web_extract", {"urls": urls, "char_limit": 50_000}
            )
            if type(result) is not str:
                raise AcquisitionError("oa_host_response_invalid")
            return result

        def deadline(_signum: int, _frame: object) -> None:
            raise AcquisitionDeadline()

        previous_handler = signal.signal(signal.SIGALRM, deadline)
        previous_timer = signal.setitimer(
            signal.ITIMER_REAL, min(float(plan["limits"]["wall_seconds"]), 60.0)
        )
        try:
            receipt, artifacts = acquire_openalex_oa_text(
                plan, metadata, args.work_id, extract=extract
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
            signal.signal(signal.SIGALRM, previous_handler)
        for name, payload in artifacts.items():
            write_exclusive_bytes(args.output / name, payload)
        write_exclusive_json(args.output / "capture.json", receipt)
        fsync_directory(args.output)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "reason": receipt["reason"],
                    "run_id": receipt["run_id"],
                    "work_id": receipt["work_id"],
                    "full_text_coverage_verified": False,
                    "mode_qualified": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0 if receipt["status"] == "article_text_candidate" else 3
    except (
        AcquisitionError,
        ContractError,
        AcquisitionDeadline,
        OSError,
        ValueError,
    ) as error:
        code = (
            error.code
            if isinstance(error, (AcquisitionError, ContractError))
            else "oa_deadline_exceeded"
            if isinstance(error, AcquisitionDeadline)
            else str(error)
            if isinstance(error, ValueError)
            and str(error).replace("_", "").isalnum()
            and len(str(error)) < 80
            else "oa_input_or_storage_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
