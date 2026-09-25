"""Bounded source acquisition for a verified beta plan, without evidence promotion."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, unquote_to_bytes, urlsplit

from .beta_modes import verify_beta_mode_plan
from .canonical import with_receipt_hash

MAX_RAW_BYTES = 250_000
MAX_SOURCE_CHARS = 50_000
_TRUNCATION = ("[TRUNCATED]", "[... middle omitted", "Full text saved to:")
_SENSITIVE_QUERY_KEY = re.compile(
    r"(?:^|[_-])(?:token|secret|password|key|apikey|api_key|auth|signature|sig|credential|session)(?:$|[_-])",
    re.IGNORECASE,
)


class AcquisitionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw: str) -> dict[str, Any]:
    if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= MAX_RAW_BYTES:
        raise AcquisitionError("provider_response_invalid")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise AcquisitionError("provider_duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                AcquisitionError("provider_nonfinite_json")
            ),
        )
    except (json.JSONDecodeError, UnicodeError):
        raise AcquisitionError("provider_response_invalid") from None
    if type(value) is not dict:
        raise AcquisitionError("provider_response_invalid")
    return value


def _safe_url(value: object) -> str:
    if type(value) is not str or not 0 < len(value) <= 2048:
        raise AcquisitionError("source_url_invalid")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise AcquisitionError("source_url_invalid") from None
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.fragment
        or port not in (None, 443)
    ):
        raise AcquisitionError("source_url_invalid")
    query = parsed.query
    if query:
        if (
            len(query) > 500
            or not query.isascii()
            or re.search(r"%(?![0-9A-Fa-f]{2})|[\x00-\x20\x7f]", query)
            or any(byte < 32 or byte == 127 for byte in unquote_to_bytes(query))
        ):
            raise AcquisitionError("source_url_invalid")
        try:
            parameters = parse_qsl(query, keep_blank_values=True, max_num_fields=32)
        except ValueError:
            raise AcquisitionError("source_url_invalid") from None
        if not parameters or any(_SENSITIVE_QUERY_KEY.search(key) for key, _ in parameters):
            raise AcquisitionError("source_url_invalid")
    host = host.lower().rstrip(".")
    if "." not in host or host.endswith((".local", ".localhost", ".internal")):
        raise AcquisitionError("source_url_invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise AcquisitionError("source_url_invalid")
    return value


def _missing_concept_groups(
    title: str, content: str, groups: list[list[str]]
) -> list[int]:
    text = (title + "\n" + content).casefold()

    def present(term: str) -> bool:
        words = re.findall(r"\w+", term.casefold())
        if re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", text):
            return True
        if not 2 <= len(words) <= 3 or any(len(word) < 3 for word in words):
            return False
        first = re.compile(r"(?<!\w)" + re.escape(words[0]) + r"(?!\w)")
        others = [
            re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)") for word in words[1:]
        ]
        for match in first.finditer(text):
            window = text[max(0, match.start() - 250) : match.end() + 250]
            if all(pattern.search(window) for pattern in others):
                return True
        return False

    return [
        index
        for index, group in enumerate(groups)
        if not any(present(term) for term in group)
    ]


def _canonical_extracted_url(requested: str, observed: object) -> tuple[str, str]:
    final = _safe_url(observed)
    if final == requested:
        return final, "none"
    before, after = urlsplit(requested), urlsplit(final)
    if before.port != after.port or before.query != after.query:
        raise AcquisitionError("extract_url_mismatch")
    before_host, after_host = before.hostname or "", after.hostname or ""
    if before.path == after.path and after_host == "www." + before_host:
        return final, "www_host_added_unattested"
    if before.path == after.path and before_host == "www." + after_host:
        return final, "www_host_removed_unattested"
    if before_host == after_host and before.path + "/" == after.path:
        return final, "trailing_slash_added_unattested"
    if before_host == after_host and before.path == after.path + "/":
        return final, "trailing_slash_removed_unattested"
    raise AcquisitionError("extract_url_mismatch")


def acquire_beta_sources(
    plan: object,
    *,
    search: Callable[[str, int], str],
    extract: Callable[[list[str]], str],
    selected_leaf_id: str | None = None,
    route_proof: dict[str, object] | None = None,
    max_candidates_per_leaf: int = 1,
    observed_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Retain bounded candidates; the first eligible source remains the leaf summary."""
    if (
        type(max_candidates_per_leaf) is not int
        or not 1 <= max_candidates_per_leaf <= 3
    ):
        raise AcquisitionError("candidate_read_limit_invalid")
    verified = verify_beta_mode_plan(plan)
    pinned_route = route_proof == {
        "search_backend": "keenable",
        "extract_backend": "keenable",
        "keyless_ring": ["keenable"],
        "keyless_rescue": False,
        "provider_tier": "free",
    }
    if route_proof is not None and not pinned_route:
        raise AcquisitionError("web_route_proof_invalid")
    leaves = verified["leaves"]
    if selected_leaf_id is not None:
        leaves = [leaf for leaf in leaves if leaf["leaf_id"] == selected_leaf_id]
        if len(leaves) != 1 or leaves[0]["source_family"] not in {"web", "official"}:
            raise AcquisitionError("web_leaf_not_routed")
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise AcquisitionError("timestamp_naive")
    files: dict[str, bytes] = {}
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    search_calls = 0
    extract_calls = 0
    for leaf in leaves:
        leaf_id = leaf["leaf_id"]
        row: dict[str, Any] = {
            "leaf_id": leaf_id,
            "declared_source_family": leaf["source_family"],
            "family_verified": False,
            "configured_route": "keenable" if pinned_route else "unverified",
            "route_configuration_verified": pinned_route,
            "status": "failed",
            "reason": "not_attempted",
        }
        rows.append(row)
        if search_calls >= verified["limits"]["search_calls"]:
            row["reason"] = "search_budget_exhausted"
            continue
        search_calls += 1
        try:
            search_raw = search(leaf["query"], 3)
        except (OSError, RuntimeError, TimeoutError, ValueError):
            row["reason"] = "search_call_failed_or_unknown"
            continue
        try:
            search_data = _strict_json(search_raw)
            raw_file = f"{leaf_id}.search.json"
            files[raw_file] = search_raw.encode("utf-8")
            row["search_response_sha256"] = _sha(files[raw_file])
            if search_data.get("success") is not True:
                raise AcquisitionError("search_failed")
            data = search_data.get("data")
            if type(data) is not dict or type(data.get("web")) is not list:
                raise AcquisitionError("search_shape_invalid")
            provider = data.get("served_by")
            row["observed_search_provider"] = (
                provider if type(provider) is str and provider else "unknown"
            )
            row["provider_reply_attested"] = provider == "keenable"
            candidates: list[tuple[str, str]] = []
            for hit in data["web"][:3]:
                if type(hit) is not dict:
                    continue
                try:
                    url = _safe_url(hit.get("url"))
                except AcquisitionError:
                    continue
                title = hit.get("title")
                if (
                    url in seen_urls
                    or any(existing_url == url for existing_url, _ in candidates)
                    or type(title) is not str
                    or not title.strip()
                    or len(title) > 1000
                    or "\n" in title
                    or "\r" in title
                ):
                    continue
                candidates.append((url, title.strip()))
            if not candidates:
                raise AcquisitionError("no_safe_distinct_source")
            attempts: list[dict[str, Any]] = []
            for index, (url, title) in enumerate(candidates, start=1):
                if extract_calls >= verified["limits"]["max_sources"]:
                    row["reason"] = "source_budget_exhausted"
                    break
                extract_calls += 1
                attempt: dict[str, Any] = {"requested_url": url, "title": title}
                try:
                    try:
                        extract_raw = extract([url])
                    except (OSError, RuntimeError, TimeoutError, ValueError):
                        raise AcquisitionError(
                            "extract_call_failed_or_unknown"
                        ) from None
                    extract_file = (
                        f"{leaf_id}.extract.json"
                        if index == 1
                        else f"{leaf_id}.extract-{index}.json"
                    )
                    files[extract_file] = extract_raw.encode("utf-8")
                    attempt["extract_response_sha256"] = _sha(files[extract_file])
                    row["extract_response_sha256"] = attempt["extract_response_sha256"]
                    extract_data = _strict_json(extract_raw)
                    matches = extract_data.get("results")
                    if type(matches) is not list or len(matches) != 1:
                        raise AcquisitionError("extract_shape_invalid")
                    item = matches[0]
                    if (
                        type(item) is not dict
                        or item.get("error")
                        or item.get("blocked_by_policy")
                    ):
                        raise AcquisitionError("extract_source_invalid")
                    final_url, rewrite = _canonical_extracted_url(url, item.get("url"))
                    content = item.get("content")
                    if (
                        type(content) is not str
                        or not 40 <= len(content) <= MAX_SOURCE_CHARS
                        or any(marker in content for marker in _TRUNCATION)
                    ):
                        raise AcquisitionError("extract_content_invalid_or_truncated")
                except AcquisitionError as error:
                    attempt["status"] = "failed"
                    attempt["reason"] = error.code
                    attempts.append(attempt)
                    row["candidate_attempts"] = attempts
                    row["reason"] = error.code
                    continue
                source_id = "SRC-" + _sha(final_url.encode("utf-8"))[:16].upper()
                filename = f"{source_id}.txt"
                payload = content.encode("utf-8")
                files[filename] = payload
                seen_urls.add(url)
                seen_urls.add(final_url)
                attempt.update(
                    {
                        "url": final_url,
                        "source_id": source_id,
                        "content_sha256": _sha(payload),
                        "url_rewrite": rewrite,
                    }
                )
                attempts.append(attempt)
                row["candidate_attempts"] = attempts
                for field in (
                    "requested_url",
                    "url_rewrite",
                    "redirect_chain_verified",
                    "missing_concept_group_indexes",
                ):
                    row.pop(field, None)
                if rewrite != "none":
                    row["requested_url"] = url
                    row["url_rewrite"] = rewrite
                    row["redirect_chain_verified"] = False
                row.update(
                    {
                        "source_id": source_id,
                        "url": final_url,
                        "title": title,
                        "content_file": filename,
                        "content_sha256": _sha(payload),
                        "content_bytes": len(payload),
                        "read_scope": "extracted_text_only",
                    }
                )
                if verified["schema_version"] == 2 and "concept_groups" in leaf:
                    missing_groups = _missing_concept_groups(
                        title, content, leaf["concept_groups"]
                    )
                    row["screening_policy"] = "literal_or_nearby_terms_v2"
                    if missing_groups:
                        attempt["status"] = "screened_out"
                        attempt["missing_concept_group_indexes"] = missing_groups
                        row["status"] = "screened_out"
                        row["reason"] = "concept_group_absent"
                        row["missing_concept_group_indexes"] = missing_groups
                        continue
                    row["concept_groups_matched"] = True
                attempt["status"] = "extracted_candidate"
                row["status"] = "extracted_candidate"
                row["reason"] = "exact_host_response_retained"
                if (
                    sum(
                        item.get("status") == "extracted_candidate" for item in attempts
                    )
                    >= max_candidates_per_leaf
                ):
                    break
            eligible = [
                item for item in attempts if item.get("status") == "extracted_candidate"
            ]
            if eligible:
                selected = eligible[0]
                filename = f"{selected['source_id']}.txt"
                row.update(
                    status="extracted_candidate",
                    reason="exact_host_response_retained",
                    source_id=selected["source_id"],
                    title=selected["title"],
                    url=selected["url"],
                    content_file=filename,
                    content_sha256=selected["content_sha256"],
                    content_bytes=len(files[filename]),
                    extract_response_sha256=selected["extract_response_sha256"],
                    retained_candidate_count=len(eligible),
                    concept_groups_matched=True,
                )
                row.pop("missing_concept_group_indexes", None)
        except AcquisitionError as error:
            row["reason"] = error.code
    successful = sum(row["status"] == "extracted_candidate" for row in rows)
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaSourceAcquisition",
            "status": "partial_candidate",
            "run_id": verified["run_id"],
            "mode": verified["mode"],
            "selected_leaf_id": selected_leaf_id,
            "plan_receipt_hash": verified["receipt_hash"],
            "observed_at": now.astimezone(UTC).isoformat(),
            "search_calls": search_calls,
            "extract_calls": extract_calls,
            "successful_sources": successful,
            "route_configuration_verified": pinned_route,
            "provider_reply_attested_for_all": bool(rows)
            and all(row.get("provider_reply_attested") is True for row in rows),
            "leaves": rows,
            "artifact_hashes": [
                {"path": name, "sha256": _sha(raw), "bytes": len(raw)}
                for name, raw in sorted(files.items())
            ],
            "source_independence_verified": False,
            "source_freshness": "unverified_cache_possible",
            "semantic_support_verified": False,
            "model_used": False,
            "qualification_status": "not_verified",
            "release_authorized": False,
            "external_delivery_authorized": False,
        }
    )
    return receipt, files
