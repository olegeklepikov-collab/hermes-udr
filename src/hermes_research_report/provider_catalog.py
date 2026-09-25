"""Versioned research-surface catalog for supported external providers.

The catalog describes contracts only.  It performs no network access and never
implies that credentials, entitlement, or a live qualification are present.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .canonical import sha256_json

CATALOG_VERSION = "2026-09-14"
ADAPTER_VERSION = "0.41.0a1"


def _operation(
    operation_id: str,
    *,
    lifecycle: str = "sync",
    auth: str = "api_key",
    status: str = "documented",
    native: tuple[str, ...] = (),
    risk: str = "low",
) -> dict[str, Any]:
    schema_ref = f"provider-contract://{operation_id}/2026-09-14"
    body: dict[str, Any] = {
        "id": operation_id,
        "capability": operation_id,
        "lifecycle": lifecycle,
        "auth": auth,
        "schema_ref": schema_ref,
        "native_extensions": list(native),
        "limits": {"provider_enforced": True},
        "cost_model": {"preflight_reservation_required": True},
        "status": status,
        "risk": risk,
        "destructive": False,
    }
    body["schema_hash"] = sha256_json(body)
    return body


def _ops(
    specifications: tuple[tuple[str, str, str, str, tuple[str, ...], str], ...],
) -> list[dict[str, Any]]:
    return [
        _operation(
            operation_id,
            lifecycle=lifecycle,
            auth=auth,
            status=status,
            native=native,
            risk=risk,
        )
        for operation_id, lifecycle, auth, status, native, risk in specifications
    ]


_D = "documented"
_E = "experimental"
_B = "access_blocked"
_G = "policy_gated"


_CATALOG_SPEC: dict[str, dict[str, Any]] = {
    "firecrawl": {
        "product_class": "web_acquisition",
        "endpoint_version": "v2",
        "surface_feasibility": "yes",
        "principal_gate": "api_key_plan_v2_and_egress_policy",
        "operations": _ops(
            (
                (
                    "firecrawl.search",
                    "sync",
                    "api_key",
                    _D,
                    ("categories", "sources"),
                    "low",
                ),
                (
                    "firecrawl.scrape",
                    "sync",
                    "api_key",
                    _D,
                    ("formats", "actions"),
                    "medium",
                ),
                ("firecrawl.parse", "async", "api_key", _D, ("file_types",), "medium"),
                (
                    "firecrawl.batch_scrape",
                    "batch",
                    "api_key",
                    _D,
                    ("job_id",),
                    "medium",
                ),
                (
                    "firecrawl.structured_extract",
                    "async",
                    "api_key",
                    _D,
                    ("json_schema",),
                    "medium",
                ),
                ("firecrawl.map", "sync", "api_key", _D, ("url_patterns",), "low"),
                (
                    "firecrawl.crawl",
                    "async",
                    "api_key",
                    _D,
                    ("crawl_status",),
                    "medium",
                ),
                (
                    "firecrawl.browser_interact",
                    "async",
                    "api_key",
                    _D,
                    ("browser_actions",),
                    "high",
                ),
                ("firecrawl.agent", "async", "api_key", _E, ("agent_events",), "high"),
                (
                    "firecrawl.change_tracking",
                    "async",
                    "api_key",
                    _D,
                    ("change_status",),
                    "medium",
                ),
                (
                    "firecrawl.webhooks",
                    "webhook",
                    "api_key",
                    _D,
                    ("event_type",),
                    "medium",
                ),
            )
        ),
    },
    "exa": {
        "product_class": "web_search_research",
        "endpoint_version": "current",
        "surface_feasibility": "conditional",
        "principal_gate": "api_key_plan_and_licensed_index",
        "operations": _ops(
            (
                (
                    "exa.search",
                    "sync",
                    "api_key",
                    _D,
                    ("search_type", "category"),
                    "low",
                ),
                (
                    "exa.contents",
                    "sync",
                    "api_key",
                    _D,
                    ("highlights", "summary"),
                    "low",
                ),
                ("exa.answer", "sync", "api_key", _D, ("citations",), "medium"),
                ("exa.agent", "async", "api_key", _D, ("agent_events",), "medium"),
                (
                    "exa.websets",
                    "async",
                    "api_key",
                    _D,
                    ("criteria", "items"),
                    "medium",
                ),
                (
                    "exa.enrichments_imports",
                    "batch",
                    "api_key",
                    _D,
                    ("enrichments", "imports"),
                    "medium",
                ),
                ("exa.monitors", "async", "api_key", _D, ("monitor_events",), "medium"),
                ("exa.batch", "batch", "api_key", _D, ("batch_items",), "medium"),
                (
                    "exa.events_webhooks",
                    "webhook",
                    "api_key",
                    _D,
                    ("event_type",),
                    "medium",
                ),
            )
        ),
    },
    "tavily": {
        "product_class": "web_search_research",
        "endpoint_version": "current",
        "surface_feasibility": "yes",
        "principal_gate": "api_key_credits",
        "operations": _ops(
            (
                ("tavily.search", "sync", "api_key", _D, ("answer", "images"), "low"),
                ("tavily.extract", "sync", "api_key", _D, ("extract_depth",), "low"),
                ("tavily.map", "sync", "api_key", _D, ("instructions",), "low"),
                ("tavily.crawl", "async", "api_key", _D, ("crawl_depth",), "medium"),
                (
                    "tavily.research",
                    "stream",
                    "api_key",
                    _D,
                    ("source_events", "structured_output"),
                    "medium",
                ),
            )
        ),
    },
    "keenable": {
        "product_class": "web_search",
        "endpoint_version": "public",
        "surface_feasibility": "bounded",
        "principal_gate": "public_contract_two_tools",
        "operations": _ops(
            (
                (
                    "keenable.search",
                    "sync",
                    "optional_api_key",
                    _D,
                    ("site_filter", "date_filter"),
                    "low",
                ),
                (
                    "keenable.fetch",
                    "sync",
                    "optional_api_key",
                    _D,
                    ("acquisition_time",),
                    "low",
                ),
                (
                    "keenable.historical",
                    "async",
                    "api_key",
                    _B,
                    ("query_time",),
                    "medium",
                ),
            )
        ),
    },
    "nimble": {
        "product_class": "web_acquisition_research",
        "endpoint_version": "current_openapi",
        "surface_feasibility": "conditional",
        "principal_gate": "plan_anti_bot_proxy_and_legal_policy",
        "operations": _ops(
            (
                ("nimble.search_serp", "sync", "api_key", _D, ("serp",), "low"),
                (
                    "nimble.extract_sync",
                    "sync",
                    "api_key",
                    _D,
                    ("rendering", "parsing_schema"),
                    "medium",
                ),
                (
                    "nimble.extract_async_batch",
                    "batch",
                    "api_key",
                    _D,
                    ("job_id",),
                    "medium",
                ),
                ("nimble.map", "sync", "api_key", _D, ("url_graph",), "low"),
                ("nimble.crawl", "async", "api_key", _D, ("crawl_events",), "medium"),
                (
                    "nimble.web_agents",
                    "async",
                    "api_key",
                    _D,
                    ("trust", "agent_events"),
                    "medium",
                ),
                (
                    "nimble.templates_jobs_tasks",
                    "async",
                    "api_key",
                    _D,
                    ("template_id", "task_id"),
                    "medium",
                ),
                (
                    "nimble.media_domain_health",
                    "sync",
                    "api_key",
                    _D,
                    ("media", "domain_health"),
                    "medium",
                ),
                (
                    "nimble.browser_actions",
                    "async",
                    "api_key",
                    _G,
                    ("browser_actions", "network_capture"),
                    "high",
                ),
                (
                    "nimble.proxy_stealth",
                    "sync",
                    "api_key",
                    _G,
                    ("proxy", "stealth"),
                    "high",
                ),
            )
        ),
    },
    "parallel": {
        "product_class": "web_search_research",
        "endpoint_version": "v1",
        "surface_feasibility": "conditional",
        "principal_gate": "api_key_credits_and_state_policy",
        "operations": _ops(
            (
                ("parallel.search", "sync", "api_key", _D, ("source_policy",), "low"),
                ("parallel.extract", "sync", "api_key", _D, ("excerpts",), "low"),
                (
                    "parallel.task",
                    "async",
                    "api_key",
                    _D,
                    ("basis", "task_events"),
                    "medium",
                ),
                (
                    "parallel.task_groups",
                    "batch",
                    "api_key",
                    _D,
                    ("group_id",),
                    "medium",
                ),
                (
                    "parallel.chat_responses",
                    "stream",
                    "api_key",
                    _D,
                    ("response_events",),
                    "medium",
                ),
                (
                    "parallel.findall",
                    "async",
                    "api_key",
                    _D,
                    ("entity_matches",),
                    "medium",
                ),
                (
                    "parallel.monitor",
                    "webhook",
                    "api_key",
                    _D,
                    ("monitor_events",),
                    "medium",
                ),
                ("parallel.memory", "async", "api_key", _G, ("memory_items",), "high"),
                (
                    "parallel.streams_webhooks",
                    "stream",
                    "api_key",
                    _D,
                    ("event_type",),
                    "medium",
                ),
                (
                    "parallel.beta_search_extract",
                    "sync",
                    "api_key",
                    "legacy",
                    ("legacy_endpoint",),
                    "low",
                ),
            )
        ),
    },
    "consensus": {
        "product_class": "scholarly_search",
        "endpoint_version": "v1",
        "surface_feasibility": "yes_for_public_api",
        "principal_gate": "one_public_rest_endpoint",
        "operations": _ops(
            (
                (
                    "consensus.search",
                    "sync",
                    "api_key",
                    _D,
                    ("filters", "next_page"),
                    "low",
                ),
            )
        ),
    },
    "scite": {
        "product_class": "scholarly_evidence",
        "endpoint_version": "contract",
        "surface_feasibility": "conditional",
        "principal_gate": "paid_contract_and_endpoint_entitlement",
        "operations": _ops(
            (
                (
                    "scite.assistant",
                    "async",
                    "contract",
                    _D,
                    ("assistant_answer",),
                    "medium",
                ),
                (
                    "scite.fulltext_citation_search",
                    "sync",
                    "contract",
                    _D,
                    ("citation_context",),
                    "medium",
                ),
                ("scite.paper", "sync", "contract", _D, ("paper_metrics",), "low"),
                (
                    "scite.tallies",
                    "sync",
                    "contract",
                    _D,
                    ("smart_citation_tallies",),
                    "medium",
                ),
                (
                    "scite.citation_statements",
                    "sync",
                    "contract",
                    _D,
                    ("classification", "statement"),
                    "medium",
                ),
                (
                    "scite.reference_check",
                    "async",
                    "contract",
                    _D,
                    ("reference_warnings",),
                    "medium",
                ),
                (
                    "scite.metrics",
                    "sync",
                    "contract",
                    _D,
                    ("journal_org_funder_metrics",),
                    "medium",
                ),
                (
                    "scite.evidence_datasets",
                    "batch",
                    "contract",
                    "entitlement_required",
                    ("dataset_class",),
                    "high",
                ),
            )
        ),
    },
    "openalex": {
        "product_class": "open_scholarly_graph",
        "endpoint_version": "current",
        "surface_feasibility": "yes",
        "principal_gate": "api_budget_schema_and_snapshot_scale",
        "operations": _ops(
            (
                (
                    "openalex.entities",
                    "sync",
                    "optional_api_key",
                    _D,
                    ("entity_type",),
                    "low",
                ),
                (
                    "openalex.query_mechanics",
                    "sync",
                    "optional_api_key",
                    _D,
                    ("filter", "sort", "group", "select"),
                    "low",
                ),
                (
                    "openalex.autocomplete",
                    "sync",
                    "optional_api_key",
                    _D,
                    ("autocomplete",),
                    "low",
                ),
                (
                    "openalex.oql_oqo",
                    "sync",
                    "optional_api_key",
                    _D,
                    ("query_language",),
                    "medium",
                ),
                (
                    "openalex.snapshot_sync",
                    "batch",
                    "optional_api_key",
                    _D,
                    ("snapshot_version",),
                    "medium",
                ),
                (
                    "openalex.fulltext_citation_oa",
                    "sync",
                    "optional_api_key",
                    _D,
                    ("derived_topics", "oa", "citation_counts"),
                    "medium",
                ),
            )
        ),
    },
    "arxiv": {
        "product_class": "preprint_repository",
        "endpoint_version": "atom_api",
        "surface_feasibility": "yes",
        "principal_gate": "courtesy_delay_limits_and_terms",
        "operations": _ops(
            (
                ("arxiv.query", "sync", "none", _D, ("atom",), "low"),
                ("arxiv.id_list", "sync", "none", _D, ("version_links",), "low"),
                ("arxiv.paging_sort", "sync", "none", _D, ("sort_order",), "low"),
                ("arxiv.oai_pmh", "batch", "none", _D, ("resumption_token",), "medium"),
                (
                    "arxiv.bulk_fulltext",
                    "batch",
                    "none",
                    _G,
                    ("version", "preprint_status"),
                    "medium",
                ),
            )
        ),
    },
    "crossref": {
        "product_class": "doi_metadata",
        "endpoint_version": "rest",
        "surface_feasibility": "yes",
        "principal_gate": "polite_pool_and_deposited_metadata_quality",
        "operations": _ops(
            (
                ("crossref.resources", "sync", "none", _D, ("resource_type",), "low"),
                ("crossref.query_filter_facet", "sync", "none", _D, ("facet",), "low"),
                ("crossref.sample", "sync", "none", _D, ("sample",), "low"),
                ("crossref.cursor", "batch", "none", _D, ("next_cursor",), "low"),
            )
        ),
    },
    "semantic_scholar": {
        "product_class": "scholarly_graph_recommendations",
        "endpoint_version": "academic_graph",
        "surface_feasibility": "conditional",
        "principal_gate": "api_key_rate_and_license",
        "operations": _ops(
            (
                (
                    "semantic_scholar.paper_author",
                    "sync",
                    "api_key",
                    _D,
                    ("fields", "external_ids"),
                    "low",
                ),
                (
                    "semantic_scholar.batch_bulk",
                    "batch",
                    "api_key",
                    _D,
                    ("bulk_cursor",),
                    "medium",
                ),
                (
                    "semantic_scholar.citations_references",
                    "batch",
                    "api_key",
                    _D,
                    ("citation_edges",),
                    "low",
                ),
                (
                    "semantic_scholar.recommendations",
                    "sync",
                    "api_key",
                    _D,
                    ("recommendation_score",),
                    "medium",
                ),
                (
                    "semantic_scholar.datasets",
                    "batch",
                    "api_key",
                    _D,
                    ("release", "diff"),
                    "medium",
                ),
            )
        ),
    },
    "pubmed": {
        "product_class": "biomedical_index",
        "endpoint_version": "eutils",
        "surface_feasibility": "yes",
        "principal_gate": "tool_email_key_rate_and_no_fulltext_inference",
        "operations": _ops(
            tuple(
                (
                    f"pubmed.{name}",
                    "sync",
                    "tool_email_optional_key",
                    _D,
                    ("webenv", "query_key"),
                    "low",
                )
                for name in (
                    "einfo",
                    "esearch",
                    "epost",
                    "esummary",
                    "efetch",
                    "elink",
                    "egquery",
                    "espell",
                    "ecitmatch",
                )
            )
            + (
                (
                    "pubmed.history_batch",
                    "batch",
                    "tool_email_optional_key",
                    _D,
                    ("webenv", "query_key"),
                    "low",
                ),
            )
        ),
    },
    "unpaywall": {
        "product_class": "open_access_resolution",
        "endpoint_version": "v2",
        "surface_feasibility": "yes",
        "principal_gate": "email_daily_limit_and_doi_scope",
        "operations": _ops(
            (
                (
                    "unpaywall.doi_lookup",
                    "sync",
                    "email",
                    _D,
                    ("oa_locations", "best_oa_location"),
                    "low",
                ),
                (
                    "unpaywall.title_search",
                    "sync",
                    "email",
                    _D,
                    ("match_score",),
                    "low",
                ),
                (
                    "unpaywall.snapshot_feed",
                    "batch",
                    "contract",
                    _G,
                    ("snapshot_version",),
                    "medium",
                ),
            )
        ),
    },
    "opencitations": {
        "product_class": "open_citation_graph",
        "endpoint_version": "index_v2_meta",
        "surface_feasibility": "yes",
        "principal_gate": "rate_coverage_and_identifier_matching",
        "operations": _ops(
            (
                (
                    "opencitations.index",
                    "sync",
                    "optional_token",
                    _D,
                    ("oci", "citation_edges"),
                    "low",
                ),
                (
                    "opencitations.references",
                    "sync",
                    "optional_token",
                    _D,
                    ("references",),
                    "low",
                ),
                (
                    "opencitations.count",
                    "sync",
                    "optional_token",
                    _D,
                    ("counts",),
                    "low",
                ),
                (
                    "opencitations.meta",
                    "sync",
                    "optional_token",
                    _D,
                    ("bibliographic_metadata",),
                    "low",
                ),
                (
                    "opencitations.dump",
                    "batch",
                    "none",
                    _D,
                    ("dump_version",),
                    "medium",
                ),
            )
        ),
    },
}


PROVIDER_IDS = tuple(_CATALOG_SPEC)


def provider_manifest(provider_id: str) -> dict[str, Any]:
    """Return a fresh, self-hashed catalog manifest."""

    spec = _CATALOG_SPEC[provider_id]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "catalog_version": CATALOG_VERSION,
        "provider_id": provider_id,
        "product_class": spec["product_class"],
        "adapter_version": ADAPTER_VERSION,
        "endpoint_version": spec["endpoint_version"],
        "surface_feasibility": spec["surface_feasibility"],
        "product_parity": False,
        "principal_gate": spec["principal_gate"],
        "source_contract_refs": [
            f"WDS-{index:03d}" for index in _source_ids(provider_id)
        ],
        "source_contract_checked_at": CATALOG_VERSION,
        "operations": deepcopy(spec["operations"]),
        "policy_constraints": {
            "terms": "operation_version_verification_required",
            "license": "provider_specific_verification_required",
            "retention": "host_policy_and_provider_terms_required",
            "redistribution": "not_assumed",
            "privacy": "data_classification_required",
            "egress": "route_policy_required",
        },
        "excluded_operation_classes": [
            "admin",
            "api_key_management",
            "billing",
            "payment",
            "destructive",
        ],
        "qualification_state": "not_verified",
    }
    manifest["manifest_hash"] = sha256_json(manifest)
    return manifest


def _source_ids(provider_id: str) -> tuple[int, ...]:
    mapping = {
        "firecrawl": (1, 2),
        "exa": (3,),
        "tavily": (4,),
        "keenable": (5, 6),
        "nimble": (7,),
        "parallel": (8,),
        "consensus": (9, 10),
        "scite": (11, 12),
        "openalex": (13, 14),
        "arxiv": (15, 16),
        "crossref": (17,),
        "semantic_scholar": (18, 19),
        "pubmed": (20, 21),
        "unpaywall": (22,),
        "opencitations": (23,),
    }
    return mapping[provider_id]
