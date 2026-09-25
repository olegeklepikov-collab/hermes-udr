"""Source selection and independently anchored fragment verification."""

from __future__ import annotations

import hashlib
import re
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

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_LEVELS = ("unusable", "weak_signal", "strong_secondary", "primary")
_RELATIONS = {
    "direct",
    "proxy",
    "context",
    "weak_signal",
    "contradiction",
    "discovery_only",
}
_AVAILABILITY = {"readable", "metadata_only", "unavailable"}
_QUALITY_DIMENSIONS = {
    "provenance",
    "proximity",
    "competence",
    "method_fit",
    "specificity",
    "recency",
    "independence",
    "incentive_risk",
    "transferability",
    "volatility_control",
}
_LOCATOR_TYPES = {
    "html_dom_text",
    "pdf_page_region",
    "pdf_text_range",
    "table_range",
    "file_byte_range",
    "file_line_range",
}
_READ_STATES = {"not_acquired", "acquired", "unreadable", "partial", "read_in_scope"}
_TEXT = {"type": "string", "minLength": 1}
_NULLABLE_TEXT = {"type": ["string", "null"]}
_QUALITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_QUALITY_DIMENSIONS),
    "properties": {
        key: {"type": "integer", "minimum": 0, "maximum": 4}
        for key in _QUALITY_DIMENSIONS
    },
}
SOURCE_SELECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "run_id", "candidate", "requirement", "quality"],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "candidate": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "candidate_id",
                "candidate_version",
                "source_family",
                "source_class",
                "availability",
                "full_text_available",
                "abstract_available",
                "origin_cluster_id",
                "citation_lineage_state",
            ],
            "properties": {
                "candidate_id": _TEXT,
                "candidate_version": _TEXT,
                "source_family": _TEXT,
                "source_class": {"enum": list(_LEVELS)},
                "availability": {"enum": sorted(_AVAILABILITY)},
                "full_text_available": {"type": "boolean"},
                "abstract_available": {"type": "boolean"},
                "origin_cluster_id": _TEXT,
                "citation_lineage_state": _TEXT,
            },
        },
        "requirement": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "requirement_id",
                "required",
                "required_relation",
                "minimum_level",
                "readable_required",
                "role_in_argument",
            ],
            "properties": {
                "requirement_id": _TEXT,
                "required": {"type": "boolean"},
                "required_relation": {"enum": sorted(_RELATIONS)},
                "minimum_level": {"enum": list(_LEVELS)},
                "readable_required": {"type": "boolean"},
                "role_in_argument": _TEXT,
            },
        },
        "quality": _QUALITY_SCHEMA,
    },
}

_TRANSFORMATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "transformation_id",
        "kind",
        "tool_version",
        "input_hash",
        "output_hash",
        "verified_against_original",
    ],
    "properties": {
        "transformation_id": _TEXT,
        "kind": {
            "enum": [
                "ocr",
                "translation",
                "normalization",
                "pdf_text_extraction",
                "table_extraction",
                "formula_extraction",
            ]
        },
        "tool_version": _TEXT,
        "input_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "output_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "verified_against_original": {"type": "boolean"},
    },
}
_SCOPE_UNIT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["unit_id", "component_id", "component_hash", "text_hash", "kind"],
    "properties": {
        "unit_id": _TEXT,
        "component_id": _TEXT,
        "component_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "text_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "kind": {"enum": ["main", "supplement"]},
    },
}
_SCOPE_READBACK = {
    "type": "object",
    "additionalProperties": False,
    "required": ["scope", "original_hash", "manifest", "manifest_hash", "reads"],
    "properties": {
        "scope": _TEXT,
        "original_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "manifest_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "manifest": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10000,
            "items": _SCOPE_UNIT,
        },
        "reads": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["unit_id", "component_hash", "read_text"],
                "properties": {
                    "unit_id": _TEXT,
                    "component_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "read_text": {"type": "string", "maxLength": 500000},
                },
            },
        },
    },
}
FRAGMENT_VERIFY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "source_asset",
        "fragment",
        "independent_verification",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "source_asset": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "source_id",
                "source_version",
                "producer_id",
                "original_content_hash",
                "verification_text",
                "verification_text_hash",
                "read_status",
                "declared_scope",
                "read_scope",
                "material_supplements_required",
                "material_supplements_read",
                "transformations",
            ],
            "properties": {
                "source_id": _TEXT,
                "source_version": _TEXT,
                "producer_id": _TEXT,
                "original_content_hash": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "verification_text": {"type": "string"},
                "verification_text_hash": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "read_status": {"enum": sorted(_READ_STATES)},
                "declared_scope": _TEXT,
                "read_scope": _NULLABLE_TEXT,
                "material_supplements_required": {"type": "boolean"},
                "material_supplements_read": {"type": "boolean"},
                "scope_readback": _SCOPE_READBACK,
                "transformations": {
                    "type": "array",
                    "maxItems": 100,
                    "items": _TRANSFORMATION_SCHEMA,
                },
            },
        },
        "fragment": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "fragment_id",
                "locator_type",
                "coordinates",
                "start",
                "end",
                "exact_fragment",
                "fragment_hash",
                "derived_registry_ref",
            ],
            "properties": {
                "fragment_id": _TEXT,
                "locator_type": {"enum": sorted(_LOCATOR_TYPES)},
                "coordinates": _TEXT,
                "start": {"type": ["integer", "null"], "minimum": 0},
                "end": {"type": ["integer", "null"], "minimum": 0},
                "exact_fragment": {"type": "string"},
                "fragment_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "derived_registry_ref": _NULLABLE_TEXT,
            },
        },
        "independent_verification": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "verifier_id",
                "locator_receipt_ref",
                "original_readback_hash",
                "resolved_fragment",
                "used_derived_registry",
                "status",
            ],
            "properties": {
                "verifier_id": _TEXT,
                "locator_receipt_ref": _TEXT,
                "original_readback_hash": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "resolved_fragment": {"type": "string"},
                "scope_manifest_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "used_derived_registry": {"type": "boolean"},
                "status": {"enum": ["pass", "fail"]},
            },
        },
    },
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def select_source(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {"schema_version", "run_id", "candidate", "requirement", "quality"},
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    candidate = require_mapping(data["candidate"], "request.candidate")
    require_exact_keys(
        candidate,
        set(SOURCE_SELECT_SCHEMA["properties"]["candidate"]["required"]),
        "request.candidate",
    )
    normalized_candidate = {
        "candidate_id": require_string(
            candidate["candidate_id"], "request.candidate.candidate_id"
        ),
        "candidate_version": require_string(
            candidate["candidate_version"], "request.candidate.candidate_version"
        ),
        "source_family": require_string(
            candidate["source_family"], "request.candidate.source_family"
        ),
        "source_class": require_string(
            candidate["source_class"], "request.candidate.source_class"
        ),
        "availability": require_string(
            candidate["availability"], "request.candidate.availability"
        ),
        "full_text_available": require_bool(
            candidate["full_text_available"], "request.candidate.full_text_available"
        ),
        "abstract_available": require_bool(
            candidate["abstract_available"], "request.candidate.abstract_available"
        ),
        "origin_cluster_id": require_string(
            candidate["origin_cluster_id"], "request.candidate.origin_cluster_id"
        ),
        "citation_lineage_state": require_string(
            candidate["citation_lineage_state"],
            "request.candidate.citation_lineage_state",
        ),
    }
    if normalized_candidate["source_class"] not in _LEVELS:
        fail(
            "invalid_source_class",
            "request.candidate.source_class",
            "Неверный класс источника.",
        )
    if normalized_candidate["availability"] not in _AVAILABILITY:
        fail(
            "invalid_availability",
            "request.candidate.availability",
            "Неверная доступность.",
        )
    requirement = require_mapping(data["requirement"], "request.requirement")
    require_exact_keys(
        requirement,
        set(SOURCE_SELECT_SCHEMA["properties"]["requirement"]["required"]),
        "request.requirement",
    )
    required = require_bool(requirement["required"], "request.requirement.required")
    relation = require_string(
        requirement["required_relation"], "request.requirement.required_relation"
    )
    minimum = require_string(
        requirement["minimum_level"], "request.requirement.minimum_level"
    )
    readable_required = require_bool(
        requirement["readable_required"], "request.requirement.readable_required"
    )
    if relation not in _RELATIONS:
        fail(
            "invalid_relation",
            "request.requirement.required_relation",
            "Неверное отношение.",
        )
    if minimum not in _LEVELS:
        fail(
            "invalid_source_level",
            "request.requirement.minimum_level",
            "Неверный минимальный уровень.",
        )
    requirement_id = require_string(
        requirement["requirement_id"], "request.requirement.requirement_id"
    )
    role = require_string(
        requirement["role_in_argument"], "request.requirement.role_in_argument"
    )
    quality = require_mapping(data["quality"], "request.quality")
    require_exact_keys(quality, _QUALITY_DIMENSIONS, "request.quality")
    scores = {
        key: require_int(quality[key], f"request.quality.{key}")
        for key in sorted(_QUALITY_DIMENSIONS)
    }
    if any(score > 4 for score in scores.values()):
        fail(
            "invalid_quality_score", "request.quality", "Оценка должна быть от 0 до 4."
        )
    quality_mean = sum(scores.values()) / len(scores)

    issues: list[str] = []
    if normalized_candidate["availability"] == "unavailable":
        issues.append("source_unavailable")
    if readable_required and (
        normalized_candidate["availability"] != "readable"
        or not normalized_candidate["full_text_available"]
    ):
        issues.append("readable_full_text_required")
    if _LEVELS.index(normalized_candidate["source_class"]) < _LEVELS.index(minimum):
        issues.append("source_level_below_requirement")
    if quality_mean < 2:
        issues.append("quality_below_threshold")

    if issues and required:
        decision = "replacement_required"
    elif "source_unavailable" in issues:
        decision = "exclude"
    elif issues:
        decision = "context_only"
    elif quality_mean < 3:
        decision = "include_with_caveat"
    elif relation == "discovery_only":
        decision = "discovery_only"
    else:
        decision = "include"
    caveat = "; ".join(issues) if issues else None
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "SourceSelectionRecord",
        "status": "decided",
        "run_id": run_id,
        "candidate_ref": {
            "id": normalized_candidate["candidate_id"],
            "version": normalized_candidate["candidate_version"],
        },
        "requirement_id": requirement_id,
        "source_family": normalized_candidate["source_family"],
        "source_class": normalized_candidate["source_class"],
        "relation": relation,
        "quality": scores,
        "quality_mean": quality_mean,
        "decision": decision,
        "role_in_argument": role,
        "caveat": caveat,
        "replacement_required": decision == "replacement_required",
        "origin_cluster_id": normalized_candidate["origin_cluster_id"],
        "citation_lineage_state": normalized_candidate["citation_lineage_state"],
        "abstract_missing_but_full_text_available": (
            not normalized_candidate["abstract_available"]
            and normalized_candidate["full_text_available"]
        ),
        "evidence_status_changed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def _resolve_range(
    locator_type: str, start: int | None, end: int | None, text: str
) -> str | None:
    if locator_type == "file_byte_range":
        if start is None or end is None or start > end:
            return None
        encoded = text.encode("utf-8")
        try:
            return encoded[start:end].decode("utf-8")
        except UnicodeDecodeError:
            return None
    if locator_type in {"pdf_text_range", "html_dom_text"}:
        if start is None or end is None or start > end:
            return None
        return text[start:end]
    if locator_type == "file_line_range":
        if start is None or end is None or start < 1 or start > end:
            return None
        return "\n".join(text.splitlines()[start - 1 : end])
    return None


