"""Retain and parse one screened, version-pinned arXiv PDF without widening hosts."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .acquire_publisher_raw import _PinnedHTTPSConnection
    from .file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
except ImportError:
    from acquire_publisher_raw import _PinnedHTTPSConnection
    from file_io import (
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )

from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import runtime_guarded

MAX_PDF_BYTES = 50_000_000
_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")
_ARXIV = re.compile(r"^https://arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5}v[1-9][0-9]*)$")
_ATOM = "{http://www.w3.org/2005/Atom}"


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
        raise ValueError("arxiv_fulltext_receipt_not_bound")
    return value


def _observed_pdf_url(capture: dict, raw_atom: bytes, versioned_url: str) -> str:
    match = _ARXIV.fullmatch(versioned_url)
    if match is None:
        raise ValueError("arxiv_fulltext_version_invalid")
    preprints = capture.get("preprints")
    if type(preprints) is not list or not any(
        type(row) is dict and row.get("versioned_url") == versioned_url
        for row in preprints
    ):
        raise ValueError("arxiv_fulltext_record_missing")
    try:
        root = ET.fromstring(raw_atom)
    except ET.ParseError:
        raise ValueError("arxiv_fulltext_atom_invalid") from None
    candidates = []
    for entry in root.findall(f"{_ATOM}entry"):
        identifier = entry.findtext(f"{_ATOM}id")
        if (
            identifier is None
            or identifier.replace("http://arxiv.org/", "https://arxiv.org/", 1)
            != versioned_url
        ):
            continue
        for link in entry.findall(f"{_ATOM}link"):
            if link.get("title") == "pdf" and link.get("type") == "application/pdf":
                candidates.append(link.get("href"))
    expected = f"https://arxiv.org/pdf/{match.group(1)}"
    if candidates != [expected]:
        raise ValueError("arxiv_fulltext_pdf_link_not_bound")
    return expected


def _public_ip() -> str:
    rows = socket.getaddrinfo(
        "arxiv.org", 443, family=socket.AF_INET, type=socket.SOCK_STREAM
    )
    addresses = sorted({row[4][0] for row in rows})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("arxiv_fulltext_dns_not_public")
    return addresses[0]


def _fetch_pdf(url: str) -> tuple[bytes, dict[str, str], str]:
    match = re.fullmatch(
        r"https://arxiv\.org/pdf/[0-9]{4}\.[0-9]{4,5}v[1-9][0-9]*", url
    )
    if match is None:
        raise ValueError("arxiv_fulltext_url_invalid")
    ip = _public_ip()
    connection = _PinnedHTTPSConnection("arxiv.org", ip, timeout=20.0)
    try:
        connection.request(
            "GET",
            url.removeprefix("https://arxiv.org"),
            headers={
                "Accept": "application/pdf",
                "Accept-Encoding": "identity",
                "User-Agent": "UltraDeepResearchBeta/0.41.0a1",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        if (
            response.status != 200
            or not headers.get("content-type", "").lower().startswith("application/pdf")
            or headers.get("content-encoding") not in (None, "", "identity")
        ):
            raise ValueError("arxiv_fulltext_http_invalid")
        payload = response.read(MAX_PDF_BYTES + 1)
        if not payload.startswith(b"%PDF-") or len(payload) > MAX_PDF_BYTES:
            raise ValueError("arxiv_fulltext_pdf_invalid")
        return payload, headers, ip
    finally:
        connection.close()


def _parse_pdf(path: Path, payload: bytes) -> tuple[str, int]:
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo is None:
        raise ValueError("arxiv_fulltext_pdfinfo_missing")
    info = subprocess.run(
        [pdfinfo, str(path)], capture_output=True, text=True, check=False, timeout=20
    )
    if info.returncode != 0 or not re.search(r"(?m)^Encrypted:\s+no\b", info.stdout):
        raise ValueError("arxiv_fulltext_pdfinfo_invalid")
    pages_match = re.search(r"(?m)^Pages:\s+([0-9]+)$", info.stdout)
    if pages_match is None or not 1 <= int(pages_match.group(1)) <= 1000:
        raise ValueError("arxiv_fulltext_page_count_invalid")
    try:
        import anydoc

        text = anydoc.to_markdown_bytes(payload)
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        raise ValueError("arxiv_fulltext_parse_failed") from error
    if type(text) is not str or not 1000 <= len(text) <= 20_000_000:
        raise ValueError("arxiv_fulltext_text_invalid")
    return text, int(pages_match.group(1))


@runtime_guarded
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--arxiv-capture", type=Path, required=True)
    parser.add_argument("--screening", type=Path, required=True)
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    output: Path | None = None
    try:
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or not args.plan.is_absolute()
            or args.plan.is_symlink()
            or args.plan.parent.is_symlink()
        ):
            raise ValueError("arxiv_fulltext_output_root_invalid")
        plan_value, _ = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        if (
            plan["mode"] != "academic"
            or plan["schema_version"] != 2
            or plan["status"] != "ready_to_execute"
        ):
            raise ValueError("arxiv_fulltext_plan_invalid")
        if (
            args.plan != args.output_root / f"{plan['run_id']}-planning/plan.json"
            or args.screening
            != args.output_root / f"{plan['run_id']}-academic-screen/screening.json"
            or args.arxiv_capture.is_symlink()
            or args.arxiv_capture.parent.is_symlink()
        ):
            raise ValueError("arxiv_fulltext_paths_invalid")
        capture = _receipt(args.arxiv_capture, "BetaArxivMetadataAcquisition", plan)
        screening = _receipt(args.screening, "BetaAcademicPreliminaryScreen", plan)
        if screening.get("included_study_count") != 0 or not any(
            type(row) is dict
            and row.get("record_id") == args.record_id
            and row.get("verdict") == "include_candidate"
            for row in screening.get("decisions", [])
        ):
            raise ValueError("arxiv_fulltext_not_screened_candidate")
        record = next(
            (
                row
                for row in capture["preprints"]
                if row.get("versioned_url") == args.record_id
            ),
            None,
        )
        if record is None or capture.get("leaf_id") not in {
            row["leaf_id"]
            for row in screening.get("records", [])
            if row.get("record_id") == args.record_id
        }:
            raise ValueError("arxiv_fulltext_source_not_bound")
        if (
            args.arxiv_capture
            != args.output_root
            / f"{plan['run_id']}-{capture['leaf_id']}-arxiv/capture.json"
        ):
            raise ValueError("arxiv_fulltext_paths_invalid")
        raw_atom = read_private_bytes(
            args.arxiv_capture.parent / capture["response_file"], maximum=250_000
        )
        if (
            len(raw_atom) != capture["response_bytes"]
            or _sha(raw_atom) != capture["response_sha256"]
        ):
            raise ValueError("arxiv_fulltext_atom_not_bound")
        pdf_url = _observed_pdf_url(capture, raw_atom, args.record_id)
        stem = _ARXIV.fullmatch(args.record_id).group(1)
        output = (
            args.output_root / f"{plan['run_id']}-{capture['leaf_id']}-{stem}-fulltext"
        )
        new_private_directory(output)
        write_exclusive_json(
            output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "run_id": plan["run_id"],
                "plan_receipt_hash": plan["receipt_hash"],
                "arxiv_capture_receipt_hash": capture["receipt_hash"],
                "screening_receipt_hash": screening["receipt_hash"],
                "record_id": args.record_id,
                "pdf_url_sha256": _sha(pdf_url.encode()),
                "retry_allowed": False,
            },
        )
        pdf, headers, ip = _fetch_pdf(pdf_url)
        write_exclusive_bytes(output / "paper.pdf", pdf)
        write_exclusive_json(output / "headers.json", headers)
        text, pages = _parse_pdf(output / "paper.pdf", pdf)
        write_exclusive_bytes(output / "paper.md", text.encode("utf-8"))
        result = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "BetaArxivFullTextRead",
                "status": "parsed_text_candidate",
                "run_id": plan["run_id"],
                "mode": "academic",
                "plan_receipt_hash": plan["receipt_hash"],
                "arxiv_capture_receipt_hash": capture["receipt_hash"],
                "screening_receipt_hash": screening["receipt_hash"],
                "record_id": args.record_id,
                "title": record["title"],
                "pdf_url": pdf_url,
                "remote_ip": ip,
                "tls_verified": True,
                "pdf_sha256": _sha(pdf),
                "pdf_bytes": len(pdf),
                "headers_sha256": _sha((output / "headers.json").read_bytes()),
                "text_sha256": _sha(text.encode()),
                "text_chars": len(text),
                "page_count": pages,
                "read_scope": "all_pdf_bytes_text_extracted_layout_and_figures_unverified",
                "peer_review_status": "unverified_preprint",
                "full_text_bytes_retained": True,
                "full_text_coverage_verified": False,
                "accepted_claim_count": 0,
                "mode_qualified": False,
                "release_authorized": False,
            }
        )
        write_exclusive_json(output / "capture.json", result)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "run_id": plan["run_id"],
                    "record_id": args.record_id,
                    "page_count": pages,
                    "text_chars": len(text),
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        code = error.code if isinstance(error, ContractError) else str(error)
        if not _CODE.fullmatch(code):
            code = "arxiv_fulltext_failed"
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
    from process_limits import guarded_main

    raise SystemExit(guarded_main(main))
