"""Source-bound arithmetic; numerical agreement does not validate study methods."""

from __future__ import annotations

import hashlib
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from .canonical import verify_receipt_hash, with_receipt_hash

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
# Recognize a whole source token before interpreting its locale. In particular,
# a quoted substring must not hide a preceding sign or grouping separator.
_SOURCE_NUMBER = re.compile(
    r"(?:[+\-−–—﹣－][ \t]*)?"
    r"(?:[0-9]{1,3}(?:[,.' \u00a0\u202f][0-9]{3})+(?:[.,][0-9]+)?"
    r"|[0-9]+(?:[.,][0-9]+)?|(?<!\w)[.,][0-9]+)"
    r"(?:[eE][+\-−]?[0-9]+)?"
)
_FORMULAS = {"sum", "difference", "ratio", "percentage", "relative_change_percent"}


def audit_binary_percentage_table(
    grid: list[list], *, positive: str, other: str
) -> dict:
    """Check displayed percentages under an explicit count/all-cells interpretation."""
    if not positive or not other or positive == other or len(grid) < 2:
        raise ValueError("academic_binary_table_invalid")
    width = len(grid[0])
    if width < 2 or any(len(row) != width for row in grid):
        raise ValueError("academic_binary_table_ragged")
    checks = []
    for axis, count in (("row", len(grid)), ("column", width)):
        for index in range(1, count):
            label = grid[index][0] if axis == "row" else grid[0][index]
            cells = grid[index][1:] if axis == "row" else [r[index] for r in grid[1:]]
            matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*%", label or ""))
            if len(matches) != 1:
                continue
            raw = matches[0].group(1)
            unknown = [
                i + 1 for i, cell in enumerate(cells) if cell not in {positive, other}
            ]
            numerator = cells.count(positive)
            digits = len(raw.partition(".")[2])
            with localcontext() as context:
                context.prec = 40
                calculated = Decimal(numerator) / len(cells) * 100
                rounded = calculated.quantize(
                    Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP
                )
            checks.append(
                {
                    "axis": axis,
                    "index": index,
                    "label": label,
                    "cells": cells,
                    "positive_count": numerator,
                    "denominator": len(cells),
                    "published_percentage": raw,
                    "calculated_percentage": str(calculated),
                    "rounded_percentage": str(rounded),
                    "unknown_cell_indices": unknown,
                    "arithmetic_match": not unknown and rounded == Decimal(raw),
                    "denominator_rule": "all_cells_in_selected_axis",
                    "denominator_semantics_verified": False,
                }
            )
    return {
        "checks": checks,
        "positive_symbol": positive,
        "other_symbol": other,
        "method_validity_verified": False,
        "complete_paper_verification": False,
    }


def _number(value: object) -> Decimal:
    if type(value) is not str or len(value) > 100 or not _NUMBER.fullmatch(value):
        raise ValueError("academic_number_invalid")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("academic_number_invalid") from None
    if not result.is_finite() or abs(result.adjusted()) > 100:
        raise ValueError("academic_number_out_of_range")
    return result


def _anchor(item: dict, sources: dict) -> dict:
    source = sources.get(item.get("source_id"))
    if source is None:
        raise ValueError("academic_numeric_source_missing")
    start, end = item.get("start"), item.get("end")
    quote = item.get("quote")
    if (
        type(start) is not int
        or type(end) is not int
        or type(quote) is not str
        or not 0 <= start < end <= len(source["text"])
    ):
        raise ValueError("academic_numeric_locator_invalid")
    matched = source["text"][start:end] == quote
    value = _number(item.get("value"))
    offset = item.get("number_start")
    token_match = next(
        (
            m
            for m in _SOURCE_NUMBER.finditer(source["text"])
            if type(offset) is int and m.start() == start + offset and m.end() <= end
        ),
        None,
    )
    raw_token = token_match.group() if token_match else None
    number_format = item.get("number_format", "decimal_point")
    normalized = raw_token.replace("−", "-") if raw_token else None
    if normalized is not None and number_format == "grouped_comma":
        if re.fullmatch(r"[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?", normalized):
            normalized = normalized.replace(",", "")
        else:
            normalized = None
    elif normalized is not None and number_format == "decimal_comma":
        if re.fullmatch(r"[+-]?[0-9]+,[0-9]+", normalized):
            normalized = normalized.replace(",", ".")
        else:
            normalized = None
    elif number_format != "decimal_point":
        normalized = None
    token_verified = bool(
        normalized is not None
        and _NUMBER.fullmatch(normalized)
        and Decimal(normalized) == value
        and ("source_token" not in item or item["source_token"] == raw_token)
    )
    return {
        **item,
        "source_text_sha256": source["text_sha256"],
        "quote_verified": matched,
        "number_token_verified": token_verified,
        "source_number_token": raw_token,
        "number_format": number_format,
        "normalized_source_number": normalized,
        "source_number_normalization_applied": raw_token != normalized,
        "decimal_value": str(value),
        "read_scope": source["read_scope"],
    }