def _scope_coverage(value, original_hash, declared_scope, supplements_required):
    data = require_mapping(value, "scope_readback")
    require_exact_keys(data, set(_SCOPE_READBACK["required"]), "scope_readback")
    manifest = require_list(data["manifest"], "scope_readback.manifest")
    reads = require_list(data["reads"], "scope_readback.reads")
    if not manifest or len(manifest) > 10000 or len(reads) > 10000:
        fail(
            "scope_manifest_size_invalid",
            "scope_readback",
            "Нужен конечный непустой состав области.",
        )
    issues = []
    if data["original_hash"] != original_hash or data["scope"] != declared_scope:
        issues.append("scope_manifest_source_mismatch")
    if _hash(data["manifest_hash"], "scope_readback.manifest_hash") != sha256_json(
        manifest
    ):
        issues.append("scope_manifest_hash_mismatch")
    units = {}
    components = {}
    for index, raw in enumerate(manifest):
        path = f"scope_readback.manifest[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, set(_SCOPE_UNIT["required"]), path)
        uid = require_string(row["unit_id"], path + ".unit_id")
        if uid in units:
            fail("scope_unit_duplicate", path, "Единица области повторена.")
        component_id = require_string(row["component_id"], path + ".component_id")
        _hash(row["component_hash"], path + ".component_hash")
        _hash(row["text_hash"], path + ".text_hash")
        kind = require_string(row["kind"], path + ".kind")
        if kind not in {"main", "supplement"}:
            fail("scope_unit_kind_invalid", path, "Неизвестный вид компонента.")
        units[uid] = row
        binding = (row["component_hash"], row["kind"])
        if (
            row["component_id"] in components
            and components[row["component_id"]] != binding
        ):
            issues.append("scope_component_version_conflict:" + component_id)
        components[row["component_id"]] = binding
        if row["kind"] == "main" and row["component_hash"] != original_hash:
            issues.append("scope_main_component_unbound")
    if supplements_required and not any(
        row["kind"] == "supplement" for row in units.values()
    ):
        issues.append("scope_supplement_manifest_missing")
    if not any(
        row["kind"] == "main" and row["component_hash"] == original_hash
        for row in units.values()
    ):
        issues.append("scope_main_component_unbound")
    observed = set()
    total = 0
    for index, raw in enumerate(reads):
        path = f"scope_readback.reads[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"unit_id", "component_hash", "read_text"}, path)
        uid = require_string(row["unit_id"], path + ".unit_id")
        if uid in observed:
            fail("scope_read_duplicate", path, "Повтор чтения не добавляет покрытия.")
        observed.add(uid)
        _hash(row["component_hash"], path + ".component_hash")
        text = require_string(row["read_text"], path + ".read_text", nonempty=False)
        total += len(text)
        if uid not in units:
            issues.append("scope_unknown_unit:" + uid)
        elif (
            row["component_hash"] != units[uid]["component_hash"]
            or hashlib.sha256(text.encode()).hexdigest() != units[uid]["text_hash"]
        ):
            issues.append("scope_readback_mismatch:" + uid)
    if total > 500000:
        fail(
            "scope_readback_size_limit",
            "scope_readback.reads",
            "Превышен размер проверяемого текста.",
        )
    missing = sorted(set(units) - observed)
    issues.extend("scope_unit_unread:" + uid for uid in missing)
    return {
        "manifest_hash": data["manifest_hash"],
        "required_unit_ids": sorted(units),
        "observed_unit_ids": sorted(observed),
        "unread_unit_ids": missing,
        "status": "complete" if not issues else "partial",
        "issues": issues,
    }


