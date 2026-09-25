"""Academic review protocol, selection, study, bias, synthesis, and replay gates."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any

from .academic_review_bindings import (
    extraction_binding_issues,
    rob_binding_issues,
    sensitivity_binding_issues,
)
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


def _schema(required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": {
            "schema_version": {"const": 1},
            **{
                name: {"type": "object"}
                for name in required
                if name != "schema_version"
            },
        },
    }


REVIEW_PROTOCOL_VALIDATE_SCHEMA = _schema(
    ["schema_version", "review_design", "protocol", "amendments"]
)
REVIEW_PROTOCOL_VALIDATE_SCHEMA["properties"]["amendments"] = {
    "type": "array",
    "items": {"type": "object"},
}
SCREENING_ADJUDICATE_SCHEMA = _schema(
    ["schema_version", "record_id", "stage", "decisions", "adjudication"]
)
SCREENING_ADJUDICATE_SCHEMA["properties"]["record_id"] = _TEXT
SCREENING_ADJUDICATE_SCHEMA["properties"]["stage"] = _TEXT
SCREENING_ADJUDICATE_SCHEMA["properties"]["decisions"] = {
    "type": "array",
    "minItems": 2,
    "items": {"type": "object"},
}
SCREENING_ADJUDICATE_SCHEMA["properties"]["adjudication"] = {
    "oneOf": [{"type": "null"}, {"type": "object"}]
}
STUDY_GRAPH_RESOLVE_SCHEMA = _schema(
    ["schema_version", "study_id", "nodes", "edges", "fulltext_receipts"]
)
STUDY_GRAPH_RESOLVE_SCHEMA["properties"]["study_id"] = _TEXT
for _field in ("nodes", "edges", "fulltext_receipts"):
    STUDY_GRAPH_RESOLVE_SCHEMA["properties"][_field] = {
        "type": "array",
        "items": {"type": "object"},
    }
EXTRACTION_ASSESS_SCHEMA = _schema(["schema_version", "schema", "codebook", "fields"])
EXTRACTION_ASSESS_SCHEMA["properties"]["fields"] = {
    "type": "array",
    "items": {"type": "object"},
}
PRISMA_ASSESS_SCHEMA = _schema(
    [
        "schema_version",
        "review_id",
        "applicable_items",
        "item_materializations",
        "flow_events",
    ]
)
PRISMA_ASSESS_SCHEMA["properties"]["review_id"] = _TEXT
for _field in ("applicable_items", "item_materializations", "flow_events"):
    PRISMA_ASSESS_SCHEMA["properties"][_field] = {
        "type": "array",
        "items": {"type": "object"},
    }
RISK_OF_BIAS_ASSESS_SCHEMA = _schema(["schema_version", "assessments"])
RISK_OF_BIAS_ASSESS_SCHEMA["properties"]["assessments"] = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "object"},
}
CERTAINTY_ASSESS_SCHEMA = _schema(
    [
        "schema_version",
        "outcome_id",
        "starting_certainty",
        "study_assessment_refs",
        "domains",
    ]
)
CERTAINTY_ASSESS_SCHEMA["properties"]["outcome_id"] = _TEXT
CERTAINTY_ASSESS_SCHEMA["properties"]["starting_certainty"] = {
    "enum": ["high", "moderate", "low", "very_low"]
}
CERTAINTY_ASSESS_SCHEMA["properties"]["study_assessment_refs"] = {
    "type": "array",
    "items": _TEXT,
}
CERTAINTY_ASSESS_SCHEMA["properties"]["domains"] = {
    "type": "array",
    "items": {"type": "object"},
}
ACADEMIC_SYNTHESIS_GATE_SCHEMA = _schema(["schema_version", "results", "model"])
ACADEMIC_SYNTHESIS_GATE_SCHEMA["properties"]["results"] = {
    "type": "array",
    "minItems": 2,
    "items": {"type": "object"},
}
COMPUTATION_REPLAY_ASSESS_SCHEMA = _schema(["schema_version", "bundle", "replay"])
PRISMA_FLOW_ACCOUNT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "review_id",
        "fulltext_input_refs",
        "dispositions",
        "not_retrieved_refs",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "review_id": _TEXT,
        "fulltext_input_refs": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": _TEXT,
        },
        "dispositions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["record_ref", "disposition", "decision_ref"],
                "properties": {
                    "record_ref": _TEXT,
                    "disposition": {"enum": ["include", "exclude", "pending"]},
                    "decision_ref": _TEXT,
                },
            },
        },
        "not_retrieved_refs": {
            "type": "array",
            "uniqueItems": True,
            "items": _TEXT,
        },
    },
}
FIXED_EFFECT_COMPUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "synthesis_ref",
        "formula",
        "confidence_z",
        "records",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "synthesis_ref": _TEXT,
        "formula": {"const": "inverse_variance_fixed_effect"},
        "confidence_z": {"type": "number", "exclusiveMinimum": 0},
        "records": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["result_ref", "estimate", "standard_error"],
                "properties": {
                    "result_ref": _TEXT,
                    "estimate": {"type": "number"},
                    "standard_error": {"type": "number", "exclusiveMinimum": 0},
                },
            },
        },
    },
}

_HASH_CHARS = set("0123456789abcdef")


def _version(data: dict[str, object]) -> None:
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if len(text) != 64 or set(text) - _HASH_CHARS:
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _time(value: object, path: str) -> str:
    text = require_string(value, path)
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None or "T" not in text:
            raise ValueError
    except ValueError:
        fail("invalid_timestamp", path, "Требуется ISO 8601 с часовым поясом.")
    return text


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _nullable(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повтор элемента запрещён.")
    return result


def _finite(
    value: object,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (minimum is not None and value < minimum)
        or (maximum is not None and value > maximum)
    ):
        fail("invalid_number", path, "Число находится вне допустимого диапазона.")
    return float(value)


def validate_review_protocol(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "review_design", "protocol", "amendments"}, "request"
    )
    _version(data)
    design = require_mapping(data["review_design"], "request.review_design")
    require_exact_keys(
        design,
        {"design_id", "review_type", "domain", "obligations"},
        "request.review_design",
    )
    obligations = []
    required_categories = set()
    for index, raw in enumerate(
        require_list(design["obligations"], "request.review_design.obligations")
    ):
        path = f"request.review_design.obligations[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"obligation_id", "category", "applicable"}, path)
        category = require_string(item["category"], f"{path}.category")
        if category not in {"search", "screening", "synthesis", "reporting"}:
            fail(
                "invalid_obligation_category",
                f"{path}.category",
                "Неизвестна категория.",
            )
        applicable = require_bool(item["applicable"], f"{path}.applicable")
        if applicable:
            required_categories.add(category)
        obligations.append(
            {
                "obligation_id": require_string(
                    item["obligation_id"], f"{path}.obligation_id"
                ),
                "category": category,
                "applicable": applicable,
            }
        )
    protocol = require_mapping(data["protocol"], "request.protocol")
    protocol_fields = {
        "protocol_id",
        "revision",
        "created_at",
        "accepted_at",
        "results_first_seen_at",
        "search_rule_refs",
        "screening_rule_refs",
        "synthesis_rule_refs",
        "reporting_rule_refs",
    }
    require_exact_keys(protocol, protocol_fields, "request.protocol")
    created_at = _time(protocol["created_at"], "request.protocol.created_at")
    accepted_at = _time(protocol["accepted_at"], "request.protocol.accepted_at")
    results_at = _time(
        protocol["results_first_seen_at"], "request.protocol.results_first_seen_at"
    )
    refs = {
        "search": _strings(
            protocol["search_rule_refs"], "request.protocol.search_rule_refs"
        ),
        "screening": _strings(
            protocol["screening_rule_refs"], "request.protocol.screening_rule_refs"
        ),
        "synthesis": _strings(
            protocol["synthesis_rule_refs"], "request.protocol.synthesis_rule_refs"
        ),
        "reporting": _strings(
            protocol["reporting_rule_refs"], "request.protocol.reporting_rule_refs"
        ),
    }
    issues = []
    if not (_dt(created_at) <= _dt(accepted_at) < _dt(results_at)):
        issues.append("protocol_timing_invalid")
    for category in sorted(required_categories):
        if not refs[category]:
            issues.append(f"design_obligation_unfulfilled:{category}")
    revision = require_int(protocol["revision"], "request.protocol.revision", minimum=1)
    amendments = []
    expected_from = revision
    seen_amendments: set[str] = set()
    for index, raw in enumerate(require_list(data["amendments"], "request.amendments")):
        path = f"request.amendments[{index}]"
        item = require_mapping(raw, path)
        fields = {
            "amendment_id",
            "from_revision",
            "to_revision",
            "created_at",
            "reason",
            "author_id",
            "delta_fields",
            "affected_decision_refs",
            "approved",
        }
        require_exact_keys(item, fields, path)
        amendment_id = require_string(item["amendment_id"], f"{path}.amendment_id")
        if amendment_id in seen_amendments:
            fail("duplicate_amendment", path, "Повтор поправки запрещён.")
        seen_amendments.add(amendment_id)
        from_revision = require_int(
            item["from_revision"], f"{path}.from_revision", minimum=1
        )
        to_revision = require_int(item["to_revision"], f"{path}.to_revision", minimum=2)
        amendment_time = _time(item["created_at"], f"{path}.created_at")
        approved = require_bool(item["approved"], f"{path}.approved")
        delta_fields = _strings(item["delta_fields"], f"{path}.delta_fields")
        affected = _strings(
            item["affected_decision_refs"], f"{path}.affected_decision_refs"
        )
        if from_revision != expected_from or to_revision != from_revision + 1:
            issues.append(f"amendment_revision_gap:{amendment_id}")
        expected_from = to_revision
        if _dt(amendment_time) <= _dt(accepted_at):
            issues.append(f"amendment_not_append_only:{amendment_id}")
        if not approved or not delta_fields or not affected:
            issues.append(f"amendment_incomplete:{amendment_id}")
        amendments.append(
            {
                "amendment_id": amendment_id,
                "from_revision": from_revision,
                "to_revision": to_revision,
                "created_at": amendment_time,
                "reason": require_string(item["reason"], f"{path}.reason"),
                "author_id": require_string(item["author_id"], f"{path}.author_id"),
                "delta_fields": delta_fields,
                "affected_decision_refs": affected,
                "approved": approved,
            }
        )
    return with_receipt_hash(
        {
            "contract": "ReviewProtocolDecisionReceipt",
            "status": "protocol_ready" if not issues else "blocked",
            "review_design": {
                "design_id": require_string(
                    design["design_id"], "request.review_design.design_id"
                ),
                "review_type": require_string(
                    design["review_type"], "request.review_design.review_type"
                ),
                "domain": require_string(
                    design["domain"], "request.review_design.domain"
                ),
                "obligations": obligations,
            },
            "protocol": {
                "protocol_id": require_string(
                    protocol["protocol_id"], "request.protocol.protocol_id"
                ),
                "base_revision": revision,
                "effective_revision": expected_from,
                "created_at": created_at,
                "accepted_at": accepted_at,
                "results_first_seen_at": results_at,
                "rule_refs": refs,
            },
            "amendments": amendments,
            "issues": sorted(set(issues)),
            "screening_allowed": not issues,
            "prior_revision_mutated": False,
        }
    )


def adjudicate_screening(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {"schema_version", "record_id", "stage", "decisions", "adjudication"},
        "request",
    )
    _version(data)
    record_id = require_string(data["record_id"], "request.record_id")
    stage = require_string(data["stage"], "request.stage")
    decisions = []
    reviewers = set()
    decision_ids = set()
    for index, raw in enumerate(require_list(data["decisions"], "request.decisions")):
        path = f"request.decisions[{index}]"
        item = require_mapping(raw, path)
        fields = {
            "decision_id",
            "reviewer_id",
            "independent_first",
            "before_disclosure",
            "decision",
            "criterion_ref",
            "reason",
            "model_ref",
            "created_at",
        }
        require_exact_keys(item, fields, path)
        reviewer = require_string(item["reviewer_id"], f"{path}.reviewer_id")
        decision_id = require_string(item["decision_id"], f"{path}.decision_id")
        if decision_id in decision_ids:
            fail(
                "duplicate_screening_decision",
                path,
                "Идентификаторы решений должны различаться.",
            )
        decision_ids.add(decision_id)
        if reviewer in reviewers:
            fail("duplicate_screening_reviewer", path, "Нужны разные проверяющие.")
        reviewers.add(reviewer)
        decision = require_string(item["decision"], f"{path}.decision")
        if decision not in {"include", "exclude", "uncertain"}:
            fail(
                "invalid_screening_decision", f"{path}.decision", "Неизвестное решение."
            )
        decisions.append(
            {
                "decision_id": require_string(
                    item["decision_id"], f"{path}.decision_id"
                ),
                "reviewer_id": reviewer,
                "independent_first": require_bool(
                    item["independent_first"], f"{path}.independent_first"
                ),
                "before_disclosure": require_bool(
                    item["before_disclosure"], f"{path}.before_disclosure"
                ),
                "decision": decision,
                "criterion_ref": require_string(
                    item["criterion_ref"], f"{path}.criterion_ref"
                ),
                "reason": require_string(item["reason"], f"{path}.reason"),
                "model_ref": _nullable(item["model_ref"], f"{path}.model_ref"),
                "created_at": _time(item["created_at"], f"{path}.created_at"),
            }
        )
    if len(decisions) < 2:
        fail(
            "screening_decisions_missing",
            "request.decisions",
            "Нужны минимум два исходных решения.",
        )
    independent = all(
        decision["independent_first"] and decision["before_disclosure"]
        for decision in decisions
    )
    disagreement = len({decision["decision"] for decision in decisions}) > 1
    adjudication = data["adjudication"]
    adjudication_record: dict[str, Any] | None = None
    issues = []
    if not independent:
        issues.append("independent_first_decision_missing")
    if not disagreement and decisions[0]["decision"] == "uncertain":
        issues.append("screening_uncertainty_unresolved")
    if disagreement:
        if adjudication is None:
            issues.append("screening_adjudication_missing")
        else:
            item = require_mapping(adjudication, "request.adjudication")
            require_exact_keys(
                item,
                {"adjudicator_id", "decision", "reason", "created_at"}
                | ({"evidence"} if "evidence" in item else set()),
                "request.adjudication",
            )
            adjudicated = require_string(
                item["decision"], "request.adjudication.decision"
            )
            if adjudicated not in {"include", "exclude"}:
                fail(
                    "invalid_adjudication",
                    "request.adjudication.decision",
                    "Неверное решение.",
                )
            adjudication_record = {
                "adjudicator_id": require_string(
                    item["adjudicator_id"], "request.adjudication.adjudicator_id"
                ),
                "decision": adjudicated,
                "reason": require_string(item["reason"], "request.adjudication.reason"),
                "created_at": _time(
                    item["created_at"], "request.adjudication.created_at"
                ),
            }
            if adjudication_record["adjudicator_id"] in reviewers:
                issues.append("screening_self_adjudication")
            if _dt(adjudication_record["created_at"]) < max(
                _dt(row["created_at"]) for row in decisions
            ):
                issues.append("screening_adjudication_precedes_decisions")
            if "evidence" not in item:
                issues.append("screening_evidence_missing")
            else:
                evidence = require_mapping(
                    item["evidence"], "request.adjudication.evidence"
                )
                require_exact_keys(
                    evidence,
                    {
                        "criterion_ref",
                        "decision_hashes",
                        "source_ref",
                        "source_sha256",
                        "source_text",
                        "quote",
                        "char_start",
                        "char_end",
                    },
                    "request.adjudication.evidence",
                )
                criterion = require_string(
                    evidence["criterion_ref"], "evidence.criterion_ref"
                )
                source_ref = require_string(
                    evidence["source_ref"], "evidence.source_ref"
                )
                source_text = require_string(
                    evidence["source_text"], "evidence.source_text"
                )
                source_hash = require_string(
                    evidence["source_sha256"], "evidence.source_sha256"
                )
                quote = require_string(evidence["quote"], "evidence.quote")
                start = require_int(
                    evidence["char_start"], "evidence.char_start", minimum=0
                )
                end = require_int(evidence["char_end"], "evidence.char_end", minimum=0)
                hashes = require_list(
                    evidence["decision_hashes"], "evidence.decision_hashes"
                )
                expected_hashes = [
                    sha256_json(row)
                    for row in require_list(data["decisions"], "request.decisions")
                ]
                if criterion not in {row["criterion_ref"] for row in decisions}:
                    issues.append("screening_criterion_unbound")
                if hashes != expected_hashes:
                    issues.append("screening_decisions_unbound")
                if (
                    not (0 <= start < end <= len(source_text))
                    or source_text[start:end] != quote
                    or hashlib.sha256(source_text.encode()).hexdigest() != source_hash
                ):
                    issues.append("screening_source_unbound")
                adjudication_record["evidence"] = {
                    "criterion_ref": criterion,
                    "decision_hashes": hashes,
                    "source_ref": source_ref,
                    "source_sha256": source_hash,
                    "quote": quote,
                    "char_start": start,
                    "char_end": end,
                    "source_authenticity_verified": False,
                }
    elif adjudication is not None:
        fail(
            "unnecessary_adjudication",
            "request.adjudication",
            "Разногласие отсутствует.",
        )
    final_decision = (
        None
        if issues
        else adjudication_record["decision"]
        if adjudication_record
        else decisions[0]["decision"]
        if decisions and not disagreement
        else None
    )
    return with_receipt_hash(
        {
            "contract": "ScreeningAdjudicationReceipt",
            "status": "adjudicated" if not issues else "review_required",
            "record_id": record_id,
            "stage": stage,
            "first_decisions": decisions,
            "disagreement": disagreement,
            "adjudication": adjudication_record,
            "final_decision": final_decision,
            "issues": issues,
            "disagreement_preserved": True,
        }
    )


def resolve_study_graph(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {"schema_version", "study_id", "nodes", "edges", "fulltext_receipts"},
        "request",
    )
    _version(data)
    study_id = require_string(data["study_id"], "request.study_id")
    node_types = {
        "study",
        "protocol",
        "preprint",
        "article",
        "correction",
        "retraction",
        "secondary_analysis",
        "result",
    }
    nodes = []
    node_index: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(require_list(data["nodes"], "request.nodes")):
        path = f"request.nodes[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {"node_id", "node_type", "version", "status", "scholarly_object_ref"},
            path,
        )
        node_id = require_string(item["node_id"], f"{path}.node_id")
        if node_id in node_index:
            fail("duplicate_study_node", path, "Повтор узла запрещён.")
        node_type = require_string(item["node_type"], f"{path}.node_type")
        if node_type not in node_types:
            fail("invalid_study_node_type", f"{path}.node_type", "Неизвестен тип узла.")
        node = {
            "node_id": node_id,
            "node_type": node_type,
            "version": require_string(item["version"], f"{path}.version"),
            "status": require_string(item["status"], f"{path}.status"),
            "scholarly_object_ref": _nullable(
                item["scholarly_object_ref"], f"{path}.scholarly_object_ref"
            ),
        }
        nodes.append(node)
        node_index[node_id] = node
    study_nodes = [node for node in nodes if node["node_type"] == "study"]
    if len(study_nodes) != 1 or study_nodes[0]["node_id"] != study_id:
        fail(
            "study_identity_invalid", "request.nodes", "Требуется один корневой study."
        )
    edges = []
    for index, raw in enumerate(require_list(data["edges"], "request.edges")):
        path = f"request.edges[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"from_id", "to_id", "relation"}, path)
        source = require_string(item["from_id"], f"{path}.from_id")
        target = require_string(item["to_id"], f"{path}.to_id")
        if source not in node_index or target not in node_index:
            fail("unknown_study_node", path, "Ребро ссылается на неизвестный узел.")
        edges.append(
            {
                "from_id": source,
                "to_id": target,
                "relation": require_string(item["relation"], f"{path}.relation"),
            }
        )
    fulltext = []
    for index, raw in enumerate(
        require_list(data["fulltext_receipts"], "request.fulltext_receipts")
    ):
        path = f"request.fulltext_receipts[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "publication_id",
                "version",
                "rights_ref",
                "content_hash",
                "read_in_scope",
            },
            path,
        )
        publication_id = require_string(
            item["publication_id"], f"{path}.publication_id"
        )
        if publication_id not in node_index:
            fail("unknown_publication", path, "Публикация отсутствует.")
        fulltext.append(
            {
                "publication_id": publication_id,
                "version": require_string(item["version"], f"{path}.version"),
                "rights_ref": require_string(item["rights_ref"], f"{path}.rights_ref"),
                "content_hash": _hash(item["content_hash"], f"{path}.content_hash"),
                "read_in_scope": require_bool(
                    item["read_in_scope"], f"{path}.read_in_scope"
                ),
            }
        )
    publication_types = {
        "protocol",
        "preprint",
        "article",
        "correction",
        "retraction",
        "secondary_analysis",
    }
    publication_nodes = [
        node for node in nodes if node["node_type"] in publication_types
    ]
    result_nodes = [node for node in nodes if node["node_type"] == "result"]
    graph = {
        "study_id": study_id,
        "nodes": nodes,
        "edges": edges,
        "fulltext_receipts": fulltext,
        "publication_version_node_ids": [node["node_id"] for node in publication_nodes],
        "result_node_ids": [node["node_id"] for node in result_nodes],
        "publication_versions_merged": False,
        "results_merged": False,
    }
    graph["graph_hash"] = sha256_json(graph)
    return with_receipt_hash(
        {
            "contract": "StudyGraphResolutionReceipt",
            "status": "resolved",
            "study_graph": graph,
            "publication_version_count": len(publication_nodes),
            "result_count": len(result_nodes),
        }
    )


def _extraction_value(text: str, path: str) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite number")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)
        # Also rejects overflow such as 1e999, which bypasses parse_constant.
        json.dumps(value, allow_nan=False)
        return value
    except (ValueError, TypeError, RecursionError):
        fail(
            "invalid_extraction_value_json",
            path,
            "Нужно корректное JSON-значение без повторных ключей и неконечных чисел.",
        )


def assess_extraction(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "schema", "codebook", "fields"}, "request"
    )
    _version(data)
    schema = require_mapping(data["schema"], "request.schema")
    require_exact_keys(
        schema, {"schema_id", "version", "pilot_status"}, "request.schema"
    )
    codebook = require_mapping(data["codebook"], "request.codebook")
    require_exact_keys(
        codebook, {"codebook_id", "version", "pilot_status"}, "request.codebook"
    )
    schema_pilot = require_string(schema["pilot_status"], "request.schema.pilot_status")
    codebook_pilot = require_string(
        codebook["pilot_status"], "request.codebook.pilot_status"
    )
    issues = []
    if schema_pilot != "pass" or codebook_pilot != "pass":
        issues.append("extraction_pilot_missing")
    fields = []
    field_ids: set[str] = set()
    for index, raw in enumerate(require_list(data["fields"], "request.fields")):
        path = f"request.fields[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {"field_id", "material", "values", "adjudication"}
            | ({"primary_verification"} if "primary_verification" in item else set()),
            path,
        )
        field_id = require_string(item["field_id"], f"{path}.field_id")
        if field_id in field_ids:
            fail("duplicate_extraction_field", path, "Поле извлечения повторяется.")
        field_ids.add(field_id)
        field_issues = []
        material = require_bool(item["material"], f"{path}.material")
        values = []
        signatures = set()
        for value_index, raw_value in enumerate(
            require_list(item["values"], f"{path}.values")
        ):
            value_path = f"{path}.values[{value_index}]"
            value = require_mapping(raw_value, value_path)
            require_exact_keys(
                value,
                {
                    "route_id",
                    "extractor_id",
                    "method_ref",
                    "context_ref",
                    "value_json",
                    "source_fragment_ref",
                },
                value_path,
            )
            signature = (
                require_string(value["extractor_id"], f"{value_path}.extractor_id"),
                require_string(value["method_ref"], f"{value_path}.method_ref"),
                require_string(value["context_ref"], f"{value_path}.context_ref"),
            )
            signatures.add(signature)
            values.append(
                {
                    "route_id": require_string(
                        value["route_id"], f"{value_path}.route_id"
                    ),
                    "extractor_id": signature[0],
                    "method_ref": signature[1],
                    "context_ref": signature[2],
                    "value_json": require_string(
                        value["value_json"], f"{value_path}.value_json", nonempty=False
                    ),
                    "source_fragment_ref": require_string(
                        value["source_fragment_ref"],
                        f"{value_path}.source_fragment_ref",
                    ),
                }
            )
        distinct_values = sorted({value["value_json"] for value in values})
        for value_index, value in enumerate(values):
            parsed = _extraction_value(
                value["value_json"], f"{path}.values[{value_index}].value_json"
            )
            if material and parsed is None:
                field_issues.append(f"material_extraction_value_missing:{field_id}")
        conflict = len(distinct_values) > 1
        adjudication = item["adjudication"]
        adjudication_record = None
        if adjudication is not None:
            adjudication_data = require_mapping(adjudication, f"{path}.adjudication")
            require_exact_keys(
                adjudication_data,
                {"value_json", "adjudicator_id", "reason", "source_fragment_ref"},
                f"{path}.adjudication",
            )
            adjudication_record = {
                "value_json": require_string(
                    adjudication_data["value_json"],
                    f"{path}.adjudication.value_json",
                    nonempty=False,
                ),
                "adjudicator_id": require_string(
                    adjudication_data["adjudicator_id"],
                    f"{path}.adjudication.adjudicator_id",
                ),
                "reason": require_string(
                    adjudication_data["reason"], f"{path}.adjudication.reason"
                ),
                "source_fragment_ref": require_string(
                    adjudication_data["source_fragment_ref"],
                    f"{path}.adjudication.source_fragment_ref",
                ),
            }
            parsed = _extraction_value(
                adjudication_record["value_json"], f"{path}.adjudication.value_json"
            )
            if material and parsed is None:
                field_issues.append(f"material_extraction_value_missing:{field_id}")
        if material and len(signatures) < 2:
            field_issues.append(f"material_double_extraction_missing:{field_id}")
        if len({value["route_id"] for value in values}) != len(values):
            field_issues.append(f"duplicate_extraction_route:{field_id}")
        if not values:
            field_issues.append(f"extraction_values_missing:{field_id}")
        if conflict and adjudication_record is None:
            field_issues.append(f"extraction_conflict_unresolved:{field_id}")
        if adjudication_record and adjudication_record["adjudicator_id"] in {
            value["extractor_id"] for value in values
        }:
            field_issues.append(f"extraction_self_adjudication:{field_id}")
        accepted_value = (
            adjudication_record["value_json"]
            if adjudication_record
            else distinct_values[0]
            if len(distinct_values) == 1
            else None
        )
        if material:
            field_issues.extend(
                extraction_binding_issues(item, accepted_value, schema, codebook)
            )
        eligible = (
            accepted_value is not None
            and not field_issues
            and schema_pilot == "pass"
            and codebook_pilot == "pass"
        )
        fields.append(
            {
                "field_id": field_id,
                "material": material,
                "values": values,
                "independent_route_count": len(signatures),
                "conflict": conflict,
                "adjudication": adjudication_record,
                "accepted_value_json": accepted_value if eligible else None,
                "synthesis_eligible": eligible,
                "primary_verification": item.get("primary_verification"),
                "issues": field_issues,
            }
        )
        issues.extend(field_issues)
    if not fields:
        issues.append("extraction_fields_missing")
    return with_receipt_hash(
        {
            "contract": "ExtractionDecisionReceipt",
            "status": "accepted" if not issues else "review_required",
            "schema_ref": f"{require_string(schema['schema_id'], 'request.schema.schema_id')}@{require_string(schema['version'], 'request.schema.version')}",
            "codebook_ref": f"{require_string(codebook['codebook_id'], 'request.codebook.codebook_id')}@{require_string(codebook['version'], 'request.codebook.version')}",
            "fields": fields,
            "issues": sorted(set(issues)),
            "mean_or_vote_used": False,
        }
    )


def assess_prisma(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "review_id",
            "applicable_items",
            "item_materializations",
            "flow_events",
        },
        "request",
    )
    _version(data)
    review_id = require_string(data["review_id"], "request.review_id")
    applicable = []
    required_ids = set()
    for index, raw in enumerate(
        require_list(data["applicable_items"], "request.applicable_items")
    ):
        path = f"request.applicable_items[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"item_id", "standard", "required"}, path)
        item_id = require_string(item["item_id"], f"{path}.item_id")
        required = require_bool(item["required"], f"{path}.required")
        if required:
            required_ids.add(item_id)
        applicable.append(
            {
                "item_id": item_id,
                "standard": require_string(item["standard"], f"{path}.standard"),
                "required": required,
            }
        )
    materialized = []
    materialized_ids = set()
    for index, raw in enumerate(
        require_list(data["item_materializations"], "request.item_materializations")
    ):
        path = f"request.item_materializations[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"item_id", "decision_refs"}, path)
        item_id = require_string(item["item_id"], f"{path}.item_id")
        refs = _strings(item["decision_refs"], f"{path}.decision_refs")
        if refs:
            materialized_ids.add(item_id)
        materialized.append({"item_id": item_id, "decision_refs": refs})
    events = []
    event_ids = set()
    flow_counts: dict[str, int] = {}
    automation_count = 0
    for index, raw in enumerate(
        require_list(data["flow_events"], "request.flow_events")
    ):
        path = f"request.flow_events[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "event_id",
                "record_id",
                "stage",
                "decision",
                "decision_ref",
                "automated",
                "automation_ref",
            },
            path,
        )
        event_id = require_string(item["event_id"], f"{path}.event_id")
        if event_id in event_ids:
            fail("duplicate_flow_event", path, "Повтор события запрещён.")
        event_ids.add(event_id)
        stage = require_string(item["stage"], f"{path}.stage")
        automated = require_bool(item["automated"], f"{path}.automated")
        automation_ref = _nullable(item["automation_ref"], f"{path}.automation_ref")
        if automated and automation_ref is None:
            fail(
                "automation_ref_missing", path, "Автоматическое решение требует ссылку."
            )
        automation_count += automated
        flow_counts[stage] = flow_counts.get(stage, 0) + 1
        events.append(
            {
                "event_id": event_id,
                "record_id": require_string(item["record_id"], f"{path}.record_id"),
                "stage": stage,
                "decision": require_string(item["decision"], f"{path}.decision"),
                "decision_ref": require_string(
                    item["decision_ref"], f"{path}.decision_ref"
                ),
                "automated": automated,
                "automation_ref": automation_ref,
            }
        )
    missing = sorted(required_ids - materialized_ids)
    return with_receipt_hash(
        {
            "contract": "PrismaReportingReceipt",
            "status": "complete" if not missing else "incomplete",
            "review_id": review_id,
            "applicable_items": applicable,
            "item_materializations": materialized,
            "missing_required_item_ids": missing,
            "flow_events": events,
            "computed_flow_counts": dict(sorted(flow_counts.items())),
            "automation_decision_count": automation_count,
            "counts_derived_from_decisions": True,
        }
    )


def assess_prisma_flow_accounting(request: object) -> dict[str, Any]:
    """Reconcile full-text dispositions without lost or overlapping records."""

    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "review_id",
            "fulltext_input_refs",
            "dispositions",
            "not_retrieved_refs",
        },
        "request",
    )
    _version(data)
    review_id = require_string(data["review_id"], "request.review_id")
    input_refs = _strings(data["fulltext_input_refs"], "request.fulltext_input_refs")
    not_retrieved = _strings(data["not_retrieved_refs"], "request.not_retrieved_refs")
    input_set = set(input_refs)
    issues = [
        f"not_retrieved_overlaps_fulltext:{ref}"
        for ref in sorted(input_set & set(not_retrieved))
    ]
    dispositions: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    counts = {"include": 0, "exclude": 0, "pending": 0}
    for index, raw in enumerate(
        require_list(data["dispositions"], "request.dispositions")
    ):
        path = f"request.dispositions[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"record_ref", "disposition", "decision_ref"}, path)
        record_ref = require_string(item["record_ref"], f"{path}.record_ref")
        disposition = require_string(item["disposition"], f"{path}.disposition")
        if disposition not in counts:
            fail(
                "invalid_disposition",
                f"{path}.disposition",
                "Неизвестный исход отбора.",
            )
        if record_ref not in input_set:
            issues.append(f"unknown_fulltext_record:{record_ref}")
        if record_ref in seen:
            issues.append(f"overlapping_dispositions:{record_ref}")
        else:
            seen[record_ref] = disposition
            counts[disposition] += 1
        dispositions.append(
            {
                "record_ref": record_ref,
                "disposition": disposition,
                "decision_ref": require_string(
                    item["decision_ref"], f"{path}.decision_ref"
                ),
            }
        )
    for ref in sorted(input_set - set(seen)):
        issues.append(f"lost_record:{ref}")
    accepted = not issues and sum(counts.values()) == len(input_refs)
    return with_receipt_hash(
        {
            "contract": "PrismaFlowAccountingReceipt",
            "status": "accepted" if accepted else "blocked",
            "review_id": review_id,
            "fulltext_input_count": len(input_refs),
            "counts": counts if accepted else None,
            "not_retrieved_count": len(not_retrieved),
            "not_retrieved_refs": not_retrieved,
            "dispositions": dispositions,
            "issues": sorted(set(issues)),
            "counts_accepted": accepted,
        }
    )


def compute_fixed_effect_estimate(request: object) -> dict[str, Any]:
    """Compute a preregistered inverse-variance fixed-effect estimate."""

    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {"schema_version", "synthesis_ref", "formula", "confidence_z", "records"},
        "request",
    )
    _version(data)
    synthesis_ref = require_string(data["synthesis_ref"], "request.synthesis_ref")
    formula = require_string(data["formula"], "request.formula")
    if formula != "inverse_variance_fixed_effect":
        fail(
            "unregistered_synthesis_formula",
            "request.formula",
            "Формула не зарегистрирована.",
        )
    confidence_z = _finite(
        data["confidence_z"], "request.confidence_z", minimum=0.000001
    )
    rows: list[dict[str, float | str]] = []
    result_refs: set[str] = set()
    for index, raw in enumerate(require_list(data["records"], "request.records")):
        path = f"request.records[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"result_ref", "estimate", "standard_error"}, path)
        result_ref = require_string(item["result_ref"], f"{path}.result_ref")
        if result_ref in result_refs:
            fail(
                "duplicate_result", f"{path}.result_ref", "Повтор результата запрещён."
            )
        result_refs.add(result_ref)
        estimate = _finite(item["estimate"], f"{path}.estimate")
        standard_error = _finite(
            item["standard_error"], f"{path}.standard_error", minimum=0.000001
        )
        rows.append(
            {
                "result_ref": result_ref,
                "estimate": estimate,
                "standard_error": standard_error,
                "weight": round(1.0 / (standard_error * standard_error), 12),
            }
        )
    if len(rows) < 2:
        fail(
            "insufficient_results",
            "request.records",
            "Требуются минимум два результата.",
        )
    total_weight = sum(float(row["weight"]) for row in rows)
    pooled = (
        sum(float(row["weight"]) * float(row["estimate"]) for row in rows)
        / total_weight
    )
    pooled_se = math.sqrt(1.0 / total_weight)
    return with_receipt_hash(
        {
            "contract": "FixedEffectComputationReceipt",
            "status": "computed",
            "synthesis_ref": synthesis_ref,
            "formula": formula,
            "records": rows,
            "total_weight": total_weight,
            "pooled_estimate": pooled,
            "pooled_standard_error": pooled_se,
            "confidence_z": confidence_z,
            "confidence_interval": {
                "lower": pooled - confidence_z * pooled_se,
                "upper": pooled + confidence_z * pooled_se,
            },
            "invented_variance_used": False,
        }
    )


def assess_risk_of_bias(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "assessments"}, "request")
    _version(data)
    assessments = []
    result_ids = set()
    issues = []
    for index, raw in enumerate(
        require_list(data["assessments"], "request.assessments")
    ):
        path = f"request.assessments[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "assessment_id",
                "result_id",
                "design",
                "scheme",
                "scheme_version",
                "questions",
                "algorithmic_judgement",
                "final_judgement",
                "override_reason",
            }
            | (set(item) & {"domains", "consequence_for_synthesis"}),
            path,
        )
        result_id = require_string(item["result_id"], f"{path}.result_id")
        if result_id in result_ids:
            fail(
                "duplicate_result_assessment",
                path,
                "Оценка должна быть отдельной для результата.",
            )
        result_ids.add(result_id)
        questions = []
        for question_index, raw_question in enumerate(
            require_list(item["questions"], f"{path}.questions")
        ):
            question_path = f"{path}.questions[{question_index}]"
            question = require_mapping(raw_question, question_path)
            require_exact_keys(
                question,
                {"question_id", "answer", "fragment_ref", "rationale"},
                question_path,
            )
            questions.append(
                {
                    "question_id": require_string(
                        question["question_id"], f"{question_path}.question_id"
                    ),
                    "answer": require_string(
                        question["answer"], f"{question_path}.answer"
                    ),
                    "fragment_ref": require_string(
                        question["fragment_ref"], f"{question_path}.fragment_ref"
                    ),
                    "rationale": require_string(
                        question["rationale"], f"{question_path}.rationale"
                    ),
                }
            )
        if not questions:
            fail(
                "signalling_questions_missing",
                f"{path}.questions",
                "Нужны вопросы-сигналы.",
            )
        algorithmic = require_string(
            item["algorithmic_judgement"], f"{path}.algorithmic_judgement"
        )
        final = require_string(item["final_judgement"], f"{path}.final_judgement")
        override = _nullable(item["override_reason"], f"{path}.override_reason")
        if algorithmic != final and override is None:
            fail(
                "rob_override_reason_missing",
                path,
                "Переопределение требует основания.",
            )
        item_issues = rob_binding_issues(item)
        issues.extend(item_issues)
        assessments.append(
            {
                "assessment_id": require_string(
                    item["assessment_id"], f"{path}.assessment_id"
                ),
                "result_id": result_id,
                "design": require_string(item["design"], f"{path}.design"),
                "scheme": require_string(item["scheme"], f"{path}.scheme"),
                "scheme_version": require_string(
                    item["scheme_version"], f"{path}.scheme_version"
                ),
                "questions": questions,
                "algorithmic_judgement": algorithmic,
                "final_judgement": final,
                "override_reason": override,
                "domains": item.get("domains", []),
                "consequence_for_synthesis": item.get("consequence_for_synthesis"),
                "issues": item_issues,
            }
        )
    if not assessments:
        issues.append("rob_assessments_missing")
    return with_receipt_hash(
        {
            "contract": "RiskOfBiasAssessmentReceipt",
            "status": "review_required" if issues else "assessed",
            "issues": sorted(set(issues)),
            "assessments": assessments,
            "result_count": len(assessments),
            "study_level_average_used": False,
        }
    )


_CERTAINTY_ORDER = ["very_low", "low", "moderate", "high"]
_CERTAINTY_DOMAINS = {
    "risk_of_bias",
    "inconsistency",
    "indirectness",
    "imprecision",
    "missing_evidence",
}


def assess_certainty(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "outcome_id",
            "starting_certainty",
            "study_assessment_refs",
            "domains",
        },
        "request",
    )
    _version(data)
    outcome_id = require_string(data["outcome_id"], "request.outcome_id")
    starting = require_string(data["starting_certainty"], "request.starting_certainty")
    if starting not in _CERTAINTY_ORDER:
        fail("invalid_certainty", "request.starting_certainty", "Неизвестен уровень.")
    study_refs = _strings(
        data["study_assessment_refs"], "request.study_assessment_refs"
    )
    domains = []
    seen = set()
    downgrade = 0
    for index, raw in enumerate(require_list(data["domains"], "request.domains")):
        path = f"request.domains[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"domain", "judgement", "rationale_refs"}, path)
        domain = require_string(item["domain"], f"{path}.domain")
        if domain not in _CERTAINTY_DOMAINS or domain in seen:
            fail(
                "invalid_or_duplicate_certainty_domain",
                path,
                "Домен неизвестен или повторён.",
            )
        seen.add(domain)
        judgement = require_string(item["judgement"], f"{path}.judgement")
        if judgement not in {"not_serious", "serious", "very_serious"}:
            fail("invalid_certainty_judgement", path, "Неизвестно суждение.")
        rationale_refs = _strings(item["rationale_refs"], f"{path}.rationale_refs")
        if not rationale_refs:
            fail("certainty_rationale_missing", path, "Нужна опора суждения.")
        downgrade += (
            1 if judgement == "serious" else 2 if judgement == "very_serious" else 0
        )
        domains.append(
            {"domain": domain, "judgement": judgement, "rationale_refs": rationale_refs}
        )
    missing = sorted(_CERTAINTY_DOMAINS - seen)
    if missing:
        fail(
            "certainty_domain_missing", "request.domains", f"Нет домена: {missing[0]}."
        )
    start_index = _CERTAINTY_ORDER.index(starting)
    final = _CERTAINTY_ORDER[max(0, start_index - downgrade)]
    return with_receipt_hash(
        {
            "contract": "BodyOfEvidenceCertaintyReceipt",
            "status": "assessed",
            "outcome_id": outcome_id,
            "starting_certainty": starting,
            "final_certainty": final,
            "downgrade_levels": downgrade,
            "study_assessment_refs": study_refs,
            "domains": domains,
            "derived_from_mean_study_score": False,
        }
    )


_ESTIMAND_FIELDS = {
    "population",
    "intervention",
    "comparator",
    "outcome",
    "timepoint",
    "measure",
    "unit",
    "analysis_set",
}


def assess_academic_synthesis_gate(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "results", "model"}, "request")
    _version(data)
    results = []
    tuples = []
    result_ids: set[str] = set()
    blockers = []
    for index, raw in enumerate(require_list(data["results"], "request.results")):
        path = f"request.results[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {"result_id", "estimand", "estimate", "standard_error", "status"},
            path,
        )
        result_id = require_string(item["result_id"], f"{path}.result_id")
        if result_id in result_ids:
            blockers.append("duplicate_synthesis_result")
        result_ids.add(result_id)
        if item["status"] != "active":
            blockers.append("synthesis_result_not_active")
        estimand = require_mapping(item["estimand"], f"{path}.estimand")
        require_exact_keys(estimand, _ESTIMAND_FIELDS, f"{path}.estimand")
        normalized_estimand = {
            field: require_string(estimand[field], f"{path}.estimand.{field}")
            for field in sorted(_ESTIMAND_FIELDS)
        }
        tuples.append(normalized_estimand)
        results.append(
            {
                "result_id": require_string(item["result_id"], f"{path}.result_id"),
                "estimand": normalized_estimand,
                "estimate": _finite(item["estimate"], f"{path}.estimate"),
                "standard_error": _finite(
                    item["standard_error"], f"{path}.standard_error", minimum=0.000001
                ),
                "status": require_string(item["status"], f"{path}.status"),
            }
        )
    if len(results) < 2:
        blockers.append("insufficient_synthesis_results")
    baseline = tuples[0] if tuples else {}
    incompatibilities = []
    for result, estimand in zip(results[1:], tuples[1:], strict=True):
        for field in sorted(_ESTIMAND_FIELDS):
            if estimand[field] != baseline[field]:
                incompatibilities.append(
                    {
                        "result_id": result["result_id"],
                        "field": field,
                        "expected": baseline[field],
                        "observed": estimand[field],
                    }
                )
    model = require_mapping(data["model"], "request.model")
    require_exact_keys(
        model,
        {
            "model_id",
            "heterogeneous",
            "tau_squared",
            "prediction_interval",
            "heterogeneity_reasons",
            "sensitivity_receipts",
            "missing_evidence_assessed",
        }
        | (
            set(model)
            & {
                "required_sensitivity",
                "sensitivity_results",
                "conclusion_limitations",
                "sensitivity_protocol_json",
                "sensitivity_protocol_sha256",
            }
        ),
        "request.model",
    )
    heterogeneous = require_bool(model["heterogeneous"], "request.model.heterogeneous")
    prediction = model["prediction_interval"]
    prediction_record = None
    if prediction is not None:
        interval = require_mapping(prediction, "request.model.prediction_interval")
        require_exact_keys(
            interval, {"lower", "upper"}, "request.model.prediction_interval"
        )
        lower = _finite(interval["lower"], "request.model.prediction_interval.lower")
        upper = _finite(interval["upper"], "request.model.prediction_interval.upper")
        if lower > upper:
            fail(
                "invalid_prediction_interval",
                "request.model.prediction_interval",
                "Границы перепутаны.",
            )
        prediction_record = {"lower": lower, "upper": upper}
    reasons = _strings(
        model["heterogeneity_reasons"], "request.model.heterogeneity_reasons"
    )
    sensitivities = _strings(
        model["sensitivity_receipts"], "request.model.sensitivity_receipts"
    )
    missing_assessed = require_bool(
        model["missing_evidence_assessed"], "request.model.missing_evidence_assessed"
    )
    if incompatibilities:
        blockers.append("estimand_incompatible")
    if heterogeneous and prediction_record is None:
        blockers.append("prediction_interval_missing")
    if heterogeneous and not reasons:
        blockers.append("heterogeneity_reasons_missing")
    if not sensitivities:
        blockers.append("sensitivity_missing")
    if not missing_assessed:
        blockers.append("missing_evidence_not_assessed")
    blockers.extend(sensitivity_binding_issues(model, results))
    allowed = not blockers
    return with_receipt_hash(
        {
            "contract": "AcademicSynthesisGateReceipt",
            "status": "pooling_allowed" if allowed else "blocked",
            "results": results,
            "estimand_incompatibilities": incompatibilities,
            "model": {
                "model_id": require_string(model["model_id"], "request.model.model_id"),
                "heterogeneous": heterogeneous,
                "tau_squared": _finite(
                    model["tau_squared"], "request.model.tau_squared", minimum=0
                ),
                "prediction_interval": prediction_record,
                "heterogeneity_reasons": reasons,
                "sensitivity_receipts": sensitivities,
                "missing_evidence_assessed": missing_assessed,
                "required_sensitivity": model.get("required_sensitivity", []),
                "sensitivity_protocol_json": model.get("sensitivity_protocol_json"),
                "sensitivity_protocol_sha256": model.get("sensitivity_protocol_sha256"),
                "sensitivity_results": model.get("sensitivity_results", []),
                "conclusion_limitations": model.get("conclusion_limitations", []),
            },
            "blockers": sorted(set(blockers)),
            "pooling_allowed": allowed,
            "i_squared_alone_sufficient": False,
        }
    )


def assess_computation_replay(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "bundle", "replay"}, "request")
    _version(data)
    bundle = require_mapping(data["bundle"], "request.bundle")
    require_exact_keys(
        bundle,
        {
            "computation_id",
            "code_hash",
            "inputs",
            "dependencies",
            "parameters_json",
            "random_seeds",
            "environment_hash",
            "outputs",
        },
        "request.bundle",
    )
    inputs = []
    for index, raw in enumerate(
        require_list(bundle["inputs"], "request.bundle.inputs")
    ):
        path = f"request.bundle.inputs[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"input_ref", "content_hash"}, path)
        inputs.append(
            {
                "input_ref": require_string(item["input_ref"], f"{path}.input_ref"),
                "content_hash": _hash(item["content_hash"], f"{path}.content_hash"),
            }
        )
    dependencies = []
    for index, raw in enumerate(
        require_list(bundle["dependencies"], "request.bundle.dependencies")
    ):
        path = f"request.bundle.dependencies[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"name", "version", "content_hash"}, path)
        dependencies.append(
            {
                "name": require_string(item["name"], f"{path}.name"),
                "version": require_string(item["version"], f"{path}.version"),
                "content_hash": _hash(item["content_hash"], f"{path}.content_hash"),
            }
        )
    outputs = []
    for index, raw in enumerate(
        require_list(bundle["outputs"], "request.bundle.outputs")
    ):
        path = f"request.bundle.outputs[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"output_id", "value", "tolerance"}, path)
        outputs.append(
            {
                "output_id": require_string(item["output_id"], f"{path}.output_id"),
                "value": _finite(item["value"], f"{path}.value"),
                "tolerance": _finite(item["tolerance"], f"{path}.tolerance", minimum=0),
            }
        )
    replay = require_mapping(data["replay"], "request.replay")
    require_exact_keys(
        replay,
        {
            "replayer_id",
            "independent",
            "code_hash",
            "input_hashes",
            "dependency_hashes",
            "parameters_json",
            "random_seeds",
            "environment_hash",
            "outputs",
        },
        "request.replay",
    )
    replay_outputs = {}
    for index, raw in enumerate(
        require_list(replay["outputs"], "request.replay.outputs")
    ):
        path = f"request.replay.outputs[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"output_id", "value"}, path)
        replay_outputs[require_string(item["output_id"], f"{path}.output_id")] = (
            _finite(item["value"], f"{path}.value")
        )
    mismatches = []
    for output in outputs:
        replay_value = replay_outputs.get(output["output_id"])
        if (
            replay_value is None
            or abs(replay_value - output["value"]) > output["tolerance"]
        ):
            mismatches.append(output["output_id"])
    material_matches = (
        _hash(replay["code_hash"], "request.replay.code_hash")
        == _hash(bundle["code_hash"], "request.bundle.code_hash")
        and sorted(_strings(replay["input_hashes"], "request.replay.input_hashes"))
        == sorted(item["content_hash"] for item in inputs)
        and sorted(
            _strings(replay["dependency_hashes"], "request.replay.dependency_hashes")
        )
        == sorted(item["content_hash"] for item in dependencies)
        and require_string(
            replay["parameters_json"], "request.replay.parameters_json", nonempty=False
        )
        == require_string(
            bundle["parameters_json"], "request.bundle.parameters_json", nonempty=False
        )
        and [
            require_int(seed, f"request.replay.random_seeds[{index}]")
            for index, seed in enumerate(
                require_list(replay["random_seeds"], "request.replay.random_seeds")
            )
        ]
        == [
            require_int(seed, f"request.bundle.random_seeds[{index}]")
            for index, seed in enumerate(
                require_list(bundle["random_seeds"], "request.bundle.random_seeds")
            )
        ]
        and _hash(replay["environment_hash"], "request.replay.environment_hash")
        == _hash(bundle["environment_hash"], "request.bundle.environment_hash")
    )
    independent = require_bool(replay["independent"], "request.replay.independent")
    reproduced = material_matches and independent and not mismatches
    return with_receipt_hash(
        {
            "contract": "ComputationReplayReceipt",
            "status": "reproduced" if reproduced else "failed",
            "computation_id": require_string(
                bundle["computation_id"], "request.bundle.computation_id"
            ),
            "bundle_hash": sha256_json(bundle),
            "replayer_id": require_string(
                replay["replayer_id"], "request.replay.replayer_id"
            ),
            "independent": independent,
            "material_inputs_match": material_matches,
            "output_mismatch_ids": mismatches,
            "reproduced": reproduced,
            "computation_executed_by_core": False,
        }
    )
