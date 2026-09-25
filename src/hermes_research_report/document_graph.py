"""Document graph construction and differential element verification."""

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
    "maxItems": 1000,
    "uniqueItems": True,
    "items": _TEXT,
}
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_ELEMENT_KINDS = {
    "text",
    "table",
    "formula",
    "figure",
    "chart",
    "caption",
    "footnote",
}
_NONTEXT_KINDS = {"formula", "figure", "chart", "caption"}
_VERIFICATION_KINDS = {
    "text",
    "table",
    "table_cell",
    "formula",
    "figure",
    "chart",
    "caption",
    "footnote",
}
_ACTIONS = {"accept", "alternate_parse", "human_review", "reject"}

DOCUMENT_GRAPH_BUILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "document_id",
        "original_artifact",
        "parse_receipt",
        "pages",
        "elements",
        "reading_order_edges",
        "hierarchy_edges",
        "tables",
        "nontext_objects",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "document_id": _TEXT,
        "original_artifact": {"type": "object"},
        "parse_receipt": {"type": "object"},
        "pages": {"type": "array", "minItems": 1, "items": {"type": "object"}},
        "elements": {"type": "array", "minItems": 1, "items": {"type": "object"}},
        "reading_order_edges": {"type": "array", "items": {"type": "object"}},
        "hierarchy_edges": {"type": "array", "items": {"type": "object"}},
        "tables": {"type": "array", "items": {"type": "object"}},
        "nontext_objects": {"type": "array", "items": {"type": "object"}},
    },
}

