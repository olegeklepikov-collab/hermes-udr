"""Materialize an exact in-memory corpus proposal from acquisition receipts."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from .canonical import sha256_json, with_receipt_hash
from .errors import (
    fail,
    require_exact_keys,
    require_list,
    require_mapping,
    require_string,
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_TEXT = {"type": "string", "minLength": 1}
_NULLABLE_TEXT = {"type": ["string", "null"]}
_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "url",
        "source_version",
        "status",
        "title",
        "abstract",
        "content",
        "content_hash",
        "error",
    ],
    "properties": {
        "url": _TEXT,
        "source_version": _TEXT,
        "status": {"enum": ["success", "error"]},
        "title": _NULLABLE_TEXT,
        "abstract": _NULLABLE_TEXT,
        "content": _NULLABLE_TEXT,
        "content_hash": {
            "anyOf": [
                {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                {"type": "null"},
            ]
        },
        "error": _NULLABLE_TEXT,
    },
}
_RECEIPT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "receipt_id",
        "route_receipt_ref",
        "accessed_at",
        "requested_urls",
        "raw_response_ref",
        "raw_response_hash",
        "results",
    ],
    "properties": {
        "receipt_id": _TEXT,
        "route_receipt_ref": _TEXT,
        "accessed_at": _TEXT,
        "requested_urls": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "uniqueItems": True,
            "items": _TEXT,
        },
        "raw_response_ref": _TEXT,
        "raw_response_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "results": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": _RESULT_SCHEMA,
        },
    },
}
CORPUS_MATERIALIZE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "run_id", "frame", "receipts"],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "frame": {
            "type": "object",
            "additionalProperties": False,
            "required": ["question", "profile", "limitations"],
            "properties": {
                "question": _TEXT,
                "profile": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["domain", "depth", "risk"],
                    "properties": {
                        "domain": {"enum": ["general", "business", "academic"]},
                        "depth": {"enum": ["search", "deep", "ultra"]},
                        "risk": {"enum": ["low", "medium", "high"]},
                    },
                },
                "limitations": {
                    "type": "array",
                    "maxItems": 100,
                    "items": _TEXT,
                },
            },
        },
        "receipts": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "items": _RECEIPT_SCHEMA,
        },
    },
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _url(value: object, path: str) -> str:
    text = require_string(value, path)
    try:
        parts = urlsplit(text)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or any(char.isspace() or char in '<>\\"' or ord(char) < 32 for char in text)
        ):
            raise ValueError
        _ = parts.port
    except ValueError:
        fail("invalid_url", path, "Требуется HTTP(S) URL без реквизитов доступа.")
    return text


def _timestamp(value: object, path: str) -> str:
    text = require_string(value, path)
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None or "T" not in text:
            raise ValueError
    except ValueError:
        fail(
            "invalid_timestamp",
            path,
            "Требуются дата и время ISO 8601 с часовым поясом.",
        )
    return text


def _nullable_text(value: object, path: str) -> str | None:
    if value is None:
        return None
    return require_string(value, path, nonempty=False)


def materialize_corpus(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "run_id", "frame", "receipts"}, "request"
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    frame = require_mapping(data["frame"], "request.frame")
    require_exact_keys(frame, {"question", "profile", "limitations"}, "request.frame")
    question = require_string(frame["question"], "request.frame.question")
    profile = require_mapping(frame["profile"], "request.frame.profile")
    require_exact_keys(profile, {"domain", "depth", "risk"}, "request.frame.profile")
    normalized_profile = {
        key: require_string(profile[key], f"request.frame.profile.{key}")
        for key in ("domain", "depth", "risk")
    }
    if normalized_profile["domain"] not in {"general", "business", "academic"}:
        fail("invalid_profile", "request.frame.profile.domain", "Неверное направление.")
    if normalized_profile["depth"] not in {"search", "deep", "ultra"}:
        fail("invalid_profile", "request.frame.profile.depth", "Неверная глубина.")
    if normalized_profile["risk"] not in {"low", "medium", "high"}:
        fail("invalid_profile", "request.frame.profile.risk", "Неверный риск.")
    limitations_raw = require_list(frame["limitations"], "request.frame.limitations")
    limitations = [
        require_string(item, f"request.frame.limitations[{index}]")
        for index, item in enumerate(limitations_raw)
    ]
    if len(limitations) > 100:
        fail("size_limit", "request.frame.limitations", "Слишком много ограничений.")

    receipts = require_list(data["receipts"], "request.receipts")
    if not receipts or len(receipts) > 10:
        fail("invalid_receipts", "request.receipts", "Требуется от 1 до 10 квитанций.")
    receipt_ids: set[str] = set()
    versions: dict[tuple[str, str], dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    total_characters = 0
    for receipt_index, raw_receipt in enumerate(receipts):
        path = f"request.receipts[{receipt_index}]"
        receipt = require_mapping(raw_receipt, path)
        require_exact_keys(receipt, set(_RECEIPT_SCHEMA["required"]), path)
        receipt_id = require_string(receipt["receipt_id"], f"{path}.receipt_id")
        if receipt_id in receipt_ids:
            fail("duplicate_receipt", f"{path}.receipt_id", "Повторная квитанция.")
        receipt_ids.add(receipt_id)
        route_ref = require_string(
            receipt["route_receipt_ref"], f"{path}.route_receipt_ref"
        )
        accessed_at = _timestamp(receipt["accessed_at"], f"{path}.accessed_at")
        raw_ref = require_string(
            receipt["raw_response_ref"], f"{path}.raw_response_ref"
        )
        raw_hash = _hash(receipt["raw_response_hash"], f"{path}.raw_response_hash")
        requested_raw = require_list(
            receipt["requested_urls"], f"{path}.requested_urls"
        )
        if not requested_raw or len(requested_raw) > 1000:
            fail(
                "invalid_urls",
                f"{path}.requested_urls",
                "Требуется непустой ограниченный URL-список.",
            )
        requested = [
            _url(item, f"{path}.requested_urls[{index}]")
            for index, item in enumerate(requested_raw)
        ]
        if len(requested) != len(set(requested)):
            fail(
                "duplicate_requested_url",
                f"{path}.requested_urls",
                "Повторный URL в одной квитанции.",
            )
        results_raw = require_list(receipt["results"], f"{path}.results")
        if len(results_raw) != len(requested):
            fail(
                "incomplete_response",
                f"{path}.results",
                "Каждому URL нужен ровно один результат.",
            )
        normalized_results: list[dict[str, Any]] = []
        result_urls: list[str] = []
        for result_index, raw_result in enumerate(results_raw):
            result_path = f"{path}.results[{result_index}]"
            result = require_mapping(raw_result, result_path)
            require_exact_keys(result, set(_RESULT_SCHEMA["required"]), result_path)
            url = _url(result["url"], f"{result_path}.url")
            result_urls.append(url)
            status = require_string(result["status"], f"{result_path}.status")
            if status not in {"success", "error"}:
                fail(
                    "invalid_result_status",
                    f"{result_path}.status",
                    "Неверный статус результата.",
                )
            normalized_results.append(
                {
                    "url": url,
                    "source_version": require_string(
                        result["source_version"], f"{result_path}.source_version"
                    ),
                    "status": status,
                    "title": _nullable_text(result["title"], f"{result_path}.title"),
                    "abstract": _nullable_text(
                        result["abstract"], f"{result_path}.abstract"
                    ),
                    "content": _nullable_text(
                        result["content"], f"{result_path}.content"
                    ),
                    "content_hash": result["content_hash"],
                    "error": _nullable_text(result["error"], f"{result_path}.error"),
                }
            )
        if sorted(result_urls) != sorted(requested) or len(result_urls) != len(
            set(result_urls)
        ):
            fail(
                "incomplete_response",
                f"{path}.results",
                "Каждому запрошенному URL нужен ровно один результат.",
            )

        for result in normalized_results:
            key = (result["url"], result["source_version"])
            row = {
                "receipt_id": receipt_id,
                "route_receipt_ref": route_ref,
                "raw_response_ref": raw_ref,
                "raw_response_hash": raw_hash,
                "url": result["url"],
                "source_version": result["source_version"],
            }
            if result["status"] == "error":
                if (
                    not result["error"]
                    or result["content"] is not None
                    or result["content_hash"] is not None
                ):
                    fail(
                        "invalid_error_result",
                        f"{path}.results",
                        "Ошибка должна иметь причину и не иметь content/hash.",
                    )
                row.update(status="excluded", reason=result["error"])
                audit.append(row)
                continue
            content = result["content"]
            if not content or result["error"] is not None:
                fail(
                    "invalid_success_result",
                    f"{path}.results",
                    "Успешный результат требует content и не допускает error.",
                )
            computed_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            supplied_hash = _hash(
                result["content_hash"], f"{path}.results.content_hash"
            )
            if supplied_hash != computed_hash:
                fail(
                    "content_hash_mismatch",
                    f"{path}.results.content_hash",
                    "Хеш текста не совпадает.",
                )
            if key in versions:
                if versions[key]["content_hash"] != computed_hash:
                    fail(
                        "source_version_conflict",
                        f"{path}.results",
                        "Разные тексты одной URL-версии нельзя заменять молча.",
                    )
                row.update(status="duplicate", source_id=versions[key]["source_id"])
                audit.append(row)
                continue
            title = (
                result["title"]
                if result["title"] and result["title"].strip()
                else result["url"][:1000]
            )
            source_id = (
                "SRC-"
                + sha256_json(
                    {
                        "url": result["url"],
                        "version": result["source_version"],
                        "content_hash": computed_hash,
                    }
                )[:20]
            )
            source = {
                "source_id": source_id,
                "run_id": run_id,
                "canonical_url": result["url"],
                "source_version": result["source_version"],
                "title": title,
                "abstract_present": bool(
                    result["abstract"] and result["abstract"].strip()
                ),
                "exact_text": content,
                "content_hash": computed_hash,
                "acquired_at": accessed_at,
                "acquisition_receipt_ref": receipt_id,
                "route_receipt_ref": route_ref,
                "raw_response_ref": raw_ref,
                "raw_response_hash": raw_hash,
                "read_status": "acquired",
                "declared_scope": "provider_returned_content",
                "read_scope": None,
                "origin_verified": False,
                "immutable_original_proposed": True,
                "persistence_applied": False,
            }
            total_characters += len(content)
            if total_characters > 500000:
                fail(
                    "size_limit",
                    "request.receipts",
                    "Общий объём text превышает 500000 символов.",
                )
            versions[key] = source
            sources.append(source)
            row.update(
                status="included",
                source_id=source_id,
                title_from_url=title == result["url"][:1000],
                abstract_missing=not source["abstract_present"],
                content_hash=computed_hash,
            )
            audit.append(row)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "CorpusMaterializationReceipt",
        "status": "materialized_proposal",
        "run_id": run_id,
        "frame": {
            "question": question,
            "profile": normalized_profile,
            "limitations": limitations,
        },
        "source_count": len(sources),
        "excluded_count": sum(row["status"] == "excluded" for row in audit),
        "duplicate_count": sum(row["status"] == "duplicate" for row in audit),
        "total_text_characters": total_characters,
        "source_proposals": sources,
        "acquisition_audit": audit,
        "raw_responses_preserved_before_summarization": True,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)
