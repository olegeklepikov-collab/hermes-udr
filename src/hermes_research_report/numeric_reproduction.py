"""Exact numeric semantics and independent calculation reproduction."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_exact_keys,
    require_list,
    require_mapping,
    require_string,
)

_TEXT = {"type": "string", "minLength": 1}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

NUMERIC_REPRODUCTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "numeric_fact", "claim", "calculation"],
    "properties": {
        "schema_version": {"const": 1},
        "numeric_fact": {"type": "object"},
        "claim": {"type": "object"},
        "calculation": {"type": "object"},
    },
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _decimal(value: object, path: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        fail("invalid_number", path, "Ожидалось конечное десятичное число.")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        fail("invalid_number", path, "Ожидалось конечное десятичное число.")
    if not result.is_finite():
        fail("invalid_number", path, "Ожидалось конечное десятичное число.")
    return result


def assess_numeric_reproduction(request: object) -> dict[str, Any]:
    """Verify numeric meaning and reproduce a registered relative-change formula."""

    data = require_mapping(request, "request")
    require_exact_keys(
        data, {"schema_version", "numeric_fact", "claim", "calculation"}, "request"
    )
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    semantic_keys = {"measure_kind", "context_ref", "unit", "uncertainty"}
    fact = require_mapping(data["numeric_fact"], "request.numeric_fact")
    require_exact_keys(fact, semantic_keys, "request.numeric_fact")
    claim = require_mapping(data["claim"], "request.claim")
    require_exact_keys(claim, semantic_keys | {"published_value"}, "request.claim")
    fact_semantics = {
        key: require_string(fact[key], f"request.numeric_fact.{key}")
        for key in sorted(semantic_keys)
    }
    claim_semantics = {
        key: require_string(claim[key], f"request.claim.{key}")
        for key in sorted(semantic_keys)
    }
    issues: list[str] = []
    if fact_semantics != claim_semantics:
        issues.append("measurement_semantics_mismatch")

    calculation = require_mapping(data["calculation"], "request.calculation")
    require_exact_keys(
        calculation,
        {
            "formula",
            "a",
            "b",
            "exit_code",
            "input_hashes",
            "code_hash",
            "output_value",
            "rounding_digits",
        },
        "request.calculation",
    )
    formula = require_string(calculation["formula"], "request.calculation.formula")
    if formula != "(a-b)/b":
        fail(
            "unregistered_formula",
            "request.calculation.formula",
            "Формула не зарегистрирована.",
        )
    a = _decimal(calculation["a"], "request.calculation.a")
    b = _decimal(calculation["b"], "request.calculation.b")
    if b == 0:
        fail("division_by_zero", "request.calculation.b", "Знаменатель равен нулю.")
    exit_code = calculation["exit_code"]
    if type(exit_code) is not int:
        fail(
            "invalid_integer", "request.calculation.exit_code", "Ожидалось целое число."
        )
    if exit_code != 0:
        issues.append("calculation_exit_nonzero")
    input_hashes = [
        _hash(value, f"request.calculation.input_hashes[{index}]")
        for index, value in enumerate(
            require_list(
                calculation["input_hashes"], "request.calculation.input_hashes"
            )
        )
    ]
    if not input_hashes:
        issues.append("calculation_input_hashes_missing")
    code_hash = _hash(calculation["code_hash"], "request.calculation.code_hash")
    reproduced = (a - b) / b
    observed = _decimal(calculation["output_value"], "request.calculation.output_value")
    if observed != reproduced:
        issues.append("reproduced_value_mismatch")
    rounding_digits = calculation["rounding_digits"]
    if type(rounding_digits) is not int or not 0 <= rounding_digits <= 12:
        fail(
            "invalid_integer",
            "request.calculation.rounding_digits",
            "Недопустимое округление.",
        )
    published = _decimal(claim["published_value"], "request.claim.published_value")
    quantum = Decimal(1).scaleb(-rounding_digits)
    rounded = reproduced.quantize(quantum)
    if published != rounded:
        issues.append("published_rounding_mismatch")
    accepted = not issues
    return with_receipt_hash(
        {
            "contract": "NumericReproductionReceipt",
            "status": "reproduced" if accepted else "rejected",
            "semantic_match": fact_semantics == claim_semantics,
            "formula": formula,
            "inputs": {"a": str(a), "b": str(b)},
            "input_hashes": input_hashes,
            "code_hash": code_hash,
            "exit_code": exit_code,
            "reproduced_value": str(reproduced),
            "observed_output_value": str(observed),
            "published_value": str(published),
            "rounded_reproduced_value": str(rounded),
            "supported_available": accepted,
            "issues": sorted(set(issues)),
        }
    )
