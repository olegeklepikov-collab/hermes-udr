"""Locate reported numeric structures without upgrading them to validated findings."""

from __future__ import annotations

import hashlib
import re
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from .academic_numeric_evidence import _SOURCE_NUMBER, assess_academic_calculations
from .canonical import with_receipt_hash

_N = r"[+\-−]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+\-−]?[0-9]+)?"
_HEADER = re.compile(r"\bn\s*\(\s*%\s*\)", re.IGNORECASE)
_COUNT = re.compile(
    r"(?<![\w.,])(?P<n>[0-9]{1,12})\s*\((?P<p>[0-9]{1,3}(?:\.[0-9]{1,6})?)\s*(?P<percent>%)?\)"
)
_INTERVAL = re.compile(
    rf"(?P<measure>SMD|MD|OR|RR|HR)\s*[=:]\s*(?P<estimate>{_N})\s*[,;(]?\s*"
    rf"(?P<level>[0-9]{{1,2}}(?:\.[0-9]+)?)\s*%\s*(?:CI|confidence\s*interval)\s*[:(]?\s*"
    rf"(?P<lower>{_N})\s*(?:to|,|;)\s*(?P<upper>{_N})",
    re.IGNORECASE,
)
_MEAN_SD = re.compile(
    rf"\bmean\s*[=:]\s*(?P<mean>{_N})\s*[,;(]\s*SD\s*[=:]\s*(?P<sd>{_N})", re.IGNORECASE
)
_PLUS_MINUS = re.compile(rf"(?P<location>{_N})\s*±\s*(?P<dispersion>{_N})")
_ORIGINAL_PART = re.compile(
    r"(?<![0-9.,+−-])(?P<count>[0-9]{1,12})\s*\(\s*(?P<percent>[0-9]{1,3}(?:\.[0-9]{1,6})?)\s*%\s*of\s*(?:the\s*)?original\s*(?P<total>[0-9]{1,12})\s*\)",
    re.IGNORECASE,
)


def _decimal(text: str) -> Decimal:
    if len(text) > 100:
        raise ValueError("numeric_inventory_value_out_of_range")
    try:
        value = Decimal(text.replace("−", "-"))
    except InvalidOperation:
        raise ValueError("numeric_inventory_value_out_of_range") from None
    if not value.is_finite() or abs(value.adjusted()) > 100:
        raise ValueError("numeric_inventory_value_out_of_range")
    return value


def denominator_interval(count: int, percentage: str) -> dict:
    """Integer totals compatible with ROUND_HALF_UP; not independent evidence of N."""
    p = Decimal(percentage)
    if count < 0 or not 0 <= p <= 100:
        return {
            "status": "invalid_count_or_percentage",
            "minimum": None,
            "maximum": None,
        }
    quantum = Decimal(1).scaleb(-len(percentage.partition(".")[2]))
    with localcontext() as ctx:
        ctx.prec = 60
        low, high = p - quantum / 2, p + quantum / 2
        if count == 0:
            return {
                "status": "compatible" if p == 0 else "no_compatible_denominator",
                "minimum": 1 if p == 0 else None,
                "maximum": None,
            }
        minimum = max(
            count,
            int((100 * Decimal(count) / high).to_integral_value(rounding=ROUND_FLOOR))
            + 1,
        )
        maximum = (
            int((100 * Decimal(count) / low).to_integral_value(rounding=ROUND_FLOOR))
            if low > 0
            else None
        )
    return {
        "status": "compatible"
        if maximum is None or minimum <= maximum
        else "no_compatible_denominator",
        "minimum": minimum,
        "maximum": maximum,
    }


