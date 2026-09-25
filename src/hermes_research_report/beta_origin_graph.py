"""Work-level origin map that never counts service replicas as independent studies."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit

from .beta_modes import verify_beta_mode_plan
from .canonical import verify_receipt_hash, with_receipt_hash
from .errors import fail, require_list, require_mapping


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16].upper()


def build_beta_origin_graph(
    *,
    plan: object,
    execution: object,
    portfolio: object,
    metadata: object,
    article: object,
    publisher: object,
    web_capture: object | None,
) -> dict[str, Any]:
    verified = verify_beta_mode_plan(plan)
    if verified["schema_version"] != 2 or verified["mode"] != "deep":
        fail("origin_plan_invalid", "plan", "Нужен план Deep версии 2.")
    receipts = {
        "execution": require_mapping(execution, "execution"),
        "portfolio": require_mapping(portfolio, "portfolio"),
        "metadata": require_mapping(metadata, "metadata"),
        "article": require_mapping(article, "article"),
        "publisher": require_mapping(publisher, "publisher"),
    }
    expected_contracts = {
        "execution": "BetaAutomaticSourceExecution",
        "portfolio": "BetaSourcePortfolio",
        "metadata": "BetaOpenAlexMetadataAcquisition",
        "article": "BetaOpenAlexArticleTextAcquisition",
        "publisher": "BetaPublisherRawAttestation",
    }
    for name, receipt in receipts.items():
        if (
            not verify_receipt_hash(receipt)
            or receipt.get("contract") != expected_contracts[name]
            or receipt.get("run_id") != verified["run_id"]
            or receipt.get("plan_receipt_hash") != verified["receipt_hash"]
            or receipt.get("release_authorized") is not False
        ):
            fail("origin_receipt_not_bound", name, "Квитанция не связана с планом.")
    execution_receipt = receipts["execution"]
    portfolio_receipt = receipts["portfolio"]
    metadata_receipt = receipts["metadata"]
    article_receipt = receipts["article"]
    publisher_receipt = receipts["publisher"]
    article_attempts = require_list(
        execution_receipt.get("article_text_attempts"),
        "execution.article_text_attempts",
    )
    publisher_attempts = require_list(
        execution_receipt.get("publisher_raw_attempts"),
        "execution.publisher_raw_attempts",
    )
    portfolio_leaves = require_list(portfolio_receipt.get("leaves"), "portfolio.leaves")
    work_id, doi, title, leaf_id = (
        article_receipt.get("work_id"),
        article_receipt.get("doi"),
        article_receipt.get("title"),
        article_receipt.get("leaf_id"),
    )
    works = metadata_receipt.get("works")
    matching = (
        [
            work
            for work in works
            if type(work) is dict and work.get("work_id") == work_id
        ]
        if type(works) is list
        else []
    )
    if (
        type(work_id) is not str
        or type(doi) is not str
        or type(title) is not str
        or type(leaf_id) is not str
        or len(matching) != 1
        or matching[0].get("doi") != doi
        or matching[0].get("title") != title
        or metadata_receipt.get("leaf_id") != leaf_id
        or article_receipt.get("metadata_receipt_hash")
        != metadata_receipt["receipt_hash"]
        or publisher_receipt.get("metadata_receipt_hash")
        != metadata_receipt["receipt_hash"]
        or publisher_receipt.get("article_receipt_hash")
        != article_receipt["receipt_hash"]
        or publisher_receipt.get("work_id") != work_id
        or publisher_receipt.get("doi") != doi
        or publisher_receipt.get("status") != "publisher_html_candidate"
        or publisher_receipt.get("redirect_chain_verified") is not True
        or publisher_receipt.get("publisher_extracted_text_overlap_verified")
        is not True
        or execution_receipt.get("portfolio_receipt_hash")
        != portfolio_receipt["receipt_hash"]
        or not any(
            type(row) is dict
            and row.get("receipt_hash") == article_receipt["receipt_hash"]
            for row in article_attempts
        )
        or not any(
            type(row) is dict
            and row.get("receipt_hash") == publisher_receipt["receipt_hash"]
            for row in publisher_attempts
        )
    ):
        fail(
            "origin_work_not_bound", "article", "Работа и её представления не связаны."
        )
    work_origin = "ORIGIN-" + _short_hash(doi)
    web_node: dict[str, Any] | None = None
    if web_capture is not None:
        web = require_mapping(web_capture, "web_capture")
        if (
            not verify_receipt_hash(web)
            or web.get("contract") != "BetaSourceAcquisition"
            or web.get("run_id") != verified["run_id"]
            or web.get("plan_receipt_hash") != verified["receipt_hash"]
            or web.get("release_authorized") is not False
        ):
            fail("origin_web_not_bound", "web_capture", "Веб-квитанция не связана.")
        rows = web.get("leaves")
        if type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict:
            fail("origin_web_not_bound", "web_capture.leaves", "Нужен один веб-лист.")
        row = rows[0]
        if row.get("status") == "extracted_candidate":
            url = row.get("url")
            source_id = row.get("source_id")
            if type(url) is not str or type(source_id) is not str:
                fail(
                    "origin_web_not_bound",
                    "web_capture.leaves",
                    "Нет адреса источника.",
                )
            host = urlsplit(url).hostname
            if not host:
                fail(
                    "origin_web_not_bound", "web_capture.leaves", "Нет узла источника."
                )
            web_node = {
                "origin_ref": "WEB-" + _short_hash(url),
                "source_id": source_id,
                "host": host,
                "read_scope": "extracted_text_only",
                "relationship_to_work": "not_established",
                "independent_primary_work_verified": False,
                "receipt_hash": web["receipt_hash"],
            }
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaWorkOriginGraph",
            "status": "partial_origin_map",
            "run_id": verified["run_id"],
            "mode": "deep",
            "plan_receipt_hash": verified["receipt_hash"],
            "execution_receipt_hash": execution_receipt["receipt_hash"],
            "portfolio_receipt_hash": portfolio_receipt["receipt_hash"],
            "work_origin_ref": work_origin,
            "work_id": work_id,
            "doi": doi,
            "title": title,
            "same_work_representations": [
                {
                    "kind": "openalex_aggregated_metadata",
                    "receipt_hash": metadata_receipt["receipt_hash"],
                },
                {
                    "kind": "hermes_extracted_article_text",
                    "receipt_hash": article_receipt["receipt_hash"],
                },
                {
                    "kind": "publisher_original_html",
                    "receipt_hash": publisher_receipt["receipt_hash"],
                },
            ],
            "web_origin": web_node,
            "observed_leaf_count": len(portfolio_leaves),
            "declared_source_families": verified["source_families"],
            "attested_publisher_work_count": 1,
            "independent_second_work_verified": False,
            "independent_primary_work_count_verified": 0,
            "reason": "three_representations_one_work_web_relationship_unresolved",
            "mode_qualified": False,
            "release_authorized": False,
        }
    )
