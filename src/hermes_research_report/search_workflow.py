"""Provider-neutral query compilation, search receipts, and safe stopping."""

from __future__ import annotations

import math
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
    "maxItems": 10000,
    "uniqueItems": True,
    "items": _TEXT,
}
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}

QUERY_AST_COMPILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "query_ast", "compiler"],
    "properties": {
        "schema_version": {"const": 1},
        "query_ast": {"type": "object"},
        "compiler": {"type": "object"},
    },
}

SEARCH_STRATEGY_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "strategy_id",
        "strategy_version",
        "strategy_hash",
        "material",
        "review",
        "repeat_requests",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "strategy_id": _TEXT,
        "strategy_version": {"type": "integer", "minimum": 1},
        "strategy_hash": _HASH,
        "material": {"type": "boolean"},
        "review": {"oneOf": [{"type": "null"}, {"type": "object"}]},
        "repeat_requests": {"type": "array", "items": {"type": "object"}},
    },
}

SEARCH_ENVIRONMENT_RECORD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "search_id",
        "executable_query",
        "provider_receipt_ref",
        "environment",
        "pages",
        "qualification_evidence",
        "requested_qualification_mode",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "search_id": _TEXT,
        "executable_query": {"type": "object"},
        "provider_receipt_ref": _TEXT,
        "environment": {"type": "object"},
        "pages": {"type": "array", "minItems": 1, "items": {"type": "object"}},
        "qualification_evidence": {"type": "array", "items": {"type": "object"}},
        "requested_qualification_mode": {"enum": ["frozen", "live"]},
    },
}

SEARCH_STOP_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "coverage_cells",
        "yield_iterations",
        "residual_estimate",
        "policy",
        "url_novelty_zero",
        "budget_exhausted",
        "citation_seeds",
        "leave_one_seed_results",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "coverage_cells": {"type": "array", "minItems": 1, "items": {"type": "object"}},
        "yield_iterations": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "object"},
        },
        "residual_estimate": {"type": "object"},
        "policy": {"type": "object"},
        "url_novelty_zero": {"type": "boolean"},
        "budget_exhausted": {"type": "boolean"},
        "citation_seeds": {"type": "array", "items": {"type": "object"}},
        "leave_one_seed_results": {"type": "array", "items": {"type": "object"}},
    },
}

SCREENING_STOP_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "model",
        "stopping_rule",
        "decisions",
        "proposal",
        "calibration",
        "tail_sample",
        "policy",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "model": {"type": "object"},
        "stopping_rule": {"type": "object"},
        "decisions": {"type": "array", "items": {"type": "object"}},
        "proposal": {"type": "object"},
        "calibration": {"oneOf": [{"type": "null"}, {"type": "object"}]},
        "tail_sample": {"oneOf": [{"type": "null"}, {"type": "object"}]},
        "policy": {"type": "object"},
    },
}

