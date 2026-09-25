"""Decomposition graph and construct operationalization contracts."""

from __future__ import annotations

from collections import defaultdict
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
_NULLABLE_TEXT = {"type": ["string", "null"]}
_TEXTS = {"type": "array", "maxItems": 1000, "uniqueItems": True, "items": _TEXT}
_SEARCH_LEVELS = {"search", "research", "deep_research", "ultra_deep_research"}

DECOMPOSITION_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "decomposition_id",
        "brief_ref",
        "engagement_level",
        "nodes",
        "dependencies",
        "overlaps",
        "coverage_status",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "decomposition_id": _TEXT,
        "brief_ref": _TEXT,
        "engagement_level": {
            "enum": [
                "parsing",
                "search",
                "research",
                "deep_research",
                "ultra_deep_research",
            ]
        },
        "nodes": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "node_ref",
                    "question",
                    "atomic",
                    "leaf_justification",
                    "verifiable",
                    "impact",
                    "uncertainty",
                    "cost_upper_bound",
                    "priority",
                    "closure_criterion",
                    "construct_refs",
                    "evidence_route_ref",
                ],
                "properties": {
                    "node_ref": _TEXT,
                    "question": _TEXT,
                    "atomic": {"type": "boolean"},
                    "leaf_justification": _NULLABLE_TEXT,
                    "verifiable": {"type": "boolean"},
                    "impact": {"enum": ["low", "medium", "high"]},
                    "uncertainty": {"enum": ["low", "medium", "high"]},
                    "cost_upper_bound": {"type": "integer", "minimum": 0},
                    "priority": {"type": "integer", "minimum": 0},
                    "closure_criterion": _TEXT,
                    "construct_refs": _TEXTS,
                    "evidence_route_ref": _TEXT,
                },
            },
        },
        "dependencies": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["from_ref", "to_ref"],
                "properties": {"from_ref": _TEXT, "to_ref": _TEXT},
            },
        },
        "overlaps": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["left_ref", "right_ref", "justified", "rationale"],
                "properties": {
                    "left_ref": _TEXT,
                    "right_ref": _TEXT,
                    "justified": {"type": "boolean"},
                    "rationale": _NULLABLE_TEXT,
                },
            },
        },
        "coverage_status": {"enum": ["complete", "partial", "not_assessed"]},
    },
}

CONSTRUCT_OPERATIONALIZE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "construct_ref",
        "revision",
        "term",
        "definitions",
        "indicator",
        "measure",
        "unit",
        "acquisition_method",
        "data_class",
        "proxy_model",
        "validity_evidence_refs",
        "known_failures",
        "confounders",
        "scope",
        "prohibited_inferences",
        "dependent_refs",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "construct_ref": _TEXT,
        "revision": {"type": "integer", "minimum": 1},
        "term": _TEXT,
        "definitions": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["definition_ref", "text", "accepted", "consequences"],
                "properties": {
                    "definition_ref": _TEXT,
                    "text": _TEXT,
                    "accepted": {"type": "boolean"},
                    "consequences": _TEXTS,
                },
            },
        },
        "indicator": _NULLABLE_TEXT,
        "measure": _NULLABLE_TEXT,
        "unit": _NULLABLE_TEXT,
        "acquisition_method": _NULLABLE_TEXT,
        "data_class": _NULLABLE_TEXT,
        "proxy_model": _NULLABLE_TEXT,
        "validity_evidence_refs": _TEXTS,
        "known_failures": _TEXTS,
        "confounders": _TEXTS,
        "scope": _NULLABLE_TEXT,
        "prohibited_inferences": _TEXTS,
        "dependent_refs": _TEXTS,
    },
}

CONSTRUCT_REVISE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "construct_ref",
        "current_revision",
        "expected_revision",
        "current_content_hash",
        "prior_definition_ref",
        "new_definition_ref",
        "reason",
        "dependent_refs",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "construct_ref": _TEXT,
        "current_revision": {"type": "integer", "minimum": 1},
        "expected_revision": {"type": "integer", "minimum": 1},
        "current_content_hash": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "prior_definition_ref": _TEXT,
        "new_definition_ref": _TEXT,
        "reason": _TEXT,
        "dependent_refs": _TEXTS,
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


def _cycle_nodes(nodes: set[str], adjacency: dict[str, set[str]]) -> list[str]:
    color = {node: 0 for node in nodes}
    stack: list[str] = []
    found: set[str] = set()

    def visit(node: str) -> None:
        color[node] = 1
        stack.append(node)
        for target in sorted(adjacency.get(node, set())):
            if color[target] == 0:
                visit(target)
            elif color[target] == 1:
                start = stack.index(target)
                found.update(stack[start:])
        stack.pop()
        color[node] = 2

    for node in sorted(nodes):
        if color[node] == 0:
            visit(node)
    return sorted(found)


