"""Scholarly identity, field provenance, derived outputs, and gap closure."""

from __future__ import annotations

from typing import Any

from .canonical import sha256_json, with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
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
_IDENTIFIER_KINDS = {
    "doi",
    "pmid",
    "pmcid",
    "arxiv",
    "openalex",
    "semantic_scholar",
    "isbn",
    "other",
}

SCHOLARLY_OBJECT_RESOLVE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "records"],
    "properties": {
        "schema_version": {"const": 1},
        "records": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "provider_id",
                    "provider_record_id",
                    "origin_ref",
                    "raw_ref",
                    "acquired_at",
                    "identifiers",
                    "fields",
                    "fulltext_read",
                    "fulltext_locations",
                    "citation_edges",
                    "classifications",
                    "derived_outputs",
                ],
                "properties": {
                    "provider_id": _TEXT,
                    "provider_record_id": _TEXT,
                    "origin_ref": _TEXT,
                    "raw_ref": _TEXT,
                    "acquired_at": _TEXT,
                    "identifiers": {"type": "array", "items": {"type": "object"}},
                    "fields": {"type": "array", "items": {"type": "object"}},
                    "fulltext_read": {"type": "boolean"},
                    "fulltext_locations": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "citation_edges": {"type": "array", "items": {"type": "object"}},
                    "classifications": {"type": "array", "items": {"type": "object"}},
                    "derived_outputs": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
    },
}

CAPABILITY_GAP_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "required_capabilities",
        "qualified_capabilities",
        "candidate_extensions",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "required_capabilities": _TEXTS,
        "qualified_capabilities": _TEXTS,
        "candidate_extensions": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["provider_id", "capabilities", "kind"],
                "properties": {
                    "provider_id": _TEXT,
                    "capabilities": _TEXTS,
                    "kind": {
                        "enum": ["orthogonal", "general_search", "domain_specific"]
                    },
                },
            },
        },
    },
}

_RECORD_FIELDS = {
    "provider_id",
    "provider_record_id",
    "origin_ref",
    "raw_ref",
    "acquired_at",
    "identifiers",
    "fields",
    "fulltext_read",
    "fulltext_locations",
    "citation_edges",
    "classifications",
    "derived_outputs",
}


def _version(data: dict[str, object]) -> None:
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )


def _parse_identifiers(value: object, path: str) -> list[dict[str, str]]:
    identifiers = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(require_list(value, path)):
        item_path = f"{path}[{index}]"
        item = require_mapping(raw, item_path)
        require_exact_keys(item, {"kind", "value"}, item_path)
        kind = require_string(item["kind"], f"{item_path}.kind").lower()
        if kind not in _IDENTIFIER_KINDS:
            fail(
                "unknown_identifier_kind",
                f"{item_path}.kind",
                "Неизвестный вид научного идентификатора.",
            )
        identifier = require_string(item["value"], f"{item_path}.value").strip().lower()
        key = (kind, identifier)
        if key in seen:
            continue
        seen.add(key)
        identifiers.append({"kind": kind, "value": identifier})
    if not identifiers:
        fail("identifier_missing", path, "Нужен хотя бы один научный идентификатор.")
    return identifiers


def _parse_fields(
    value: object, path: str, record: dict[str, Any]
) -> list[dict[str, Any]]:
    fields = []
    for index, raw in enumerate(require_list(value, path)):
        item_path = f"{path}[{index}]"
        item = require_mapping(raw, item_path)
        require_exact_keys(item, {"name", "value_json", "status"}, item_path)
        status = require_string(item["status"], f"{item_path}.status")
        if status not in {"observed", "derived", "missing"}:
            fail(
                "invalid_field_status", f"{item_path}.status", "Неизвестен статус поля."
            )
        fields.append(
            {
                "name": require_string(item["name"], f"{item_path}.name"),
                "value_json": require_string(
                    item["value_json"], f"{item_path}.value_json", nonempty=False
                ),
                "status": status,
                "provider_id": record["provider_id"],
                "provider_record_id": record["provider_record_id"],
                "acquired_at": record["acquired_at"],
                "raw_ref": record["raw_ref"],
            }
        )
    return fields