_NODE_FIELDS = {
    "node_id",
    "type",
    "value",
    "field",
    "operator",
    "children",
    "distance",
    "ordered",
    "lower",
    "upper",
}
_NODE_TYPES = {
    "term",
    "phrase",
    "heading",
    "field",
    "boolean",
    "proximity",
    "range",
    "limit",
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


def _nullable_text(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def _parse_field_map(value: object, path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, raw in enumerate(require_list(value, path)):
        item_path = f"{path}[{index}]"
        item = require_mapping(raw, item_path)
        require_exact_keys(item, {"canonical", "native"}, item_path)
        canonical = require_string(item["canonical"], f"{item_path}.canonical")
        native = require_string(item["native"], f"{item_path}.native")
        if canonical in result:
            fail("duplicate_field_mapping", item_path, "Повтор поля запрещён.")
        result[canonical] = native
    return result


def compile_query_ast(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "query_ast", "compiler"}, "request")
    _version(data)
    ast = require_mapping(data["query_ast"], "request.query_ast")
    require_exact_keys(
        ast, {"ast_id", "version", "root_id", "nodes"}, "request.query_ast"
    )
    ast_id = require_string(ast["ast_id"], "request.query_ast.ast_id")
    ast_version = require_int(ast["version"], "request.query_ast.version", minimum=1)
    root_id = require_string(ast["root_id"], "request.query_ast.root_id")
    nodes: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(require_list(ast["nodes"], "request.query_ast.nodes")):
        path = f"request.query_ast.nodes[{index}]"
        node = require_mapping(raw, path)
        require_exact_keys(node, _NODE_FIELDS, path)
        node_id = require_string(node["node_id"], f"{path}.node_id")
        if node_id in nodes:
            fail("duplicate_query_node", path, "Повтор узла запрещён.")
        node_type = require_string(node["type"], f"{path}.type")
        if node_type not in _NODE_TYPES:
            fail("invalid_query_node_type", f"{path}.type", "Неизвестен вид узла.")
        nodes[node_id] = {
            "node_id": node_id,
            "type": node_type,
            "value": _nullable_text(node["value"], f"{path}.value"),
            "field": _nullable_text(node["field"], f"{path}.field"),
            "operator": _nullable_text(node["operator"], f"{path}.operator"),
            "children": [
                require_string(child, f"{path}.children[{child_index}]")
                for child_index, child in enumerate(
                    require_list(node["children"], f"{path}.children")
                )
            ],
            "distance": (
                None
                if node["distance"] is None
                else require_int(node["distance"], f"{path}.distance", minimum=1)
            ),
            "ordered": (
                None
                if node["ordered"] is None
                else require_bool(node["ordered"], f"{path}.ordered")
            ),
            "lower": _nullable_text(node["lower"], f"{path}.lower"),
            "upper": _nullable_text(node["upper"], f"{path}.upper"),
        }
    if root_id not in nodes:
        fail(
            "query_root_missing",
            "request.query_ast.root_id",
            "Корневой узел отсутствует.",
        )
    for node in nodes.values():
        unknown = sorted(set(node["children"]) - set(nodes))
        if unknown:
            fail(
                "unknown_query_child",
                f"request.query_ast.nodes.{node['node_id']}",
                f"Неизвестный потомок: {unknown[0]}.",
            )

    compiler = require_mapping(data["compiler"], "request.compiler")
    compiler_fields = {
        "compiler_id",
        "compiler_version",
        "database",
        "platform",
        "syntax_profile",
        "field_map",
        "heading_mode",
        "supports_proximity",
        "supports_range",
        "semantic_extensions",
    }
    require_exact_keys(compiler, compiler_fields, "request.compiler")
    compiler_id = require_string(
        compiler["compiler_id"], "request.compiler.compiler_id"
    )
    compiler_version = require_string(
        compiler["compiler_version"], "request.compiler.compiler_version"
    )
    database = require_string(compiler["database"], "request.compiler.database")
    platform = require_string(compiler["platform"], "request.compiler.platform")
    syntax_profile = require_string(
        compiler["syntax_profile"], "request.compiler.syntax_profile"
    )
    if syntax_profile not in {"pubmed", "ovid", "generic"}:
        fail(
            "invalid_syntax_profile",
            "request.compiler.syntax_profile",
            "Неизвестный профиль синтаксиса.",
        )
    field_map = _parse_field_map(compiler["field_map"], "request.compiler.field_map")
    heading_mode = require_string(
        compiler["heading_mode"], "request.compiler.heading_mode"
    )
    if heading_mode not in {"native", "term_fallback", "unsupported"}:
        fail(
            "invalid_heading_mode",
            "request.compiler.heading_mode",
            "Неизвестен режим рубрики.",
        )
    supports_proximity = require_bool(
        compiler["supports_proximity"], "request.compiler.supports_proximity"
    )
    supports_range = require_bool(
        compiler["supports_range"], "request.compiler.supports_range"
    )
    semantic_extensions = [
        require_string(item, f"request.compiler.semantic_extensions[{index}]")
        for index, item in enumerate(
            require_list(
                compiler["semantic_extensions"],
                "request.compiler.semantic_extensions",
            )
        )
    ]
    losses: list[dict[str, str]] = []
    translations: list[dict[str, Any]] = []
    visiting: set[str] = set()
    rendered: dict[str, str] = {}

    def render(node_id: str) -> str:
        if node_id in rendered:
            return rendered[node_id]
        if node_id in visiting:
            fail(
                "query_ast_cycle", "request.query_ast.nodes", "QueryAST содержит цикл."
            )
        visiting.add(node_id)
        node = nodes[node_id]
        node_type = node["type"]
        status = "exact"
        reason = None
        if node_type == "term":
            if node["value"] is None:
                fail("query_value_missing", node_id, "Терм требует value.")
            text = node["value"]
        elif node_type == "phrase":
            if node["value"] is None:
                fail("query_value_missing", node_id, "Фраза требует value.")
            text = f'"{node["value"]}"'
        elif node_type == "heading":
            if node["value"] is None:
                fail("query_value_missing", node_id, "Рубрика требует value.")
            if heading_mode == "unsupported":
                status = "unsupported"
                reason = "controlled_heading_unsupported"
                text = node["value"]
            elif heading_mode == "term_fallback":
                status = "loss"
                reason = "controlled_heading_degraded_to_term"
                text = node["value"]
            elif syntax_profile == "pubmed":
                text = f'"{node["value"]}"[MeSH Terms]'
            elif syntax_profile == "ovid":
                text = f"exp {node['value']}/"
            else:
                text = f'HEADING("{node["value"]}")'
        elif node_type == "field":
            if len(node["children"]) != 1 or node["field"] is None:
                fail(
                    "invalid_field_node",
                    node_id,
                    "Поле требует одного потомка и field.",
                )
            child = render(node["children"][0])
            native_field = field_map.get(node["field"])
            if native_field is None:
                status = "loss"
                reason = "field_scope_removed"
                text = child
            elif syntax_profile == "pubmed":
                text = f"({child})[{native_field}]"
            elif syntax_profile == "ovid":
                text = f"({child}).{native_field}."
            else:
                text = f"{native_field}:({child})"
        elif node_type == "boolean":
            operator = node["operator"]
            if operator not in {"AND", "OR", "NOT"} or len(node["children"]) < 2:
                fail(
                    "invalid_boolean_node",
                    node_id,
                    "Boolean требует AND/OR/NOT и минимум двух потомков.",
                )
            text = (
                f"({f' {operator} '.join(render(child) for child in node['children'])})"
            )
        elif node_type == "proximity":
            if len(node["children"]) != 2 or node["distance"] is None:
                fail(
                    "invalid_proximity_node",
                    node_id,
                    "Proximity требует двух потомков и distance.",
                )
            left, right = (render(child) for child in node["children"])
            if supports_proximity:
                if syntax_profile == "ovid":
                    operator = f"adj{node['distance']}"
                    text = f"({left} {operator} {right})"
                else:
                    order = "ORDERED" if node["ordered"] else "UNORDERED"
                    text = f"PROX/{node['distance']}/{order}({left},{right})"
            else:
                status = "loss"
                reason = "proximity_degraded_to_conjunction"
                text = f"({left} AND {right})"
        elif node_type == "range":
            if node["field"] is None or node["lower"] is None or node["upper"] is None:
                fail("invalid_range_node", node_id, "Range требует field/lower/upper.")
            native_field = field_map.get(node["field"], node["field"])
            if supports_range:
                text = f"{native_field}:[{node['lower']} TO {node['upper']}]"
            else:
                status = "unsupported"
                reason = "range_unsupported"
                text = ""
        else:
            if node["value"] is None:
                fail("query_value_missing", node_id, "Limit требует value.")
            status = "extension"
            reason = "limit_applied_outside_query_string"
            text = ""
        visiting.remove(node_id)
        rendered[node_id] = text
        translations.append(
            {
                "node_id": node_id,
                "node_type": node_type,
                "rendered": text,
                "status": status,
                "reason": reason,
            }
        )
        if status in {"loss", "unsupported", "extension"}:
            losses.append(
                {
                    "node_id": node_id,
                    "kind": status,
                    "reason": reason or status,
                }
            )
        return text

    executable = render(root_id)
    unsupported = [loss for loss in losses if loss["kind"] == "unsupported"]
    ast_payload = {
        "ast_id": ast_id,
        "version": ast_version,
        "root_id": root_id,
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
    }
    compiled = {
        "ast_id": ast_id,
        "ast_version": ast_version,
        "ast_hash": sha256_json(ast_payload),
        "compiler_id": compiler_id,
        "compiler_version": compiler_version,
        "database": database,
        "platform": platform,
        "syntax_profile": syntax_profile,
        "executable_query": executable,
        "executable_query_hash": sha256_json({"query": executable}),
        "translations": sorted(translations, key=lambda row: row["node_id"]),
        "translation_losses": sorted(losses, key=lambda row: row["node_id"]),
        "semantic_extensions": semantic_extensions,
    }
    return with_receipt_hash(
        {
            "contract": "QueryCompilationReceipt",
            "status": (
                "blocked"
                if unsupported
                else "compiled_with_changes"
                if losses or semantic_extensions
                else "compiled_exact"
            ),
            "compiled_query": compiled,
            "translation_losses": compiled["translation_losses"],
            "execution_allowed": not unsupported and bool(executable),
            "external_call_performed": False,
        }
    )


def assess_search_strategy(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(SEARCH_STRATEGY_ASSESS_SCHEMA["required"]), "request")
    _version(data)
    strategy_id = require_string(data["strategy_id"], "request.strategy_id")
    strategy_version = require_int(
        data["strategy_version"], "request.strategy_version", minimum=1
    )
    strategy_hash = _hash(data["strategy_hash"], "request.strategy_hash")
    material = require_bool(data["material"], "request.material")
    review = data["review"]
    review_valid = not material
    review_record = None
    issues = []
    if review is None:
        if material:
            issues.append("search_strategy_review_required")
    else:
        review_data = require_mapping(review, "request.review")
        fields = {
            "review_id",
            "reviewer_id",
            "independent",
            "reviewed_strategy_hash",
            "status",
            "reviewed_at",
            "valid_until",
            "dimensions",
            "findings",
        }
        require_exact_keys(review_data, fields, "request.review")
        dimensions = [
            require_string(item, f"request.review.dimensions[{index}]")
            for index, item in enumerate(
                require_list(review_data["dimensions"], "request.review.dimensions")
            )
        ]
        required_dimensions = {"concepts", "syntax", "sources", "limits"}
        review_valid = (
            require_bool(review_data["independent"], "request.review.independent")
            and _hash(
                review_data["reviewed_strategy_hash"],
                "request.review.reviewed_strategy_hash",
            )
            == strategy_hash
            and require_string(review_data["status"], "request.review.status") == "pass"
            and required_dimensions <= set(dimensions)
        )
        review_record = {
            "review_id": require_string(
                review_data["review_id"], "request.review.review_id"
            ),
            "reviewer_id": require_string(
                review_data["reviewer_id"], "request.review.reviewer_id"
            ),
            "independent": review_data["independent"],
            "reviewed_strategy_hash": review_data["reviewed_strategy_hash"],
            "status": review_data["status"],
            "reviewed_at": require_string(
                review_data["reviewed_at"], "request.review.reviewed_at"
            ),
            "valid_until": require_string(
                review_data["valid_until"], "request.review.valid_until"
            ),
            "dimensions": dimensions,
            "findings": [
                require_string(item, f"request.review.findings[{index}]")
                for index, item in enumerate(
                    require_list(review_data["findings"], "request.review.findings")
                )
            ],
        }
        if not review_valid:
            issues.append("search_strategy_review_invalid")
    repeats = []
    for index, raw in enumerate(
        require_list(data["repeat_requests"], "request.repeat_requests")
    ):
        path = f"request.repeat_requests[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "repeat_id",
                "tool_ref",
                "new_purpose",
                "new_scope",
                "new_method",
                "expected_gain",
            },
            path,
        )
        changes = {
            "purpose": require_bool(item["new_purpose"], f"{path}.new_purpose"),
            "scope": require_bool(item["new_scope"], f"{path}.new_scope"),
            "method": require_bool(item["new_method"], f"{path}.new_method"),
        }
        expected_gain = _finite(
            item["expected_gain"], f"{path}.expected_gain", minimum=0
        )
        allowed = any(changes.values()) and expected_gain > 0
        if not allowed:
            issues.append(
                f"repeat_without_new_information:{require_string(item['repeat_id'], f'{path}.repeat_id')}"
            )
        repeats.append(
            {
                "repeat_id": item["repeat_id"],
                "tool_ref": require_string(item["tool_ref"], f"{path}.tool_ref"),
                "changed_dimensions": [key for key, value in changes.items() if value],
                "expected_gain": expected_gain,
                "allowed": allowed,
            }
        )
    ready = review_valid and not issues
    return with_receipt_hash(
        {
            "contract": "SearchStrategyDecisionReceipt",
            "status": "strategy_ready" if ready else "blocked",
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "strategy_hash": strategy_hash,
            "review": review_record,
            "repeat_decisions": repeats,
            "issues": sorted(set(issues)),
            "main_search_allowed": ready,
            "external_call_performed": False,
        }
    )


