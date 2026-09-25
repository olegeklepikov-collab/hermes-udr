"""Bounded publisher-text candidate for one exact OpenAlex work."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from .academic_openalex import _WORK_ID
from .beta_acquisition import (
    _TRUNCATION,
    MAX_SOURCE_CHARS,
    AcquisitionError,
    _safe_url,
    _strict_json,
)
from .beta_modes import verify_beta_mode_plan
from .canonical import verify_receipt_hash, with_receipt_hash


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def article_source_id(work_id: str, text_sha256: str) -> str:
    if not _WORK_ID.fullmatch(work_id) or not re.fullmatch(
        r"[0-9a-f]{64}", text_sha256
    ):
        raise AcquisitionError("oa_source_identity_invalid")
    return "SRC-" + _sha((work_id + "\0" + text_sha256).encode("utf-8"))[:16].upper()


def _final_url(
    value: object, expected_host: str, requested_doi: str
) -> tuple[str, str, str]:
    if type(value) is not str or not 0 < len(value) <= 2048:
        raise AcquisitionError("oa_final_url_invalid")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise AcquisitionError("oa_final_url_invalid") from None
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.fragment
        or len(parsed.query) > 500
    ):
        raise AcquisitionError("oa_final_url_invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise AcquisitionError("oa_final_url_invalid")
    safe = f"https://{host}{parsed.path or '/'}"
    _safe_url(safe)
    if host.lower().rstrip(".") == expected_host:
        scope = "reported_publisher_host"
    elif value == requested_doi:
        scope = "requested_doi_resolver_only"
    else:
        raise AcquisitionError("oa_final_url_invalid")
    return safe, _sha(value.encode("utf-8")), scope


def acquire_openalex_oa_text(
    plan: object,
    metadata: object,
    work_id: str,
    *,
    extract: Callable[[list[str]], str],
    observed_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    verified = verify_beta_mode_plan(plan)
    if verified["schema_version"] != 2 or verified["mode"] not in {
        "deep",
        "ultra",
        "academic",
    }:
        raise AcquisitionError("oa_plan_not_executable")
    if type(metadata) is not dict or not verify_receipt_hash(metadata):
        raise AcquisitionError("oa_metadata_receipt_invalid")
    if (
        metadata.get("contract") != "BetaOpenAlexMetadataAcquisition"
        or metadata.get("status") != "partial_candidate"
        or metadata.get("provider_identity_verified") is not True
        or metadata.get("run_id") != verified["run_id"]
        or metadata.get("mode") != verified["mode"]
        or metadata.get("plan_receipt_hash") != verified["receipt_hash"]
        or metadata.get("release_authorized") is not False
    ):
        raise AcquisitionError("oa_metadata_not_bound")
    leaf_id = metadata.get("leaf_id")
    if not any(
        leaf["leaf_id"] == leaf_id and leaf["source_family"] == "scholarly_index"
        for leaf in verified["leaves"]
    ):
        raise AcquisitionError("oa_leaf_not_bound")
    if type(work_id) is not str or not _WORK_ID.fullmatch(work_id):
        raise AcquisitionError("oa_work_id_invalid")
    works = metadata.get("works")
    matches = (
        [
            work
            for work in works
            if type(work) is dict and work.get("work_id") == work_id
        ]
        if type(works) is list
        else []
    )
    if len(matches) != 1:
        raise AcquisitionError("oa_work_not_in_metadata")
    work = matches[0]
    location = work.get("open_access_location")
    if type(location) is not dict:
        raise AcquisitionError("oa_location_not_eligible")
    doi = work.get("doi")
    pdf_url = location.get("pdf_url")
    if (
        location.get("is_oa_reported") is not True
        or location.get("license_reported") not in {"cc0", "cc-by"}
        or location.get("version_reported")
        not in {"publishedVersion", "acceptedVersion"}
        or type(doi) is not str
        or not doi.startswith("https://doi.org/")
        or type(pdf_url) is not str
    ):
        raise AcquisitionError("oa_location_not_eligible")
    _safe_url(doi)
    expected_host = urlsplit(pdf_url).hostname
    if not expected_host:
        raise AcquisitionError("oa_location_not_eligible")
    _final_url(pdf_url, expected_host, doi)
    title = work.get("title")
    if type(title) is not str or not 5 <= len(title) <= 1000:
        raise AcquisitionError("oa_work_title_invalid")
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise AcquisitionError("timestamp_naive")
    raw = extract([doi])
    data = _strict_json(raw)
    artifacts: dict[str, bytes] = {}
    raw_name = f"{leaf_id}.oa-extract.raw.json"
    artifacts[raw_name] = raw.encode("utf-8")
    reason = "not_evaluated"
    final_url: str | None = None
    final_url_sha: str | None = None
    final_url_scope: str | None = None
    text: str | None = None
    results = data.get("results")
    if type(results) is not list or len(results) != 1 or type(results[0]) is not dict:
        reason = "oa_extract_shape_invalid"
    else:
        result = results[0]
        if result.get("error") or result.get("blocked_by_policy"):
            reason = "oa_extract_failed"
        else:
            try:
                final_url, final_url_sha, final_url_scope = _final_url(
                    result.get("url"), expected_host, doi
                )
            except AcquisitionError as error:
                reason = error.code
            else:
                content = result.get("content")
                if (
                    type(content) is not str
                    or not 1000 <= len(content) <= MAX_SOURCE_CHARS
                    or any(marker in content for marker in _TRUNCATION)
                ):
                    reason = "oa_text_incomplete_or_invalid"
                else:
                    doi_suffix = doi.removeprefix("https://doi.org/")
                    normalized_title = re.sub(r"\W+", " ", title).strip().casefold()
                    normalized_content = re.sub(r"\W+", " ", content).casefold()
                    if (
                        normalized_title not in normalized_content
                        or doi_suffix.casefold() not in content.casefold()
                    ):
                        reason = "oa_work_identity_text_mismatch"
                    else:
                        text = content
                        reason = "publisher_text_candidate_retained"
    text_name = f"{leaf_id}.oa-text.txt" if text is not None else None
    if text_name is not None and text is not None:
        artifacts[text_name] = text.encode("utf-8")
    source_id = (
        article_source_id(work_id, _sha(text.encode("utf-8")))
        if text is not None
        else None
    )
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaOpenAlexArticleTextAcquisition",
            "status": "article_text_candidate" if text is not None else "blocked",
            "reason": reason,
            "run_id": verified["run_id"],
            "mode": verified["mode"],
            "leaf_id": leaf_id,
            "work_id": work_id,
            "source_id": source_id,
            "doi": doi,
            "title": title,
            "plan_receipt_hash": verified["receipt_hash"],
            "metadata_receipt_hash": metadata["receipt_hash"],
            "observed_at": now.astimezone(UTC).isoformat(),
            "requested_doi_sha256": _sha(doi.encode("utf-8")),
            "expected_pdf_host": expected_host,
            "final_url_without_query": final_url,
            "final_url_sha256": final_url_sha,
            "final_url_scope": final_url_scope,
            "redirect_chain_verified": False,
            "raw_response_file": raw_name,
            "raw_response_sha256": _sha(artifacts[raw_name]),
            "raw_response_bytes": len(artifacts[raw_name]),
            "text_file": text_name,
            "text_sha256": _sha(artifacts[text_name]) if text_name else None,
            "text_bytes": len(artifacts[text_name]) if text_name else None,
            "reported_license": location["license_reported"],
            "reported_version": location["version_reported"],
            "publisher_license_verified": False,
            "source_origin_independence_verified": False,
            "full_text_coverage_verified": False,
            "read_scope": "extracted_article_text_unverified_completeness"
            if text
            else "none",
            "mode_qualified": False,
            "release_authorized": False,
            "external_delivery_authorized": False,
        }
    )
    return receipt, artifacts
