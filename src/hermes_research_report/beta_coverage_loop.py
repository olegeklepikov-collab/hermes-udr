"""Bind a first source batch to its atom without promoting candidates to evidence."""

from __future__ import annotations

from typing import Any, cast

from .beta_acquisition import _missing_concept_groups
from .beta_coverage import assess_beta_coverage
from .canonical import sha256_json, verify_receipt_hash, with_receipt_hash


def observe_coverage_source_batch(
    *,
    frame: object,
    review: object,
    plan: object,
    batch_plan: object,
    execution: object,
    portfolio: object,
    web_capture: object,
    scholarly_capture: object,
    previous_observations: object | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    values = (
        frame,
        review,
        plan,
        batch_plan,
        execution,
        portfolio,
        web_capture,
        scholarly_capture,
    )
    if any(
        type(value) is not dict or not verify_receipt_hash(value) for value in values
    ):
        raise ValueError("coverage_batch_receipts_invalid")
    (
        frame,
        review,
        plan,
        batch_plan,
        execution,
        portfolio,
        web_capture,
        scholarly_capture,
    ) = (cast(dict[str, Any], value) for value in values)
    if (
        frame.get("contract") != "BetaCoverageFrame"
        or review.get("contract") != "BetaCoverageCriticReview"
        or batch_plan.get("contract") != "BetaCoverageSourceBatchPlan"
        or execution.get("contract") != "BetaAutomaticSourceExecution"
        or portfolio.get("contract") != "BetaSourcePortfolio"
        or web_capture.get("contract") != "BetaSourceAcquisition"
        or scholarly_capture.get("contract") != "BetaOpenAlexMetadataAcquisition"
        or web_capture.get("run_id") != plan.get("run_id")
        or scholarly_capture.get("run_id") != plan.get("run_id")
        or execution.get("run_id") != plan.get("run_id")
        or portfolio.get("run_id") != plan.get("run_id")
        or batch_plan.get("run_id") != frame.get("run_id")
        or review.get("frame_receipt_hash") != frame["receipt_hash"]
        or batch_plan.get("frame_receipt_hash") != frame["receipt_hash"]
        or batch_plan.get("review_receipt_hash") != review["receipt_hash"]
        or batch_plan.get("subplan_receipt_hash") != plan["receipt_hash"]
        or execution.get("plan_receipt_hash") != plan["receipt_hash"]
        or portfolio.get("plan_receipt_hash") != plan["receipt_hash"]
        or web_capture.get("plan_receipt_hash") != plan["receipt_hash"]
        or scholarly_capture.get("plan_receipt_hash") != plan["receipt_hash"]
        or plan.get("run_id") != batch_plan.get("batch_run_id")
        or plan.get("mode") != "deep"
        or len(plan.get("leaves", [])) != 2
        or plan["leaves"][0]["source_family"] != "web"
        or plan["leaves"][1]["source_family"] != "scholarly_index"
        or web_capture.get("leaf_id") not in (None, "LEAF-001")
        or scholarly_capture.get("leaf_id") != "LEAF-002"
        or execution.get("source_calls_completed") != 2
    ):
        raise ValueError("coverage_batch_lineage_invalid")
    atom_id = batch_plan["atom_id"]
    if not any(atom["atom_id"] == atom_id for atom in frame["atoms"]):
        raise ValueError("coverage_batch_atom_invalid")
    batch_number = batch_plan["batch_number"]
    if (
        previous_observations is not None
        and type(previous_observations) is not list
        or batch_number == 1
        and previous_observations is not None
        or batch_number > 1
        and previous_observations is None
    ):
        raise ValueError("coverage_batch_history_invalid")
    prior = [] if previous_observations is None else previous_observations
    assert type(prior) is list
    observations: list[dict[str, Any]] = []
    query_hashes = {
        leaf["leaf_id"]: sha256_json(
            {
                "plan_receipt_hash": plan["receipt_hash"],
                "leaf_id": leaf["leaf_id"],
                "query": leaf["query"],
            }
        )
        for leaf in plan["leaves"]
    }
    web_rows = web_capture.get("leaves")
    if type(web_rows) is not list or len(web_rows) != 1:
        raise ValueError("coverage_batch_web_capture_invalid")
    web_row = web_rows[0]
    if type(web_row) is not dict or web_row.get("leaf_id") != "LEAF-001":
        raise ValueError("coverage_batch_web_capture_invalid")
    if web_row.get("status") == "failed":
        observations.append(
            {
                "atom_id": atom_id,
                "batch": batch_number,
                "query_receipt_hash": query_hashes["LEAF-001"],
                "source_family": "web",
                "polarity": "neutral",
                "source_ref": None,
                "origin_ref": None,
                "relevance": "uncertain",
                "read_scope": "none",
                "material_claim_refs": [],
                "origin_verified": False,
                "result_status": "error",
                "gap_kind": "access_barrier",
            }
        )
    elif web_row.get("status") == "empty":
        observations.append(
            {
                "atom_id": atom_id,
                "batch": batch_number,
                "query_receipt_hash": query_hashes["LEAF-001"],
                "source_family": "web",
                "polarity": "neutral",
                "source_ref": None,
                "origin_ref": None,
                "relevance": "uncertain",
                "read_scope": "none",
                "material_claim_refs": [],
                "origin_verified": False,
                "result_status": "empty",
                "gap_kind": "search_absence",
            }
        )
    elif web_row.get("status") in {"screened_out", "extracted_candidate"}:
        attempts = web_row.get("candidate_attempts", [])
        if type(attempts) is not list or any(type(row) is not dict for row in attempts):
            raise ValueError("coverage_batch_web_candidates_invalid")
        seen_urls: set[str] = set()
        failed = False
        for attempt in attempts:
            status = attempt.get("status")
            if status == "failed":
                failed = True
                continue
            url = attempt.get("url") or attempt.get("requested_url")
            if (
                status not in {"screened_out", "extracted_candidate"}
                or type(url) is not str
            ):
                raise ValueError("coverage_batch_web_candidates_invalid")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            observations.append(
                {
                    "atom_id": atom_id,
                    "batch": batch_number,
                    "query_receipt_hash": query_hashes["LEAF-001"],
                    "source_family": "web",
                    "polarity": "neutral",
                    "source_ref": url,
                    "origin_ref": None,
                    "relevance": "uncertain",
                    "read_scope": "partial_text"
                    if type(attempt.get("content_sha256")) is str
                    else "metadata",
                    "material_claim_refs": [],
                    "origin_verified": False,
                    "result_status": "hit",
                    "gap_kind": "method_limit" if status == "screened_out" else None,
                }
            )
        if failed:
            observations.append(
                {
                    "atom_id": atom_id,
                    "batch": batch_number,
                    "query_receipt_hash": query_hashes["LEAF-001"],
                    "source_family": "web",
                    "polarity": "neutral",
                    "source_ref": None,
                    "origin_ref": None,
                    "relevance": "uncertain",
                    "read_scope": "none",
                    "material_claim_refs": [],
                    "origin_verified": False,
                    "result_status": "error",
                    "gap_kind": "access_barrier",
                }
            )
        if not observations:
            raise ValueError("coverage_batch_web_candidates_invalid")
    else:
        raise ValueError("coverage_batch_web_status_invalid")
    works = scholarly_capture.get("works")
    if (
        scholarly_capture.get("status") != "partial_candidate"
        or type(works) is not list
        or len(works) != scholarly_capture.get("candidate_count")
    ):
        raise ValueError("coverage_batch_scholarly_capture_invalid")
    lexical_rows: list[dict[str, Any]] = []
    groups = plan["leaves"][1]["concept_groups"]
    for work in works:
        if (
            type(work) is not dict
            or type(work.get("work_id")) is not str
            or type(work.get("title")) is not str
        ):
            raise ValueError("coverage_batch_scholarly_work_invalid")
        abstract = work.get("abstract_text")
        missing = _missing_concept_groups(
            work["title"], abstract if type(abstract) is str else "", groups
        )
        lexical_rows.append(
            {
                "work_id": work["work_id"],
                "missing_concept_group_indexes": missing,
                "semantic_relevance_verified": False,
            }
        )
        observations.append(
            {
                "atom_id": atom_id,
                "batch": batch_number,
                "query_receipt_hash": query_hashes["LEAF-002"],
                "source_family": "scholarly_index",
                "polarity": "neutral",
                "source_ref": work["work_id"],
                "origin_ref": work.get("doi"),
                "relevance": "uncertain",
                "read_scope": "abstract" if type(abstract) is str else "metadata",
                "material_claim_refs": [],
                "origin_verified": False,
                "result_status": "hit",
                "gap_kind": "method_limit" if missing else None,
            }
        )
    cumulative = [*prior, *observations]
    assessed = assess_beta_coverage(frame, cumulative, budget_exhausted=False)
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageSourceBatchObservation",
            "run_id": frame["run_id"],
            "batch_run_id": plan["run_id"],
            "batch_number": batch_number,
            "atom_id": atom_id,
            "frame_receipt_hash": frame["receipt_hash"],
            "review_receipt_hash": review["receipt_hash"],
            "batch_plan_receipt_hash": batch_plan["receipt_hash"],
            "execution_receipt_hash": execution["receipt_hash"],
            "portfolio_receipt_hash": portfolio["receipt_hash"],
            "web_capture_receipt_hash": web_capture["receipt_hash"],
            "scholarly_capture_receipt_hash": scholarly_capture["receipt_hash"],
            "query_receipt_hashes": query_hashes,
            "observations": observations,
            "previous_observation_count": len(prior),
            "cumulative_observation_count": len(cumulative),
            "lexical_screen": lexical_rows,
            "unresolved_critic_omission_count": len(review["omitted_facets"]),
            "coverage_assessment_receipt_hash": assessed["receipt_hash"],
            "candidate_count": len(works)
            + sum(
                row["source_family"] == "web" and row["source_ref"] is not None
                for row in observations
            ),
            "semantic_relevance_verified_count": 0,
            "source_calls_completed": execution["source_calls_completed"],
            "source_calls_to_close_atom": 0,
            "release_authorized": False,
        }
    )
    return cumulative, assessed, receipt