def record_search_environment(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data, set(SEARCH_ENVIRONMENT_RECORD_SCHEMA["required"]), "request"
    )
    _version(data)
    search_id = require_string(data["search_id"], "request.search_id")
    executable = require_mapping(data["executable_query"], "request.executable_query")
    executable_fields = {
        "ast_id",
        "ast_version",
        "ast_hash",
        "compiler_id",
        "compiler_version",
        "database",
        "platform",
        "syntax_profile",
        "executable_query",
        "executable_query_hash",
        "translations",
        "translation_losses",
        "semantic_extensions",
    }
    require_exact_keys(executable, executable_fields, "request.executable_query")
    exact_query = require_string(
        executable["executable_query"], "request.executable_query.executable_query"
    )
    environment = require_mapping(data["environment"], "request.environment")
    environment_fields = {
        "database",
        "platform",
        "coverage_start",
        "coverage_end",
        "executed_at",
        "locale",
        "index_version",
        "ranking_version",
        "filters",
        "personalization",
        "paid_insertions",
        "mode",
        "stable_snapshot",
        "snapshot_id",
        "cursor_id",
    }
    require_exact_keys(environment, environment_fields, "request.environment")
    database = require_string(environment["database"], "request.environment.database")
    platform = require_string(environment["platform"], "request.environment.platform")
    if database != executable["database"] or platform != executable["platform"]:
        fail(
            "query_environment_mismatch",
            "request.environment",
            "Среда не совпадает с компилятором.",
        )
    mode = require_string(environment["mode"], "request.environment.mode")
    if mode not in {"frozen", "live"}:
        fail(
            "invalid_search_mode",
            "request.environment.mode",
            "Неизвестен режим корпуса.",
        )
    stable_snapshot = require_bool(
        environment["stable_snapshot"], "request.environment.stable_snapshot"
    )
    snapshot_id = _nullable_text(
        environment["snapshot_id"], "request.environment.snapshot_id"
    )
    cursor_id = _nullable_text(
        environment["cursor_id"], "request.environment.cursor_id"
    )
    if stable_snapshot and snapshot_id is None and cursor_id is None:
        fail(
            "stable_snapshot_id_missing",
            "request.environment",
            "Снимок требует ID или cursor.",
        )
    pages = []
    page_numbers: set[int] = set()
    all_item_ids: list[str] = []
    set_versions: set[str] = set()
    previous_continuation = None
    continuation_gaps = []
    for index, raw in enumerate(require_list(data["pages"], "request.pages")):
        path = f"request.pages[{index}]"
        page = require_mapping(raw, path)
        fields = {
            "page_number",
            "item_ids",
            "set_version",
            "watermark",
            "request_cursor",
            "continuation_cursor",
            "raw_receipt_ref",
            "observed_at",
        }
        require_exact_keys(page, fields, path)
        page_number = require_int(page["page_number"], f"{path}.page_number", minimum=1)
        if page_number in page_numbers:
            fail("duplicate_search_page", path, "Повтор страницы запрещён.")
        page_numbers.add(page_number)
        request_cursor = _nullable_text(
            page["request_cursor"], f"{path}.request_cursor"
        )
        if index > 0 and request_cursor != previous_continuation:
            continuation_gaps.append(page_number)
        continuation = _nullable_text(
            page["continuation_cursor"], f"{path}.continuation_cursor"
        )
        previous_continuation = continuation
        item_ids = [
            require_string(item, f"{path}.item_ids[{item_index}]")
            for item_index, item in enumerate(
                require_list(page["item_ids"], f"{path}.item_ids")
            )
        ]
        set_version = require_string(page["set_version"], f"{path}.set_version")
        set_versions.add(set_version)
        all_item_ids.extend(item_ids)
        pages.append(
            {
                "page_number": page_number,
                "item_ids": item_ids,
                "set_version": set_version,
                "watermark": require_string(page["watermark"], f"{path}.watermark"),
                "request_cursor": request_cursor,
                "continuation_cursor": continuation,
                "raw_receipt_ref": require_string(
                    page["raw_receipt_ref"], f"{path}.raw_receipt_ref"
                ),
                "observed_at": require_string(
                    page["observed_at"], f"{path}.observed_at"
                ),
            }
        )
    if sorted(page_numbers) != list(range(1, len(page_numbers) + 1)):
        fail(
            "search_page_gap", "request.pages", "Номера страниц должны быть непрерывны."
        )
    duplicates = sorted(
        item_id for item_id in set(all_item_ids) if all_item_ids.count(item_id) > 1
    )
    drift = (not stable_snapshot and len(set_versions) > 1) or bool(continuation_gaps)

    qualified_modes = []
    qualification_records = []
    for index, raw in enumerate(
        require_list(data["qualification_evidence"], "request.qualification_evidence")
    ):
        path = f"request.qualification_evidence[{index}]"
        evidence = require_mapping(raw, path)
        require_exact_keys(
            evidence,
            {"mode", "status", "receipt_ref", "environment_hash"},
            path,
        )
        evidence_mode = require_string(evidence["mode"], f"{path}.mode")
        if evidence_mode not in {"frozen", "live"}:
            fail("invalid_search_mode", f"{path}.mode", "Неизвестен режим.")
        status = require_string(evidence["status"], f"{path}.status")
        if status not in {"pass", "fail"}:
            fail("invalid_qualification_status", f"{path}.status", "Неизвестен статус.")
        record = {
            "mode": evidence_mode,
            "status": status,
            "receipt_ref": require_string(
                evidence["receipt_ref"], f"{path}.receipt_ref"
            ),
            "environment_hash": _hash(
                evidence["environment_hash"], f"{path}.environment_hash"
            ),
        }
        qualification_records.append(record)
        if status == "pass":
            qualified_modes.append(evidence_mode)
    requested_mode = require_string(
        data["requested_qualification_mode"], "request.requested_qualification_mode"
    )
    if requested_mode not in {"frozen", "live"}:
        fail(
            "invalid_search_mode",
            "request.requested_qualification_mode",
            "Неизвестен режим.",
        )
    environment_record = {
        "database": database,
        "platform": platform,
        "coverage_start": require_string(
            environment["coverage_start"], "request.environment.coverage_start"
        ),
        "coverage_end": require_string(
            environment["coverage_end"], "request.environment.coverage_end"
        ),
        "executed_at": require_string(
            environment["executed_at"], "request.environment.executed_at"
        ),
        "locale": require_string(environment["locale"], "request.environment.locale"),
        "index_version": require_string(
            environment["index_version"], "request.environment.index_version"
        ),
        "ranking_version": require_string(
            environment["ranking_version"], "request.environment.ranking_version"
        ),
        "filters": require_mapping(
            environment["filters"], "request.environment.filters"
        ),
        "personalization": require_string(
            environment["personalization"], "request.environment.personalization"
        ),
        "paid_insertions": require_string(
            environment["paid_insertions"], "request.environment.paid_insertions"
        ),
        "mode": mode,
        "stable_snapshot": stable_snapshot,
        "snapshot_id": snapshot_id,
        "cursor_id": cursor_id,
    }
    return with_receipt_hash(
        {
            "contract": "SearchEnvironmentReceipt",
            "status": "result_set_drift" if drift else "recorded",
            "search_id": search_id,
            "provider_receipt_ref": require_string(
                data["provider_receipt_ref"], "request.provider_receipt_ref"
            ),
            "exact_executable_query": exact_query,
            "executable_query_hash": _hash(
                executable["executable_query_hash"],
                "request.executable_query.executable_query_hash",
            ),
            "environment": environment_record,
            "environment_hash": sha256_json(environment_record),
            "pages": pages,
            "raw_result_count": len(all_item_ids),
            "deduplicated_result_count": len(set(all_item_ids)),
            "duplicate_item_ids": duplicates,
            "result_set_drift": drift,
            "continuation_gap_pages": continuation_gaps,
            "potential_omission": drift,
            "deduplication_hides_omission": False,
            "qualification_evidence": qualification_records,
            "qualified_modes": sorted(set(qualified_modes)),
            "requested_qualification_mode": requested_mode,
            "qualification_claim_status": (
                "accepted" if requested_mode in qualified_modes else "rejected"
            ),
            "mode_qualification_transfer": False,
            "external_call_performed": False,
        }
    )