def assess_decomposition(request: object) -> dict[str, Any]:
    data = _schema(request, set(DECOMPOSITION_ASSESS_SCHEMA["required"]))
    decomposition_id = require_string(
        data["decomposition_id"], "request.decomposition_id"
    )
    brief_ref = require_string(data["brief_ref"], "request.brief_ref")
    level = require_string(data["engagement_level"], "request.engagement_level")
    nodes: list[dict[str, Any]] = []
    node_refs: set[str] = set()
    issues: list[str] = []
    paths: list[str] = []
    for index, raw in enumerate(require_list(data["nodes"], "request.nodes")):
        path = f"request.nodes[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "node_ref",
                "question",
                "atomic",
                "leaf_justification",
                "verifiable",
                "impact",
                "uncertainty",
                "cost_upper_bound",
                "priority",
                "closure_criterion",
                "construct_refs",
                "evidence_route_ref",
            },
            path,
        )
        ref = require_string(row["node_ref"], f"{path}.node_ref")
        if ref in node_refs:
            fail("duplicate_node", f"{path}.node_ref", "Повтор узла запрещён.")
        node_refs.add(ref)
        atomic = require_bool(row["atomic"], f"{path}.atomic")
        justification = _optional(
            row["leaf_justification"], f"{path}.leaf_justification"
        )
        verifiable = require_bool(row["verifiable"], f"{path}.verifiable")
        if atomic and justification is None:
            issues.append(f"atomic_leaf_justification_missing:{ref}")
            paths.append(f"{path}.leaf_justification")
        if atomic and not verifiable:
            issues.append(f"atomic_leaf_not_verifiable:{ref}")
            paths.append(f"{path}.verifiable")
        nodes.append(
            {
                "node_ref": ref,
                "question": require_string(row["question"], f"{path}.question"),
                "atomic": atomic,
                "leaf_justification": justification,
                "verifiable": verifiable,
                "impact": require_string(row["impact"], f"{path}.impact"),
                "uncertainty": require_string(
                    row["uncertainty"], f"{path}.uncertainty"
                ),
                "cost_upper_bound": require_int(
                    row["cost_upper_bound"], f"{path}.cost_upper_bound"
                ),
                "priority": require_int(row["priority"], f"{path}.priority"),
                "closure_criterion": require_string(
                    row["closure_criterion"], f"{path}.closure_criterion"
                ),
                "construct_refs": _strings(
                    row["construct_refs"], f"{path}.construct_refs"
                ),
                "evidence_route_ref": require_string(
                    row["evidence_route_ref"], f"{path}.evidence_route_ref"
                ),
            }
        )
    if level in _SEARCH_LEVELS and not nodes:
        issues.append("decomposition_required")
        paths.append("request.nodes")

    adjacency: dict[str, set[str]] = defaultdict(set)
    for index, raw in enumerate(
        require_list(data["dependencies"], "request.dependencies")
    ):
        path = f"request.dependencies[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"from_ref", "to_ref"}, path)
        source = require_string(row["from_ref"], f"{path}.from_ref")
        target = require_string(row["to_ref"], f"{path}.to_ref")
        if source not in node_refs or target not in node_refs:
            fail("unknown_node", path, "Зависимость ссылается на неизвестный узел.")
        adjacency[source].add(target)
    cycle = _cycle_nodes(node_refs, adjacency)
    if cycle:
        issues.append("dependency_cycle")
        paths.append("request.dependencies")

    unjustified_overlaps: list[list[str]] = []
    for index, raw in enumerate(require_list(data["overlaps"], "request.overlaps")):
        path = f"request.overlaps[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"left_ref", "right_ref", "justified", "rationale"}, path
        )
        left = require_string(row["left_ref"], f"{path}.left_ref")
        right = require_string(row["right_ref"], f"{path}.right_ref")
        if left not in node_refs or right not in node_refs or left == right:
            fail("invalid_overlap_pair", path, "Неверная пара перекрытия.")
        justified = require_bool(row["justified"], f"{path}.justified")
        rationale = _optional(row["rationale"], f"{path}.rationale")
        if not justified or rationale is None:
            unjustified_overlaps.append(sorted([left, right]))
            paths.append(path)
    if unjustified_overlaps:
        issues.append("overlapping_branches")
    coverage = require_string(data["coverage_status"], "request.coverage_status")
    if level in _SEARCH_LEVELS and coverage == "not_assessed":
        issues.append("coverage_not_assessed")
        paths.append("request.coverage_status")
    record = {
        "decomposition_id": decomposition_id,
        "brief_ref": brief_ref,
        "engagement_level": level,
        "nodes": nodes,
        "dependencies": [
            {"from_ref": source, "to_ref": target}
            for source in sorted(adjacency)
            for target in sorted(adjacency[source])
        ],
        "coverage_status": coverage,
    }
    record["content_hash"] = sha256_json(record)
    payload = {
        "schema_version": 1,
        "contract": "DecompositionDecisionReceipt",
        "status": "decomposition_ready" if not issues else "blocked",
        "decomposition": record,
        "atomic_leaf_refs": sorted(row["node_ref"] for row in nodes if row["atomic"]),
        "cycle_node_refs": cycle,
        "unjustified_overlaps": sorted(unjustified_overlaps),
        "execution_allowed": not issues,
        "blocking_paths": sorted(set(paths)),
        "persistence_applied": False,
        "issues": sorted(set(issues)),
    }
    return with_receipt_hash(payload)