def observe_cross_domain_batch(
    *,
    frame: object,
    review: object,
    plan: object,
    batch_plan: object,
    execution: object,
    portfolio: object,
    captures: object,
    previous_observations: object,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    bound = (frame, review, plan, batch_plan, execution, portfolio)
    if any(
        type(value) is not dict or not verify_receipt_hash(value) for value in bound
    ):
        raise ValueError("coverage_cross_domain_receipts_invalid")
    if type(captures) is not dict or type(previous_observations) is not list:
        raise ValueError("coverage_cross_domain_inputs_invalid")
    frame, review, plan, batch_plan, execution, portfolio = (
        cast(dict[str, Any], value) for value in bound
    )
    if (
        plan.get("run_id") != batch_plan.get("batch_run_id")
        or batch_plan.get("batch_number") != 3
        or batch_plan.get("decomposition") != "digital_physical_by_instrument"
        or batch_plan.get("frame_receipt_hash") != frame["receipt_hash"]
        or batch_plan.get("review_receipt_hash") != review["receipt_hash"]
        or batch_plan.get("subplan_receipt_hash") != plan["receipt_hash"]
        or execution.get("plan_receipt_hash") != plan["receipt_hash"]
        or portfolio.get("plan_receipt_hash") != plan["receipt_hash"]
        or execution.get("source_calls_completed") != 4
        or len(plan.get("leaves", [])) != 4
        or set(captures) != {leaf["leaf_id"] for leaf in plan["leaves"]}
    ):
        raise ValueError("coverage_cross_domain_lineage_invalid")
    atom_id = batch_plan["atom_id"]
    if not any(atom["atom_id"] == atom_id for atom in frame["atoms"]):
        raise ValueError("coverage_cross_domain_atom_invalid")
    rows: list[dict[str, Any]] = []
    lexical: list[dict[str, Any]] = []
    web_attempts: list[dict[str, Any]] = []
    capture_hashes: dict[str, str] = {}
    for leaf in plan["leaves"]:
        leaf_id, family = leaf["leaf_id"], leaf["source_family"]
        capture = captures[leaf_id]
        if (
            type(capture) is not dict
            or not verify_receipt_hash(capture)
            or capture.get("plan_receipt_hash") != plan["receipt_hash"]
            or capture.get("run_id") != plan["run_id"]
            or capture.get("contract")
            != (
                "BetaSourceAcquisition"
                if family == "web"
                else "BetaOpenAlexMetadataAcquisition"
            )
        ):
            raise ValueError("coverage_cross_domain_capture_invalid")
        capture_hashes[leaf_id] = capture["receipt_hash"]
        query_hash = sha256_json(
            {
                "plan_receipt_hash": plan["receipt_hash"],
                "leaf_id": leaf_id,
                "query": leaf["query"],
            }
        )

        def observation(
            *,
            source_ref: str | None,
            origin_ref: str | None,
            read_scope: str,
            result_status: str,
            gap_kind: str | None,
            query_hash: str = query_hash,
            family: str = family,
        ) -> dict[str, Any]:
            return {
                "atom_id": atom_id,
                "batch": 3,
                "query_receipt_hash": query_hash,
                "source_family": family,
                "polarity": "neutral",
                "source_ref": source_ref,
                "origin_ref": origin_ref,
                "relevance": "uncertain",
                "read_scope": read_scope,
                "material_claim_refs": [],
                "origin_verified": False,
                "result_status": result_status,
                "gap_kind": gap_kind,
            }

        if family == "web":
            source_rows = capture.get("leaves")
            if (
                type(source_rows) is not list
                or len(source_rows) != 1
                or type(source_rows[0]) is not dict
                or source_rows[0].get("leaf_id") != leaf_id
            ):
                raise ValueError("coverage_cross_domain_web_invalid")
            source_row = source_rows[0]
            attempts = source_row.get("candidate_attempts", [])
            if type(attempts) is not list:
                raise ValueError("coverage_cross_domain_web_invalid")
            retained = 0
            for attempt in attempts:
                if type(attempt) is not dict:
                    raise ValueError("coverage_cross_domain_web_invalid")
                web_attempts.append(
                    {
                        "leaf_id": leaf_id,
                        "status": attempt.get("status"),
                        "reason": attempt.get("reason"),
                        "source_id": attempt.get("source_id"),
                        "url": attempt.get("url"),
                        "missing_concept_group_indexes": attempt.get(
                            "missing_concept_group_indexes", []
                        ),
                    }
                )
                if attempt.get("status") in {"screened_out", "extracted_candidate"}:
                    source_id = attempt.get("source_id")
                    url = attempt.get("url")
                    if type(source_id) is not str or type(url) is not str:
                        raise ValueError("coverage_cross_domain_web_invalid")
                    rows.append(
                        observation(
                            source_ref=source_id,
                            origin_ref=url,
                            read_scope="partial_text",
                            result_status="hit",
                            gap_kind="method_limit"
                            if attempt["status"] == "screened_out"
                            else None,
                        )
                    )
                    retained += 1
            if retained == 0:
                rows.append(
                    observation(
                        source_ref=None,
                        origin_ref=None,
                        read_scope="none",
                        result_status="error"
                        if source_row.get("status") == "failed"
                        else "empty",
                        gap_kind="access_barrier"
                        if source_row.get("status") == "failed"
                        else "search_absence",
                    )
                )
        elif family == "scholarly_index":
            works = capture.get("works")
            if (
                capture.get("status") != "partial_candidate"
                or type(works) is not list
                or len(works) != capture.get("candidate_count")
            ):
                raise ValueError("coverage_cross_domain_scholarly_invalid")
            for work in works:
                if (
                    type(work) is not dict
                    or type(work.get("work_id")) is not str
                    or type(work.get("title")) is not str
                ):
                    raise ValueError("coverage_cross_domain_scholarly_invalid")
                abstract = work.get("abstract_text")
                missing = _missing_concept_groups(
                    work["title"],
                    abstract if type(abstract) is str else "",
                    leaf["concept_groups"],
                )
                lexical.append(
                    {
                        "leaf_id": leaf_id,
                        "work_id": work["work_id"],
                        "missing_concept_group_indexes": missing,
                        "semantic_relevance_verified": False,
                    }
                )
                rows.append(
                    observation(
                        source_ref=work["work_id"],
                        origin_ref=work.get("doi"),
                        read_scope="abstract" if type(abstract) is str else "metadata",
                        result_status="hit",
                        gap_kind="method_limit" if missing else None,
                    )
                )
        else:
            raise ValueError("coverage_cross_domain_family_invalid")
    cumulative = [*previous_observations, *rows]
    progress = assess_beta_coverage(frame, cumulative, budget_exhausted=False)
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageCrossDomainObservation",
            "run_id": frame["run_id"],
            "batch_run_id": plan["run_id"],
            "batch_number": 3,
            "atom_id": atom_id,
            "frame_receipt_hash": frame["receipt_hash"],
            "review_receipt_hash": review["receipt_hash"],
            "batch_plan_receipt_hash": batch_plan["receipt_hash"],
            "execution_receipt_hash": execution["receipt_hash"],
            "portfolio_receipt_hash": portfolio["receipt_hash"],
            "capture_receipt_hashes": capture_hashes,
            "observations": rows,
            "previous_observation_count": len(previous_observations),
            "cumulative_observation_count": len(cumulative),
            "lexical_screen": lexical,
            "web_attempts": web_attempts,
            "unresolved_critic_omission_count": len(review["omitted_facets"]),
            "coverage_assessment_receipt_hash": progress["receipt_hash"],
            "candidate_count": sum(row["source_ref"] is not None for row in rows),
            "semantic_relevance_verified_count": 0,
            "source_calls_completed": execution["source_calls_completed"],
            "saturation_verified": False,
            "release_authorized": False,
        }
    )
    return cumulative, progress, receipt


