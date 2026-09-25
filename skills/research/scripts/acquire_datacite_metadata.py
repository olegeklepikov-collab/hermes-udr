"""One bounded public DataCite DOI metadata request for a Dataset leaf."""

from __future__ import annotations

import argparse
import json
import signal
import ssl
import sys
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

from hermes_research_report.academic_datacite import (
    MAX_RAW_BYTES,
    acquire_datacite_datasets,
)
from hermes_research_report.beta_acquisition import AcquisitionError
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import runtime_guarded


class AcquisitionDeadline(BaseException):
    """Abort the bounded request if the API does not answer in time."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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
        if args.output.name != f"{plan['run_id']}-{args.leaf_id}-datacite":
            raise AcquisitionError("output_run_leaf_mismatch")
        new_private_directory(args.output)
        write_exclusive_json(
            args.output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "run_id": plan["run_id"],
                "leaf_id": args.leaf_id,
                "provider": "datacite",
                "plan_receipt_hash": plan["receipt_hash"],
                "plan_file_sha256": plan_file_sha,
                "retry_allowed": False,
            },
        )
        opener = build_opener(
            HTTPSHandler(context=ssl.create_default_context()), NoRedirect()
        )

        def fetch(url: str) -> tuple[int, dict[str, str], bytes, str, bool, int]:
            request = Request(
                url,
                method="GET",
                headers={
                    "Accept": "application/vnd.api+json",
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

        def deadline(_signum: int, _frame: object) -> None:
            raise AcquisitionDeadline()

        previous_handler = signal.signal(signal.SIGALRM, deadline)
        previous_timer = signal.setitimer(
            signal.ITIMER_REAL, min(float(plan["limits"]["wall_seconds"]), 30.0)
        )
        try:
            receipt, artifacts = acquire_datacite_datasets(
                plan, args.leaf_id, fetch=fetch
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
                    "leaf_id": receipt["leaf_id"],
                    "candidate_count": receipt["candidate_count"],
                    "dataset_content_read": False,
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
