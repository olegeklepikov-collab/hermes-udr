"""Bounded OpenAlex Works metadata acquisition; no full-text evidence promotion."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

from .academic_publisher_raw import _validated_url
from .beta_acquisition import AcquisitionError, _safe_url
from .beta_modes import verify_beta_mode_plan
from .canonical import with_receipt_hash

API_BASE = "https://api.openalex.org/works"
SELECT_FIELDS = (
    "id,doi,display_name,publication_year,type,best_oa_location,abstract_inverted_index"
)
MAX_RAW_BYTES = 250_000
MAX_RECORDS = 3
_WORK_ID = re.compile(r"^https://openalex\.org/W[0-9]+$")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise AcquisitionError("openalex_duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                AcquisitionError("openalex_nonfinite_json")
            ),
        )
    except (UnicodeError, json.JSONDecodeError):
        raise AcquisitionError("openalex_json_invalid") from None
    if type(value) is not dict:
        raise AcquisitionError("openalex_json_invalid")
    return value


def _reconstruct_abstract(value: object) -> tuple[str | None, str]:
    if value is None:
        return None, "not_reported"
    if type(value) is not dict or not value or len(value) > 1000:
        return None, "invalid_inverted_index"
    positions: dict[int, str] = {}
    for word, indexes in value.items():
        if (
            type(word) is not str
            or not 1 <= len(word) <= 80
            or any(character.isspace() or ord(character) < 32 for character in word)
            or type(indexes) is not list
            or not indexes
        ):
            return None, "invalid_inverted_index"
        for position in indexes:
            if (
                type(position) is not int
                or not 0 <= position < 1000
                or position in positions
            ):
                return None, "invalid_inverted_index"
            positions[position] = word
    if (
        not positions
        or len(positions) > 1000
        or set(positions) != set(range(len(positions)))
    ):
        return None, "invalid_inverted_index"
    abstract = " ".join(positions[index] for index in range(len(positions)))
    if len(abstract) > 12_000:
        return None, "invalid_inverted_index"
    return abstract, "reconstructed_inverted_index"


def _metadata_rows(
    value: dict[str, Any], expected_page_size: int
) -> tuple[int, float, list[dict[str, Any]]]:
    meta, results = value.get("meta"), value.get("results")
    if type(meta) is not dict or type(results) is not list:
        raise AcquisitionError("openalex_shape_invalid")
    total, page_size, cost = (
        meta.get("count"),
        meta.get("per_page"),
        meta.get("cost_usd"),
    )
    if type(cost) not in (float, int):
        raise AcquisitionError("openalex_metadata_invalid")
    cost_number = float(cast(int | float, cost))
    if (
        type(total) is not int
        or total < 0
        or type(page_size) is not int
        or page_size != expected_page_size
        or not math.isfinite(cost_number)
        or cost_number < 0
        or len(results) > expected_page_size
    ):
        raise AcquisitionError("openalex_metadata_invalid")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in results:
        if type(item) is not dict:
            raise AcquisitionError("openalex_work_invalid")
        work_id, title, doi, year, work_type = (
            item.get("id"),
            item.get("display_name"),
            item.get("doi"),
            item.get("publication_year"),
            item.get("type"),
        )
        if (
            type(work_id) is not str
            or not _WORK_ID.fullmatch(work_id)
            or work_id in seen_ids
            or type(title) is not str
            or not 1 <= len(title) <= 1000
            or any(ord(character) < 32 for character in title)
            or doi is not None
            and (type(doi) is not str or not doi.startswith("https://doi.org/"))
            or year is not None
            and (type(year) is not int or not 1000 <= year <= 2200)
            or type(work_type) is not str
            or not work_type
        ):
            raise AcquisitionError("openalex_work_invalid")
        location = item.get("best_oa_location")
        oa_location: dict[str, Any] | None = None
        oa_reason = "not_reported"
        if location is not None:
            if type(location) is not dict:
                raise AcquisitionError("openalex_oa_location_invalid")
            landing, pdf, license_name, version = (
                location.get("landing_page_url"),
                location.get("pdf_url"),
                location.get("license"),
                location.get("version"),
            )
            if (
                type(location.get("is_oa")) is not bool
                or license_name is not None
                and (
                    type(license_name) is not str
                    or not re.fullmatch(r"[a-z0-9-]{1,40}", license_name)
                )
                or version is not None
                and (
                    type(version) is not str
                    or version
                    not in {"publishedVersion", "acceptedVersion", "submittedVersion"}
                )
            ):
                raise AcquisitionError("openalex_oa_location_invalid")
            safe_urls: dict[str, str | None] = {}
            for name, location_url in (("landing_page_url", landing), ("pdf_url", pdf)):
                if location_url is None:
                    safe_urls[name] = None
                    continue
                try:
                    safe_urls[name] = _safe_url(location_url)
                except AcquisitionError:
                    try:
                        host = urlsplit(location_url).hostname
                        if not host:
                            raise AcquisitionError("openalex_oa_host_missing")
                        _validated_url(location_url, host, max_query_chars=1800)
                        safe_urls[name] = location_url
                    except (AcquisitionError, ValueError, TypeError):
                        safe_urls[name] = None
            oa_location = {
                "is_oa_reported": location["is_oa"],
                "landing_page_url": safe_urls["landing_page_url"],
                "pdf_url": safe_urls["pdf_url"],
                "license_reported": license_name,
                "version_reported": version,
                "origin_identity_verified": False,
                "full_text_read": False,
            }
            oa_reason = (
                "candidate_location_only" if location["is_oa"] else "not_open_access"
            )
        abstract, abstract_status = _reconstruct_abstract(
            item.get("abstract_inverted_index")
        )
        rows.append(
            {
                "work_id": work_id,
                "title": title,
                "doi": doi,
                "publication_year": year,
                "type": work_type,
                "open_access_location": oa_location,
                "open_access_location_status": oa_reason,
                "abstract_text": abstract,
                "abstract_status": abstract_status,
                "read_scope": "metadata_and_reconstructed_abstract"
                if abstract is not None
                else "metadata_only",
                "full_text_read": False,
            }
        )
        seen_ids.add(work_id)
    return total, cost_number, rows


def acquire_openalex_metadata(
    plan: object,
    leaf_id: str,
    *,
    fetch: Callable[[str], tuple[int, Mapping[str, str], bytes, str, bool, int]],
    observed_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    verified = verify_beta_mode_plan(plan)
    if verified["mode"] not in {"deep", "ultra", "academic"}:
        raise AcquisitionError("openalex_mode_invalid")
    matching = [leaf for leaf in verified["leaves"] if leaf["leaf_id"] == leaf_id]
    if len(matching) != 1 or matching[0]["source_family"] != "scholarly_index":
        raise AcquisitionError("openalex_leaf_not_routed")
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise AcquisitionError("timestamp_naive")
    query = matching[0]["query"]
    url = (
        API_BASE
        + "?"
        + urlencode({"search": query, "per_page": MAX_RECORDS, "select": SELECT_FIELDS})
    )
    status_code, headers, raw, final_url, tls_verified, redirect_count = fetch(url)
    if (
        type(status_code) is not int
        or type(raw) is not bytes
        or len(raw) > MAX_RAW_BYTES
    ):
        raise AcquisitionError("openalex_response_invalid")
    remaining_raw = headers.get("x-ratelimit-remaining") or headers.get(
        "X-RateLimit-Remaining"
    )
    remaining = (
        int(remaining_raw)
        if type(remaining_raw) is str
        and 1 <= len(remaining_raw) <= 12
        and remaining_raw.isascii()
        and remaining_raw.isdecimal()
        else None
    )
    filename = f"{leaf_id}.openalex.raw.json"
    files = {filename: raw}
    proof_valid = (
        final_url == url
        and tls_verified is True
        and type(redirect_count) is int
        and redirect_count == 0
    )
    reason = "not_evaluated"
    total: int | None = None
    cost: float | None = None
    rows: list[dict[str, Any]] = []
    if not proof_valid:
        reason = "transport_identity_unverified"
    elif status_code != 200:
        reason = "http_status_not_200"
    else:
        try:
            total, cost, rows = _metadata_rows(_strict_json(raw), MAX_RECORDS)
        except AcquisitionError as error:
            reason = error.code
        else:
            reason = "metadata_candidates_retained"
            if cost > verified["limits"]["max_estimated_cost_usd"]:
                reason = "provider_cost_over_plan_limit"
    status = (
        "partial_candidate" if reason == "metadata_candidates_retained" else "blocked"
    )
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaOpenAlexMetadataAcquisition",
            "status": status,
            "reason": reason,
            "run_id": verified["run_id"],
            "mode": verified["mode"],
            "leaf_id": leaf_id,
            "plan_receipt_hash": verified["receipt_hash"],
            "observed_at": now.astimezone(UTC).isoformat(),
            "provider": "openalex",
            "provider_contract_url": "https://help.openalex.org/api/",
            "provider_identity_verified": proof_valid,
            "source_family": "scholarly_index",
            "source_origin_independence_verified": False,
            "request_url_sha256": _sha(url.encode("utf-8")),
            "http_status": status_code,
            "response_sha256": _sha(raw),
            "response_bytes": len(raw),
            "response_file": filename,
            "reported_total": total,
            "reported_cost_usd": cost,
            "rate_limit_remaining": remaining,
            "works": rows,
            "candidate_count": len(rows),
            "full_text_read": False,
            "semantic_support_verified": False,
            "qualification_status": "not_verified",
            "release_authorized": False,
            "external_delivery_authorized": False,
        }
    )
    return receipt, files