def assess_academic_calculations(corpus: dict, requests: list[dict]) -> dict:
    """Verify exact operands and execute only registered, bounded arithmetic."""
    if not verify_receipt_hash(corpus):
        raise ValueError("academic_numeric_corpus_invalid")
    sources = {}
    for source in corpus["sources"]:
        key = source["source_id"]
        if (
            key in sources
            or hashlib.sha256(source["text"].encode()).hexdigest()
            != source["text_sha256"]
        ):
            raise ValueError("academic_numeric_source_changed")
        sources[key] = source
    seen = set()
    results = []
    for request in requests:
        identifier = request["calculation_id"]
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("academic_calculation_id_invalid")
        seen.add(identifier)
        formula = request["formula"]
        if formula not in _FORMULAS:
            raise ValueError("academic_formula_unregistered")
        inputs = request["operands"]
        if not 1 <= len(inputs) <= 100 or (formula != "sum" and len(inputs) != 2):
            raise ValueError("academic_operands_invalid")
        anchors = [_anchor(item, sources) for item in inputs]
        published = (
            _anchor(request["published"], sources)
            if request["published"] is not None
            else None
        )
        bound_values = [*anchors, published] if published is not None else anchors
        digits = request["rounding_digits"]
        if type(digits) is not int or not 0 <= digits <= 12:
            raise ValueError("academic_rounding_invalid")
        issues = []
        for anchor in bound_values:
            if not anchor["quote_verified"] or not anchor["number_token_verified"]:
                issues.append("operand_or_result_not_anchored")
        semantics = (
            "measure",
            "unit",
            "population",
            "timepoint",
            "denominator_definition",
        )
        contexts = []
        for item in bound_values:
            context = item.get("context", {})
            if any(
                type(context.get(k)) is not str or not context[k].strip()
                for k in semantics
            ):
                issues.append("measurement_context_incomplete")
            contexts.append(context)
        # A submitted semantic match is explicitly not independent validation.
        if any(
            c.get("population") != contexts[0].get("population")
            or c.get("timepoint") != contexts[0].get("timepoint")
            for c in contexts[1:]
        ):
            issues.append("population_or_timepoint_mismatch")
        if len({a.get("context", {}).get("unit") for a in anchors}) != 1:
            issues.append("operand_units_mismatch")
        expected_unit = (
            "%"
            if formula.endswith("percent") or formula == "percentage"
            else "ratio"
            if formula == "ratio"
            else contexts[0].get("unit")
        )
        if published is not None and contexts[-1].get("unit") != expected_unit:
            issues.append("result_unit_mismatch")
        values = [_number(a["value"]) for a in anchors]
        calculated = None
        rounded = None
        with localcontext() as context:
            context.prec = 256
            if (
                formula in {"ratio", "percentage", "relative_change_percent"}
                and values[1] == 0
            ):
                issues.append("zero_denominator")
            else:
                if formula == "sum":
                    calculated = sum(values, Decimal(0))
                elif formula == "difference":
                    calculated = values[0] - values[1]
                elif formula == "relative_change_percent":
                    calculated = (values[0] - values[1]) / values[1] * 100
                else:
                    calculated = (
                        values[0] / values[1] * (100 if formula == "percentage" else 1)
                    )
                rounded = calculated.quantize(
                    Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP
                )
                if published is not None and rounded != _number(published["value"]):
                    issues.append("published_value_mismatch")
        results.append(
            {
                "calculation_id": identifier,
                "formula": formula,
                "operands": anchors,
                "published": published,
                "calculated_value": str(calculated) if calculated is not None else None,
                "rounded_value": str(rounded) if rounded is not None else None,
                "rounding_digits": digits,
                "rounding_mode": "ROUND_HALF_UP",
                "status": "source_bound_arithmetic_match"
                if not issues and published is not None
                else "source_bound_arithmetic_derived"
                if not issues
                else "requires_review",
                "result_unit": expected_unit,
                "author_reported_result": published is not None,
                "issues": sorted(set(issues)),
                "semantic_assignment_basis": "submitted_context",
                "measurement_semantics_verified": False,
                "table_layout_verified": False,
                "causal_validity_verified": False,
                "partial_result_allowed": True,
            }
        )
    return with_receipt_hash(
        {
            "contract": "AcademicSourceBoundCalculations",
            "corpus_receipt_hash": corpus["receipt_hash"],
            "calculations": results,
            "arithmetic_match_count": sum(
                r["status"] == "source_bound_arithmetic_match" for r in results
            ),
            "request_count": len(requests),
            "all_essential_results_checked": False,
            "release_authorized": False,
        }
    )