def operationalize_construct(request: object) -> dict[str, Any]:
    data = _schema(request, set(CONSTRUCT_OPERATIONALIZE_SCHEMA["required"]))
    construct_ref = require_string(data["construct_ref"], "request.construct_ref")
    revision = require_int(data["revision"], "request.revision", minimum=1)
    definitions = []
    definition_refs: set[str] = set()
    accepted_refs: list[str] = []
    for index, raw in enumerate(
        require_list(data["definitions"], "request.definitions")
    ):
        path = f"request.definitions[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"definition_ref", "text", "accepted", "consequences"}, path
        )
        ref = require_string(row["definition_ref"], f"{path}.definition_ref")
        if ref in definition_refs:
            fail(
                "duplicate_definition", f"{path}.definition_ref", "Повтор определения."
            )
        definition_refs.add(ref)
        accepted = require_bool(row["accepted"], f"{path}.accepted")
        if accepted:
            accepted_refs.append(ref)
        definitions.append(
            {
                "definition_ref": ref,
                "text": require_string(row["text"], f"{path}.text"),
                "accepted": accepted,
                "consequences": _strings(row["consequences"], f"{path}.consequences"),
            }
        )
    issues: list[str] = []
    missing: list[str] = []
    if len(accepted_refs) != 1:
        issues.append("accepted_definition_count_not_one")
        missing.append("request.definitions")
    values = {
        "indicator": _optional(data["indicator"], "request.indicator"),
        "measure": _optional(data["measure"], "request.measure"),
        "unit": _optional(data["unit"], "request.unit"),
        "acquisition_method": _optional(
            data["acquisition_method"], "request.acquisition_method"
        ),
        "data_class": _optional(data["data_class"], "request.data_class"),
        "proxy_model": _optional(data["proxy_model"], "request.proxy_model"),
        "scope": _optional(data["scope"], "request.scope"),
    }
    for field, value in values.items():
        if value is None:
            missing.append(f"request.{field}")
    array_values = {
        "validity_evidence_refs": _strings(
            data["validity_evidence_refs"], "request.validity_evidence_refs"
        ),
        "known_failures": _strings(data["known_failures"], "request.known_failures"),
        "confounders": _strings(data["confounders"], "request.confounders"),
        "prohibited_inferences": _strings(
            data["prohibited_inferences"], "request.prohibited_inferences"
        ),
        "dependent_refs": _strings(data["dependent_refs"], "request.dependent_refs"),
    }
    for field in (
        "validity_evidence_refs",
        "known_failures",
        "confounders",
        "prohibited_inferences",
    ):
        if not array_values[field]:
            missing.append(f"request.{field}")
    if missing:
        issues.append("construct_not_operationalized")
    record = {
        "construct_ref": construct_ref,
        "revision": revision,
        "term": require_string(data["term"], "request.term"),
        "definitions": definitions,
        "accepted_definition_ref": accepted_refs[0]
        if len(accepted_refs) == 1
        else None,
        **values,
        **array_values,
    }
    record["content_hash"] = sha256_json(record)
    payload = {
        "schema_version": 1,
        "contract": "ConstructOperationalizationReceipt",
        "status": "operationalized" if not issues else "blocked",
        "construct": record,
        "search_allowed": not issues,
        "missing_fields": sorted(set(missing)),
        "persistence_applied": False,
        "issues": sorted(set(issues)),
    }
    return with_receipt_hash(payload)


def propose_construct_revision(request: object) -> dict[str, Any]:
    data = _schema(request, set(CONSTRUCT_REVISE_SCHEMA["required"]))
    construct_ref = require_string(data["construct_ref"], "request.construct_ref")
    current = require_int(
        data["current_revision"], "request.current_revision", minimum=1
    )
    expected = require_int(
        data["expected_revision"], "request.expected_revision", minimum=1
    )
    if current != expected:
        fail("stale_revision", "request.expected_revision", "Редакция устарела.")
    prior = require_string(data["prior_definition_ref"], "request.prior_definition_ref")
    new = require_string(data["new_definition_ref"], "request.new_definition_ref")
    if prior == new:
        fail(
            "definition_unchanged",
            "request.new_definition_ref",
            "Определение не изменилось.",
        )
    dependents = _strings(data["dependent_refs"], "request.dependent_refs")
    proposal = {
        "construct_ref": construct_ref,
        "revision": current + 1,
        "prior_content_hash": require_string(
            data["current_content_hash"], "request.current_content_hash"
        ),
        "prior_definition_ref": prior,
        "new_definition_ref": new,
        "reason": require_string(data["reason"], "request.reason"),
    }
    proposal["content_hash"] = sha256_json(proposal)
    payload = {
        "schema_version": 1,
        "contract": "ConstructRevisionReceipt",
        "status": "revision_proposed",
        "construct_revision": proposal,
        "invalidated_refs": sorted(dependents),
        "unaffected_refs": [],
        "prior_construct_mutated": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)
