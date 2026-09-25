"""Attest one publisher HTML response for an exact OpenAlex work."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from .beta_acquisition import AcquisitionError, _safe_url
from .beta_modes import verify_beta_mode_plan
from .canonical import verify_receipt_hash, with_receipt_hash

MAX_HTML_BYTES = 2_000_000
MAX_HOPS = 6
_REDIRECTS = {301, 302, 303, 307, 308}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validated_url(
    value: str, publisher_host: str, *, max_query_chars: int = 500
) -> tuple[str, str, str]:
    if type(value) is not str or not 0 < len(value) <= 2048:
        raise AcquisitionError("publisher_url_invalid")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise AcquisitionError("publisher_url_invalid") from None
    base = publisher_host.removeprefix("www.")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.fragment
        or port not in (None, 443)
        or type(max_query_chars) is not int
        or not 0 <= max_query_chars <= 1800
        or len(parsed.query) > max_query_chars
        or not (host == "doi.org" or host == base or host.endswith("." + base))
    ):
        raise AcquisitionError("publisher_url_invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise AcquisitionError("publisher_url_invalid")
    safe_without_query = f"https://{host}{parsed.path or '/'}"
    _safe_url(safe_without_query)
    target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
    return host, target, safe_without_query


class _ArticleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.sections: set[str] = set()
        self.license_links: list[str] = []
        self.article_main_seen = False
        self.main_text_chunks: list[str] = []
        self._in_main = False
        self._skip_text = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta":
            name, content = values.get("name"), values.get("content")
            if name in {"citation_title", "citation_doi"} and content is not None:
                self.meta.setdefault(name, []).append(content)
        if tag == "main" and "article" in (values.get("class") or "").casefold():
            self.article_main_seen = True
            self._in_main = True
        if tag in {"script", "style"}:
            self._skip_text = True
        if tag == "section" and values.get("data-title"):
            self.sections.add((values["data-title"] or "").casefold())
        if tag == "a" and values.get("href"):
            self.license_links.append(values["href"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "main":
            self._in_main = False
        if tag in {"script", "style"}:
            self._skip_text = False

    def handle_data(self, data: str) -> None:
        if self._in_main and not self._skip_text and data.strip():
            self.main_text_chunks.append(data)


def _text_overlap(raw: bytes, extracted_text: str) -> tuple[int, int]:
    parser = _ArticleHTML()
    parser.feed(raw.decode("utf-8"))
    parser.close()
    publisher_words = re.findall(r"\w+", " ".join(parser.main_text_chunks).casefold())
    extracted_words = re.findall(r"\w+", extracted_text.casefold())
    width = 12
    if len(publisher_words) < width or len(extracted_words) < width:
        return 0, 0
    publisher_windows = {
        tuple(publisher_words[index : index + width])
        for index in range(len(publisher_words) - width + 1)
    }
    matches = [
        index
        for index in range(0, len(extracted_words) - width + 1, 20)
        if tuple(extracted_words[index : index + width]) in publisher_windows
    ]
    regions = {min(2, 3 * index // len(extracted_words)) for index in matches}
    return len(matches), len(regions)


def _html_observation(
    raw: bytes, title: str, doi: str
) -> tuple[bool, dict[str, object]]:
    if not 1000 <= len(raw) <= MAX_HTML_BYTES:
        return False, {"reason": "publisher_html_size_invalid"}
    try:
        decoded = raw.decode("utf-8")
    except UnicodeError:
        return False, {"reason": "publisher_html_encoding_invalid"}
    parser = _ArticleHTML()
    try:
        parser.feed(decoded)
        parser.close()
    except (ValueError, TypeError):
        return False, {"reason": "publisher_html_invalid"}
    doi_suffix = doi.removeprefix("https://doi.org/")
    observed_title = parser.meta.get("citation_title", [])
    observed_doi = parser.meta.get("citation_doi", [])
    title_match = (
        len(observed_title) == 1
        and html.unescape(observed_title[0]).strip().casefold()
        == title.strip().casefold()
    )
    doi_match = (
        len(observed_doi) == 1
        and observed_doi[0].strip().casefold() == doi_suffix.casefold()
    )
    rights_section = "rights and permissions" in parser.sections
    license_link = any(
        "creativecommons.org/licenses/by/4.0" in link.lower()
        for link in parser.license_links
    )
    body_sections = bool({"comment", "results", "methods", "article"} & parser.sections)
    references_seen = "references" in parser.sections
    good = (
        title_match
        and doi_match
        and parser.article_main_seen
        and body_sections
        and references_seen
        and rights_section
        and license_link
    )
    return good, {
        "reason": "publisher_page_identity_and_rights_observed"
        if good
        else "publisher_html_obligations_missing",
        "citation_title_match": title_match,
        "citation_doi_match": doi_match,
        "article_main_seen": parser.article_main_seen,
        "body_section_seen": body_sections,
        "references_seen": references_seen,
        "rights_section_seen": rights_section,
        "cc_by_4_license_link_seen": license_link,
    }


def attest_openalex_publisher_raw(
    plan: object,
    metadata: object,
    article: object,
    *,
    extracted_text: str,
    fetch: Callable[[str, int], tuple[int, Mapping[str, str], bytes, str, bool]],
    observed_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    verified = verify_beta_mode_plan(plan)
    if verified["schema_version"] != 2 or verified["mode"] not in {
        "deep",
        "ultra",
        "academic",
    }:
        raise AcquisitionError("publisher_plan_invalid")
    if (
        type(metadata) is not dict
        or type(article) is not dict
        or not verify_receipt_hash(metadata)
        or not verify_receipt_hash(article)
    ):
        raise AcquisitionError("publisher_receipt_invalid")
    if (
        metadata.get("contract") != "BetaOpenAlexMetadataAcquisition"
        or article.get("contract") != "BetaOpenAlexArticleTextAcquisition"
        or article.get("status") != "article_text_candidate"
        or article.get("metadata_receipt_hash") != metadata["receipt_hash"]
        or metadata.get("plan_receipt_hash") != verified["receipt_hash"]
        or article.get("plan_receipt_hash") != verified["receipt_hash"]
        or metadata.get("run_id") != verified["run_id"]
        or article.get("run_id") != verified["run_id"]
        or article.get("release_authorized") is not False
    ):
        raise AcquisitionError("publisher_receipt_not_bound")
    work_id, title, doi, leaf_id = (
        article.get("work_id"),
        article.get("title"),
        article.get("doi"),
        article.get("leaf_id"),
    )
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
    if (
        len(matches) != 1
        or matches[0].get("title") != title
        or matches[0].get("doi") != doi
    ):
        raise AcquisitionError("publisher_work_not_bound")
    if (
        type(extracted_text) is not str
        or len(extracted_text.encode("utf-8")) != article.get("text_bytes")
        or _sha(extracted_text.encode("utf-8")) != article.get("text_sha256")
    ):
        raise AcquisitionError("publisher_extracted_text_not_bound")
    location = matches[0].get("open_access_location")
    if (
        type(location) is not dict
        or location.get("is_oa_reported") is not True
        or location.get("license_reported") != "cc-by"
        or location.get("version_reported") != "publishedVersion"
        or type(location.get("pdf_url")) is not str
        or type(doi) is not str
        or type(title) is not str
        or type(leaf_id) is not str
    ):
        raise AcquisitionError("publisher_location_not_eligible")
    _safe_url(doi)
    _safe_url(location["pdf_url"])
    publisher_host = urlsplit(location["pdf_url"]).hostname
    if not publisher_host:
        raise AcquisitionError("publisher_host_invalid")
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise AcquisitionError("timestamp_naive")
    hops: list[dict[str, object]] = []
    artifacts: dict[str, bytes] = {}
    current = doi
    raw_final: bytes | None = None
    final_without_query: str | None = None
    overlap_matches = 0
    overlap_regions = 0
    reason = "publisher_redirect_limit"
    remaining = MAX_HTML_BYTES
    for index in range(MAX_HOPS):
        host, _target, sanitized = _validated_url(current, publisher_host)
        status, headers, raw, remote_ip, tls_verified = fetch(current, remaining)
        if (
            type(status) is not int
            or type(raw) is not bytes
            or len(raw) > remaining
            or type(remote_ip) is not str
            or not ipaddress.ip_address(remote_ip).is_global
            or tls_verified is not True
        ):
            raise AcquisitionError("publisher_transport_unverified")
        remaining -= len(raw)
        header_bytes = json.dumps(
            dict(headers), sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        if len(header_bytes) > 20_000:
            raise AcquisitionError("publisher_headers_over_limit")
        body_name = f"{leaf_id}.publisher.hop-{index + 1}.body"
        header_name = f"{leaf_id}.publisher.hop-{index + 1}.headers.json"
        artifacts[body_name] = raw
        artifacts[header_name] = header_bytes
        location_header = headers.get("location") or headers.get("Location")
        hops.append(
            {
                "url_without_query": sanitized,
                "url_sha256": _sha(current.encode("utf-8")),
                "host": host,
                "remote_ip": remote_ip,
                "http_status": status,
                "response_sha256": _sha(raw),
                "response_bytes": len(raw),
                "body_file": body_name,
                "headers_file": header_name,
                "headers_sha256": _sha(header_bytes),
                "headers_bytes": len(header_bytes),
                "headers_representation": "normalized_mapping",
                "location_sha256": _sha(location_header.encode("utf-8"))
                if type(location_header) is str
                else None,
                "tls_verified": True,
            }
        )
        if status in _REDIRECTS:
            if type(location_header) is not str or not location_header:
                reason = "publisher_redirect_location_missing"
                break
            next_url = urljoin(current, location_header)
            _validated_url(next_url, publisher_host)
            current = next_url
            continue
        if status != 200:
            reason = "publisher_http_status_not_200"
            break
        if host == "doi.org" or not host.endswith(publisher_host.removeprefix("www.")):
            reason = "publisher_final_host_invalid"
            break
        content_type = headers.get("content-type") or headers.get("Content-Type") or ""
        encoding = headers.get("content-encoding") or headers.get("Content-Encoding")
        if not content_type.lower().startswith("text/html") or encoding not in (
            None,
            "identity",
            "",
        ):
            reason = "publisher_html_transport_invalid"
            break
        raw_final = raw
        final_without_query = sanitized
        good, observation = _html_observation(raw, title, doi)
        reason = str(observation["reason"])
        if good:
            overlap_matches, overlap_regions = _text_overlap(raw, extracted_text)
            good = overlap_matches >= 3 and overlap_regions >= 2
            if not good:
                reason = "publisher_extracted_text_mismatch"
                observation["reason"] = reason
        break
    else:
        good = False
        observation = {"reason": reason}
    if raw_final is None:
        good = False
        observation = {"reason": reason}
    filename = f"{leaf_id}.publisher.raw.html" if raw_final is not None else None
    if filename and raw_final is not None:
        artifacts[filename] = raw_final
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaPublisherRawAttestation",
            "status": "publisher_html_candidate" if good else "blocked",
            "reason": reason,
            "run_id": verified["run_id"],
            "mode": verified["mode"],
            "leaf_id": leaf_id,
            "work_id": work_id,
            "doi": doi,
            "title": title,
            "plan_receipt_hash": verified["receipt_hash"],
            "metadata_receipt_hash": metadata["receipt_hash"],
            "article_receipt_hash": article["receipt_hash"],
            "observed_at": now.astimezone(UTC).isoformat(),
            "requested_doi_sha256": _sha(doi.encode("utf-8")),
            "expected_publisher_host": publisher_host,
            "redirect_hops": hops,
            "redirect_chain_verified": good,
            "final_url_without_query": final_without_query,
            "raw_file": filename,
            "raw_sha256": _sha(raw_final) if raw_final is not None else None,
            "raw_bytes": len(raw_final) if raw_final is not None else None,
            "html_observation": observation,
            "extracted_text_sha256": article["text_sha256"],
            "publisher_extracted_text_overlap_verified": good,
            "overlap_12word_samples": overlap_matches,
            "overlap_regions": overlap_regions,
            "publisher_license_corroborated": good,
            "publisher_article_main_observed": good,
            "full_text_coverage_verified": False,
            "independent_second_work_verified": False,
            "mode_qualified": False,
            "release_authorized": False,
        }
    )
    return receipt, artifacts
