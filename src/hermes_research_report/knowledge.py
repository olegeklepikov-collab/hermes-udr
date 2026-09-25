"""Fact, causal, and synchronized knowledge-projection contracts."""

from __future__ import annotations

from typing import Any

from .canonical import with_receipt_hash
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
_NULLABLE_TEXT = {"type": ["string", "null"]}
_TEXTS = {"type": "array", "maxItems": 1000, "uniqueItems": True, "items": _TEXT}
_PROJECTIONS = {"fact_map", "root_cause_map", "claim_dag", "semantic_graph"}

FACT_MAP_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "authority_ref", "authority_revision", "facts"],
    "properties": {
        "schema_version": {"const": 1},
        "authority_ref": _TEXT,
        "authority_revision": {"type": "integer", "minimum": 1},
        "facts": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "fact_ref",
                    "subject",
                    "predicate",
                    "value",
                    "unit",
                    "period",
                    "population",
                    "as_of",
                    "volatility",
                    "recheck_due",
                    "status",
                    "fragment_ref",
                    "provenance_root_ref",
                ],
                "properties": {
                    "fact_ref": _TEXT,
                    "subject": _TEXT,
                    "predicate": _TEXT,
                    "value": _TEXT,
                    "unit": _TEXT,
                    "period": _TEXT,
                    "population": _TEXT,
                    "as_of": _NULLABLE_TEXT,
                    "volatility": {"enum": ["stable", "slow", "volatile"]},
                    "recheck_due": _NULLABLE_TEXT,
                    "status": {"enum": ["supported", "contested", "unknown", "stale"]},
                    "fragment_ref": _TEXT,
                    "provenance_root_ref": _TEXT,
                },
            },
        },
    },
}

ROOT_CAUSE_MAP_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "authority_ref",
        "authority_revision",
        "nodes",
        "edges",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "authority_ref": _TEXT,
        "authority_revision": {"type": "integer", "minimum": 1},
        "nodes": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["node_ref", "kind", "label"],
                "properties": {"node_ref": _TEXT, "kind": _TEXT, "label": _TEXT},
            },
        },
        "edges": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "edge_ref",
                    "cause_ref",
                    "effect_ref",
                    "mechanism",
                    "conditions",
                    "mediators",
                    "moderators",
                    "confounders",
                    "feedback_refs",
                    "requested_evidence_class",
                    "scope",
                    "support_refs",
                    "alternatives",
                    "discriminator",
                    "control_present",
                    "temporal_order_verified",
                    "causal_wording_requested",
                    "action_requested",
                ],
                "properties": {
                    "edge_ref": _TEXT,
                    "cause_ref": _TEXT,
                    "effect_ref": _TEXT,
                    "mechanism": _NULLABLE_TEXT,
                    "conditions": _TEXTS,
                    "mediators": _TEXTS,
                    "moderators": _TEXTS,
                    "confounders": _TEXTS,
                    "feedback_refs": _TEXTS,
                    "requested_evidence_class": {
                        "enum": ["asserted", "correlational", "causal"]
                    },
                    "scope": _TEXT,
                    "support_refs": _TEXTS,
                    "alternatives": _TEXTS,
                    "discriminator": _NULLABLE_TEXT,
                    "control_present": {"type": "boolean"},
                    "temporal_order_verified": {"type": "boolean"},
                    "causal_wording_requested": {"type": "boolean"},
                    "action_requested": {"type": "boolean"},
                },
            },
        },
    },
}

PROJECTIONS_RECONCILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "authority_ref",
        "prior_authority_revision",
        "new_authority_revision",
        "changed_refs",
        "projections",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "authority_ref": _TEXT,
        "prior_authority_revision": {"type": "integer", "minimum": 1},
        "new_authority_revision": {"type": "integer", "minimum": 2},
        "changed_refs": _TEXTS,
        "projections": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["projection", "authority_revision", "nodes"],
                "properties": {
                    "projection": {"enum": sorted(_PROJECTIONS)},
                    "authority_revision": {"type": "integer", "minimum": 1},
                    "nodes": {
                        "type": "array",
                        "maxItems": 10000,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["node_ref", "source_refs", "status"],
                            "properties": {
                                "node_ref": _TEXT,
                                "source_refs": _TEXTS,
                                "status": {"enum": ["current", "stale"]},
                            },
                        },
                    },
                },
            },
        },
    },
}


