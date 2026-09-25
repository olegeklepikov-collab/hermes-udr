"""Bounded characteristic network probes for the fifteen provider families."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError

from .canonical import with_receipt_hash
from .errors import fail, require_exact_keys, require_mapping, require_string
from .provider_catalog import _CATALOG_SPEC
from .runtime_snapshot import verify_runtime

PROVIDER_LIVE_PROBE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "provider_id", "query", "host_receipt"],
    "properties": {
        "schema_version": {"const": 1},
        "provider_id": {"type": "string", "minLength": 1},
        "query": {"type": "string", "minLength": 1},
        "host_receipt": {"type": ["object", "null"]},
    },
}

_HOST_ONLY = {"keenable", "consensus", "scite"}
_KEYS = {
    "firecrawl": "FIRECRAWL_API_KEY",
    "exa": "EXA_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "nimble": "NIMBLE_API_KEY",
    "parallel": "PARALLEL_API_KEY",
    "unpaywall": "UNPAYWALL_EMAIL",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Diagnostic requests must not forward credentials to another endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_probe(request: urllib.request.Request, *, timeout: int) -> Any:
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _request(provider: str, query: str, credential: str) -> urllib.request.Request:
    encoded = urllib.parse.quote_plus(query)
    if provider == "firecrawl":
        return urllib.request.Request(
            "https://api.firecrawl.dev/v2/search",
            data=json.dumps({"query": query, "limit": 1}).encode(),
            headers={
                "Authorization": f"Bearer {credential}",
                "Content-Type": "application/json",
            },
        )
    if provider == "exa":
        return urllib.request.Request(
            "https://api.exa.ai/search",
            data=json.dumps({"query": query, "numResults": 1}).encode(),
            headers={"x-api-key": credential, "Content-Type": "application/json"},
        )
    if provider == "tavily":
        return urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps(
                {"api_key": credential, "query": query, "max_results": 1}
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
    if provider == "nimble":
        return urllib.request.Request(
            "https://api.webit.live/api/v1/realtime/serp",
            data=json.dumps(
                {
                    "search_engine": "google_search",
                    "country": "US",
                    "locale": "en",
                    "query": query,
                    "parse": True,
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {credential}",
                "Content-Type": "application/json",
            },
        )
    if provider == "parallel":
        return urllib.request.Request(
            "https://api.parallel.ai/v1beta/search",
            data=json.dumps(
                {"objective": query, "search_queries": [query], "max_results": 1}
            ).encode(),
            headers={"x-api-key": credential, "Content-Type": "application/json"},
        )
    urls = {
        "openalex": f"https://api.openalex.org/works?search={encoded}&per-page=1",
        "arxiv": f"https://export.arxiv.org/api/query?search_query=all:{encoded}&max_results=1",
        "crossref": f"https://api.crossref.org/works?query={encoded}&rows=1",
        "semantic_scholar": f"https://api.semanticscholar.org/graph/v1/paper/search?query={encoded}&limit=1&fields=title",
        "pubmed": f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&retmax=1&term={encoded}",
        "unpaywall": f"https://api.unpaywall.org/v2/10.1038/nphys1170?email={urllib.parse.quote_plus(credential)}",
        "opencitations": "https://api.opencitations.net/index/v2/citation-count/doi:10.1038/nphys1170",
    }
    return urllib.request.Request(
        urls[provider], headers={"User-Agent": "UltraDeepResearch/0.41"}
    )


def probe_provider_live(
    request: object,
    *,
    opener: Callable[..., Any] = _open_probe,
) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "provider_id", "query", "host_receipt"}, "request"
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    provider = require_string(data["provider_id"], "request.provider_id")
    if provider not in _CATALOG_SPEC:
        fail(
            "unknown_provider",
            "request.provider_id",
            "Поставщик отсутствует в каталоге.",
        )
    query = require_string(data["query"], "request.query")
    host = data["host_receipt"]
    if provider in _HOST_ONLY:
        qualified = False
        raw_hash = None
        if host is not None:
            row = require_mapping(host, "request.host_receipt")
            require_exact_keys(
                row, {"provider_id", "status", "raw_sha256"}, "request.host_receipt"
            )
            qualified = (
                row["provider_id"] == provider
                and row["status"] == "success"
                and isinstance(row["raw_sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", row["raw_sha256"]) is not None
            )
            raw_hash = row["raw_sha256"] if qualified else None
        return with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "ProviderLiveProbeReceipt",
                "provider_id": provider,
                "status": "unverified_host_observation"
                if qualified
                else "entitlement_blocked",
                "product_qualified": False,
                "host_evidence_authenticated": False,
                "network_calls": 0,
                "operation": f"{provider}.host_surface",
                "raw_response_sha256": raw_hash,
                "credential_value_recorded": False,
                "issues": [] if qualified else ["host_subscription_connector_required"],
            }
        )
    verify_runtime()
    credential = os.environ.get(_KEYS.get(provider, ""), "")
    if provider in _KEYS and not credential:
        return with_receipt_hash(
            {
                "schema_version": 1,
                "contract": "ProviderLiveProbeReceipt",
                "provider_id": provider,
                "status": "entitlement_blocked",
                "network_calls": 0,
                "operation": _CATALOG_SPEC[provider]["operations"][0]["id"],
                "raw_response_sha256": None,
                "credential_value_recorded": False,
                "issues": [f"missing_credential:{_KEYS[provider]}"],
            }
        )
    try:
        response = opener(_request(provider, query, credential), timeout=20)
        try:
            raw = response.read(1_000_001)
            status_code = int(getattr(response, "status", 200))
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if len(raw) > 1_000_000:
            raise ValueError("provider_response_too_large")
        qualified = 200 <= status_code < 300 and bool(raw.strip())
        result_status = "transport_observed" if qualified else "live_failed"
        issue = [] if qualified else [f"http_status:{status_code}"]
    except HTTPError as error:
        error.close()
        raw = b""
        qualified = False
        status_code = error.code
        result_status = (
            "entitlement_blocked" if error.code in {401, 402, 403} else "live_failed"
        )
        issue = [f"http_status:{error.code}"]
    except (OSError, ValueError, TimeoutError) as error:
        raw = b""
        qualified = False
        status_code = None
        result_status = "live_failed"
        issue = [f"live_probe_failed:{type(error).__name__}"]
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "ProviderLiveProbeReceipt",
            "provider_id": provider,
            "status": result_status,
            "product_qualified": False,
            "response_semantics_verified": False,
            "automatic_redirects_allowed": False,
            "network_calls": 1,
            "operation": _CATALOG_SPEC[provider]["operations"][0]["id"],
            "http_status": status_code,
            "raw_response_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
            "raw_response_bytes": len(raw),
            "credential_value_recorded": False,
            "issues": issue,
        }
    )
