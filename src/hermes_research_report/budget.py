"""Finite budget assessment without invented completion or external effects."""

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
from .run_contract import (
    DEPTHS,
    RUN_CONTRACT_REVISE_SCHEMA,
    _dependencies,
    _policy,
    _validate_contract,
    propose_run_contract_revision,
)

_CONTRACT_SCHEMA = RUN_CONTRACT_REVISE_SCHEMA["properties"]["contract"]
_POLICY_SCHEMA = RUN_CONTRACT_REVISE_SCHEMA["properties"]["policy"]
_DEPENDENCIES_SCHEMA = RUN_CONTRACT_REVISE_SCHEMA["properties"]["dependencies"]
BUDGET_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "contract",
        "policy",
        "expected_revision",
        "available_units",
        "obligation_costs",
        "proposed_depth",
        "user_consent",
        "dependencies",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "contract": _CONTRACT_SCHEMA,
        "policy": _POLICY_SCHEMA,
        "expected_revision": {"type": "integer", "minimum": 1},
        "available_units": {"type": "integer", "minimum": 0},
        "obligation_costs": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["obligation", "cost_units"],
                "properties": {
                    "obligation": {"type": "string", "minLength": 1},
                    "cost_units": {"type": "integer", "minimum": 0},
                },
            },
        },
        "proposed_depth": {"anyOf": [{"enum": list(DEPTHS)}, {"type": "null"}]},
        "user_consent": {"type": "boolean"},
        "dependencies": _DEPENDENCIES_SCHEMA,
    },
}


def assess_budget(request: object) -> dict[str, Any]:
    """Assess caller estimates and optionally propose a consented lower depth."""
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "contract",
            "policy",
            "expected_revision",
            "available_units",
            "obligation_costs",
            "proposed_depth",
            "user_consent",
            "dependencies",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    policy = _policy(data["policy"])
    contract = _validate_contract(data["contract"], policy, "request.contract")
    expected_revision = require_int(
        data["expected_revision"], "request.expected_revision", minimum=1
    )
    if expected_revision != contract["revision"]:
        fail(
            "stale_revision",
            "request.expected_revision",
            "Ожидаемая редакция устарела.",
        )
    available = require_int(data["available_units"], "request.available_units")
    consent = require_bool(data["user_consent"], "request.user_consent")
    dependencies = _dependencies(data["dependencies"], "request.dependencies")

    rows = require_list(data["obligation_costs"], "request.obligation_costs")
    if len(rows) > 100:
        fail("size_limit", "request.obligation_costs", "Слишком много строк стоимости.")
    costs: dict[str, int] = {}
    for index, raw in enumerate(rows):
        path = f"request.obligation_costs[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"obligation", "cost_units"}, path)
        obligation = require_string(row["obligation"], f"{path}.obligation")
        if obligation in costs:
            fail(
                "duplicate_obligation", f"{path}.obligation", "Повторное обязательство."
            )
        costs[obligation] = require_int(row["cost_units"], f"{path}.cost_units")
    contract_obligations = contract["payload"]["obligations"]
    if set(costs) != set(contract_obligations):
        fail(
            "incomplete_obligation_costs",
            "request.obligation_costs",
            "Стоимость требуется для каждого и только действующего обязательства.",
        )

    proposed = data["proposed_depth"]
    if proposed is not None:
        proposed = require_string(proposed, "request.proposed_depth")
        if proposed not in DEPTHS:
            fail("invalid_value", "request.proposed_depth", "Неверная глубина.")
        if DEPTHS.index(proposed) >= DEPTHS.index(contract["payload"]["depth"]):
            fail(
                "not_lower_depth",
                "request.proposed_depth",
                "Предложенная глубина не ниже текущей.",
            )
    elif consent:
        fail(
            "consent_without_proposal",
            "request.user_consent",
            "Согласие без точного предложения недопустимо.",
        )

    revision_receipt: dict[str, Any] | None = None
    assessed_contract = contract
    if proposed is not None and consent:
        revision_receipt = propose_run_contract_revision(
            {
                "schema_version": 1,
                "contract": contract,
                "expected_revision": expected_revision,
                "changes": {"depth": proposed},
                "dependencies": dependencies,
                "user_consent": True,
                "policy": policy,
            }
        )
        assessed_contract = revision_receipt["run_contract"]
    assessed_obligations = assessed_contract["payload"]["obligations"]
    required = sum(costs[obligation] for obligation in assessed_obligations)
    shortfall = max(0, required - available)
    budget_status = "partial" if shortfall else "budget_sufficient"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "BudgetDecisionReceipt",
        "status": "revision_proposed" if revision_receipt else budget_status,
        "budget_status": budget_status,
        "run_contract": assessed_contract,
        "proposed_depth": proposed,
        "required_units": required,
        "available_units": available,
        "shortfall_units": shortfall,
        "obligations_at_risk": assessed_obligations if shortfall else [],
        "obligations_completed": [],
        "completion_claim_allowed": False,
        "outputs_to_revisit": (
            revision_receipt["outputs_to_revisit"] if revision_receipt else []
        ),
        "persistence_applied": False,
        "semantic_certified": False,
        "host_decision_required": True,
    }
    return with_receipt_hash(payload)
