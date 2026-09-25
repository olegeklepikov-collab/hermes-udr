"""Narrative planning, material-statement validation, and invalidation."""

from __future__ import annotations

from typing import Any, cast

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_exact_keys,
    require_list,
    require_mapping,
    require_string,
)

_TEXT = {"type": "string", "minLength": 1}
_TEXTS = {"type": "array", "maxItems": 1000, "uniqueItems": True, "items": _TEXT}

NARRATIVE_PLAN_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "plan_ref",
        "audience",
        "decision_ref",
        "detail_level",
        "knowledge_nodes",
        "sections",
        "changed_node_refs",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "plan_ref": _TEXT,
        "audience": _TEXT,
        "decision_ref": _TEXT,
        "detail_level": {"enum": ["concise", "standard", "detailed"]},
        "knowledge_nodes": {
            "type": "array",
            "maxItems": 10000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["node_ref", "kind", "status"],
                "properties": {
                    "node_ref": _TEXT,
                    "kind": {"enum": ["fact", "claim", "cause", "contradiction"]},
                    "status": {
                        "enum": [
                            "supported",
                            "contested",
                            "disputed",
                            "unresolved",
                            "unknown",
                        ]
                    },
                },
            },
        },
        "sections": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "section_ref",
                    "purpose",
                    "material_statements",
                    "counterarguments",
                    "uncertainties",
                    "non_inferences",
                    "visual_refs",
                    "freshness_deadline",
                ],
                "properties": {
                    "section_ref": _TEXT,
                    "purpose": _TEXT,
                    "material_statements": {
                        "type": "array",
                        "maxItems": 1000,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["text", "knowledge_refs"],
                            "properties": {"text": _TEXT, "knowledge_refs": _TEXTS},
                        },
                    },
                    "counterarguments": _TEXTS,
                    "uncertainties": _TEXTS,
                    "non_inferences": _TEXTS,
                    "visual_refs": _TEXTS,
                    "freshness_deadline": _TEXT,
                },
            },
        },
        "changed_node_refs": _TEXTS,
    },
}


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_value", path, "Повтор значения запрещён.")
    return result


def assess_narrative_plan(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(NARRATIVE_PLAN_ASSESS_SCHEMA["required"]), "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    nodes: dict[str, dict[str, str]] = {}
    for index, raw in enumerate(
        require_list(data["knowledge_nodes"], "request.knowledge_nodes")
    ):
        path = f"request.knowledge_nodes[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"node_ref", "kind", "status"}, path)
        ref = require_string(row["node_ref"], f"{path}.node_ref")
        if ref in nodes:
            fail("duplicate_knowledge_node", f"{path}.node_ref", "Повтор узла.")
        nodes[ref] = {
            "node_ref": ref,
            "kind": require_string(row["kind"], f"{path}.kind"),
            "status": require_string(row["status"], f"{path}.status"),
        }
    changed = set(_strings(data["changed_node_refs"], "request.changed_node_refs"))
    issues = []
    sections = []
    invalidated = []
    represented: set[str] = set()
    for index, raw in enumerate(require_list(data["sections"], "request.sections")):
        path = f"request.sections[{index}]"
        row = require_mapping(raw, path)
        fields = {
            "section_ref",
            "purpose",
            "material_statements",
            "counterarguments",
            "uncertainties",
            "non_inferences",
            "visual_refs",
            "freshness_deadline",
        }
        require_exact_keys(row, fields, path)
        section_ref = require_string(row["section_ref"], f"{path}.section_ref")
        statements = []
        section_refs: set[str] = set()
        for statement_index, raw_statement in enumerate(
            require_list(row["material_statements"], f"{path}.material_statements")
        ):
            statement_path = f"{path}.material_statements[{statement_index}]"
            statement = require_mapping(raw_statement, statement_path)
            require_exact_keys(statement, {"text", "knowledge_refs"}, statement_path)
            refs = _strings(
                statement["knowledge_refs"], f"{statement_path}.knowledge_refs"
            )
            if not refs:
                issues.append(
                    f"material_statement_unreferenced:{section_ref}:{statement_index}"
                )
            unknown = sorted(set(refs) - set(nodes))
            for ref in unknown:
                issues.append(f"material_statement_unknown_ref:{section_ref}:{ref}")
            section_refs.update(refs)
            represented.update(set(refs) & set(nodes))
            statements.append(
                {
                    "text": require_string(statement["text"], f"{statement_path}.text"),
                    "knowledge_refs": refs,
                    "evidence_statuses": [nodes[ref] for ref in refs if ref in nodes],
                    "limitations": list(cast(list[str], row["uncertainties"])),
                    "non_inferences": list(cast(list[str], row["non_inferences"])),
                }
            )
        uncertain_refs = [
            ref
            for ref in section_refs & set(nodes)
            if nodes[ref]["status"] != "supported"
        ]
        if uncertain_refs and not row["uncertainties"]:
            issues.append(f"uncertain_claim_without_local_limitations:{section_ref}")
        if section_refs & changed:
            invalidated.append(section_ref)
        sections.append(
            {
                "section_ref": section_ref,
                "purpose": require_string(row["purpose"], f"{path}.purpose"),
                "material_statements": statements,
                "counterarguments": _strings(
                    row["counterarguments"], f"{path}.counterarguments"
                ),
                "uncertainties": _strings(
                    row["uncertainties"], f"{path}.uncertainties"
                ),
                "non_inferences": _strings(
                    row["non_inferences"], f"{path}.non_inferences"
                ),
                "visual_refs": _strings(row["visual_refs"], f"{path}.visual_refs"),
                "freshness_deadline": require_string(
                    row["freshness_deadline"], f"{path}.freshness_deadline"
                ),
                "knowledge_refs": sorted(section_refs),
            }
        )
    material_statuses = [nodes[ref] for ref in sorted(represented)]
    payload = {
        "schema_version": 1,
        "contract": "NarrativePlanDecisionReceipt",
        "status": "narrative_plan_ready" if not issues else "blocked",
        "plan_ref": require_string(data["plan_ref"], "request.plan_ref"),
        "audience": require_string(data["audience"], "request.audience"),
        "decision_ref": require_string(data["decision_ref"], "request.decision_ref"),
        "detail_level": require_string(data["detail_level"], "request.detail_level"),
        "sections": sections,
        "represented_knowledge": material_statuses,
        "invalidated_section_refs": sorted(invalidated),
        "unaffected_section_refs": sorted(
            row["section_ref"]
            for row in sections
            if row["section_ref"] not in invalidated
        ),
        "new_material_facts_created": False,
        "certainty_raised_by_narrative": False,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)
