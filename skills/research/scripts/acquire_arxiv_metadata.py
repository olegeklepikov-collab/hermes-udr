"""One arXiv Atom request with a local three-second single-connection limit."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import ssl
import stat
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

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
except ImportError:
    from file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )

from hermes_research_report.academic_arxiv import MAX_RAW_BYTES, acquire_arxiv_metadata
from hermes_research_report.beta_acquisition import AcquisitionError
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import runtime_guarded


class AcquisitionDeadline(BaseException):
    """Abort the whole provider call on timeout."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _rate_limited_fetch(
    url: str, home: Path
) -> tuple[int, dict[str, str], bytes, str, bool, int]:
    root = home / "foundation" / "artifacts"
    metadata = root.stat()
    if (
        root.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_mode & 0o077
    ):
        raise AcquisitionError("arxiv_rate_root_not_private")
    descriptor = os.open(
        root / "arxiv-api.lock",
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise AcquisitionError("arxiv_rate_ledger_invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        prior_raw = os.read(descriptor, 64)
        if prior_raw:
            try:
                prior = float(prior_raw.decode("ascii"))
            except (UnicodeError, ValueError):
                raise AcquisitionError("arxiv_rate_ledger_invalid") from None
            if not 0 < prior < time.time() + 60:
                raise AcquisitionError("arxiv_rate_ledger_invalid")
            time.sleep(max(0.0, 3.1 - (time.time() - prior)))
        timestamp = f"{time.time():.6f}".encode("ascii")
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, timestamp)
        os.ftruncate(descriptor, len(timestamp))
        os.fsync(descriptor)
        opener = build_opener(
            HTTPSHandler(context=ssl.create_default_context()), NoRedirect()
        )
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/atom+xml",
                "User-Agent": "UltraDeepResearchBeta/0.41.0a1",
            },
        )
        try:
            with opener.open(request, timeout=15) as response:
                return (
                    response.status,
                    dict(response.headers.items()),
                    response.read(MAX_RAW_BYTES + 1),
                    response.geturl(),
                    True,
                    0,
                )
        except HTTPError as error:
            return (
                error.code,
                dict(error.headers.items()),
                error.read(MAX_RAW_BYTES + 1),
                error.geturl(),
                True,
                0,
            )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _fetch_or_negative(
    url: str, home: Path
) -> tuple[tuple[int, dict[str, str], bytes, str, bool, int], str | None]:
    try:
        return _rate_limited_fetch(url, home), None
    except OSError as error:
        return (0, {}, b"", url, False, 0), type(error).__name__


@runtime_guarded
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--leaf-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-query-ack", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.public_query_ack:
            raise AcquisitionError("public_query_ack_required")
        plan_value, plan_file_sha = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        if plan["schema_version"] != 2 or any(
            "concept_groups" not in leaf for leaf in plan["leaves"]
        ):
            raise AcquisitionError("plan_policy_invalid")
        matching = [leaf for leaf in plan["leaves"] if leaf["leaf_id"] == args.leaf_id]
        if (
            plan["mode"] not in {"deep", "ultra", "academic"}
            or len(matching) != 1
            or matching[0]["source_family"] != "preprint_archive"
        ):
            raise AcquisitionError("arxiv_leaf_not_routed")
        if args.output.name != f"{plan['run_id']}-{args.leaf_id}-arxiv":
            raise AcquisitionError("output_run_leaf_mismatch")
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
                "leaf_id": args.leaf_id,
                "provider": "arxiv",
                "plan_receipt_hash": plan["receipt_hash"],
                "plan_file_sha256": plan_file_sha,
                "retry_allowed": False,
            },
        )

        def deadline(_signum: int, _frame: object) -> None:
            raise AcquisitionDeadline()

        previous_handler = signal.signal(signal.SIGALRM, deadline)
        previous_timer = signal.setitimer(
            signal.ITIMER_REAL, min(float(plan["limits"]["wall_seconds"]), 30.0)
        )
        transport_error_type: str | None = None

        def fetch_or_record_failure(
            url: str,
        ) -> tuple[int, dict[str, str], bytes, str, bool, int]:
            nonlocal transport_error_type
            result, transport_error_type = _fetch_or_negative(url, home)
            return result

        try:
            receipt, artifacts = acquire_arxiv_metadata(
                plan,
                args.leaf_id,
                fetch=fetch_or_record_failure,
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
            signal.signal(signal.SIGALRM, previous_handler)
        if transport_error_type is not None:
            receipt = with_receipt_hash(
                {
                    **{
                        key: value
                        for key, value in receipt.items()
                        if key != "receipt_hash"
                    },
                    "reason": "provider_transport_failure",
                    "transport_error_type": transport_error_type,
                }
            )
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
                    "leaf_id": receipt["leaf_id"],
                    "candidate_count": receipt["candidate_count"],
                    "qualification_status": receipt["qualification_status"],
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0 if receipt["status"] == "partial_candidate" else 3
    except (
        AcquisitionError,
        AcquisitionDeadline,
        ContractError,
        OSError,
        ValueError,
    ) as error:
        code = (
            error.code
            if isinstance(error, (AcquisitionError, ContractError))
            else "acquisition_deadline_exceeded"
            if isinstance(error, AcquisitionDeadline)
            else "acquisition_input_or_storage_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