def _parse_locations(
    value: object, path: str, record: dict[str, Any]
) -> list[dict[str, Any]]:
    locations = []
    for index, raw in enumerate(require_list(value, path)):
        item_path = f"{path}[{index}]"
        item = require_mapping(raw, item_path)
        require_exact_keys(
            item, {"location_ref", "access", "version", "license"}, item_path
        )
        locations.append(
            {
                "location_ref": require_string(
                    item["location_ref"], f"{item_path}.location_ref"
                ),
                "access": require_string(item["access"], f"{item_path}.access"),
                "version": require_string(item["version"], f"{item_path}.version"),
                "license": require_string(item["license"], f"{item_path}.license"),
                "provider_id": record["provider_id"],
                "read_in_scope": record["fulltext_read"],
            }
        )
    return locations


def _parse_edges(
    value: object, path: str, record: dict[str, Any]
) -> list[dict[str, Any]]:
    edges = []
    for index, raw in enumerate(require_list(value, path)):
        item_path = f"{path}[{index}]"
        item = require_mapping(raw, item_path)
        require_exact_keys(item, {"target_identifier", "relation"}, item_path)
        relation = require_string(item["relation"], f"{item_path}.relation")
        if relation != "cites":
            fail(
                "citation_semantics_forbidden",
                f"{item_path}.relation",
                "Ребро графа цитирования означает только cites.",
            )
        edges.append(
            {
                "target_identifier": require_string(
                    item["target_identifier"], f"{item_path}.target_identifier"
                ),
                "relation": "cites",
                "provider_id": record["provider_id"],
                "claim_effect": "none",
            }
        )
    return edges


def _parse_classifications(
    value: object, path: str, record: dict[str, Any]
) -> list[dict[str, Any]]:
    classifications = []
    for index, raw in enumerate(require_list(value, path)):
        item_path = f"{path}[{index}]"
        item = require_mapping(raw, item_path)
        require_exact_keys(item, {"scheme", "label", "statement_ref"}, item_path)
        classifications.append(
            {
                "scheme": require_string(item["scheme"], f"{item_path}.scheme"),
                "label": require_string(item["label"], f"{item_path}.label"),
                "statement_ref": require_string(
                    item["statement_ref"], f"{item_path}.statement_ref"
                ),
                "provider_id": record["provider_id"],
                "claim_status_effect": "none",
            }
        )
    return classifications


def _parse_derived(
    value: object, path: str, record: dict[str, Any]
) -> list[dict[str, Any]]:
    outputs = []
    for index, raw in enumerate(require_list(value, path)):
        item_path = f"{path}[{index}]"
        item = require_mapping(raw, item_path)
        require_exact_keys(
            item, {"output_type", "value_ref", "source_fragment_refs"}, item_path
        )
        refs = [
            require_string(ref, f"{item_path}.source_fragment_refs[{ref_index}]")
            for ref_index, ref in enumerate(
                require_list(
                    item["source_fragment_refs"], f"{item_path}.source_fragment_refs"
                )
            )
        ]
        traceable = bool(refs) and record["fulltext_read"]
        outputs.append(
            {
                "output_type": require_string(
                    item["output_type"], f"{item_path}.output_type"
                ),
                "value_ref": require_string(
                    item["value_ref"], f"{item_path}.value_ref"
                ),
                "source_fragment_refs": refs,
                "provider_id": record["provider_id"],
                "evidence_class": "derived_provider_output",
                "claim_eligible": traceable,
                "claim_status": "candidate" if traceable else "unsupported_unresolved",
            }
        )
    return outputs


