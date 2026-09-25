"""One bounded arXiv Atom metadata query with explicit preprint version."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

from .beta_acquisition import AcquisitionError
from .beta_modes import ARXIV_VERSIONED_ID, verify_beta_mode_plan
from .canonical import with_receipt_hash

API_BASE = "https://export.arxiv.org/api/query"
MAX_RAW_BYTES = 250_000
MAX_RECORDS = 3
ATOM = "{http://www.w3.org/2005/Atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
_VERSION = re.compile(r"v([1-9][0-9]*)$")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _text(element: ET.Element, name: str, *, maximum: int) -> str:
    value = element.findtext(ATOM + name)
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise AcquisitionError("arxiv_entry_invalid")
    return " ".join(value.split())


def _entry_id(value: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname != "arxiv.org"
        or not parsed.path.startswith("/abs/")
        or parsed.query
        or parsed.fragment
        or len(parsed.path) > 100
    ):
        raise AcquisitionError("arxiv_entry_id_invalid")
    suffix = parsed.path.removeprefix("/abs/")
    if not suffix or any(char.isspace() for char in suffix):
        raise AcquisitionError("arxiv_entry_id_invalid")
    match = _VERSION.search(suffix)
    return (
        "https://arxiv.org" + parsed.path,
        suffix[: match.start()] if match else suffix,
        int(match.group(1)) if match else None,
    )


def _records(raw: bytes) -> tuple[int, list[dict[str, Any]]]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise AcquisitionError("arxiv_xml_entity_forbidden")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise AcquisitionError("arxiv_atom_invalid") from None
    if root.tag != ATOM + "feed":
        raise AcquisitionError("arxiv_atom_invalid")
    total_text = root.findtext(OPENSEARCH + "totalResults")
    if (
        type(total_text) is not str
        or not total_text.isascii()
        or not total_text.isdecimal()
    ):
        raise AcquisitionError("arxiv_total_invalid")
    total = int(total_text)
    entries = root.findall(ATOM + "entry")
    if len(entries) > MAX_RECORDS:
        raise AcquisitionError("arxiv_result_limit_exceeded")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        url, base_id, version = _entry_id(_text(entry, "id", maximum=200))
        if url in seen:
            raise AcquisitionError("arxiv_duplicate_entry")
        seen.add(url)
        title = _text(entry, "title", maximum=1000)
        abstract = _text(entry, "summary", maximum=10_000)
        published = _text(entry, "published", maximum=64)
        updated = _text(entry, "updated", maximum=64)
        try:
            for value in (published, updated):
                if datetime.fromisoformat(value).tzinfo is None:
                    raise ValueError
        except ValueError:
            raise AcquisitionError("arxiv_date_invalid") from None
        rows.append(
            {
                "versioned_url": url,
                "base_id": base_id,
                "version": version,
                "title": title,
                "abstract": abstract,
                "published": published,
                "updated": updated,
                "read_scope": "parsed_atom_abstract_only",
                "full_text_read": False,
                "peer_review_status": "unverified_preprint",
            }
        )
    return total, rows


def acquire_arxiv_metadata(
    plan: object,
    leaf_id: str,
    *,
    fetch: Callable[[str], tuple[int, Mapping[str, str], bytes, str, bool, int]],
    observed_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    verified = verify_beta_mode_plan(plan)
    if verified["mode"] not in {"deep", "ultra", "academic"}:
        raise AcquisitionError("arxiv_mode_invalid")
    matching = [leaf for leaf in verified["leaves"] if leaf["leaf_id"] == leaf_id]
    if len(matching) != 1 or matching[0]["source_family"] != "preprint_archive":
        raise AcquisitionError("arxiv_leaf_not_routed")
    query = matching[0]["query"]
    versioned_id = (
        query.removeprefix("id_list:") if query.startswith("id_list:") else None
    )
    if versioned_id is not None:
        if not ARXIV_VERSIONED_ID.fullmatch(versioned_id):
            raise AcquisitionError("arxiv_query_not_structured")
    elif not re.match(r"^(all|ti|abs|au|cat):", query):
        raise AcquisitionError("arxiv_query_not_structured")
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise AcquisitionError("timestamp_naive")
    parameters = (
        {"id_list": versioned_id, "start": 0, "max_results": MAX_RECORDS}
        if versioned_id is not None
        else {"search_query": query, "start": 0, "max_results": MAX_RECORDS}
    )
    url = API_BASE + "?" + urlencode(parameters)
    status_code, _headers, raw, final_url, tls_verified, redirects = fetch(url)
    if type(status_code) is not int or type(raw) is not bytes:
        raise AcquisitionError("arxiv_response_invalid")
    response_truncated = len(raw) > MAX_RAW_BYTES
    retained = raw[:MAX_RAW_BYTES]
    proof_valid = (
        final_url == url
        and tls_verified is True
        and type(redirects) is int
        and redirects == 0
    )
    reason = "not_evaluated"
    total: int | None = None
    rows: list[dict[str, Any]] = []
    if not proof_valid:
        reason = "transport_identity_unverified"
    elif response_truncated:
        reason = "response_size_exceeded"
    elif status_code != 200:
        reason = "http_status_not_200"
    else:
        try:
            total, rows = _records(retained)
        except AcquisitionError as error:
            reason = error.code
        else:
            if versioned_id is not None and (
                len(rows) != 1
                or rows[0]["versioned_url"] != f"https://arxiv.org/abs/{versioned_id}"
            ):
                rows = []
                reason = "versioned_id_not_returned"
            else:
                reason = "preprint_metadata_retained"
    filename = f"{leaf_id}.arxiv.raw.atom"
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaArxivMetadataAcquisition",
            "status": "partial_candidate"
            if reason == "preprint_metadata_retained"
            else "blocked",
            "reason": reason,
            "run_id": verified["run_id"],
            "mode": verified["mode"],
            "leaf_id": leaf_id,
            "plan_receipt_hash": verified["receipt_hash"],
            "observed_at": now.astimezone(UTC).isoformat(),
            "provider": "arxiv",
            "provider_contract_url": "https://info.arxiv.org/help/api/user-manual.html",
            "provider_identity_verified": proof_valid,
            "source_family": "preprint_archive",
            "source_origin_independence_verified": False,
            "request_url_sha256": _sha(url.encode()),
            "request_selector": "id_list"
            if versioned_id is not None
            else "search_query",
            "requested_versioned_id": versioned_id,
            "http_status": status_code,
            "response_file": filename,
            "response_sha256": _sha(retained),
            "response_bytes": len(retained),
            "response_truncated": response_truncated,
            "observed_response_bytes_at_least": len(raw),
            "reported_total": total,
            "candidate_count": len(rows),
            "preprints": rows,
            "full_text_read": False,
            "semantic_support_verified": False,
            "qualification_status": "not_verified",
            "release_authorized": False,
            "external_delivery_authorized": False,
        }
    )
    return receipt, {filename: retained}