def inspect_numeric_text(text: str) -> dict:
    """Scan exact text spans; missing matches never mean all results were checked."""
    counts, intervals, descriptives = [], [], []
    number_ends = {m.start(): m.end() for m in _SOURCE_NUMBER.finditer(text)}
    header = None
    offset = 0
    for line in text.splitlines(keepends=True):
        if _HEADER.search(line):
            declared = list(
                re.finditer(r"\bN\s*=\s*([0-9]{1,12})\b", line, re.IGNORECASE)
            )
            header = {
                "notation": "count_and_percentage",
                "start": offset,
                "end": offset + len(line),
                "text": line,
                "denominator": int(declared[0].group(1))
                if len(declared) == 1
                else None,
                "denominator_source": "same_header_line"
                if len(declared) == 1
                else "not_stated_unambiguously",
            }
        elif re.search(
            r"(?i)(?:sample|participants|subjects|patients).{0,30}\(\s*%\s*[a-z]", line
        ):
            header = {
                "start": offset,
                "end": offset + len(line),
                "text": line,
                "notation": "sample_size_and_subgroup_percentage",
                "denominator": None,
                "denominator_source": "not_applicable_to_total_count",
            }
        elif re.search(
            r"(?i)\b(?:median|mean|quartile|standard\s*deviation)\b|^\s*Table\s*\d",
            line,
        ):
            header = None
        for match in _COUNT.finditer(line):
            if not match["percent"] and header is None:
                continue
            count, p = int(match["n"]), match["p"]
            count_role = (
                "provisional_part_count"
                if header and header["notation"] == "count_and_percentage"
                else "sample_size"
                if header
                else "unresolved"
            )
            candidate = (
                denominator_interval(count, p)
                if count_role == "provisional_part_count"
                else None
            )
            denominator = header["denominator"] if header else None
            status = (
                "denominator_unverified"
                if candidate is not None
                else "count_percentage_relation_unverified"
            )
            calculated = None
            if candidate is not None and candidate["status"] != "compatible":
                status = candidate["status"]
            if denominator is not None:
                if (
                    denominator <= 0
                    or count > denominator
                    or not 0 <= Decimal(p) <= 100
                ):
                    status = "invalid_declared_denominator_or_count"
                else:
                    with localcontext() as ctx:
                        ctx.prec = 60
                        calculated = Decimal(count) / denominator * 100
                        rounded = calculated.quantize(
                            Decimal(1).scaleb(-len(p.partition(".")[2])),
                            rounding=ROUND_HALF_UP,
                        )
                    status = (
                        "declared_denominator_arithmetic_match"
                        if rounded == Decimal(p)
                        else "reported_percentage_mismatch"
                    )
            if any(
                number_ends.get(offset + match.start(k)) != offset + match.end(k)
                for k in ("n", "p")
            ):
                status = "number_token_ambiguous"
            counts.append(
                {
                    "start": offset + match.start(),
                    "end": offset + match.end(),
                    "raw": match.group(),
                    "row_context": line.strip(),
                    "header_context": header,
                    "count": count,
                    "count_role": count_role,
                    "reported_percentage": p,
                    "denominator": denominator,
                    "compatible_denominator_interval": candidate,
                    "denominator_inference_is_circular": denominator is None
                    and candidate is not None,
                    "calculated_percentage": str(calculated)
                    if calculated is not None
                    else None,
                    "status": status,
                    "population_binding_verified": False,
                    "rounding": "ROUND_HALF_UP",
                }
            )
        offset += len(line)
    for match in _INTERVAL.finditer(text):
        try:
            point, lower, upper, level = (
                _decimal(match[k]) for k in ("estimate", "lower", "upper", "level")
            )
        except ValueError:
            intervals.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "raw": match.group(),
                    "status": "number_out_of_range",
                    "statistical_validity_verified": False,
                }
            )
            continue
        measure = match["measure"].upper()
        null = Decimal(1 if measure in {"OR", "RR", "HR"} else 0)
        issues = []
        if any(
            number_ends.get(match.start(k)) != match.end(k)
            for k in ("estimate", "lower", "upper")
        ):
            issues.append("number_token_ambiguous")
        if lower > upper:
            issues.append("interval_bounds_reversed")
        if not 0 < level < 100:
            issues.append("confidence_level_invalid")
        if not lower <= point <= upper:
            issues.append("point_outside_interval_review_required")
        if null == 1 and min(point, lower, upper) <= 0:
            issues.append("ratio_scale_nonpositive_value")
        intervals.append(
            {
                "start": match.start(),
                "end": match.end(),
                "raw": match.group(),
                "measure": measure,
                "estimate": str(point),
                "lower": str(lower),
                "upper": str(upper),
                "confidence_level_percent": str(level),
                "null_value": str(null),
                "includes_null": lower <= null <= upper if not issues else None,
                "issues": issues,
                "status": "reported_interval_located"
                if not issues
                else "requires_review",
                "statistical_validity_verified": False,
                "null_inclusion_does_not_prove_no_effect": True,
            }
        )
    for match in _MEAN_SD.finditer(text):
        try:
            mean, sd = _decimal(match["mean"]), _decimal(match["sd"])
            status = (
                "reported_mean_sd_located" if sd >= 0 else "negative_standard_deviation"
            )
        except ValueError:
            mean = sd = None
            status = "number_out_of_range"
        if any(number_ends.get(match.start(k)) != match.end(k) for k in ("mean", "sd")):
            status = "number_token_ambiguous"
        descriptives.append(
            {
                "start": match.start(),
                "end": match.end(),
                "raw": match.group(),
                "mean": str(mean),
                "sd": str(sd),
                "status": status,
                "measurement_semantics_verified": False,
            }
        )
    paired_dispersion = []
    for match in _PLUS_MINUS.finditer(text):
        paired_dispersion.append(
            {
                "start": match.start(),
                "end": match.end(),
                "raw": match.group(),
                "location_raw": match["location"],
                "dispersion_raw": match["dispersion"],
                "dispersion_kind": "unspecified_not_assumed_sd_or_se",
                "number_tokens_verified": all(
                    number_ends.get(match.start(k)) == match.end(k)
                    for k in ("location", "dispersion")
                ),
                "measurement_semantics_verified": False,
            }
        )
    proportions = []
    corpus = with_receipt_hash(
        {
            "sources": [
                {
                    "source_id": "page",
                    "text": text,
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "read_scope": "page_text",
                }
            ]
        }
    )
    for match in _ORIGINAL_PART.finditer(text):

        def operand(key, unit, match=match):
            return {
                "source_id": "page",
                "start": match.start(),
                "end": match.end(),
                "quote": match.group(),
                "number_start": match.start(key) - match.start(),
                "value": match[key],
                "context": {
                    "measure": "reported part of original group",
                    "unit": unit,
                    "population": "group in exact source phrase",
                    "timepoint": "as reported",
                    "denominator_definition": "explicit original total in same source phrase",
                },
            }

        check = assess_academic_calculations(
            corpus,
            [
                {
                    "calculation_id": f"ORIGINAL-{match.start()}",
                    "formula": "percentage",
                    "operands": [operand("count", "count"), operand("total", "count")],
                    "published": operand("percent", "%"),
                    "rounding_digits": len(match["percent"].partition(".")[2]),
                }
            ],
        )
        proportions.append(
            {
                "start": match.start(),
                "end": match.end(),
                "raw": match.group(),
                "interpretation": "reported_part_of_original_group",
                "calculation": check,
                "rounding_basis": "assumed_half_up_at_displayed_precision",
                "population_binding_verified": False,
            }
        )
    return with_receipt_hash(
        {
            "contract": "AcademicNumericTextInventory",
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "count_percent_records": counts,
            "confidence_intervals": intervals,
            "mean_sd_records": descriptives,
            "location_dispersion_pairs": paired_dispersion,
            "explicit_proportion_checks": proportions,
            "selection_basis": "explicit_notation_not_semantic_importance",
            "all_essential_results_checked": False,
            "release_authorized": False,
        }
    )