def _connected_components(
    identifier_sets: list[set[tuple[str, str]]],
) -> list[list[int]]:
    remaining = set(range(len(identifier_sets)))
    components: list[list[int]] = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        component = {seed}
        identity = set(identifier_sets[seed])
        changed = True
        while changed:
            changed = False
            for index in sorted(remaining):
                if identity & identifier_sets[index]:
                    remaining.remove(index)
                    component.add(index)
                    identity.update(identifier_sets[index])
                    changed = True
        components.append(sorted(component))
    return components


def resolve_scholarly_object(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "records"}, "request")
    _version(data)
    records: list[dict[str, Any]] = []
    record_keys: set[tuple[str, str]] = set()
    for index, raw in enumerate(require_list(data["records"], "request.records")):
        path = f"request.records[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, _RECORD_FIELDS, path)
        record = {
            "provider_id": require_string(item["provider_id"], f"{path}.provider_id"),
            "provider_record_id": require_string(
                item["provider_record_id"], f"{path}.provider_record_id"
            ),
            "origin_ref": require_string(item["origin_ref"], f"{path}.origin_ref"),
            "raw_ref": require_string(item["raw_ref"], f"{path}.raw_ref"),
            "acquired_at": require_string(item["acquired_at"], f"{path}.acquired_at"),
            "fulltext_read": require_bool(
                item["fulltext_read"], f"{path}.fulltext_read"
            ),
        }
        record_key = (record["provider_id"], record["provider_record_id"])
        if record_key in record_keys:
            fail(
                "duplicate_provider_record", path, "Повтор записи провайдера запрещен."
            )
        record_keys.add(record_key)
        record["identifiers"] = _parse_identifiers(
            item["identifiers"], f"{path}.identifiers"
        )
        record["fields"] = _parse_fields(item["fields"], f"{path}.fields", record)
        record["fulltext_locations"] = _parse_locations(
            item["fulltext_locations"], f"{path}.fulltext_locations", record
        )
        record["citation_edges"] = _parse_edges(
            item["citation_edges"], f"{path}.citation_edges", record
        )
        record["classifications"] = _parse_classifications(
            item["classifications"], f"{path}.classifications", record
        )
        record["derived_outputs"] = _parse_derived(
            item["derived_outputs"], f"{path}.derived_outputs", record
        )
        records.append(record)
    identifier_sets = [
        {
            (identifier["kind"], identifier["value"])
            for identifier in record["identifiers"]
        }
        for record in records
    ]
    components = _connected_components(identifier_sets)
    objects = []
    for component_number, indexes in enumerate(components, start=1):
        group = [records[index] for index in indexes]
        identifiers = sorted(
            {pair for index in indexes for pair in identifier_sets[index]}
        )
        assertions = [field for record in group for field in record["fields"]]
        by_field: dict[str, list[dict[str, Any]]] = {}
        for assertion in assertions:
            by_field.setdefault(assertion["name"], []).append(assertion)
        conflicts = []
        for name, field_assertions in sorted(by_field.items()):
            values = sorted(
                {
                    row["value_json"]
                    for row in field_assertions
                    if row["status"] != "missing"
                }
            )
            if len(values) > 1:
                conflicts.append(
                    {
                        "field": name,
                        "values_json": values,
                        "assertion_refs": [
                            f"{row['provider_id']}:{row['provider_record_id']}:{name}"
                            for row in field_assertions
                        ],
                        "resolution": "unresolved",
                    }
                )
        origin_refs = sorted({record["origin_ref"] for record in group})
        objects.append(
            {
                "scholarly_object_id": f"SO-{sha256_json(identifiers)[:16]}",
                "component_number": component_number,
                "identifiers": [
                    {"kind": kind, "value": value} for kind, value in identifiers
                ],
                "provider_records": [
                    {
                        "provider_id": record["provider_id"],
                        "provider_record_id": record["provider_record_id"],
                        "raw_ref": record["raw_ref"],
                        "acquired_at": record["acquired_at"],
                    }
                    for record in group
                ],
                "field_assertions": assertions,
                "conflicts": conflicts,
                "fulltext_locations": [
                    location
                    for record in group
                    for location in record["fulltext_locations"]
                ],
                "citation_edges": [
                    edge for record in group for edge in record["citation_edges"]
                ],
                "classifications": [
                    classification
                    for record in group
                    for classification in record["classifications"]
                ],
                "derived_outputs": [
                    output for record in group for output in record["derived_outputs"]
                ],
                "origin_refs": origin_refs,
                "independent_origin_count": len(origin_refs),
                "provider_count": len({record["provider_id"] for record in group}),
            }
        )
    return with_receipt_hash(
        {
            "contract": "ScholarlyObjectResolutionReceipt",
            "status": "resolved" if len(objects) == 1 else "multiple_identity_clusters",
            "objects": objects,
            "object_count": len(objects),
            "provider_record_count": len(records),
            "silent_conflict_resolution": False,
            "service_count_increases_independent_origins": False,
        }
    )


