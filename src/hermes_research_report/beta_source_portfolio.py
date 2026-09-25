"""Reconcile profiled source receipts without inflating evidential independence."""

from __future__ import annotations

import math
import re
from typing import Any, cast

from .academic_datacite import MAX_RAW_BYTES as MAX_DATACITE_RAW_BYTES
from .beta_modes import verify_beta_mode_plan
from .canonical import verify_receipt_hash, with_receipt_hash
from .errors import fail, require_exact_keys, require_list, require_mapping

_HASH = re.compile(r"^[0-9a-f]{64}$")


def _expected_files(receipt: dict[str, object]) -> list[dict[str, object]]:
    contract = receipt.get("contract")
    if contract == "BetaSourceAcquisition":
        rows = require_list(receipt.get("artifact_hashes"), "receipt.artifact_hashes")
        return [require_mapping(row, "receipt.artifact_hashes[]") for row in rows]
    if contract in {
        "BetaOpenAlexMetadataAcquisition",
        "BetaArxivMetadataAcquisition",
        "BetaDataCiteDatasetMetadataAcquisition",
    }:
        return [
            {
                "path": receipt.get("response_file"),
                "sha256": receipt.get("response_sha256"),
                "bytes": receipt.get("response_bytes"),
            }
        ]
    fail("unknown_acquisition_contract", "receipt.contract", "Неизвестная квитанция.")


def _file_rows(
    value: object, path: str, *, maximum: int = 250_000
) -> list[dict[str, object]]:
    rows = []
    for index, item in enumerate(require_list(value, path)):
        row = require_mapping(item, f"{path}[{index}]")
        require_exact_keys(row, {"path", "sha256", "bytes"}, f"{path}[{index}]")
        name, digest, size = row["path"], row["sha256"], row["bytes"]
        if (
            type(name) is not str
            or not name
            or "/" in name
            or "\\" in name
            or name in (".", "..")
            or type(digest) is not str
            or not _HASH.fullmatch(digest)
            or type(size) is not int
            or not 0 <= size <= maximum
        ):
            fail(
                "artifact_row_invalid", f"{path}[{index}]", "Недопустимая запись файла."
            )
        rows.append({"path": name, "sha256": digest, "bytes": size})
    if len({row["path"] for row in rows}) != len(rows):
        fail("duplicate_artifact", path, "Файл указан повторно.")
    return sorted(rows, key=lambda row: str(row["path"]))