def observe_dataset_batch(
    *,
    frame: object,
    batch_plan: object,
    plan: object,
    execution: object,
    portfolio: object,
    scholarly_capture: object,
    dataset_capture: object,
    previous_observations: object,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    bound = (
        frame,
        batch_plan,
        plan,
        execution,
        portfolio,
        scholarly_capture,
        dataset_capture,
    )
    if any(
        type(value) is not dict or not verify_receipt_hash(value) for value in bound
    ):
        raise ValueError("coverage_dataset_receipts_invalid")
    if type(previous_observations) is not list:
        raise ValueError("coverage_dataset_history_invalid")
    (
        frame,
        batch_plan,
        plan,
        execution,
        portfolio,
        scholarly_capture,
        dataset_capture,
    ) = (cast(dict[str, Any], value) for value in bound)
    if (
        batch_plan.get("contract") != "BetaCoverageDatasetBatchPlan"
        or batch_plan.get("batch_number") != 4
        or batch_plan.get("frame_receipt_hash") != frame["receipt_hash"]
        or batch_plan.get("subplan_receipt_hash") != plan["receipt_hash"]
        or plan.get("run_id") != batch_plan.get("batch_run_id")
        or plan.get("mode") != "deep"
        or len(plan.get("leaves", [])) != 2
        or plan["leaves"][0]["source_family"] != "scholarly_index"
        or plan["leaves"][1]["source_family"] != "dataset"
        or execution.get("plan_receipt_hash") != plan["receipt_hash"]
        or execution.get("source_calls_completed") != 2
        or portfolio.get("plan_receipt_hash") != plan["receipt_hash"]
        or scholarly_capture.get("contract") != "BetaOpenAlexMetadataAcquisition"
        or dataset_capture.get("contract") != "BetaDataCiteDatasetMetadataAcquisition"
        or scholarly_capture.get("plan_receipt_hash") != plan["receipt_hash"]
        or dataset_capture.get("plan_receipt_hash") != plan["receipt_hash"]
    ):
        raise ValueError("coverage_dataset_lineage_invalid")
    atom_id = batch_plan["atom_id"]
    if not any(atom["atom_id"] == atom_id for atom in frame["atoms"]):
        raise ValueError("coverage_dataset_atom_invalid")
    query_hashes = {
        leaf["leaf_id"]: sha256_json(
            {
                "plan_receipt_hash": plan["receipt_hash"],
                "leaf_id": leaf["leaf_id"],
                "query": leaf["query"],
            }
        )
        for leaf in plan["leaves"]
    }
    rows: list[dict[str, Any]] = []
    lexical: list[dict[str, Any]] = []
    works = scholarly_capture.get("works")
    if (
        scholarly_capture.get("status") != "partial_candidate"
        or type(works) is not list
        or len(works) != scholarly_capture.get("candidate_count")
    ):
        raise ValueError("coverage_dataset_scholarly_invalid")
    for work in works:
        if type(work) is not dict or type(work.get("work_id")) is not str:
            raise ValueError("coverage_dataset_scholarly_invalid")
        abstract = work.get("abstract_text")
        missing = _missing_concept_groups(
            work["title"],
            abstract if type(abstract) is str else "",
            plan["leaves"][0]["concept_groups"],
        )
        lexical.append(
            {"work_id": work["work_id"], "missing_concept_group_indexes": missing}
        )
        rows.append(
            {
                "atom_id": atom_id,
                "batch": 4,
                "query_receipt_hash": query_hashes["LEAF-001"],
                "source_family": "scholarly_index",
                "polarity": "neutral",
                "source_ref": work["work_id"],
                "origin_ref": work.get("doi"),
                "relevance": "uncertain",
                "read_scope": "abstract" if type(abstract) is str else "metadata",
                "material_claim_refs": [],
                "origin_verified": False,
                "result_status": "hit",
                "gap_kind": "method_limit" if missing else None,
            }
        )
    records = dataset_capture.get("records")
    if (
        type(records) is not list
        or len(records) != dataset_capture.get("candidate_count")
        or dataset_capture.get("dataset_content_read") is not False
    ):
        raise ValueError("coverage_dataset_capture_invalid")
    if not records:
        rows.append(
            {
                "atom_id": atom_id,
                "batch": 4,
                "query_receipt_hash": query_hashes["LEAF-002"],
                "source_family": "dataset",
                "polarity": "neutral",
                "source_ref": None,
                "origin_ref": None,
                "relevance": "uncertain",
                "read_scope": "none",
                "material_claim_refs": [],
                "origin_verified": False,
                "result_status": "empty",
                "gap_kind": "search_absence",
            }
        )
    else:
        for record in records:
            if type(record) is not dict or type(record.get("doi")) is not str:
                raise ValueError("coverage_dataset_record_invalid")
            rows.append(
                {
                    "atom_id": atom_id,
                    "batch": 4,
                    "query_receipt_hash": query_hashes["LEAF-002"],
                    "source_family": "dataset",
                    "polarity": "neutral",
                    "source_ref": "https://doi.org/" + record["doi"],
                    "origin_ref": record["doi"],
                    "relevance": "uncertain",
                    "read_scope": "metadata",
                    "material_claim_refs": [],
                    "origin_verified": False,
                    "result_status": "hit",
                    "gap_kind": None,
                }
            )
    cumulative = [*previous_observations, *rows]
    progress = assess_beta_coverage(frame, cumulative, budget_exhausted=False)
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaCoverageDatasetBatchObservation",
            "run_id": frame["run_id"],
            "batch_run_id": plan["run_id"],
            "batch_number": 4,
            "atom_id": atom_id,
            "frame_receipt_hash": frame["receipt_hash"],
            "batch_plan_receipt_hash": batch_plan["receipt_hash"],
            "execution_receipt_hash": execution["receipt_hash"],
            "portfolio_receipt_hash": portfolio["receipt_hash"],
            "scholarly_capture_receipt_hash": scholarly_capture["receipt_hash"],
            "dataset_capture_receipt_hash": dataset_capture["receipt_hash"],
            "query_receipt_hashes": query_hashes,
            "observations": rows,
            "previous_observation_count": len(previous_observations),
            "cumulative_observation_count": len(cumulative),
            "scholarly_lexical_screen": lexical,
            "dataset_doi_metadata_candidate_count": len(records),
            "dataset_content_read": False,
            "empty_dataset_query_is_not_field_absence": not records,
            "coverage_assessment_receipt_hash": progress["receipt_hash"],
            "semantic_relevance_verified_count": 0,
            "saturation_verified": False,
            "release_authorized": False,
        }
    )
    return cumulative, progress, receipt