_ORTHOGONAL_DEFAULTS = {
    "dataset_doi": ["datacite"],
    "biomedical_fulltext": ["europe_pmc", "pmc"],
    "researcher_identity": ["orcid"],
    "organization_identity": ["ror"],
    "historical_web": ["common_crawl", "memento_archive"],
}


def assess_capability_gap(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(CAPABILITY_GAP_ASSESS_SCHEMA["required"]), "request")
    _version(data)
    required = {
        require_string(item, f"request.required_capabilities[{index}]")
        for index, item in enumerate(
            require_list(data["required_capabilities"], "request.required_capabilities")
        )
    }
    qualified = {
        require_string(item, f"request.qualified_capabilities[{index}]")
        for index, item in enumerate(
            require_list(
                data["qualified_capabilities"], "request.qualified_capabilities"
            )
        )
    }
    gaps = sorted(required - qualified)
    candidates = []
    for index, raw in enumerate(
        require_list(data["candidate_extensions"], "request.candidate_extensions")
    ):
        path = f"request.candidate_extensions[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"provider_id", "capabilities", "kind"}, path)
        capabilities = {
            require_string(capability, f"{path}.capabilities[{capability_index}]")
            for capability_index, capability in enumerate(
                require_list(item["capabilities"], f"{path}.capabilities")
            )
        }
        kind = require_string(item["kind"], f"{path}.kind")
        if kind not in {"orthogonal", "general_search", "domain_specific"}:
            fail(
                "invalid_extension_kind", f"{path}.kind", "Неизвестный вид расширения."
            )
        candidates.append(
            {
                "provider_id": require_string(
                    item["provider_id"], f"{path}.provider_id"
                ),
                "capabilities": capabilities,
                "kind": kind,
            }
        )
    selected = []
    unresolved = []
    rejected = []
    for gap in gaps:
        matching = [
            candidate
            for candidate in candidates
            if gap in candidate["capabilities"]
            and candidate["kind"] != "general_search"
        ]
        if matching:
            selected.append(
                {
                    "capability": gap,
                    "provider_id": min(row["provider_id"] for row in matching),
                }
            )
            continue
        defaults = _ORTHOGONAL_DEFAULTS.get(gap, [])
        if defaults:
            selected.extend(
                {"capability": gap, "provider_id": provider_id}
                for provider_id in defaults
            )
        else:
            unresolved.append(gap)
    for candidate in candidates:
        if candidate["kind"] == "general_search" and not (
            candidate["capabilities"] & set(gaps)
        ):
            rejected.append(
                {
                    "provider_id": candidate["provider_id"],
                    "reason": "does_not_close_required_capability",
                }
            )
    return with_receipt_hash(
        {
            "contract": "CapabilityGapDecisionReceipt",
            "status": "gap_closure_selected" if not unresolved else "gap_open",
            "gaps": gaps,
            "selected_extensions": selected,
            "rejected_extensions": rejected,
            "unresolved_capabilities": unresolved,
            "another_general_search_is_sufficient": False,
            "qualification_required_before_routing": True,
            "external_call_performed": False,
        }
    )