def assess_beta_source_portfolio(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "plan", "observations"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    plan = verify_beta_mode_plan(data["plan"])
    observations = require_list(data["observations"], "request.observations")
    if not 1 <= len(observations) <= 20:
        fail(
            "observation_count_invalid", "request.observations", "Нужно 1–20 квитанций."
        )
    planned = {leaf["leaf_id"]: leaf for leaf in plan["leaves"]}
    observed: dict[str, dict[str, Any]] = {}
    cost_total = 0.0
    for index, raw in enumerate(observations):
        path = f"request.observations[{index}]"
        observation = require_mapping(raw, path)
        require_exact_keys(observation, {"receipt", "artifact_readback"}, path)
        receipt = require_mapping(observation["receipt"], f"{path}.receipt")
        if not verify_receipt_hash(receipt):
            fail(
                "acquisition_receipt_hash_invalid",
                f"{path}.receipt",
                "Хеш квитанции не совпадает.",
            )
        if (
            receipt.get("run_id") != plan["run_id"]
            or receipt.get("mode") != plan["mode"]
            or receipt.get("plan_receipt_hash") != plan["receipt_hash"]
            or receipt.get("release_authorized") is not False
        ):
            fail(
                "acquisition_not_bound_to_plan",
                f"{path}.receipt",
                "Квитанция от другого плана.",
            )
        file_maximum = (
            MAX_DATACITE_RAW_BYTES
            if receipt.get("contract") == "BetaDataCiteDatasetMetadataAcquisition"
            else 250_000
        )
        expected_files = _file_rows(
            _expected_files(receipt), f"{path}.expected_files", maximum=file_maximum
        )
        actual_files = _file_rows(
            observation["artifact_readback"],
            f"{path}.artifact_readback",
            maximum=file_maximum,
        )
        if expected_files != actual_files:
            fail(
                "artifact_readback_mismatch",
                f"{path}.artifact_readback",
                "Файлы не совпадают с квитанцией.",
            )
        contract = receipt.get("contract")
        if contract == "BetaSourceAcquisition":
            leaf_rows = require_list(receipt.get("leaves"), f"{path}.receipt.leaves")
            if plan["mode"] != "search" and (
                len(leaf_rows) != 1
                or receipt.get("selected_leaf_id")
                != require_mapping(leaf_rows[0], path).get("leaf_id")
            ):
                fail(
                    "unprofiled_web_receipt",
                    f"{path}.receipt",
                    "Нужен один адресный веб-лист.",
                )
            for raw_leaf in leaf_rows:
                row = require_mapping(raw_leaf, f"{path}.receipt.leaves[]")
                leaf_id = row.get("leaf_id")
                if (
                    type(leaf_id) is not str
                    or leaf_id not in planned
                    or planned[leaf_id]["source_family"] not in {"web", "official"}
                    or row.get("declared_source_family")
                    != planned[leaf_id]["source_family"]
                    or leaf_id in observed
                ):
                    fail(
                        "web_leaf_binding_invalid",
                        f"{path}.receipt.leaves",
                        "Веб-лист не совпадает с планом.",
                    )
                positive = row.get("status") == "extracted_candidate"
                attempts = row.get("candidate_attempts")
                artifacts = receipt.get("artifact_hashes")
                retained_hashes = (
                    {
                        artifact["path"].removesuffix(".txt"): artifact.get("sha256")
                        for artifact in artifacts
                        if type(artifact) is dict
                        and type(artifact.get("path")) is str
                        and artifact["path"].endswith(".txt")
                    }
                    if type(artifacts) is list
                    else {}
                )
                screened_count = (
                    sum(
                        type(attempt) is dict
                        and attempt.get("status") == "screened_out"
                        and type(attempt.get("source_id")) is str
                        and attempt.get("content_sha256")
                        == retained_hashes.get(attempt["source_id"])
                        for attempt in attempts
                    )
                    if type(attempts) is list
                    else 0
                )
                failed_extract_count = (
                    sum(
                        type(attempt) is dict and attempt.get("status") == "failed"
                        for attempt in attempts
                    )
                    if type(attempts) is list
                    else 0
                )
                observed[leaf_id] = {
                    "leaf_id": leaf_id,
                    "provider": "keenable_configured",
                    "source_family": planned[leaf_id]["source_family"],
                    "status": "candidate" if positive else "failed",
                    "reason": row.get("reason"),
                    "read_scope": "extracted_text_only"
                    if positive
                    else "extracted_text_screened_unverified"
                    if screened_count
                    else "none",
                    "candidate_count": row.get("retained_candidate_count", 1)
                    if positive
                    else 0,
                    "retained_screened_text_count": screened_count,
                    "failed_extract_attempt_count": failed_extract_count,
                    "route_configuration_verified": receipt.get(
                        "route_configuration_verified"
                    )
                    is True,
                    "provider_reply_attested": row.get("provider_reply_attested")
                    is True,
                    "primary_origin_independence_verified": False,
                    "receipt_hash": receipt["receipt_hash"],
                }
        elif contract == "BetaOpenAlexMetadataAcquisition":
            leaf_id = receipt.get("leaf_id")
            if (
                type(leaf_id) is not str
                or leaf_id not in planned
                or planned[leaf_id]["source_family"] != "scholarly_index"
                or receipt.get("source_family") != "scholarly_index"
                or receipt.get("provider") != "openalex"
                or leaf_id in observed
            ):
                fail(
                    "scholarly_leaf_binding_invalid",
                    f"{path}.receipt",
                    "Научный лист не совпадает с планом.",
                )
            positive = (
                receipt.get("status") == "partial_candidate"
                and receipt.get("provider_identity_verified") is True
            )
            cost = receipt.get("reported_cost_usd")
            if type(cost) in (int, float):
                cost_number = float(cast(int | float, cost))
                if not math.isfinite(cost_number) or cost_number < 0:
                    fail(
                        "provider_cost_invalid",
                        f"{path}.receipt",
                        "Недопустимая стоимость.",
                    )
                cost_total += cost_number
            elif positive:
                fail(
                    "provider_cost_missing",
                    f"{path}.receipt",
                    "Нет стоимости обращения.",
                )
            works = receipt.get("works")
            abstract_count = (
                sum(
                    type(work) is dict
                    and work.get("read_scope") == "metadata_and_reconstructed_abstract"
                    for work in works
                )
                if type(works) is list
                else 0
            )
            observed[leaf_id] = {
                "leaf_id": leaf_id,
                "provider": "openalex",
                "source_family": "scholarly_index",
                "status": "candidate" if positive else "failed",
                "reason": receipt.get("reason"),
                "read_scope": "metadata_or_reconstructed_abstract_only"
                if positive and abstract_count
                else "metadata_only"
                if positive
                else "none",
                "abstract_candidate_count": abstract_count if positive else 0,
                "candidate_count": receipt.get("candidate_count") if positive else 0,
                "route_configuration_verified": receipt.get(
                    "provider_identity_verified"
                )
                is True,
                "provider_reply_attested": positive,
                "primary_origin_independence_verified": False,
                "receipt_hash": receipt["receipt_hash"],
            }
        elif contract == "BetaArxivMetadataAcquisition":
            leaf_id = receipt.get("leaf_id")
            if (
                type(leaf_id) is not str
                or leaf_id not in planned
                or planned[leaf_id]["source_family"] != "preprint_archive"
                or receipt.get("source_family") != "preprint_archive"
                or receipt.get("provider") != "arxiv"
                or leaf_id in observed
            ):
                fail(
                    "preprint_leaf_binding_invalid",
                    f"{path}.receipt",
                    "Архивный лист не совпадает с планом.",
                )
            positive = (
                receipt.get("status") == "partial_candidate"
                and receipt.get("provider_identity_verified") is True
            )
            observed[leaf_id] = {
                "leaf_id": leaf_id,
                "provider": "arxiv",
                "source_family": "preprint_archive",
                "status": "candidate" if positive else "failed",
                "reason": receipt.get("reason"),
                "read_scope": "parsed_atom_abstract_only" if positive else "none",
                "candidate_count": receipt.get("candidate_count") if positive else 0,
                "route_configuration_verified": receipt.get(
                    "provider_identity_verified"
                )
                is True,
                "provider_reply_attested": positive,
                "primary_origin_independence_verified": False,
                "receipt_hash": receipt["receipt_hash"],
            }
        elif contract == "BetaDataCiteDatasetMetadataAcquisition":
            leaf_id = receipt.get("leaf_id")
            if (
                type(leaf_id) is not str
                or leaf_id not in planned
                or planned[leaf_id]["source_family"] != "dataset"
                or receipt.get("source_family") != "dataset"
                or receipt.get("provider") != "datacite"
                or leaf_id in observed
                or receipt.get("dataset_content_read") is not False
                or receipt.get("dataset_schema_verified") is not False
            ):
                fail(
                    "dataset_leaf_binding_invalid",
                    f"{path}.receipt",
                    "Запись DataCite не совпадает с планом либо преувеличивает чтение данных.",
                )
            positive = (
                receipt.get("status") == "partial_candidate"
                and receipt.get("provider_identity_verified") is True
            )
            reported_cost = receipt.get("reported_cost_usd")
            if type(reported_cost) not in (int, float):
                fail(
                    "provider_cost_invalid",
                    f"{path}.receipt",
                    "Недопустимая стоимость.",
                )
            cost_number = float(cast(int | float, reported_cost))
            if cost_number < 0:
                fail(
                    "provider_cost_invalid",
                    f"{path}.receipt",
                    "Недопустимая стоимость.",
                )
            cost_total += cost_number
            observed[leaf_id] = {
                "leaf_id": leaf_id,
                "provider": "datacite",
                "source_family": "dataset",
                "status": "candidate" if positive else "failed",
                "reason": receipt.get("reason"),
                "read_scope": "dataset_doi_metadata_only" if positive else "none",
                "candidate_count": receipt.get("candidate_count") if positive else 0,
                "dataset_content_read": False,
                "dataset_schema_verified": False,
                "route_configuration_verified": receipt.get(
                    "provider_identity_verified"
                )
                is True,
                "provider_reply_attested": positive,
                "primary_origin_independence_verified": False,
                "receipt_hash": receipt["receipt_hash"],
            }
    ordered = [
        observed[leaf["leaf_id"]]
        for leaf in plan["leaves"]
        if leaf["leaf_id"] in observed
    ]
    covered = [row["leaf_id"] for row in ordered if row["status"] == "candidate"]
    missing = sorted(set(planned) - set(covered))
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaSourcePortfolio",
            "status": (
                "partial_review_required"
                if plan["schema_version"] == 1
                else "partial_analysis_required"
            )
            if covered
            else "blocked",
            "run_id": plan["run_id"],
            "mode": plan["mode"],
            "plan_receipt_hash": plan["receipt_hash"],
            "observed_leaf_count": len(ordered),
            "candidate_leaf_ids": covered,
            "missing_or_failed_leaf_ids": missing,
            "leaves": ordered,
            "retained_screened_text_count": sum(
                row.get("retained_screened_text_count", 0) for row in ordered
            ),
            "reported_provider_cost_usd": cost_total,
            "independent_primary_source_count": 0,
            "source_family_diversity_as_evidence_verified": False,
            "semantic_support_verified": False,
            "mode_qualified": False,
            "release_authorized": False,
            "external_delivery_authorized": False,
        }
    )
