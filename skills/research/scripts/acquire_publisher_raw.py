"""Fetch exact publisher HTML through pinned public-IP HTTPS hops."""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import signal
import socket
import ssl
import sys
from pathlib import Path
from urllib.parse import urlsplit

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .acquire_openalex_oa_text import _preflight as _metadata_preflight
    from .file_io import (
        fsync_directory,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from .screen_openalex_oa_text import _preflight
except ImportError:
    from acquire_openalex_oa_text import _preflight as _metadata_preflight
    from file_io import (
        fsync_directory,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from screen_openalex_oa_text import _preflight

from hermes_research_report.academic_publisher_raw import (
    _validated_url,
    attest_openalex_publisher_raw,
)
from hermes_research_report.beta_acquisition import AcquisitionError
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import runtime_guarded


class AcquisitionDeadline(BaseException):
    """Abort all redirect hops at the overall deadline."""


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, *, timeout: float) -> None:
        super().__init__(
            host, 443, context=ssl.create_default_context(), timeout=timeout
        )
        self._pinned_ip = ip

    def connect(self) -> None:
        plain = socket.create_connection((self._pinned_ip, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(plain, server_hostname=self.host)
        except BaseException:
            plain.close()
            raise


def _public_ipv4(host: str) -> str:
    try:
        rows = socket.getaddrinfo(
            host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM
        )
    except OSError:
        raise AcquisitionError("publisher_dns_unavailable") from None
    addresses = sorted({row[4][0] for row in rows})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise AcquisitionError("publisher_dns_not_public")
    return addresses[0]


def _fetch_one(
    url: str, maximum: int, publisher_host: str, *, max_query_chars: int = 500
) -> tuple[int, dict[str, str], bytes, str, bool]:
    host, target, _safe = _validated_url(
        url, publisher_host, max_query_chars=max_query_chars
    )
    ip = _public_ipv4(host)
    connection = _PinnedHTTPSConnection(host, ip, timeout=12.0)
    try:
        connection.request(
            "GET",
            target,
            headers={
                "Accept": "text/html",
                "Accept-Encoding": "identity",
                "User-Agent": "UltraDeepResearchBeta/0.41.0a1",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        header_rows = response.getheaders()
        if sum(key.lower() == "location" for key, _value in header_rows) > 1:
            raise AcquisitionError("publisher_redirect_location_ambiguous")
        headers = {key.lower(): value for key, value in header_rows}
        payload = response.read(maximum + 1)
        if len(payload) > maximum:
            raise AcquisitionError("publisher_body_over_limit")
        return response.status, headers, payload, ip, True
    finally:
        connection.close()


@runtime_guarded
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--metadata-capture", type=Path, required=True)
    parser.add_argument("--article-capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output_created = False
    try:
        plan, metadata, article, _source_id, text, _excerpt, _prompt, _cost = (
            _preflight(args.plan, args.metadata_capture, args.article_capture)
        )
        raw_plan, raw_metadata, _short = _metadata_preflight(
            args.plan, args.metadata_capture, article["work_id"]
        )
        if (
            raw_plan["receipt_hash"] != plan["receipt_hash"]
            or raw_metadata["receipt_hash"] != metadata["receipt_hash"]
        ):
            raise AcquisitionError("publisher_metadata_raw_not_bound")
        short = article["work_id"].removeprefix("https://openalex.org/")
        leaf_id = article["leaf_id"]
        if args.output.name != f"{plan['run_id']}-{leaf_id}-{short}-publisher-raw":
            raise AcquisitionError("publisher_output_name_invalid")
        works = metadata.get("works")
        matching = (
            [
                work
                for work in works
                if type(work) is dict and work.get("work_id") == article["work_id"]
            ]
            if type(works) is list
            else []
        )
        if (
            len(matching) != 1
            or type(matching[0].get("open_access_location")) is not dict
        ):
            raise AcquisitionError("publisher_location_not_eligible")
        pdf_url = matching[0]["open_access_location"].get("pdf_url")
        publisher_host = urlsplit(pdf_url).hostname if type(pdf_url) is str else None
        if not publisher_host:
            raise AcquisitionError("publisher_host_invalid")
        new_private_directory(args.output)
        output_created = True
        write_exclusive_json(
            args.output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "run_id": plan["run_id"],
                "leaf_id": leaf_id,
                "work_id": article["work_id"],
                "plan_receipt_hash": plan["receipt_hash"],
                "metadata_receipt_hash": metadata["receipt_hash"],
                "article_receipt_hash": article["receipt_hash"],
                "expected_publisher_host": publisher_host,
                "retry_allowed": False,
            },
        )

        def deadline(_signum: int, _frame: object) -> None:
            raise AcquisitionDeadline()

        previous_handler = signal.signal(signal.SIGALRM, deadline)
        previous_timer = signal.setitimer(
            signal.ITIMER_REAL, min(float(plan["limits"]["wall_seconds"]), 60.0)
        )
        try:
            receipt, artifacts = attest_openalex_publisher_raw(
                plan,
                metadata,
                article,
                extracted_text=text,
                fetch=lambda url, maximum: _fetch_one(url, maximum, publisher_host),
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
                    "redirect_chain_verified": receipt["redirect_chain_verified"],
                    "raw_bytes": receipt["raw_bytes"],
                    "full_text_coverage_verified": False,
                    "mode_qualified": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0 if receipt["status"] == "publisher_html_candidate" else 3
    except (
        AcquisitionError,
        ContractError,
        AcquisitionDeadline,
        OSError,
        ValueError,
        ssl.SSLError,
    ) as error:
        code = (
            error.code
            if isinstance(error, (AcquisitionError, ContractError))
            else "publisher_deadline_exceeded"
            if isinstance(error, AcquisitionDeadline)
            else str(error)
            if isinstance(error, ValueError)
            and str(error).replace("_", "").isalnum()
            and len(str(error)) < 80
            else "publisher_acquisition_failed"
        )
        if output_created:
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
