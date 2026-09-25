"""Safe byte intake, immutable original, parser-run, and Unicode contracts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import unicodedata
from typing import Any

from .canonical import sha256_json, with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

_TEXT = {"type": "string", "minLength": 1}
_TEXTS = {
    "type": "array",
    "maxItems": 1000,
    "uniqueItems": True,
    "items": _TEXT,
}
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_HARD_MAX_INPUT_BYTES = 64 * 1024 * 1024
_BIDI_CONTROLS = {
    "\u061c",
    "\u200e",
    "\u200f",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
}
_TYPE_PROPERTIES = {
    "pdf": ("application/pdf", ".pdf"),
    "zip": ("application/zip", ".zip"),
    "png": ("image/png", ".png"),
    "jpeg": ("image/jpeg", ".jpg"),
    "gif": ("image/gif", ".gif"),
    "json": ("application/json", ".json"),
    "xml": ("application/xml", ".xml"),
    "utf8_text": ("text/plain", ".txt"),
    "binary": ("application/octet-stream", ".bin"),
}

PARSE_INTAKE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "intake_id",
        "filename",
        "declared_mime",
        "declared_extension",
        "content_base64",
        "source",
        "rights",
        "policy",
        "container_observation",
        "storage_receipt",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "intake_id": _TEXT,
        "filename": _TEXT,
        "declared_mime": _TEXT,
        "declared_extension": _TEXT,
        "content_base64": {"type": "string"},
        "source": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "reference", "acquired_at"],
            "properties": {
                "kind": _TEXT,
                "reference": _TEXT,
                "acquired_at": _TEXT,
            },
        },
        "rights": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "reference"],
            "properties": {
                "status": {"enum": ["allowed", "denied", "unknown"]},
                "reference": _TEXT,
            },
        },
        "policy": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "max_input_bytes",
                "max_processing_ms",
                "max_archive_depth",
                "max_expansion_ratio",
                "max_entries",
                "max_attachments",
                "allow_encrypted",
                "allow_active_content",
                "allowed_detected_types",
                "rights_required",
            ],
            "properties": {
                "max_input_bytes": {"type": "integer", "minimum": 1},
                "max_processing_ms": {"type": "integer", "minimum": 1},
                "max_archive_depth": {"type": "integer", "minimum": 0},
                "max_expansion_ratio": {"type": "number", "exclusiveMinimum": 0},
                "max_entries": {"type": "integer", "minimum": 0},
                "max_attachments": {"type": "integer", "minimum": 0},
                "allow_encrypted": {"type": "boolean"},
                "allow_active_content": {"type": "boolean"},
                "allowed_detected_types": _TEXTS,
                "rights_required": {"type": "boolean"},
            },
        },
        "container_observation": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "elapsed_ms",
                "archive_depth",
                "expanded_bytes",
                "entry_count",
                "attachment_count",
                "encrypted",
                "active_content",
            ],
            "properties": {
                "elapsed_ms": {"type": "integer", "minimum": 0},
                "archive_depth": {"type": "integer", "minimum": 0},
                "expanded_bytes": {"type": "integer", "minimum": 0},
                "entry_count": {"type": "integer", "minimum": 0},
                "attachment_count": {"type": "integer", "minimum": 0},
                "encrypted": {"type": "boolean"},
                "active_content": {"type": "boolean"},
            },
        },
        "storage_receipt": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "storage_ref",
                        "stored_content_hash",
                        "stored_byte_size",
                        "created_exclusive",
                        "immutable",
                        "readback_verified",
                    ],
                    "properties": {
                        "storage_ref": _TEXT,
                        "stored_content_hash": _HASH,
                        "stored_byte_size": {"type": "integer", "minimum": 0},
                        "created_exclusive": {"type": "boolean"},
                        "immutable": {"type": "boolean"},
                        "readback_verified": {"type": "boolean"},
                    },
                },
            ]
        },
    },
}

PARSE_RUNS_RECORD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "original_artifact", "parser_runs"],
    "properties": {
        "schema_version": {"const": 1},
        "original_artifact": {"type": "object"},
        "parser_runs": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "parse_id",
                    "parser_id",
                    "parser_version",
                    "parser_binary_hash",
                    "configuration_hash",
                    "resource_limits",
                    "elapsed_ms",
                    "warnings",
                    "derived_representations",
                    "quality_ref",
                ],
                "properties": {
                    "parse_id": _TEXT,
                    "parser_id": _TEXT,
                    "parser_version": _TEXT,
                    "parser_binary_hash": _HASH,
                    "configuration_hash": _HASH,
                    "resource_limits": {"type": "object"},
                    "elapsed_ms": {"type": "integer", "minimum": 0},
                    "warnings": _TEXTS,
                    "derived_representations": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "quality_ref": _TEXT,
                },
            },
        },
    },
}

UNICODE_REPRESENTATIONS_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "artifact_ref",
        "exact_text",
        "confusable_overrides",
        "quote_candidates",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "artifact_ref": _TEXT,
        "exact_text": {"type": "string"},
        "confusable_overrides": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["exact_index", "expected_character", "search_replacement"],
                "properties": {
                    "exact_index": {"type": "integer", "minimum": 0},
                    "expected_character": _TEXT,
                    "search_replacement": _TEXT,
                },
            },
        },
        "quote_candidates": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["candidate_id", "text", "source_view"],
                "properties": {
                    "candidate_id": _TEXT,
                    "text": {"type": "string"},
                    "source_view": {
                        "enum": ["exact", "display_safe", "search_normalized"]
                    },
                },
            },
        },
    },
}


def _version(data: dict[str, object]) -> None:
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _finite_positive(value: object, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        fail("invalid_number", path, "Требуется конечное положительное число.")
    return float(value)


def _detect_type(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    stripped = content.lstrip()
    if stripped.startswith((b"{", b"[")):
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return "binary"
        return "json"
    if stripped.startswith(b"<"):
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return "binary"
        return "xml"
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    return "utf8_text"


def _decode_base64(value: object, max_bytes: int) -> bytes:
    text = require_string(value, "request.content_base64", nonempty=False)
    encoded_limit = 4 * ((max_bytes + 2) // 3) + 4
    if len(text) > encoded_limit:
        fail(
            "encoded_input_limit_exceeded",
            "request.content_base64",
            "Кодированное представление превышает предел до декодирования.",
        )
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        fail(
            "invalid_base64",
            "request.content_base64",
            "Требуется каноническое Base64-представление.",
        )


def assess_parse_intake(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(PARSE_INTAKE_ASSESS_SCHEMA["required"]), "request")
    _version(data)
    intake_id = require_string(data["intake_id"], "request.intake_id")
    filename = require_string(data["filename"], "request.filename")
    declared_mime = require_string(
        data["declared_mime"], "request.declared_mime"
    ).lower()
    declared_extension = require_string(
        data["declared_extension"], "request.declared_extension"
    ).lower()
    if not declared_extension.startswith("."):
        fail(
            "invalid_extension",
            "request.declared_extension",
            "Расширение должно начинаться с точки.",
        )
    policy = require_mapping(data["policy"], "request.policy")
    policy_fields = {
        "max_input_bytes",
        "max_processing_ms",
        "max_archive_depth",
        "max_expansion_ratio",
        "max_entries",
        "max_attachments",
        "allow_encrypted",
        "allow_active_content",
        "allowed_detected_types",
        "rights_required",
    }
    require_exact_keys(policy, policy_fields, "request.policy")
    max_bytes = require_int(
        policy["max_input_bytes"], "request.policy.max_input_bytes", minimum=1
    )
    if max_bytes > _HARD_MAX_INPUT_BYTES:
        fail(
            "policy_limit_too_large",
            "request.policy.max_input_bytes",
            f"Жёсткий предел равен {_HARD_MAX_INPUT_BYTES} байтам.",
        )
    max_ms = require_int(
        policy["max_processing_ms"], "request.policy.max_processing_ms", minimum=1
    )
    max_depth = require_int(
        policy["max_archive_depth"], "request.policy.max_archive_depth"
    )
    max_ratio = _finite_positive(
        policy["max_expansion_ratio"], "request.policy.max_expansion_ratio"
    )
    max_entries = require_int(policy["max_entries"], "request.policy.max_entries")
    max_attachments = require_int(
        policy["max_attachments"], "request.policy.max_attachments"
    )
    allow_encrypted = require_bool(
        policy["allow_encrypted"], "request.policy.allow_encrypted"
    )
    allow_active = require_bool(
        policy["allow_active_content"], "request.policy.allow_active_content"
    )
    rights_required = require_bool(
        policy["rights_required"], "request.policy.rights_required"
    )
    allowed_types = {
        require_string(item, f"request.policy.allowed_detected_types[{index}]")
        for index, item in enumerate(
            require_list(
                policy["allowed_detected_types"],
                "request.policy.allowed_detected_types",
            )
        )
    }
    unknown_types = sorted(allowed_types - set(_TYPE_PROPERTIES))
    if unknown_types:
        fail(
            "unknown_detected_type",
            "request.policy.allowed_detected_types",
            f"Неизвестный тип: {unknown_types[0]}.",
        )
    content = _decode_base64(data["content_base64"], max_bytes)
    content_hash = hashlib.sha256(content).hexdigest()
    byte_size = len(content)
    detected_type = _detect_type(content)
    detected_mime, canonical_extension = _TYPE_PROPERTIES[detected_type]

    source = require_mapping(data["source"], "request.source")
    require_exact_keys(source, {"kind", "reference", "acquired_at"}, "request.source")
    source_record = {
        "kind": require_string(source["kind"], "request.source.kind"),
        "reference": require_string(source["reference"], "request.source.reference"),
        "acquired_at": require_string(
            source["acquired_at"], "request.source.acquired_at"
        ),
    }
    rights = require_mapping(data["rights"], "request.rights")
    require_exact_keys(rights, {"status", "reference"}, "request.rights")
    rights_status = require_string(rights["status"], "request.rights.status")
    if rights_status not in {"allowed", "denied", "unknown"}:
        fail(
            "invalid_rights_status", "request.rights.status", "Неизвестен статус права."
        )
    rights_record = {
        "status": rights_status,
        "reference": require_string(rights["reference"], "request.rights.reference"),
    }
    observation = require_mapping(
        data["container_observation"], "request.container_observation"
    )
    observation_fields = {
        "elapsed_ms",
        "archive_depth",
        "expanded_bytes",
        "entry_count",
        "attachment_count",
        "encrypted",
        "active_content",
    }
    require_exact_keys(observation, observation_fields, "request.container_observation")
    observed = {
        "elapsed_ms": require_int(
            observation["elapsed_ms"], "request.container_observation.elapsed_ms"
        ),
        "archive_depth": require_int(
            observation["archive_depth"],
            "request.container_observation.archive_depth",
        ),
        "expanded_bytes": require_int(
            observation["expanded_bytes"],
            "request.container_observation.expanded_bytes",
        ),
        "entry_count": require_int(
            observation["entry_count"], "request.container_observation.entry_count"
        ),
        "attachment_count": require_int(
            observation["attachment_count"],
            "request.container_observation.attachment_count",
        ),
        "encrypted": require_bool(
            observation["encrypted"], "request.container_observation.encrypted"
        ),
        "active_content": require_bool(
            observation["active_content"],
            "request.container_observation.active_content",
        ),
    }
    expansion_ratio = observed["expanded_bytes"] / max(byte_size, 1)
    type_mismatch = (
        declared_mime != detected_mime
        or declared_extension
        not in {
            canonical_extension,
            ".jpeg" if detected_type == "jpeg" else canonical_extension,
        }
        or not filename.lower().endswith(declared_extension)
    )
    violations = []
    if type_mismatch:
        violations.append("declared_type_mismatch")
    if byte_size > max_bytes:
        violations.append("input_size_limit_exceeded")
    if observed["elapsed_ms"] > max_ms:
        violations.append("processing_time_limit_exceeded")
    if observed["archive_depth"] > max_depth:
        violations.append("archive_depth_limit_exceeded")
    if expansion_ratio > max_ratio:
        violations.append("expansion_ratio_limit_exceeded")
    if observed["entry_count"] > max_entries:
        violations.append("archive_entry_limit_exceeded")
    if observed["attachment_count"] > max_attachments:
        violations.append("attachment_limit_exceeded")
    if observed["encrypted"] and not allow_encrypted:
        violations.append("encrypted_content_denied")
    if observed["active_content"] and not allow_active:
        violations.append("active_content_denied")
    if detected_type not in allowed_types:
        violations.append("detected_type_denied")
    if rights_required and rights_status != "allowed":
        violations.append("processing_right_not_allowed")

    storage = data["storage_receipt"]
    storage_valid = False
    storage_record = None
    if storage is not None:
        storage_data = require_mapping(storage, "request.storage_receipt")
        storage_fields = {
            "storage_ref",
            "stored_content_hash",
            "stored_byte_size",
            "created_exclusive",
            "immutable",
            "readback_verified",
        }
        require_exact_keys(storage_data, storage_fields, "request.storage_receipt")
        storage_record = {
            "storage_ref": require_string(
                storage_data["storage_ref"], "request.storage_receipt.storage_ref"
            ),
            "stored_content_hash": _hash(
                storage_data["stored_content_hash"],
                "request.storage_receipt.stored_content_hash",
            ),
            "stored_byte_size": require_int(
                storage_data["stored_byte_size"],
                "request.storage_receipt.stored_byte_size",
            ),
            "created_exclusive": require_bool(
                storage_data["created_exclusive"],
                "request.storage_receipt.created_exclusive",
            ),
            "immutable": require_bool(
                storage_data["immutable"], "request.storage_receipt.immutable"
            ),
            "readback_verified": require_bool(
                storage_data["readback_verified"],
                "request.storage_receipt.readback_verified",
            ),
        }
        storage_valid = (
            storage_record["stored_content_hash"] == content_hash
            and storage_record["stored_byte_size"] == byte_size
            and storage_record["created_exclusive"]
            and storage_record["immutable"]
            and storage_record["readback_verified"]
        )
        if not storage_valid:
            violations.append("original_storage_verification_failed")
    else:
        violations.append("original_storage_receipt_missing")

    accepted = not violations and storage_valid
    original_artifact = None
    if accepted and storage_record is not None:
        original_artifact = {
            "artifact_id": f"ORIGINAL-{content_hash[:20]}",
            "intake_id": intake_id,
            "content_hash": content_hash,
            "byte_size": byte_size,
            "detected_type": detected_type,
            "detected_mime": detected_mime,
            "storage_ref": storage_record["storage_ref"],
            "source": source_record,
            "rights": rights_record,
            "immutable": True,
            "readback_verified": True,
            "content_embedded": False,
        }
    return with_receipt_hash(
        {
            "contract": "ParseIntakeDecisionReceipt",
            "status": "accepted" if accepted else "quarantined",
            "intake_id": intake_id,
            "filename": filename,
            "content_hash": content_hash,
            "byte_size": byte_size,
            "detected_type": detected_type,
            "detected_mime": detected_mime,
            "canonical_extension": canonical_extension,
            "declared_type_mismatch": type_mismatch,
            "policy_limits": {
                "max_input_bytes": max_bytes,
                "max_processing_ms": max_ms,
                "max_archive_depth": max_depth,
                "max_expansion_ratio": max_ratio,
                "max_entries": max_entries,
                "max_attachments": max_attachments,
            },
            "container_observation": observed,
            "expansion_ratio": expansion_ratio,
            "violations": sorted(set(violations)),
            "quarantine_record": (
                {
                    "intake_id": intake_id,
                    "content_hash": content_hash,
                    "reason_codes": sorted(set(violations)),
                    "pre_parse": True,
                }
                if not accepted
                else None
            ),
            "original_artifact": original_artifact,
            "parser_allowed": accepted,
            "indexer_allowed": accepted,
            "model_access_allowed": accepted,
            "external_action_performed": False,
        }
    )


_ORIGINAL_FIELDS = {
    "artifact_id",
    "intake_id",
    "content_hash",
    "byte_size",
    "detected_type",
    "detected_mime",
    "storage_ref",
    "source",
    "rights",
    "immutable",
    "readback_verified",
    "content_embedded",
}


def record_parse_runs(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "original_artifact", "parser_runs"}, "request"
    )
    _version(data)
    artifact = require_mapping(data["original_artifact"], "request.original_artifact")
    require_exact_keys(artifact, _ORIGINAL_FIELDS, "request.original_artifact")
    artifact_id = require_string(
        artifact["artifact_id"], "request.original_artifact.artifact_id"
    )
    content_hash = _hash(
        artifact["content_hash"], "request.original_artifact.content_hash"
    )
    if (
        require_bool(artifact["immutable"], "request.original_artifact.immutable")
        is not True
        or require_bool(
            artifact["readback_verified"],
            "request.original_artifact.readback_verified",
        )
        is not True
        or require_bool(
            artifact["content_embedded"], "request.original_artifact.content_embedded"
        )
        is not False
    ):
        fail(
            "original_artifact_not_verified",
            "request.original_artifact",
            "Разбор разрешён только для неизменяемого проверенного оригинала.",
        )
    runs = []
    parse_ids: set[str] = set()
    run_fields = set(
        PARSE_RUNS_RECORD_SCHEMA["properties"]["parser_runs"]["items"]["required"]
    )
    for index, raw in enumerate(
        require_list(data["parser_runs"], "request.parser_runs")
    ):
        path = f"request.parser_runs[{index}]"
        run = require_mapping(raw, path)
        require_exact_keys(run, run_fields, path)
        parse_id = require_string(run["parse_id"], f"{path}.parse_id")
        if parse_id in parse_ids:
            fail("duplicate_parse_id", f"{path}.parse_id", "Повтор parse_id запрещён.")
        parse_ids.add(parse_id)
        resources = require_mapping(run["resource_limits"], f"{path}.resource_limits")
        if not resources:
            fail(
                "resource_limits_missing",
                f"{path}.resource_limits",
                "Границы ресурсов обязательны.",
            )
        warnings = [
            require_string(item, f"{path}.warnings[{warning_index}]")
            for warning_index, item in enumerate(
                require_list(run["warnings"], f"{path}.warnings")
            )
        ]
        representations = []
        representation_kinds: set[str] = set()
        for representation_index, raw_representation in enumerate(
            require_list(
                run["derived_representations"], f"{path}.derived_representations"
            )
        ):
            representation_path = (
                f"{path}.derived_representations[{representation_index}]"
            )
            representation = require_mapping(raw_representation, representation_path)
            require_exact_keys(
                representation,
                {"kind", "reference", "content_hash"},
                representation_path,
            )
            kind = require_string(representation["kind"], f"{representation_path}.kind")
            if kind in representation_kinds:
                fail(
                    "duplicate_representation_kind",
                    f"{representation_path}.kind",
                    "В одном разборе представление каждого вида должно быть единственным.",
                )
            representation_kinds.add(kind)
            representations.append(
                {
                    "kind": kind,
                    "reference": require_string(
                        representation["reference"],
                        f"{representation_path}.reference",
                    ),
                    "content_hash": _hash(
                        representation["content_hash"],
                        f"{representation_path}.content_hash",
                    ),
                }
            )
        runs.append(
            {
                "contract": "ParseIntakeReceipt",
                "parse_id": parse_id,
                "original_artifact_id": artifact_id,
                "original_content_hash": content_hash,
                "parser_id": require_string(run["parser_id"], f"{path}.parser_id"),
                "parser_version": require_string(
                    run["parser_version"], f"{path}.parser_version"
                ),
                "parser_binary_hash": _hash(
                    run["parser_binary_hash"], f"{path}.parser_binary_hash"
                ),
                "configuration_hash": _hash(
                    run["configuration_hash"], f"{path}.configuration_hash"
                ),
                "resource_limits": resources,
                "elapsed_ms": require_int(run["elapsed_ms"], f"{path}.elapsed_ms"),
                "warnings": warnings,
                "derived_representations": representations,
                "quality_ref": require_string(
                    run["quality_ref"], f"{path}.quality_ref"
                ),
            }
        )
    return with_receipt_hash(
        {
            "contract": "ParseRunSetReceipt",
            "status": "recorded",
            "original_artifact_id": artifact_id,
            "original_content_hash": content_hash,
            "parse_receipts": runs,
            "parse_count": len(runs),
            "all_runs_share_original": all(
                run["original_artifact_id"] == artifact_id
                and run["original_content_hash"] == content_hash
                for run in runs
            ),
            "parser_execution_performed": False,
        }
    )


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _search_normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def build_unicode_representations(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, set(UNICODE_REPRESENTATIONS_BUILD_SCHEMA["required"]), "request"
    )
    _version(data)
    artifact_ref = require_string(data["artifact_ref"], "request.artifact_ref")
    exact_text = require_string(
        data["exact_text"], "request.exact_text", nonempty=False
    )
    overrides: dict[int, tuple[str, str]] = {}
    for index, raw in enumerate(
        require_list(data["confusable_overrides"], "request.confusable_overrides")
    ):
        path = f"request.confusable_overrides[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {"exact_index", "expected_character", "search_replacement"},
            path,
        )
        exact_index = require_int(item["exact_index"], f"{path}.exact_index")
        expected = require_string(
            item["expected_character"], f"{path}.expected_character"
        )
        replacement = require_string(
            item["search_replacement"], f"{path}.search_replacement"
        )
        if exact_index >= len(exact_text) or exact_text[exact_index] != expected:
            fail(
                "confusable_locator_mismatch",
                path,
                "Позиция или ожидаемый символ не совпадают с точным текстом.",
            )
        if exact_index in overrides:
            fail(
                "duplicate_confusable_override",
                f"{path}.exact_index",
                "Для позиции разрешена одна замена.",
            )
        overrides[exact_index] = (expected, replacement)

    display_parts: list[str] = []
    search_parts: list[str] = []
    position_map = []
    bidi_positions = []
    confusable_positions = []
    display_offset = 0
    search_offset = 0
    for exact_index, character in enumerate(exact_text):
        transformations = []
        if character in _BIDI_CONTROLS:
            display_piece = f"⟦U+{ord(character):04X}⟧"
            search_piece = ""
            bidi_positions.append(exact_index)
            transformations.append("bidi_control_exposed_and_removed_from_search")
        elif exact_index in overrides:
            replacement = overrides[exact_index][1]
            display_piece = f"{character}⟦U+{ord(character):04X}→{replacement}⟧"
            search_piece = replacement
            confusable_positions.append(exact_index)
            transformations.append("declared_confusable_search_skeleton")
        else:
            display_piece = character
            search_piece = character
        display_start = display_offset
        search_start = search_offset
        display_parts.append(display_piece)
        search_parts.append(search_piece)
        display_offset += len(display_piece)
        search_offset += len(search_piece)
        position_map.append(
            {
                "exact_index": exact_index,
                "display_span": [display_start, display_offset],
                "pre_normalized_search_span": [search_start, search_offset],
                "transformations": transformations,
            }
        )
    display_safe = "".join(display_parts)
    pre_normalized_search = "".join(search_parts)
    search_normalized = _search_normalize(pre_normalized_search)

    candidate_results = []
    candidate_ids: set[str] = set()
    for index, raw in enumerate(
        require_list(data["quote_candidates"], "request.quote_candidates")
    ):
        path = f"request.quote_candidates[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"candidate_id", "text", "source_view"}, path)
        candidate_id = require_string(item["candidate_id"], f"{path}.candidate_id")
        if candidate_id in candidate_ids:
            fail(
                "duplicate_candidate_id",
                f"{path}.candidate_id",
                "Повтор candidate_id запрещён.",
            )
        candidate_ids.add(candidate_id)
        candidate_text = require_string(item["text"], f"{path}.text")
        source_view = require_string(item["source_view"], f"{path}.source_view")
        if source_view not in {"exact", "display_safe", "search_normalized"}:
            fail(
                "invalid_source_view",
                f"{path}.source_view",
                "Неизвестное представление.",
            )
        search_match = _search_normalize(candidate_text) in search_normalized
        exact_match = candidate_text in exact_text
        exact_quote_eligible = source_view == "exact" and exact_match
        candidate_results.append(
            {
                "candidate_id": candidate_id,
                "source_view": source_view,
                "search_match": search_match,
                "exact_sequence_match": exact_match,
                "exact_quote_eligible": exact_quote_eligible,
                "decision": "exact_quote"
                if exact_quote_eligible
                else "search_only_or_unmatched",
            }
        )
    representations = {
        "exact": {
            "text": exact_text,
            "content_hash": _text_hash(exact_text),
            "quote_authority": True,
            "normalization": "none",
        },
        "display_safe": {
            "text": display_safe,
            "content_hash": _text_hash(display_safe),
            "quote_authority": False,
            "normalization": "bidi_visible_confusable_annotated",
        },
        "search_normalized": {
            "text": search_normalized,
            "content_hash": _text_hash(search_normalized),
            "quote_authority": False,
            "normalization": "NFKC_casefold_bidi_removed_declared_confusable_skeleton",
        },
    }
    return with_receipt_hash(
        {
            "contract": "UnicodeRepresentationReceipt",
            "status": "representations_built",
            "artifact_ref": artifact_ref,
            "representations": representations,
            "position_map": position_map,
            "bidi_control_positions": bidi_positions,
            "confusable_positions": confusable_positions,
            "quote_candidates": candidate_results,
            "search_match_implies_exact_quote": False,
            "exact_text_mutated": False,
            "external_action_performed": False,
            "representation_set_hash": sha256_json(representations),
        }
    )