def assess_search_stop(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(SEARCH_STOP_ASSESS_SCHEMA["required"]), "request")
    _version(data)
    uncovered = []
    coverage = []
    for index, raw in enumerate(
        require_list(data["coverage_cells"], "request.coverage_cells")
    ):
        path = f"request.coverage_cells[{index}]"
        cell = require_mapping(raw, path)
        require_exact_keys(
            cell, {"cell_id", "family", "channel", "status", "receipt_refs"}, path
        )
        status = require_string(cell["status"], f"{path}.status")
        if status not in {"covered", "uncovered", "blocked", "not_applicable"}:
            fail(
                "invalid_coverage_status",
                f"{path}.status",
                "Неизвестен статус покрытия.",
            )
        normalized = {
            "cell_id": require_string(cell["cell_id"], f"{path}.cell_id"),
            "family": require_string(cell["family"], f"{path}.family"),
            "channel": require_string(cell["channel"], f"{path}.channel"),
            "status": status,
            "receipt_refs": [
                require_string(item, f"{path}.receipt_refs[{receipt_index}]")
                for receipt_index, item in enumerate(
                    require_list(cell["receipt_refs"], f"{path}.receipt_refs")
                )
            ],
        }
        coverage.append(normalized)
        if status in {"uncovered", "blocked"}:
            uncovered.append(normalized["cell_id"])
    yields = []
    for index, raw in enumerate(
        require_list(data["yield_iterations"], "request.yield_iterations")
    ):
        path = f"request.yield_iterations[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {"iteration", "new_origins", "new_families", "new_material_claims"},
            path,
        )
        yields.append(
            {
                "iteration": require_int(
                    row["iteration"], f"{path}.iteration", minimum=1
                ),
                "new_origins": require_int(row["new_origins"], f"{path}.new_origins"),
                "new_families": require_int(
                    row["new_families"], f"{path}.new_families"
                ),
                "new_material_claims": require_int(
                    row["new_material_claims"], f"{path}.new_material_claims"
                ),
            }
        )
    residual = require_mapping(data["residual_estimate"], "request.residual_estimate")
    residual_fields = {
        "estimated_mass",
        "missing_probability",
        "uncertainty",
        "model_ref",
        "model_version",
        "calibrated",
    }
    require_exact_keys(residual, residual_fields, "request.residual_estimate")
    residual_record = {
        "estimated_mass": _finite(
            residual["estimated_mass"],
            "request.residual_estimate.estimated_mass",
            minimum=0,
        ),
        "missing_probability": _finite(
            residual["missing_probability"],
            "request.residual_estimate.missing_probability",
            minimum=0,
            maximum=1,
        ),
        "uncertainty": _finite(
            residual["uncertainty"],
            "request.residual_estimate.uncertainty",
            minimum=0,
            maximum=1,
        ),
        "model_ref": require_string(
            residual["model_ref"], "request.residual_estimate.model_ref"
        ),
        "model_version": require_string(
            residual["model_version"], "request.residual_estimate.model_version"
        ),
        "calibrated": require_bool(
            residual["calibrated"], "request.residual_estimate.calibrated"
        ),
    }
    policy = require_mapping(data["policy"], "request.policy")
    policy_fields = {
        "max_residual_mass",
        "max_missing_probability",
        "max_uncertainty",
        "max_recent_material_gain",
        "minimum_independent_seeds",
    }
    require_exact_keys(policy, policy_fields, "request.policy")
    thresholds = {
        "max_residual_mass": _finite(
            policy["max_residual_mass"], "request.policy.max_residual_mass", minimum=0
        ),
        "max_missing_probability": _finite(
            policy["max_missing_probability"],
            "request.policy.max_missing_probability",
            minimum=0,
            maximum=1,
        ),
        "max_uncertainty": _finite(
            policy["max_uncertainty"],
            "request.policy.max_uncertainty",
            minimum=0,
            maximum=1,
        ),
        "max_recent_material_gain": require_int(
            policy["max_recent_material_gain"],
            "request.policy.max_recent_material_gain",
        ),
        "minimum_independent_seeds": require_int(
            policy["minimum_independent_seeds"],
            "request.policy.minimum_independent_seeds",
            minimum=1,
        ),
    }
    seeds = []
    origins = set()
    for index, raw in enumerate(
        require_list(data["citation_seeds"], "request.citation_seeds")
    ):
        path = f"request.citation_seeds[{index}]"
        seed = require_mapping(raw, path)
        require_exact_keys(
            seed,
            {
                "seed_id",
                "origin_cluster",
                "selection_method",
                "unique_result_ids",
                "claim_ids",
            },
            path,
        )
        origin = require_string(seed["origin_cluster"], f"{path}.origin_cluster")
        origins.add(origin)
        seeds.append(
            {
                "seed_id": require_string(seed["seed_id"], f"{path}.seed_id"),
                "origin_cluster": origin,
                "selection_method": require_string(
                    seed["selection_method"], f"{path}.selection_method"
                ),
                "unique_result_ids": [
                    require_string(item, f"{path}.unique_result_ids[{item_index}]")
                    for item_index, item in enumerate(
                        require_list(
                            seed["unique_result_ids"], f"{path}.unique_result_ids"
                        )
                    )
                ],
                "claim_ids": [
                    require_string(item, f"{path}.claim_ids[{item_index}]")
                    for item_index, item in enumerate(
                        require_list(seed["claim_ids"], f"{path}.claim_ids")
                    )
                ],
            }
        )
    seed_ids = {seed["seed_id"] for seed in seeds}
    sensitivity = []
    for index, raw in enumerate(
        require_list(data["leave_one_seed_results"], "request.leave_one_seed_results")
    ):
        path = f"request.leave_one_seed_results[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {"removed_seed_id", "lost_result_ids", "changed_claim_ids"},
            path,
        )
        removed = require_string(item["removed_seed_id"], f"{path}.removed_seed_id")
        if removed not in seed_ids:
            fail("unknown_seed", f"{path}.removed_seed_id", "Семя отсутствует.")
        sensitivity.append(
            {
                "removed_seed_id": removed,
                "lost_result_ids": [
                    require_string(value, f"{path}.lost_result_ids[{item_index}]")
                    for item_index, value in enumerate(
                        require_list(item["lost_result_ids"], f"{path}.lost_result_ids")
                    )
                ],
                "changed_claim_ids": [
                    require_string(value, f"{path}.changed_claim_ids[{item_index}]")
                    for item_index, value in enumerate(
                        require_list(
                            item["changed_claim_ids"], f"{path}.changed_claim_ids"
                        )
                    )
                ],
            }
        )
    missing_sensitivity = sorted(
        seed_ids - {row["removed_seed_id"] for row in sensitivity}
    )
    recent_gain = sum(row["new_material_claims"] for row in yields[-2:])
    blockers = []
    if uncovered:
        blockers.append("coverage_open")
    if not residual_record["calibrated"]:
        blockers.append("residual_model_uncalibrated")
    if residual_record["estimated_mass"] > thresholds["max_residual_mass"]:
        blockers.append("residual_mass_above_threshold")
    if residual_record["missing_probability"] > thresholds["max_missing_probability"]:
        blockers.append("missing_probability_above_threshold")
    if residual_record["uncertainty"] > thresholds["max_uncertainty"]:
        blockers.append("residual_uncertainty_above_threshold")
    if recent_gain > thresholds["max_recent_material_gain"]:
        blockers.append("material_gain_continues")
    if len(origins) < thresholds["minimum_independent_seeds"]:
        blockers.append("independent_seed_coverage_insufficient")
    if missing_sensitivity:
        blockers.append("leave_one_seed_analysis_incomplete")
    budget_exhausted = require_bool(
        data["budget_exhausted"], "request.budget_exhausted"
    )
    approved = not blockers
    status = (
        "stop_approved"
        if approved
        else "partial_budget"
        if budget_exhausted
        else "continue"
    )
    return with_receipt_hash(
        {
            "contract": "SearchStopDecisionReceipt",
            "status": status,
            "stop_approved": approved,
            "uncovered_cell_ids": sorted(uncovered),
            "coverage": coverage,
            "yield_iterations": yields,
            "recent_material_gain": recent_gain,
            "residual_estimate": residual_record,
            "policy": thresholds,
            "url_novelty_zero": require_bool(
                data["url_novelty_zero"], "request.url_novelty_zero"
            ),
            "citation_seed_count": len(seeds),
            "independent_seed_origin_count": len(origins),
            "seed_sensitivity": sensitivity,
            "missing_seed_sensitivity": missing_sensitivity,
            "blockers": sorted(set(blockers)),
            "budget_exhausted": budget_exhausted,
            "residual_unknown_treated_as_complete": False,
            "repeated_url_is_sufficient": False,
            "external_call_performed": False,
        }
    )