def _schema(request: object, fields: set[str]) -> dict[str, object]:
    data = require_mapping(request, "request")
    require_exact_keys(data, fields, "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    return data


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_value", path, "Повтор значения запрещён.")
    return result


def _optional(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def build_fact_map(request: object) -> dict[str, Any]:
    data = _schema(request, set(FACT_MAP_BUILD_SCHEMA["required"]))
    authority_ref = require_string(data["authority_ref"], "request.authority_ref")
    revision = require_int(
        data["authority_revision"], "request.authority_revision", minimum=1
    )
    facts = []
    issues = []
    paths = []
    refs: set[str] = set()
    for index, raw in enumerate(require_list(data["facts"], "request.facts")):
        path = f"request.facts[{index}]"
        row = require_mapping(raw, path)
        fields = {
            "fact_ref",
            "subject",
            "predicate",
            "value",
            "unit",
            "period",
            "population",
            "as_of",
            "volatility",
            "recheck_due",
            "status",
            "fragment_ref",
            "provenance_root_ref",
        }
        require_exact_keys(row, fields, path)
        fact_ref = require_string(row["fact_ref"], f"{path}.fact_ref")
        if fact_ref in refs:
            fail("duplicate_fact", f"{path}.fact_ref", "Повтор факта.")
        refs.add(fact_ref)
        as_of = _optional(row["as_of"], f"{path}.as_of")
        volatility = require_string(row["volatility"], f"{path}.volatility")
        recheck = _optional(row["recheck_due"], f"{path}.recheck_due")
        if as_of is None:
            issues.append(f"fact_as_of_missing:{fact_ref}")
            paths.append(f"{path}.as_of")
        if volatility == "volatile" and recheck is None:
            issues.append(f"volatile_recheck_missing:{fact_ref}")
            paths.append(f"{path}.recheck_due")
        facts.append(
            {
                "fact_ref": fact_ref,
                "subject": require_string(row["subject"], f"{path}.subject"),
                "predicate": require_string(row["predicate"], f"{path}.predicate"),
                "value": require_string(row["value"], f"{path}.value"),
                "unit": require_string(row["unit"], f"{path}.unit"),
                "period": require_string(row["period"], f"{path}.period"),
                "population": require_string(row["population"], f"{path}.population"),
                "as_of": as_of,
                "volatility": volatility,
                "recheck_due": recheck,
                "status": require_string(row["status"], f"{path}.status"),
                "fragment_ref": require_string(
                    row["fragment_ref"], f"{path}.fragment_ref"
                ),
                "provenance_root_ref": require_string(
                    row["provenance_root_ref"], f"{path}.provenance_root_ref"
                ),
            }
        )
    payload = {
        "schema_version": 1,
        "contract": "FactMapDecisionReceipt",
        "status": "fact_map_ready" if not issues else "blocked",
        "authority_ref": authority_ref,
        "authority_revision": revision,
        "facts": facts,
        "blocking_paths": sorted(paths),
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def build_root_cause_map(request: object) -> dict[str, Any]:
    data = _schema(request, set(ROOT_CAUSE_MAP_BUILD_SCHEMA["required"]))
    authority_ref = require_string(data["authority_ref"], "request.authority_ref")
    revision = require_int(
        data["authority_revision"], "request.authority_revision", minimum=1
    )
    nodes = []
    node_refs: set[str] = set()
    for index, raw in enumerate(require_list(data["nodes"], "request.nodes")):
        path = f"request.nodes[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"node_ref", "kind", "label"}, path)
        ref = require_string(row["node_ref"], f"{path}.node_ref")
        if ref in node_refs:
            fail("duplicate_node", f"{path}.node_ref", "Повтор узла.")
        node_refs.add(ref)
        nodes.append(
            {
                "node_ref": ref,
                "kind": require_string(row["kind"], f"{path}.kind"),
                "label": require_string(row["label"], f"{path}.label"),
            }
        )
    edges = []
    issues = []
    for index, raw in enumerate(require_list(data["edges"], "request.edges")):
        path = f"request.edges[{index}]"
        row = require_mapping(raw, path)
        fields = {
            "edge_ref",
            "cause_ref",
            "effect_ref",
            "mechanism",
            "conditions",
            "mediators",
            "moderators",
            "confounders",
            "feedback_refs",
            "requested_evidence_class",
            "scope",
            "support_refs",
            "alternatives",
            "discriminator",
            "control_present",
            "temporal_order_verified",
            "causal_wording_requested",
            "action_requested",
        }
        require_exact_keys(row, fields, path)
        edge_ref = require_string(row["edge_ref"], f"{path}.edge_ref")
        cause = require_string(row["cause_ref"], f"{path}.cause_ref")
        effect = require_string(row["effect_ref"], f"{path}.effect_ref")
        if cause not in node_refs or effect not in node_refs:
            fail("unknown_node", path, "Неизвестный узел ребра.")
        mechanism = _optional(row["mechanism"], f"{path}.mechanism")
        conditions = _strings(row["conditions"], f"{path}.conditions")
        mediators = _strings(row["mediators"], f"{path}.mediators")
        moderators = _strings(row["moderators"], f"{path}.moderators")
        confounders = _strings(row["confounders"], f"{path}.confounders")
        feedback = _strings(row["feedback_refs"], f"{path}.feedback_refs")
        supports = _strings(row["support_refs"], f"{path}.support_refs")
        alternatives = _strings(row["alternatives"], f"{path}.alternatives")
        discriminator = _optional(row["discriminator"], f"{path}.discriminator")
        requested = require_string(
            row["requested_evidence_class"], f"{path}.requested_evidence_class"
        )
        control = require_bool(row["control_present"], f"{path}.control_present")
        temporal = require_bool(
            row["temporal_order_verified"], f"{path}.temporal_order_verified"
        )
        causal_supported = bool(
            control
            and temporal
            and mechanism
            and supports
            and alternatives
            and discriminator
            and conditions
        )
        effective = (
            "causal"
            if requested == "causal" and causal_supported
            else ("correlational" if temporal or supports else "asserted")
        )
        causal_wording_requested = require_bool(
            row["causal_wording_requested"], f"{path}.causal_wording_requested"
        )
        action_requested = require_bool(
            row["action_requested"], f"{path}.action_requested"
        )
        if causal_wording_requested and effective != "causal":
            issues.append(f"causal_wording_forbidden:{edge_ref}")
        if action_requested and effective != "causal":
            issues.append(f"causal_action_forbidden:{edge_ref}")
        edges.append(
            {
                "edge_ref": edge_ref,
                "cause_ref": cause,
                "effect_ref": effect,
                "mechanism": mechanism,
                "conditions": conditions,
                "mediators": mediators,
                "moderators": moderators,
                "confounders": confounders,
                "feedback_refs": feedback,
                "evidence_class": effective,
                "scope": require_string(row["scope"], f"{path}.scope"),
                "support_refs": supports,
                "alternatives": alternatives,
                "discriminator": discriminator,
                "causal_wording_allowed": effective == "causal",
                "causal_action_allowed": effective == "causal",
            }
        )
    payload = {
        "schema_version": 1,
        "contract": "RootCauseMapDecisionReceipt",
        "status": "root_cause_map_ready" if not issues else "limited",
        "authority_ref": authority_ref,
        "authority_revision": revision,
        "nodes": nodes,
        "edges": edges,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def reconcile_knowledge_projections(request: object) -> dict[str, Any]:
    data = _schema(request, set(PROJECTIONS_RECONCILE_SCHEMA["required"]))
    authority_ref = require_string(data["authority_ref"], "request.authority_ref")
    prior = require_int(
        data["prior_authority_revision"], "request.prior_authority_revision", minimum=1
    )
    new = require_int(
        data["new_authority_revision"], "request.new_authority_revision", minimum=2
    )
    if new != prior + 1:
        fail(
            "nonsequential_revision",
            "request.new_authority_revision",
            "Новая редакция должна быть следующей.",
        )
    changed = set(_strings(data["changed_refs"], "request.changed_refs"))
    outputs = []
    seen: set[str] = set()
    issues = []
    for index, raw in enumerate(
        require_list(data["projections"], "request.projections")
    ):
        path = f"request.projections[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"projection", "authority_revision", "nodes"}, path)
        projection = require_string(row["projection"], f"{path}.projection")
        if projection in seen:
            fail("duplicate_projection", f"{path}.projection", "Повтор проекции.")
        seen.add(projection)
        source_revision = require_int(
            row["authority_revision"], f"{path}.authority_revision", minimum=1
        )
        if source_revision != prior:
            issues.append(f"projection_revision_mismatch:{projection}")
        nodes = []
        for node_index, raw_node in enumerate(
            require_list(row["nodes"], f"{path}.nodes")
        ):
            node_path = f"{path}.nodes[{node_index}]"
            node = require_mapping(raw_node, node_path)
            require_exact_keys(node, {"node_ref", "source_refs", "status"}, node_path)
            refs = _strings(node["source_refs"], f"{node_path}.source_refs")
            affected = bool(set(refs) & changed)
            nodes.append(
                {
                    "node_ref": require_string(
                        node["node_ref"], f"{node_path}.node_ref"
                    ),
                    "source_refs": refs,
                    "prior_status": require_string(
                        node["status"], f"{node_path}.status"
                    ),
                    "new_status": "stale" if affected else node["status"],
                    "affected": affected,
                }
            )
        outputs.append(
            {"projection": projection, "authority_revision": new, "nodes": nodes}
        )
    missing = sorted(_PROJECTIONS - seen)
    issues.extend(f"projection_missing:{value}" for value in missing)
    payload = {
        "schema_version": 1,
        "contract": "KnowledgeProjectionReconciliationReceipt",
        "status": "projections_reconciled" if not issues else "blocked",
        "authority_ref": authority_ref,
        "prior_authority_revision": prior,
        "new_authority_revision": new,
        "changed_refs": sorted(changed),
        "projections": sorted(outputs, key=lambda row: row["projection"]),
        "all_projections_same_revision": not issues,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)
