"""Bounded public DataCite Dataset DOI metadata discovery, not dataset reading."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from .beta_acquisition import AcquisitionError, _safe_url
from .beta_modes import verify_beta_mode_plan
from .canonical import with_receipt_hash

API_BASE = "https://api.datacite.org/dois"
MAX_RAW_BYTES = 1_048_576
MAX_RECORDS = 3
_DOI = re.compile(r"^10\.[0-9]{4,9}/[^\s]{1,240}$", re.IGNORECASE)


def _strict_json(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise AcquisitionError("datacite_duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                AcquisitionError("datacite_nonfinite_json")
            ),
        )
    except (UnicodeError, json.JSONDecodeError):
        raise AcquisitionError("datacite_json_invalid") from None
    if type(value) is not dict:
        raise AcquisitionError("datacite_json_invalid")
    return value


def _text(value: object, *, maximum: int = 1000) -> str | None:
    if (
        type(value) is not str
        or not 1 <= len(value.strip()) <= maximum
        or any(ord(char) < 32 for char in value)
    ):
        return None
    return value.strip()


def _metadata_rows(value: dict[str, Any]) -> tuple[int, list[dict[str, Any]], int]:
    meta, data = value.get("meta"), value.get("data")
    if (
        type(meta) is not dict
        or type(meta.get("total")) is not int
        or meta["total"] < 0
        or type(data) is not list
        or len(data) > MAX_RECORDS
    ):
        raise AcquisitionError("datacite_shape_invalid")
    rows = []
    invalid = 0
    seen: set[str] = set()
    for item in data:
        if type(item) is not dict or item.get("type") != "dois":
            invalid += 1
            continue
        attributes = item.get("attributes")
        if type(attributes) is not dict:
            invalid += 1
            continue
        doi = attributes.get("doi")
        titles = attributes.get("titles")
        types = attributes.get("types")
        if (
            type(doi) is not str
            or not _DOI.fullmatch(doi)
            or type(item.get("id")) is not str
            or item.get("id", "").casefold() != doi.casefold()
            or doi.casefold() in seen
            or type(titles) is not list
            or not titles
            or type(titles[0]) is not dict
            or (title := _text(titles[0].get("title"))) is None
            or type(types) is not dict
            or types.get("resourceTypeGeneral") != "Dataset"
        ):
            invalid += 1
            continue
        landing = attributes.get("url")
        try:
            safe_landing = _safe_url(landing)
        except AcquisitionError:
            safe_landing = None
        year = attributes.get("publicationYear")
        if year is not None and (type(year) is not int or not 1000 <= year <= 2200):
            year = None
        rows.append(
            {
                "doi": doi.lower(),
                "title": title,
                "publisher_reported": _text(attributes.get("publisher")),
                "publication_year": year,
                "resource_type_general_reported": "Dataset",
                "landing_url": safe_landing,
                "landing_url_identity_verified": False,
                "dataset_content_read": False,
                "dataset_schema_verified": False,
                "read_scope": "datacite_doi_metadata_only",
            }
        )
        seen.add(doi.casefold())
    return meta["total"], rows, invalid


def acquire_datacite_datasets(
    plan: object,
    leaf_id: str,
    *,
    fetch: Callable[[str], tuple[int, Mapping[str, str], bytes, str, bool, int]],
    observed_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    verified = verify_beta_mode_plan(plan)
    matching = [leaf for leaf in verified["leaves"] if leaf["leaf_id"] == leaf_id]
    if (
        verified["schema_version"] != 2
        or verified["mode"] not in {"deep", "ultra", "academic"}
        or len(matching) != 1
        or matching[0]["source_family"] != "dataset"
    ):
        raise AcquisitionError("datacite_leaf_not_routed")
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise AcquisitionError("timestamp_naive")
    query = matching[0]["query"]
    url = (
        API_BASE
        + "?"
        + urlencode(
            {"query": query, "resource-type-id": "dataset", "page[size]": MAX_RECORDS}
        )
    )
    status_code, _headers, raw, final_url, tls_verified, redirects = fetch(url)
    if type(raw) is not bytes:
        raise AcquisitionError("datacite_response_invalid")
    response_truncated = len(raw) > MAX_RAW_BYTES
    retained = raw[:MAX_RAW_BYTES]
    filename = f"{leaf_id}.datacite.raw.json"
    files = {filename: retained}
    transport_ok = (
        status_code == 200
        and final_url == url
        and tls_verified is True
        and redirects == 0
    )
    total = None
    records: list[dict[str, Any]] = []
    invalid = 0
    reason = "transport_identity_unverified" if not transport_ok else "not_evaluated"
    if transport_ok and response_truncated:
        reason = "response_size_exceeded"
    elif transport_ok:
        try:
            total, records, invalid = _metadata_rows(_strict_json(retained))
        except AcquisitionError as error:
            reason = error.code
        else:
            reason = (
                "dataset_doi_metadata_candidates_retained"
                if records
                else "no_valid_dataset_metadata"
            )
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaDataCiteDatasetMetadataAcquisition",
            "status": "partial_candidate" if records else "blocked",
            "reason": reason,
            "run_id": verified["run_id"],
            "mode": verified["mode"],
            "leaf_id": leaf_id,
            "plan_receipt_hash": verified["receipt_hash"],
            "observed_at": now.astimezone(UTC).isoformat(),
            "provider": "datacite",
            "provider_contract_url": "https://support.datacite.org/docs/api-get-lists",
            "provider_identity_verified": transport_ok,
            "source_family": "dataset",
            "request_url_sha256": hashlib.sha256(url.encode()).hexdigest(),
            "http_status": status_code,
            "response_file": filename,
            "response_sha256": hashlib.sha256(retained).hexdigest(),
            "response_bytes": len(retained),
            "response_truncated": response_truncated,
            "observed_response_bytes_at_least": len(raw),
            "reported_total": total,
            "records": records,
            "candidate_count": len(records),
            "invalid_metadata_record_count": invalid,
            "dataset_content_read": False,
            "dataset_schema_verified": False,
            "source_origin_independence_verified": False,
            "semantic_support_verified": False,
            "reported_cost_usd": 0.0,
            "cost_reporting_basis": "public_metadata_route_no_provider_charge_reported",
            "qualification_status": "not_verified",
            "release_authorized": False,
            "external_delivery_authorized": False,
        }
    )
    return receipt, files