def assess_screening_stop(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(SCREENING_STOP_ASSESS_SCHEMA["required"]), "request")
    _version(data)
    model = require_mapping(data["model"], "request.model")
    model_fields = {
        "model_id",
        "model_version",
        "model_hash",
        "instruction_hash",
        "feature_schema_hash",
        "seed_examples_hash",
    }
    require_exact_keys(model, model_fields, "request.model")
    model_record = {
        "model_id": require_string(model["model_id"], "request.model.model_id"),
        "model_version": require_string(
            model["model_version"], "request.model.model_version"
        ),
        "model_hash": _hash(model["model_hash"], "request.model.model_hash"),
        "instruction_hash": _hash(
            model["instruction_hash"], "request.model.instruction_hash"
        ),
        "feature_schema_hash": _hash(
            model["feature_schema_hash"], "request.model.feature_schema_hash"
        ),
        "seed_examples_hash": _hash(
            model["seed_examples_hash"], "request.model.seed_examples_hash"
        ),
    }
    stopping = require_mapping(data["stopping_rule"], "request.stopping_rule")
    require_exact_keys(
        stopping,
        {"rule_id", "rule_version", "rule_hash", "frozen_before_screening"},
        "request.stopping_rule",
    )
    stopping_record = {
        "rule_id": require_string(stopping["rule_id"], "request.stopping_rule.rule_id"),
        "rule_version": require_string(
            stopping["rule_version"], "request.stopping_rule.rule_version"
        ),
        "rule_hash": _hash(stopping["rule_hash"], "request.stopping_rule.rule_hash"),
        "frozen_before_screening": require_bool(
            stopping["frozen_before_screening"],
            "request.stopping_rule.frozen_before_screening",
        ),
    }
    decisions = []
    record_ids: set[str] = set()
    for index, raw in enumerate(require_list(data["decisions"], "request.decisions")):
        path = f"request.decisions[{index}]"
        item = require_mapping(raw, path)
        fields = {
            "record_id",
            "rank",
            "probability",
            "model_decision",
            "human_override",
            "final_decision",
            "reason",
        }
        require_exact_keys(item, fields, path)
        record_id = require_string(item["record_id"], f"{path}.record_id")
        if record_id in record_ids:
            fail("duplicate_screening_record", path, "Повтор записи запрещён.")
        record_ids.add(record_id)
        model_decision = require_string(
            item["model_decision"], f"{path}.model_decision"
        )
        final_decision = require_string(
            item["final_decision"], f"{path}.final_decision"
        )
        if model_decision not in {
            "include",
            "exclude",
            "uncertain",
        } or final_decision not in {
            "include",
            "exclude",
            "uncertain",
        }:
            fail("invalid_screening_decision", path, "Неизвестно решение отбора.")
        override = _nullable_text(item["human_override"], f"{path}.human_override")
        if override is not None and override != final_decision:
            fail(
                "override_final_mismatch",
                path,
                "Переопределение не совпадает с итогом.",
            )
        decisions.append(
            {
                "record_id": record_id,
                "rank": require_int(item["rank"], f"{path}.rank", minimum=1),
                "probability": _finite(
                    item["probability"],
                    f"{path}.probability",
                    minimum=0,
                    maximum=1,
                ),
                "model_decision": model_decision,
                "human_override": override,
                "final_decision": final_decision,
                "reason": require_string(item["reason"], f"{path}.reason"),
            }
        )
    proposal = require_mapping(data["proposal"], "request.proposal")
    require_exact_keys(
        proposal,
        {"tail_record_ids", "exclusion_fraction", "probability_threshold"},
        "request.proposal",
    )
    tail_ids = [
        require_string(item, f"request.proposal.tail_record_ids[{index}]")
        for index, item in enumerate(
            require_list(
                proposal["tail_record_ids"], "request.proposal.tail_record_ids"
            )
        )
    ]
    unknown_tail = sorted(set(tail_ids) - record_ids)
    if unknown_tail:
        fail(
            "unknown_tail_record",
            "request.proposal.tail_record_ids",
            f"Запись отсутствует: {unknown_tail[0]}.",
        )
    proposal_record = {
        "tail_record_ids": tail_ids,
        "exclusion_fraction": _finite(
            proposal["exclusion_fraction"],
            "request.proposal.exclusion_fraction",
            minimum=0,
            maximum=1,
        ),
        "probability_threshold": _finite(
            proposal["probability_threshold"],
            "request.proposal.probability_threshold",
            minimum=0,
            maximum=1,
        ),
    }
    policy = require_mapping(data["policy"], "request.policy")
    require_exact_keys(
        policy,
        {
            "minimum_calibration_size",
            "minimum_tail_sample_size",
            "maximum_false_negative_rate",
            "allowed_sampling_methods",
        },
        "request.policy",
    )
    policy_record = {
        "minimum_calibration_size": require_int(
            policy["minimum_calibration_size"],
            "request.policy.minimum_calibration_size",
            minimum=1,
        ),
        "minimum_tail_sample_size": require_int(
            policy["minimum_tail_sample_size"],
            "request.policy.minimum_tail_sample_size",
            minimum=1,
        ),
        "maximum_false_negative_rate": _finite(
            policy["maximum_false_negative_rate"],
            "request.policy.maximum_false_negative_rate",
            minimum=0,
            maximum=1,
        ),
        "allowed_sampling_methods": [
            require_string(item, f"request.policy.allowed_sampling_methods[{index}]")
            for index, item in enumerate(
                require_list(
                    policy["allowed_sampling_methods"],
                    "request.policy.allowed_sampling_methods",
                )
            )
        ],
    }
    calibration_record = None
    sample_record = None
    blockers = []
    calibration = data["calibration"]
    if calibration is None:
        blockers.append("calibration_missing")
    else:
        item = require_mapping(calibration, "request.calibration")
        require_exact_keys(
            item,
            {"sample_size", "recall", "false_negative_rate", "receipt_ref"},
            "request.calibration",
        )
        calibration_record = {
            "sample_size": require_int(
                item["sample_size"], "request.calibration.sample_size"
            ),
            "recall": _finite(
                item["recall"], "request.calibration.recall", minimum=0, maximum=1
            ),
            "false_negative_rate": _finite(
                item["false_negative_rate"],
                "request.calibration.false_negative_rate",
                minimum=0,
                maximum=1,
            ),
            "receipt_ref": require_string(
                item["receipt_ref"], "request.calibration.receipt_ref"
            ),
        }
        if (
            calibration_record["sample_size"]
            < policy_record["minimum_calibration_size"]
        ):
            blockers.append("calibration_sample_too_small")
        if (
            calibration_record["false_negative_rate"]
            > policy_record["maximum_false_negative_rate"]
        ):
            blockers.append("calibration_false_negative_rate_exceeded")
    sample = data["tail_sample"]
    if sample is None:
        blockers.append("tail_sample_missing")
    else:
        item = require_mapping(sample, "request.tail_sample")
        require_exact_keys(
            item,
            {
                "method",
                "sampled_record_ids",
                "relevant_record_ids",
                "estimated_false_negative_rate",
                "uncertainty",
                "receipt_ref",
            },
            "request.tail_sample",
        )
        method = require_string(item["method"], "request.tail_sample.method")
        sampled_ids = [
            require_string(value, f"request.tail_sample.sampled_record_ids[{index}]")
            for index, value in enumerate(
                require_list(
                    item["sampled_record_ids"],
                    "request.tail_sample.sampled_record_ids",
                )
            )
        ]
        relevant_ids = [
            require_string(value, f"request.tail_sample.relevant_record_ids[{index}]")
            for index, value in enumerate(
                require_list(
                    item["relevant_record_ids"],
                    "request.tail_sample.relevant_record_ids",
                )
            )
        ]
        if not set(sampled_ids) <= set(tail_ids) or not set(relevant_ids) <= set(
            sampled_ids
        ):
            fail(
                "tail_sample_scope_invalid",
                "request.tail_sample",
                "Выборка выходит за хвост.",
            )
        sample_record = {
            "method": method,
            "sampled_record_ids": sampled_ids,
            "relevant_record_ids": relevant_ids,
            "estimated_false_negative_rate": _finite(
                item["estimated_false_negative_rate"],
                "request.tail_sample.estimated_false_negative_rate",
                minimum=0,
                maximum=1,
            ),
            "uncertainty": _finite(
                item["uncertainty"],
                "request.tail_sample.uncertainty",
                minimum=0,
                maximum=1,
            ),
            "receipt_ref": require_string(
                item["receipt_ref"], "request.tail_sample.receipt_ref"
            ),
        }
        if method not in policy_record["allowed_sampling_methods"]:
            blockers.append("tail_sampling_method_not_allowed")
        if len(sampled_ids) < policy_record["minimum_tail_sample_size"]:
            blockers.append("tail_sample_too_small")
        if relevant_ids:
            blockers.append("screening_false_negative_observed")
        if (
            sample_record["estimated_false_negative_rate"]
            > policy_record["maximum_false_negative_rate"]
        ):
            blockers.append("tail_false_negative_rate_exceeded")
    if not stopping_record["frozen_before_screening"]:
        blockers.append("stopping_rule_not_precommitted")
    approved = not blockers
    return with_receipt_hash(
        {
            "contract": "ScreeningStopDecisionReceipt",
            "status": "stop_approved" if approved else "stop_rejected",
            "model": model_record,
            "stopping_rule": stopping_record,
            "decisions": decisions,
            "human_override_count": sum(
                decision["human_override"] is not None for decision in decisions
            ),
            "proposal": proposal_record,
            "calibration": calibration_record,
            "tail_sample": sample_record,
            "policy": policy_record,
            "blockers": sorted(set(blockers)),
            "automatic_tail_exclusion_allowed": approved,
            "screening_must_resume": "screening_false_negative_observed" in blockers,
            "external_action_performed": False,
        }
    )