def verify_fragment(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "run_id",
            "source_asset",
            "fragment",
            "independent_verification",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    source = require_mapping(data["source_asset"], "request.source_asset")
    require_exact_keys(
        source,
        set(FRAGMENT_VERIFY_SCHEMA["properties"]["source_asset"]["required"])
        | ({"scope_readback"} if "scope_readback" in source else set()),
        "request.source_asset",
    )
    source_id = require_string(source["source_id"], "request.source_asset.source_id")
    source_version = require_string(
        source["source_version"], "request.source_asset.source_version"
    )
    producer_id = require_string(
        source["producer_id"], "request.source_asset.producer_id"
    )
    original_hash = _hash(
        source["original_content_hash"], "request.source_asset.original_content_hash"
    )
    verification_text = require_string(
        source["verification_text"],
        "request.source_asset.verification_text",
        nonempty=False,
    )
    verification_hash = _hash(
        source["verification_text_hash"], "request.source_asset.verification_text_hash"
    )
    read_status = require_string(
        source["read_status"], "request.source_asset.read_status"
    )
    if read_status not in _READ_STATES:
        fail(
            "invalid_read_status",
            "request.source_asset.read_status",
            "Неверный статус чтения.",
        )
    declared_scope = require_string(
        source["declared_scope"], "request.source_asset.declared_scope"
    )
    read_scope = source["read_scope"]
    if read_scope is not None:
        read_scope = require_string(read_scope, "request.source_asset.read_scope")
    supplements_required = require_bool(
        source["material_supplements_required"],
        "request.source_asset.material_supplements_required",
    )
    supplements_read = require_bool(
        source["material_supplements_read"],
        "request.source_asset.material_supplements_read",
    )
    if (
        hashlib.sha256(verification_text.encode("utf-8")).hexdigest()
        != verification_hash
    ):
        fail(
            "verification_text_hash_mismatch",
            "request.source_asset.verification_text_hash",
            "Хеш проверочного текста не совпадает.",
        )

    transformations_raw = require_list(
        source["transformations"], "request.source_asset.transformations"
    )
    if len(transformations_raw) > 100:
        fail(
            "size_limit",
            "request.source_asset.transformations",
            "Слишком много преобразований.",
        )
    transformations: list[dict[str, Any]] = []
    prior_hash = original_hash
    transformation_issues: list[str] = []
    seen_transformations: set[str] = set()
    for index, raw in enumerate(transformations_raw):
        path = f"request.source_asset.transformations[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, set(_TRANSFORMATION_SCHEMA["required"]), path)
        transformation_id = require_string(
            row["transformation_id"], f"{path}.transformation_id"
        )
        if transformation_id in seen_transformations:
            fail(
                "duplicate_transformation",
                f"{path}.transformation_id",
                "Повторное преобразование.",
            )
        seen_transformations.add(transformation_id)
        kind = require_string(row["kind"], f"{path}.kind")
        if kind not in {
            "ocr",
            "translation",
            "normalization",
            "pdf_text_extraction",
            "table_extraction",
            "formula_extraction",
        }:
            fail("invalid_transformation", f"{path}.kind", "Неверное преобразование.")
        input_hash = _hash(row["input_hash"], f"{path}.input_hash")
        output_hash = _hash(row["output_hash"], f"{path}.output_hash")
        verified = require_bool(
            row["verified_against_original"], f"{path}.verified_against_original"
        )
        if input_hash != prior_hash:
            transformation_issues.append(
                f"transformation_chain_broken:{transformation_id}"
            )
        if not verified:
            transformation_issues.append(
                f"transformation_not_verified:{transformation_id}"
            )
        prior_hash = output_hash
        transformations.append(
            {
                "transformation_id": transformation_id,
                "kind": kind,
                "tool_version": require_string(
                    row["tool_version"], f"{path}.tool_version"
                ),
                "input_hash": input_hash,
                "output_hash": output_hash,
                "verified_against_original": verified,
            }
        )
    if transformations and prior_hash != verification_hash:
        transformation_issues.append("transformation_output_hash_mismatch")
    if not transformations and original_hash != verification_hash:
        transformation_issues.append("untracked_transformation")

    fragment = require_mapping(data["fragment"], "request.fragment")
    require_exact_keys(
        fragment,
        set(FRAGMENT_VERIFY_SCHEMA["properties"]["fragment"]["required"]),
        "request.fragment",
    )
    fragment_id = require_string(
        fragment["fragment_id"], "request.fragment.fragment_id"
    )
    locator_type = require_string(
        fragment["locator_type"], "request.fragment.locator_type"
    )
    if locator_type not in _LOCATOR_TYPES:
        fail(
            "invalid_locator_type",
            "request.fragment.locator_type",
            "Неверный тип локатора.",
        )
    coordinates = require_string(
        fragment["coordinates"], "request.fragment.coordinates"
    )
    start = fragment["start"]
    end = fragment["end"]
    if start is not None:
        start = require_int(start, "request.fragment.start")
    if end is not None:
        end = require_int(end, "request.fragment.end")
    exact_fragment = require_string(
        fragment["exact_fragment"], "request.fragment.exact_fragment", nonempty=False
    )
    fragment_hash = _hash(fragment["fragment_hash"], "request.fragment.fragment_hash")
    derived_ref = fragment["derived_registry_ref"]
    if derived_ref is not None:
        derived_ref = require_string(
            derived_ref, "request.fragment.derived_registry_ref"
        )

    verification = require_mapping(
        data["independent_verification"], "request.independent_verification"
    )
    require_exact_keys(
        verification,
        set(
            FRAGMENT_VERIFY_SCHEMA["properties"]["independent_verification"]["required"]
        )
        | ({"scope_manifest_hash"} if "scope_manifest_hash" in verification else set()),
        "request.independent_verification",
    )
    verifier_id = require_string(
        verification["verifier_id"], "request.independent_verification.verifier_id"
    )
    locator_receipt_ref = require_string(
        verification["locator_receipt_ref"],
        "request.independent_verification.locator_receipt_ref",
    )
    readback_hash = _hash(
        verification["original_readback_hash"],
        "request.independent_verification.original_readback_hash",
    )
    resolved_fragment = require_string(
        verification["resolved_fragment"],
        "request.independent_verification.resolved_fragment",
        nonempty=False,
    )
    used_derived = require_bool(
        verification["used_derived_registry"],
        "request.independent_verification.used_derived_registry",
    )
    verification_status = require_string(
        verification["status"], "request.independent_verification.status"
    )
    if verification_status not in {"pass", "fail"}:
        fail(
            "invalid_verification_status",
            "request.independent_verification.status",
            "Неверный статус проверки.",
        )

    issues = list(transformation_issues)
    if read_scope != declared_scope:
        issues.append("source_scope_mismatch")
    scope_coverage = None
    if "scope_readback" in source:
        scope_coverage = _scope_coverage(
            source["scope_readback"],
            original_hash,
            declared_scope,
            supplements_required,
        )
        issues.extend(scope_coverage["issues"])
        expected_manifest_hash = verification.get("scope_manifest_hash")
        if expected_manifest_hash is None:
            issues.append("independent_scope_manifest_missing")
        elif _hash(
            expected_manifest_hash, "independent_verification.scope_manifest_hash"
        ) != sha256_json(
            require_mapping(source["scope_readback"], "scope_readback")["manifest"]
        ):
            issues.append("independent_scope_manifest_mismatch")
        if expected_manifest_hash is not None:
            scope_coverage["independent_manifest_hash"] = expected_manifest_hash
    elif transformations or supplements_required:
        issues.append("scope_readbacks_missing")
    if verifier_id == producer_id:
        issues.append("verifier_not_independent")
    if readback_hash != original_hash:
        issues.append("original_readback_hash_mismatch")
    if used_derived:
        issues.append("derived_registry_used_as_authority")
    if verification_status != "pass":
        issues.append("independent_verification_failed")
    if not exact_fragment:
        issues.append("empty_fragment")
    if hashlib.sha256(exact_fragment.encode("utf-8")).hexdigest() != fragment_hash:
        issues.append("fragment_hash_mismatch")
    if resolved_fragment != exact_fragment:
        issues.append("independent_resolved_fragment_mismatch")
    computed_fragment = _resolve_range(locator_type, start, end, verification_text)
    if computed_fragment is not None and computed_fragment != exact_fragment:
        issues.append("locator_mismatch")
    if (
        locator_type
        in {"html_dom_text", "pdf_text_range", "file_byte_range", "file_line_range"}
        and computed_fragment is None
    ):
        issues.append("locator_coordinates_invalid")
    if read_status != "read_in_scope" or not read_scope:
        issues.append("source_not_read_in_scope")
    if supplements_required and not supplements_read:
        issues.append("material_supplements_unread")
    issues = sorted(set(issues))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "SourceFragmentDecisionReceipt",
        "status": "verified" if not issues else "rejected",
        "run_id": run_id,
        "source_ref": {
            "id": source_id,
            "version": source_version,
            "original_content_hash": original_hash,
        },
        "fragment_id": fragment_id,
        "locator": {
            "type": locator_type,
            "coordinates": coordinates,
            "start": start,
            "end": end,
        },
        "fragment_hash": fragment_hash,
        "locator_receipt_ref": locator_receipt_ref,
        "declared_scope": declared_scope,
        "read_scope": read_scope,
        "transformation_count": len(transformations),
        "derived_registry_ref": derived_ref,
        "independent_original_resolution": not used_derived,
        "evidence_status_changed": False,
        "persistence_applied": False,
        "issues": issues,
    }
    if scope_coverage is not None:
        payload["scope_coverage"] = scope_coverage
    return with_receipt_hash(payload)