DOCUMENT_GRAPH_VERIFY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "document_graph",
        "quality_policy",
        "observations",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "document_graph": {"type": "object"},
        "quality_policy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["document_type", "rules"],
            "properties": {
                "document_type": _TEXT,
                "rules": {"type": "array", "minItems": 1, "items": {"type": "object"}},
            },
        },
        "observations": {"type": "array", "items": {"type": "object"}},
    },
}

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
_PARSE_FIELDS = {
    "contract",
    "parse_id",
    "original_artifact_id",
    "original_content_hash",
    "parser_id",
    "parser_version",
    "parser_binary_hash",
    "configuration_hash",
    "resource_limits",
    "elapsed_ms",
    "warnings",
    "derived_representations",
    "quality_ref",
}
_PAGE_FIELDS = {
    "page_number",
    "width",
    "height",
    "coordinate_unit",
    "representation_ref",
}
_ELEMENT_FIELDS = {
    "element_id",
    "kind",
    "page_number",
    "bbox",
    "parent_id",
    "exact_ref",
    "display_ref",
    "search_ref",
    "evidence_relevant",
    "critical",
    "quality",
    "uncertainty",
    "known_losses",
}
_EDGE_FIELDS = {"from_id", "to_id"}
_TABLE_FIELDS = {
    "table_id",
    "element_id",
    "row_count",
    "column_count",
    "cells",
    "footnotes",
    "continuation_of",
    "continued_by",
}
_CELL_FIELDS = {
    "cell_id",
    "row_start",
    "row_end",
    "column_start",
    "column_end",
    "header_level",
    "value_ref",
    "unit",
    "footnote_refs",
    "locator",
    "evidence_relevant",
    "critical",
    "quality",
    "uncertainty",
}
_NONTEXT_FIELDS = {
    "object_id",
    "element_id",
    "kind",
    "region",
    "recognized_representation",
    "relations",
    "known_losses",
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
    value: object, path: str, *, minimum: float = 0, maximum: float | None = None
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        fail("invalid_number", path, "Число находится вне допустимого диапазона.")
    return float(value)


def _bbox(value: object, path: str) -> list[float]:
    raw = require_list(value, path)
    if len(raw) != 4:
        fail("invalid_bbox", path, "Область должна содержать четыре координаты.")
    result = [
        _finite(coordinate, f"{path}[{index}]") for index, coordinate in enumerate(raw)
    ]
    if result[0] >= result[2] or result[1] >= result[3]:
        fail(
            "invalid_bbox",
            path,
            "Координаты области должны иметь положительную площадь.",
        )
    return result


def _nullable_text(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def _topological_order(
    nodes: set[str], edges: list[dict[str, str]]
) -> tuple[list[str], bool]:
    outgoing = {node: [] for node in nodes}
    indegree = {node: 0 for node in nodes}
    for edge in edges:
        outgoing[edge["from_id"]].append(edge["to_id"])
        indegree[edge["to_id"]] += 1
    ready = sorted(node for node, count in indegree.items() if count == 0)
    order = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for target in sorted(outgoing[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    return order, len(order) != len(nodes)


def _verification_targets(elements, tables):
    verification_targets = [
        {
            "target_id": element["element_id"],
            "target_kind": element["kind"],
            "critical": element["critical"],
            "evidence_relevant": element["evidence_relevant"],
            "quality": element["quality"],
            "uncertainty": element["uncertainty"],
            "value_ref": element["exact_ref"],
        }
        for element in elements
        if element["evidence_relevant"]
    ]
    verification_targets.extend(
        {
            "target_id": cell["cell_id"],
            "target_kind": "table_cell",
            "critical": cell["critical"],
            "evidence_relevant": cell["evidence_relevant"],
            "quality": cell["quality"],
            "uncertainty": cell["uncertainty"],
            "value_ref": cell["value_ref"],
        }
        for table in tables
        for cell in table["cells"]
        if cell["evidence_relevant"]
    )
    return verification_targets


def build_document_graph(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(DOCUMENT_GRAPH_BUILD_SCHEMA["required"]), "request")
    _version(data)
    document_id = require_string(data["document_id"], "request.document_id")
    original = require_mapping(data["original_artifact"], "request.original_artifact")
    require_exact_keys(original, _ORIGINAL_FIELDS, "request.original_artifact")
    artifact_id = require_string(
        original["artifact_id"], "request.original_artifact.artifact_id"
    )
    artifact_hash = _hash(
        original["content_hash"], "request.original_artifact.content_hash"
    )
    if not require_bool(
        original["immutable"], "request.original_artifact.immutable"
    ) or not require_bool(
        original["readback_verified"], "request.original_artifact.readback_verified"
    ):
        fail(
            "original_artifact_not_verified",
            "request.original_artifact",
            "DocumentGraph требует неизменяемый проверенный оригинал.",
        )
    parse = require_mapping(data["parse_receipt"], "request.parse_receipt")
    require_exact_keys(parse, _PARSE_FIELDS, "request.parse_receipt")
    parse_id = require_string(parse["parse_id"], "request.parse_receipt.parse_id")
    if (
        require_string(
            parse["original_artifact_id"], "request.parse_receipt.original_artifact_id"
        )
        != artifact_id
        or _hash(
            parse["original_content_hash"],
            "request.parse_receipt.original_content_hash",
        )
        != artifact_hash
    ):
        fail(
            "parse_original_mismatch",
            "request.parse_receipt",
            "Квитанция разбора относится к другому оригиналу.",
        )

    pages = []
    page_map: dict[int, dict[str, Any]] = {}
    for index, raw in enumerate(require_list(data["pages"], "request.pages")):
        path = f"request.pages[{index}]"
        page = require_mapping(raw, path)
        require_exact_keys(page, _PAGE_FIELDS, path)
        number = require_int(page["page_number"], f"{path}.page_number", minimum=1)
        if number in page_map:
            fail("duplicate_page", f"{path}.page_number", "Повтор страницы запрещён.")
        normalized = {
            "page_number": number,
            "width": _finite(page["width"], f"{path}.width", minimum=0.000001),
            "height": _finite(page["height"], f"{path}.height", minimum=0.000001),
            "coordinate_unit": require_string(
                page["coordinate_unit"], f"{path}.coordinate_unit"
            ),
            "representation_ref": require_string(
                page["representation_ref"], f"{path}.representation_ref"
            ),
        }
        page_map[number] = normalized
        pages.append(normalized)
    if sorted(page_map) != list(range(1, len(page_map) + 1)):
        fail(
            "non_contiguous_pages",
            "request.pages",
            "Номера страниц должны быть непрерывны.",
        )

    elements = []
    element_map: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(require_list(data["elements"], "request.elements")):
        path = f"request.elements[{index}]"
        element = require_mapping(raw, path)
        require_exact_keys(element, _ELEMENT_FIELDS, path)
        element_id = require_string(element["element_id"], f"{path}.element_id")
        if element_id in element_map:
            fail("duplicate_element", f"{path}.element_id", "Повтор элемента запрещён.")
        kind = require_string(element["kind"], f"{path}.kind")
        if kind not in _ELEMENT_KINDS:
            fail("invalid_element_kind", f"{path}.kind", "Неизвестен вид элемента.")
        page_number = require_int(
            element["page_number"], f"{path}.page_number", minimum=1
        )
        if page_number not in page_map:
            fail("unknown_page", f"{path}.page_number", "Страница отсутствует.")
        bbox = _bbox(element["bbox"], f"{path}.bbox")
        page = page_map[page_number]
        if bbox[2] > page["width"] or bbox[3] > page["height"]:
            fail("bbox_outside_page", f"{path}.bbox", "Область выходит за страницу.")
        known_losses = [
            require_string(item, f"{path}.known_losses[{loss_index}]")
            for loss_index, item in enumerate(
                require_list(element["known_losses"], f"{path}.known_losses")
            )
        ]
        normalized = {
            "element_id": element_id,
            "kind": kind,
            "page_number": page_number,
            "bbox": bbox,
            "parent_id": _nullable_text(element["parent_id"], f"{path}.parent_id"),
            "exact_ref": _nullable_text(element["exact_ref"], f"{path}.exact_ref"),
            "display_ref": _nullable_text(
                element["display_ref"], f"{path}.display_ref"
            ),
            "search_ref": _nullable_text(element["search_ref"], f"{path}.search_ref"),
            "evidence_relevant": require_bool(
                element["evidence_relevant"], f"{path}.evidence_relevant"
            ),
            "critical": require_bool(element["critical"], f"{path}.critical"),
            "quality": _finite(
                element["quality"], f"{path}.quality", minimum=0, maximum=1
            ),
            "uncertainty": _finite(
                element["uncertainty"],
                f"{path}.uncertainty",
                minimum=0,
                maximum=1,
            ),
            "known_losses": known_losses,
        }
        if normalized["evidence_relevant"] and normalized["exact_ref"] is None:
            fail(
                "evidence_exact_ref_missing",
                f"{path}.exact_ref",
                "Доказательный элемент требует exact_ref.",
            )
        element_map[element_id] = normalized
        elements.append(normalized)

    edge_sets: dict[str, list[dict[str, str]]] = {}
    for field in ("reading_order_edges", "hierarchy_edges"):
        parsed_edges = []
        seen_edges: set[tuple[str, str]] = set()
        for index, raw in enumerate(require_list(data[field], f"request.{field}")):
            path = f"request.{field}[{index}]"
            edge = require_mapping(raw, path)
            require_exact_keys(edge, _EDGE_FIELDS, path)
            source = require_string(edge["from_id"], f"{path}.from_id")
            target = require_string(edge["to_id"], f"{path}.to_id")
            if source not in element_map or target not in element_map:
                fail(
                    "unknown_edge_node", path, "Ребро ссылается на неизвестный элемент."
                )
            if source == target:
                fail("self_edge", path, "Петля элемента запрещена.")
            pair = (source, target)
            if pair in seen_edges:
                fail("duplicate_edge", path, "Повтор ребра запрещён.")
            seen_edges.add(pair)
            parsed_edges.append({"from_id": source, "to_id": target})
        edge_sets[field] = parsed_edges
    reading_nodes = {
        element["element_id"] for element in elements if element["evidence_relevant"]
    }
    reading_edges = [
        edge
        for edge in edge_sets["reading_order_edges"]
        if edge["from_id"] in reading_nodes and edge["to_id"] in reading_nodes
    ]
    reading_order, reading_cycle = _topological_order(reading_nodes, reading_edges)
    if reading_cycle:
        fail(
            "reading_order_cycle",
            "request.reading_order_edges",
            "Порядок чтения содержит цикл.",
        )
    hierarchy_order, hierarchy_cycle = _topological_order(
        set(element_map), edge_sets["hierarchy_edges"]
    )
    if hierarchy_cycle:
        fail("hierarchy_cycle", "request.hierarchy_edges", "Иерархия содержит цикл.")
    hierarchy_pairs = {
        (edge["from_id"], edge["to_id"]) for edge in edge_sets["hierarchy_edges"]
    }
    for element in elements:
        parent_id = element["parent_id"]
        if parent_id is not None:
            if parent_id not in element_map:
                fail(
                    "unknown_parent",
                    f"request.elements.{element['element_id']}.parent_id",
                    "Родительский элемент отсутствует.",
                )
            if (parent_id, element["element_id"]) not in hierarchy_pairs:
                fail(
                    "hierarchy_edge_missing",
                    "request.hierarchy_edges",
                    "Связь parent_id должна иметь явное ребро иерархии.",
                )

    tables = []
    cell_ids: set[str] = set()
    table_ids: set[str] = set()
    for index, raw in enumerate(require_list(data["tables"], "request.tables")):
        path = f"request.tables[{index}]"
        table = require_mapping(raw, path)
        require_exact_keys(table, _TABLE_FIELDS, path)
        table_id = require_string(table["table_id"], f"{path}.table_id")
        if table_id in table_ids:
            fail("duplicate_table", f"{path}.table_id", "Повтор таблицы запрещён.")
        table_ids.add(table_id)
        element_id = require_string(table["element_id"], f"{path}.element_id")
        if element_id not in element_map or element_map[element_id]["kind"] != "table":
            fail(
                "invalid_table_element",
                f"{path}.element_id",
                "Таблица требует element kind=table.",
            )
        rows = require_int(table["row_count"], f"{path}.row_count", minimum=1)
        columns = require_int(table["column_count"], f"{path}.column_count", minimum=1)
        cells = []
        occupied: set[tuple[int, int]] = set()
        for cell_index, raw_cell in enumerate(
            require_list(table["cells"], f"{path}.cells")
        ):
            cell_path = f"{path}.cells[{cell_index}]"
            cell = require_mapping(raw_cell, cell_path)
            require_exact_keys(cell, _CELL_FIELDS, cell_path)
            cell_id = require_string(cell["cell_id"], f"{cell_path}.cell_id")
            if cell_id in cell_ids:
                fail(
                    "duplicate_cell", f"{cell_path}.cell_id", "Повтор ячейки запрещён."
                )
            cell_ids.add(cell_id)
            row_start = require_int(
                cell["row_start"], f"{cell_path}.row_start", minimum=1
            )
            row_end = require_int(cell["row_end"], f"{cell_path}.row_end", minimum=1)
            column_start = require_int(
                cell["column_start"], f"{cell_path}.column_start", minimum=1
            )
            column_end = require_int(
                cell["column_end"], f"{cell_path}.column_end", minimum=1
            )
            if (
                row_start > row_end
                or column_start > column_end
                or row_end > rows
                or column_end > columns
            ):
                fail("cell_span_outside_grid", cell_path, "Ячейка выходит за сетку.")
            span = {
                (row, column)
                for row in range(row_start, row_end + 1)
                for column in range(column_start, column_end + 1)
            }
            if occupied & span:
                fail("overlapping_cell_span", cell_path, "Ячейки перекрываются.")
            occupied.update(span)
            header_level = cell["header_level"]
            if header_level is not None:
                header_level = require_int(
                    header_level, f"{cell_path}.header_level", minimum=1
                )
            locator = require_mapping(cell["locator"], f"{cell_path}.locator")
            require_exact_keys(locator, {"page_number", "bbox"}, f"{cell_path}.locator")
            locator_page = require_int(
                locator["page_number"],
                f"{cell_path}.locator.page_number",
                minimum=1,
            )
            if locator_page not in page_map:
                fail(
                    "unknown_page",
                    f"{cell_path}.locator.page_number",
                    "Страница отсутствует.",
                )
            cell_bbox = _bbox(locator["bbox"], f"{cell_path}.locator.bbox")
            cells.append(
                {
                    "cell_id": cell_id,
                    "row_start": row_start,
                    "row_end": row_end,
                    "column_start": column_start,
                    "column_end": column_end,
                    "header_level": header_level,
                    "value_ref": require_string(
                        cell["value_ref"], f"{cell_path}.value_ref"
                    ),
                    "unit": _nullable_text(cell["unit"], f"{cell_path}.unit"),
                    "footnote_refs": [
                        require_string(
                            item, f"{cell_path}.footnote_refs[{footnote_index}]"
                        )
                        for footnote_index, item in enumerate(
                            require_list(
                                cell["footnote_refs"], f"{cell_path}.footnote_refs"
                            )
                        )
                    ],
                    "locator": {
                        "page_number": locator_page,
                        "bbox": cell_bbox,
                    },
                    "evidence_relevant": require_bool(
                        cell["evidence_relevant"],
                        f"{cell_path}.evidence_relevant",
                    ),
                    "critical": require_bool(cell["critical"], f"{cell_path}.critical"),
                    "quality": _finite(
                        cell["quality"],
                        f"{cell_path}.quality",
                        minimum=0,
                        maximum=1,
                    ),
                    "uncertainty": _finite(
                        cell["uncertainty"],
                        f"{cell_path}.uncertainty",
                        minimum=0,
                        maximum=1,
                    ),
                }
            )
        footnotes = []
        footnote_ids: set[str] = set()
        for footnote_index, raw_footnote in enumerate(
            require_list(table["footnotes"], f"{path}.footnotes")
        ):
            footnote_path = f"{path}.footnotes[{footnote_index}]"
            footnote = require_mapping(raw_footnote, footnote_path)
            require_exact_keys(
                footnote, {"footnote_id", "text_ref", "locator"}, footnote_path
            )
            footnote_id = require_string(
                footnote["footnote_id"], f"{footnote_path}.footnote_id"
            )
            if footnote_id in footnote_ids:
                fail("duplicate_footnote", footnote_path, "Повтор сноски запрещён.")
            footnote_ids.add(footnote_id)
            footnotes.append(
                {
                    "footnote_id": footnote_id,
                    "text_ref": require_string(
                        footnote["text_ref"], f"{footnote_path}.text_ref"
                    ),
                    "locator": require_string(
                        footnote["locator"], f"{footnote_path}.locator"
                    ),
                }
            )
        for cell in cells:
            unknown = sorted(set(cell["footnote_refs"]) - footnote_ids)
            if unknown:
                fail(
                    "unknown_footnote",
                    f"request.tables.{table_id}.cells.{cell['cell_id']}.footnote_refs",
                    f"Неизвестная сноска: {unknown[0]}.",
                )
        tables.append(
            {
                "table_id": table_id,
                "element_id": element_id,
                "row_count": rows,
                "column_count": columns,
                "cells": cells,
                "footnotes": footnotes,
                "continuation_of": _nullable_text(
                    table["continuation_of"], f"{path}.continuation_of"
                ),
                "continued_by": _nullable_text(
                    table["continued_by"], f"{path}.continued_by"
                ),
            }
        )
    for table in tables:
        for field in ("continuation_of", "continued_by"):
            target = table[field]
            if target is not None and target not in table_ids:
                fail(
                    "unknown_table_continuation",
                    f"request.tables.{table['table_id']}.{field}",
                    "Продолжение таблицы отсутствует.",
                )

    nontext_objects = []
    object_ids: set[str] = set()
    for index, raw in enumerate(
        require_list(data["nontext_objects"], "request.nontext_objects")
    ):
        path = f"request.nontext_objects[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, _NONTEXT_FIELDS, path)
        object_id = require_string(item["object_id"], f"{path}.object_id")
        if object_id in object_ids:
            fail("duplicate_nontext_object", path, "Повтор объекта запрещён.")
        object_ids.add(object_id)
        element_id = require_string(item["element_id"], f"{path}.element_id")
        kind = require_string(item["kind"], f"{path}.kind")
        if (
            kind not in _NONTEXT_KINDS
            or element_id not in element_map
            or element_map[element_id]["kind"] != kind
        ):
            fail(
                "nontext_element_mismatch",
                path,
                "Объект не совпадает с видом элемента.",
            )
        region = require_mapping(item["region"], f"{path}.region")
        require_exact_keys(region, {"page_number", "bbox"}, f"{path}.region")
        region_page = require_int(
            region["page_number"], f"{path}.region.page_number", minimum=1
        )
        if region_page not in page_map:
            fail("unknown_page", f"{path}.region.page_number", "Страница отсутствует.")
        relations = []
        for relation_index, raw_relation in enumerate(
            require_list(item["relations"], f"{path}.relations")
        ):
            relation_path = f"{path}.relations[{relation_index}]"
            relation = require_mapping(raw_relation, relation_path)
            require_exact_keys(relation, {"relation", "target_id"}, relation_path)
            relations.append(
                {
                    "relation": require_string(
                        relation["relation"], f"{relation_path}.relation"
                    ),
                    "target_id": require_string(
                        relation["target_id"], f"{relation_path}.target_id"
                    ),
                }
            )
        nontext_objects.append(
            {
                "object_id": object_id,
                "element_id": element_id,
                "kind": kind,
                "region": {
                    "page_number": region_page,
                    "bbox": _bbox(region["bbox"], f"{path}.region.bbox"),
                },
                "recognized_representation": require_string(
                    item["recognized_representation"],
                    f"{path}.recognized_representation",
                ),
                "relations": relations,
                "known_losses": [
                    require_string(loss, f"{path}.known_losses[{loss_index}]")
                    for loss_index, loss in enumerate(
                        require_list(item["known_losses"], f"{path}.known_losses")
                    )
                ],
            }
        )
    relation_targets = set(element_map) | object_ids
    for item in nontext_objects:
        for relation in item["relations"]:
            if relation["target_id"] not in relation_targets:
                fail(
                    "unknown_relation_target",
                    f"request.nontext_objects.{item['object_id']}.relations",
                    "Связанный объект отсутствует.",
                )

    verification_targets = _verification_targets(elements, tables)
    graph: dict[str, Any] = {
        "schema_version": 1,
        "document_id": document_id,
        "original_artifact_id": artifact_id,
        "original_content_hash": artifact_hash,
        "parse_id": parse_id,
        "parser": {
            "id": require_string(parse["parser_id"], "request.parse_receipt.parser_id"),
            "version": require_string(
                parse["parser_version"], "request.parse_receipt.parser_version"
            ),
            "binary_hash": _hash(
                parse["parser_binary_hash"], "request.parse_receipt.parser_binary_hash"
            ),
            "configuration_hash": _hash(
                parse["configuration_hash"], "request.parse_receipt.configuration_hash"
            ),
        },
        "pages": pages,
        "elements": elements,
        "reading_order_edges": edge_sets["reading_order_edges"],
        "reading_order": reading_order,
        "hierarchy_edges": edge_sets["hierarchy_edges"],
        "hierarchy_topological_order": hierarchy_order,
        "tables": tables,
        "nontext_objects": nontext_objects,
        "verification_targets": verification_targets,
    }
    graph["graph_hash"] = sha256_json(graph)
    return with_receipt_hash(
        {
            "contract": "DocumentGraphBuildReceipt",
            "status": "graph_built",
            "document_graph": graph,
            "page_count": len(pages),
            "element_count": len(elements),
            "table_count": len(tables),
            "nontext_object_count": len(nontext_objects),
            "verification_target_count": len(verification_targets),
            "parser_execution_performed": False,
        }
    )


def verify_document_graph(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(DOCUMENT_GRAPH_VERIFY_SCHEMA["required"]), "request")
    _version(data)
    graph = require_mapping(data["document_graph"], "request.document_graph")
    graph_hash = _hash(graph.get("graph_hash"), "request.document_graph.graph_hash")
    if (
        sha256_json({key: value for key, value in graph.items() if key != "graph_hash"})
        != graph_hash
    ):
        fail(
            "document_graph_hash_mismatch",
            "request.document_graph.graph_hash",
            "Содержимое графа изменено после построения.",
        )
    document_id = require_string(
        graph.get("document_id"), "request.document_graph.document_id"
    )
    targets_data = require_list(
        graph.get("verification_targets"),
        "request.document_graph.verification_targets",
    )
    if not targets_data:
        fail(
            "document_verification_targets_missing",
            "request.document_graph.verification_targets",
            "Пустой набор целей не подтверждает проверку документа.",
        )
    try:
        expected_targets = _verification_targets(graph["elements"], graph["tables"])
    except (KeyError, TypeError):
        fail(
            "document_graph_structure_invalid",
            "request.document_graph",
            "Структура графа неполна.",
        )
    if targets_data != expected_targets:
        fail(
            "document_verification_targets_mismatch",
            "request.document_graph.verification_targets",
            "Цели проверки не соответствуют элементам и ячейкам графа.",
        )
    targets: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(targets_data):
        path = f"request.document_graph.verification_targets[{index}]"
        target = require_mapping(raw, path)
        fields = {
            "target_id",
            "target_kind",
            "critical",
            "evidence_relevant",
            "quality",
            "uncertainty",
            "value_ref",
        }
        require_exact_keys(target, fields, path)
        target_id = require_string(target["target_id"], f"{path}.target_id")
        if target_id in targets:
            fail("duplicate_verification_target", path, "Повтор цели запрещён.")
        kind = require_string(target["target_kind"], f"{path}.target_kind")
        if kind not in _VERIFICATION_KINDS:
            fail("invalid_target_kind", f"{path}.target_kind", "Неизвестен вид цели.")
        targets[target_id] = {
            "target_id": target_id,
            "target_kind": kind,
            "critical": require_bool(target["critical"], f"{path}.critical"),
            "evidence_relevant": require_bool(
                target["evidence_relevant"], f"{path}.evidence_relevant"
            ),
            "quality": _finite(
                target["quality"], f"{path}.quality", minimum=0, maximum=1
            ),
            "uncertainty": _finite(
                target["uncertainty"],
                f"{path}.uncertainty",
                minimum=0,
                maximum=1,
            ),
            "value_ref": _nullable_text(target["value_ref"], f"{path}.value_ref"),
        }

    policy = require_mapping(data["quality_policy"], "request.quality_policy")
    require_exact_keys(policy, {"document_type", "rules"}, "request.quality_policy")
    document_type = require_string(
        policy["document_type"], "request.quality_policy.document_type"
    )
    rules: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(
        require_list(policy["rules"], "request.quality_policy.rules")
    ):
        path = f"request.quality_policy.rules[{index}]"
        rule = require_mapping(raw, path)
        require_exact_keys(
            rule,
            {
                "target_kind",
                "minimum_quality",
                "maximum_uncertainty",
                "below_threshold_action",
                "critical_requires_independent_routes",
            },
            path,
        )
        kind = require_string(rule["target_kind"], f"{path}.target_kind")
        if kind not in _VERIFICATION_KINDS or kind in rules:
            fail(
                "invalid_or_duplicate_quality_rule",
                f"{path}.target_kind",
                "Правило неизвестно или повторено.",
            )
        action = require_string(
            rule["below_threshold_action"], f"{path}.below_threshold_action"
        )
        if action not in {"alternate_parse", "human_review", "reject"}:
            fail(
                "invalid_quality_action",
                f"{path}.below_threshold_action",
                "Недопустимое действие.",
            )
        routes = require_int(
            rule["critical_requires_independent_routes"],
            f"{path}.critical_requires_independent_routes",
            minimum=1,
        )
        rules[kind] = {
            "target_kind": kind,
            "minimum_quality": _finite(
                rule["minimum_quality"],
                f"{path}.minimum_quality",
                minimum=0,
                maximum=1,
            ),
            "maximum_uncertainty": _finite(
                rule["maximum_uncertainty"],
                f"{path}.maximum_uncertainty",
                minimum=0,
                maximum=1,
            ),
            "below_threshold_action": action,
            "critical_requires_independent_routes": routes,
        }
    missing_rules = sorted(
        {target["target_kind"] for target in targets.values()} - set(rules)
    )
    if missing_rules:
        fail(
            "quality_rule_missing",
            "request.quality_policy.rules",
            f"Нет правила для {missing_rules[0]}.",
        )

    observations_by_target: dict[str, list[dict[str, Any]]] = {
        target_id: [] for target_id in targets
    }
    observation_ids: set[str] = set()
    for index, raw in enumerate(
        require_list(data["observations"], "request.observations")
    ):
        path = f"request.observations[{index}]"
        observation = require_mapping(raw, path)
        fields = {
            "observation_id",
            "target_id",
            "route_id",
            "parser_id",
            "model_ref",
            "method_ref",
            "context_ref",
            "value_json",
            "confidence",
            "uncertainty",
            "locator_verified",
            "ground_truth",
            "reviewer_authority",
        }
        require_exact_keys(
            observation,
            fields | ({"graph_hash"} if "graph_hash" in observation else set()),
            path,
        )
        observation_id = require_string(
            observation["observation_id"], f"{path}.observation_id"
        )
        if observation_id in observation_ids:
            fail("duplicate_observation", path, "Повтор наблюдения запрещён.")
        observation_ids.add(observation_id)
        target_id = require_string(observation["target_id"], f"{path}.target_id")
        if target_id not in targets:
            fail(
                "unknown_verification_target", f"{path}.target_id", "Цель отсутствует."
            )
        observations_by_target[target_id].append(
            {
                "observation_id": observation_id,
                "graph_bound": "graph_hash" in observation
                and _hash(observation["graph_hash"], f"{path}.graph_hash")
                == graph_hash,
                "target_id": target_id,
                "route_id": require_string(observation["route_id"], f"{path}.route_id"),
                "parser_id": require_string(
                    observation["parser_id"], f"{path}.parser_id"
                ),
                "model_ref": require_string(
                    observation["model_ref"], f"{path}.model_ref"
                ),
                "method_ref": require_string(
                    observation["method_ref"], f"{path}.method_ref"
                ),
                "context_ref": require_string(
                    observation["context_ref"], f"{path}.context_ref"
                ),
                "value_json": require_string(
                    observation["value_json"], f"{path}.value_json", nonempty=False
                ),
                "confidence": _finite(
                    observation["confidence"],
                    f"{path}.confidence",
                    minimum=0,
                    maximum=1,
                ),
                "uncertainty": _finite(
                    observation["uncertainty"],
                    f"{path}.uncertainty",
                    minimum=0,
                    maximum=1,
                ),
                "locator_verified": require_bool(
                    observation["locator_verified"], f"{path}.locator_verified"
                ),
                "ground_truth": require_bool(
                    observation["ground_truth"], f"{path}.ground_truth"
                ),
                "reviewer_authority": require_bool(
                    observation["reviewer_authority"],
                    f"{path}.reviewer_authority",
                ),
            }
        )

    decisions = []
    conflict_set = []
    for target_id, target in sorted(targets.items()):
        rule = rules[target["target_kind"]]
        all_observations = observations_by_target[target_id]
        target_observations = [row for row in all_observations if row["graph_bound"]]
        unbound = [
            row["observation_id"] for row in all_observations if not row["graph_bound"]
        ]
        below_threshold = (
            target["quality"] < rule["minimum_quality"]
            or target["uncertainty"] > rule["maximum_uncertainty"]
        )
        signatures = {
            (
                observation["parser_id"],
                observation["model_ref"],
                observation["method_ref"],
                observation["context_ref"],
            )
            for observation in target_observations
            if observation["locator_verified"]
        }
        ground_truth = [
            observation
            for observation in target_observations
            if observation["ground_truth"]
            and observation["reviewer_authority"]
            and observation["locator_verified"]
        ]
        values = sorted(
            {
                observation["value_json"]
                for observation in target_observations
                if observation["locator_verified"]
            }
        )
        conflict = len(values) > 1
        selected_value = None
        action = "accept"
        reasons = []
        if below_threshold:
            action = rule["below_threshold_action"]
            reasons.append("quality_threshold_failed")
        if target["critical"]:
            required_routes = rule["critical_requires_independent_routes"]
            if len(signatures) < required_routes and not ground_truth:
                action = "human_review"
                reasons.append("independent_route_requirement_failed")
        if conflict:
            authoritative_values = sorted(
                {observation["value_json"] for observation in ground_truth}
            )
            if len(authoritative_values) == 1:
                selected_value = authoritative_values[0]
                if not below_threshold:
                    action = "accept"
                reasons.append("conflict_resolved_by_authorized_ground_truth")
            else:
                action = "human_review"
                reasons.append("unresolved_parser_conflict")
                conflict_set.append(
                    {
                        "target_id": target_id,
                        "values_json": values,
                        "observation_ids": [
                            observation["observation_id"]
                            for observation in target_observations
                        ],
                        "resolution": "unresolved",
                        "aggregation": "none",
                    }
                )
        elif len(values) == 1 and action == "accept":
            selected_value = values[0]
        elif not values:
            action = "human_review" if target["critical"] else "alternate_parse"
            reasons.append("verification_observation_missing")
        if unbound:
            action = "human_review"
            selected_value = None
            reasons.append("observation_graph_unbound")
        evidence_usable = action == "accept" and selected_value is not None
        decisions.append(
            {
                "target_id": target_id,
                "target_kind": target["target_kind"],
                "critical": target["critical"],
                "quality": target["quality"],
                "uncertainty": target["uncertainty"],
                "independent_route_count": len(signatures),
                "ground_truth_count": len(ground_truth),
                "unbound_observation_ids": unbound,
                "conflict": conflict,
                "action": action,
                "reasons": sorted(set(reasons)),
                "selected_value_json": selected_value,
                "evidence_usable": evidence_usable,
                "aggregation": "none",
            }
        )
    blocked = [
        decision["target_id"]
        for decision in decisions
        if not decision["evidence_usable"]
    ]
    qualification_cells = [
        {
            "document_type": document_type,
            "target_kind": kind,
            "target_count": sum(
                decision["target_kind"] == kind for decision in decisions
            ),
            "accepted_count": sum(
                decision["target_kind"] == kind and decision["evidence_usable"]
                for decision in decisions
            ),
        }
        for kind in sorted({decision["target_kind"] for decision in decisions})
    ]
    return with_receipt_hash(
        {
            "contract": "DocumentGraphVerificationReceipt",
            "status": "verified" if not blocked else "review_required",
            "document_id": document_id,
            "document_graph_hash": graph_hash,
            "document_type": document_type,
            "element_decisions": decisions,
            "conflict_set": conflict_set,
            "blocked_target_ids": blocked,
            "qualification_cells": qualification_cells,
            "mean_score_used_for_acceptance": False,
            "majority_vote_used_for_acceptance": False,
            "external_action_performed": False,
        }
    )
