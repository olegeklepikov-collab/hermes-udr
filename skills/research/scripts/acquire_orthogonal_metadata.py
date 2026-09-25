"""Bounded public reads for four orthogonal research metadata capabilities.

This command is deliberately narrow: fixed HTTPS hosts, validated identifiers,
no credentials, no redirects, one response per invocation, and no claim that
metadata alone supports a research conclusion. It complements the existing
DataCite dataset DOI acquisition command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import (
        fsync_directory,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
except ImportError:
    from file_io import (
        fsync_directory,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )

from hermes_research_report.canonical import with_receipt_hash
from hermes_research_report.runtime_snapshot import runtime_guarded

MAX_RAW_BYTES = 2_000_000
PROVIDER_DOCS = {
    "europe_pmc": "https://europepmc.org/RestfulWebService",
    "pmc": "https://europepmc.org/RestfulWebService",
    "orcid": "https://info.orcid.org/documentation/api-tutorials/api-tutorial-read-data-on-a-record/",
    "ror": "https://ror.readme.io/docs/rest-api",
    "common_crawl": "https://index.commoncrawl.org/",
}
CAPABILITIES = {
    "europe_pmc": "biomedical_fulltext",
    "pmc": "biomedical_fulltext",
    "orcid": "researcher_identity",
    "ror": "organization_identity",
    "common_crawl": "historical_web",
}
_JATS_DOCTYPE = re.compile(
    rb'<!DOCTYPE\s+article(?:\s+PUBLIC\s+"[^"<>\[\]]{1,400}"\s+"[^"<>\[\]]{1,400}"'
    rb'|\s+SYSTEM\s+"[^"<>\[\]]{1,400}")?\s*>',
    re.IGNORECASE,
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_url(provider: str, identifier: str, *, index: str | None = None) -> str:
    if provider == "europe_pmc":
        if not re.fullmatch(r"[0-9]{1,12}", identifier):
            raise ValueError("pmid_invalid")
        return "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urlencode(
            {"query": f"EXT_ID:{identifier}", "format": "json", "pageSize": 1}
        )
    if provider == "pmc":
        if not re.fullmatch(r"PMC[0-9]{1,12}", identifier):
            raise ValueError("pmcid_invalid")
        return (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/{identifier}/fullTextXML"
        )
    if provider == "orcid":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]", identifier):
            raise ValueError("orcid_invalid")
        return f"https://pub.orcid.org/v3.0/{identifier}/record"
    if provider == "ror":
        if not re.fullmatch(r"0[0-9a-z]{8}", identifier):
            raise ValueError("ror_invalid")
        return f"https://api.ror.org/v2/organizations/{identifier}"
    if provider == "common_crawl":
        parsed = urlsplit(identifier)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port
            or parsed.hostname in {"localhost", "127.0.0.1"}
        ):
            raise ValueError("archive_target_invalid")
        if not index or not re.fullmatch(r"CC-MAIN-[0-9]{4}-[0-9]{2}", index):
            raise ValueError("archive_index_invalid")
        return f"https://index.commoncrawl.org/{index}-index?" + urlencode(
            {
                "url": identifier,
                "output": "json",
                "filter": "status:200",
                "matchType": "exact",
            }
        )
    raise ValueError("provider_unsupported")


def _strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError("nonfinite_json")
        ),
    )


def assess_response(provider: str, identifier: str, raw: bytes) -> dict:
    """Return only identity-checked metadata; never infer semantic support."""
    if provider == "pmc":
        upper = raw.upper()
        if b"<!ENTITY" in upper:
            raise ValueError("xml_active_declaration")
        if b"<!DOCTYPE" in upper:
            declarations = list(_JATS_DOCTYPE.finditer(raw))
            if len(declarations) != 1 or upper.count(b"<!DOCTYPE") != 1:
                raise ValueError("xml_active_declaration")
            declaration = declarations[0]
            # Strip the external DTD reference before ElementTree sees it. Internal
            # subsets and entity declarations never match the bounded JATS shape.
            raw = raw[: declaration.start()] + raw[declaration.end() :]
        root = ET.fromstring(raw)
        ids = [x.text for x in root.findall(".//article-id[@pub-id-type='pmc']")]
        ids += [x.text for x in root.findall(".//article-id[@pub-id-type='pmcid']")]
        if root.tag != "article" or not ({identifier, identifier[3:]} & set(ids)):
            raise ValueError("pmc_identity_mismatch")
        title = " ".join(root.findtext(".//article-title", default="").split())
        # ElementTree.findtext only captures direct text; count itertext for scope.
        body = root.find(".//body")
        body_chars = (
            len(" ".join(" ".join(body.itertext()).split())) if body is not None else 0
        )
        if not title or body_chars == 0:
            raise ValueError("pmc_fulltext_missing")
        return {
            "identity": identifier,
            "title": title,
            "body_characters": body_chars,
            "read_scope": "open_access_fulltext_xml",
            "semantic_support_verified": False,
        }
    if provider == "common_crawl":
        rows = [_strict_json(line) for line in raw.splitlines() if line.strip()]
        if not rows or any(type(row) is not dict for row in rows):
            raise ValueError("archive_index_shape_invalid")
        matches = [
            row
            for row in rows
            if row.get("url") == identifier
            and row.get("status") == "200"
            and re.fullmatch(r"[0-9]{14}", str(row.get("timestamp", "")))
            and isinstance(row.get("filename"), str)
        ]
        if not matches:
            raise ValueError("archive_capture_missing")
        first = matches[0]
        return {
            "identity": identifier,
            "capture_count": len(matches),
            "first_timestamp": first["timestamp"],
            "first_warc_ref": first["filename"],
            "read_scope": "archive_index_metadata_only",
            "archived_page_read": False,
            "semantic_support_verified": False,
        }
    data = _strict_json(raw)
    if type(data) is not dict:
        raise ValueError("metadata_shape_invalid")
    if provider == "europe_pmc":
        result_list = data.get("resultList")
        if type(result_list) is not dict or type(result_list.get("result")) is not list:
            raise ValueError("europe_pmc_shape_invalid")
        rows = result_list["result"]
        if any(type(row) is not dict for row in rows):
            raise ValueError("europe_pmc_shape_invalid")
        matches = [row for row in rows if str(row.get("id")) == identifier]
        if not matches:
            raise ValueError("pmid_identity_mismatch")
        row = matches[0]
        return {
            "identity": identifier,
            "pmcid": row.get("pmcid"),
            "title": row.get("title"),
            "read_scope": "biomedical_metadata_only",
            "fulltext_read": False,
            "semantic_support_verified": False,
        }
    if provider == "orcid":
        identifier_record = data.get("orcid-identifier")
        if (
            type(identifier_record) is not dict
            or identifier_record.get("path") != identifier
        ):
            raise ValueError("orcid_identity_mismatch")
        return {
            "identity": identifier,
            "read_scope": "public_researcher_identity_only",
            "semantic_support_verified": False,
        }
    if provider == "ror":
        if data.get("id") != f"https://ror.org/{identifier}":
            raise ValueError("ror_identity_mismatch")
        return {
            "identity": identifier,
            "read_scope": "organization_identity_only",
            "semantic_support_verified": False,
        }
    raise ValueError("provider_unsupported")


def fetch_once(url: str, provider: str) -> tuple[int, bytes, str]:
    opener = build_opener(
        HTTPSHandler(context=ssl.create_default_context()), NoRedirect()
    )
    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/xml" if provider == "pmc" else "application/json",
            "User-Agent": "UltraDeepResearchOrthogonal/0.41.0a1",
        },
    )
    try:
        with opener.open(request, timeout=15) as response:
            return response.status, response.read(MAX_RAW_BYTES + 1), response.geturl()
    except HTTPError as error:
        return error.code, error.read(MAX_RAW_BYTES + 1), error.geturl()


@runtime_guarded
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=sorted(PROVIDER_DOCS), required=True)
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--index")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-query-ack", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.public_query_ack:
            raise ValueError("public_query_ack_required")
        url = request_url(args.provider, args.identifier, index=args.index)
        new_private_directory(args.output)
        write_exclusive_json(
            args.output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "provider": args.provider,
                "capability": CAPABILITIES[args.provider],
                "request_url_sha256": hashlib.sha256(url.encode()).hexdigest(),
                "retry_allowed": False,
            },
        )
        status, raw, final_url = fetch_once(url, args.provider)
        retained = raw[:MAX_RAW_BYTES]
        write_exclusive_bytes(args.output / "response.raw", retained)
        reason = None
        record = None
        if final_url != url:
            reason = "provider_redirect_or_identity_change"
        elif status != 200:
            reason = f"http_{status}"
        elif len(raw) > MAX_RAW_BYTES:
            reason = "response_size_exceeded"
        else:
            try:
                record = assess_response(args.provider, args.identifier, retained)
            except (
                ValueError,
                TypeError,
                KeyError,
                ET.ParseError,
                UnicodeError,
            ) as error:
                reason = str(error)[:120]
        receipt = with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "OrthogonalPublicMetadataAcquisition",
                "status": "partial_candidate" if record is not None else "blocked",
                "reason": reason,
                "provider": args.provider,
                "capability": CAPABILITIES[args.provider],
                "identifier": args.identifier,
                "index": args.index if args.provider == "common_crawl" else None,
                "request_url_sha256": hashlib.sha256(url.encode()).hexdigest(),
                "provider_contract_url": PROVIDER_DOCS[args.provider],
                "http_status": status,
                "response_file": "response.raw",
                "response_sha256": hashlib.sha256(retained).hexdigest(),
                "response_bytes": len(retained),
                "response_truncated": len(raw) > MAX_RAW_BYTES,
                "observed_at": datetime.now(UTC).isoformat(),
                "record": record,
                "external_call_count": 1,
                "release_authorized": False,
            }
        )
        write_exclusive_json(args.output / "capture.json", receipt)
        fsync_directory(args.output)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "provider": args.provider,
                    "receipt_hash": receipt["receipt_hash"],
                }
            )
        )
        return 0 if record is not None else 2
    except (ValueError, OSError) as error:
        print(
            json.dumps({"status": "error", "code": str(error)[:120]}), file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
