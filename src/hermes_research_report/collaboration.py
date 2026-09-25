"""Role, independence, consilium, topology, and modality contracts."""

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
_ROLE_FIELDS = {
    "role_ref",
    "mission",
    "competence",
    "knowledge_position",
    "motive",
    "success_criteria",
    "input_refs",
    "output_schema_ref",
    "allowed_actions",
    "prohibited_actions",
    "biases",
    "incompetence_boundary",
    "mandatory_objections",
    "interaction_style",
    "model_family",
    "corpus_ref",
    "method_ref",
    "independence_group",
    "acceptance_gate_ref",
}

ROLE_PROFILE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "role_ref"],
    "properties": {
        "schema_version": {"const": 1},
        "role_ref": _TEXT,
        "mission": _TEXT,
        "competence": _TEXTS,
        "knowledge_position": _TEXT,
        "motive": _TEXT,
        "success_criteria": _TEXTS,
        "input_refs": _TEXTS,
        "output_schema_ref": _TEXT,
        "allowed_actions": _TEXTS,
        "prohibited_actions": _TEXTS,
        "biases": _TEXTS,
        "incompetence_boundary": _TEXT,
        "mandatory_objections": _TEXTS,
        "interaction_style": _TEXT,
        "model_family": _TEXT,
        "corpus_ref": _TEXT,
        "method_ref": _TEXT,
        "independence_group": _TEXT,
        "acceptance_gate_ref": _TEXT,
    },
}

ROLE_INDEPENDENCE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "roles"],
    "properties": {
        "schema_version": {"const": 1},
        "roles": {
            "type": "array",
            "minItems": 2,
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "role_ref",
                    "model_family",
                    "corpus_ref",
                    "method_ref",
                    "context_hash",
                    "independence_group",
                ],
                "properties": {
                    "role_ref": _TEXT,
                    "model_family": _TEXT,
                    "corpus_ref": _TEXT,
                    "method_ref": _TEXT,
                    "context_hash": _TEXT,
                    "independence_group": _TEXT,
                },
            },
        },
    },
}

CONSILIUM_PLAN_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "consilium_ref",
        "question_ref",
        "role_refs",
        "isolated_inputs",
        "position_format_ref",
        "max_rounds",
        "chair_role_ref",
        "arbiter_role_ref",
        "first_positions",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "consilium_ref": _TEXT,
        "question_ref": _TEXT,
        "role_refs": _TEXTS,
        "isolated_inputs": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["role_ref", "input_refs"],
                "properties": {"role_ref": _TEXT, "input_refs": _TEXTS},
            },
        },
        "position_format_ref": _TEXT,
        "max_rounds": {"type": "integer", "minimum": 1},
        "chair_role_ref": _TEXT,
        "arbiter_role_ref": _TEXT,
        "first_positions": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "position_ref",
                    "role_ref",
                    "created_before_disclosure",
                    "context_contains_other_positions",
                ],
                "properties": {
                    "position_ref": _TEXT,
                    "role_ref": _TEXT,
                    "created_before_disclosure": {"type": "boolean"},
                    "context_contains_other_positions": {"type": "boolean"},
                },
            },
        },
    },
}

CONSILIUM_RESULT_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "consilium_ref",
        "round_count",
        "max_rounds",
        "positions",
        "arbiter_role_ref",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "consilium_ref": _TEXT,
        "round_count": {"type": "integer", "minimum": 1},
        "max_rounds": {"type": "integer", "minimum": 1},
        "positions": {
            "type": "array",
            "minItems": 2,
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "position_ref",
                    "role_ref",
                    "conclusion",
                    "evidence_directness",
                    "support_refs",
                ],
                "properties": {
                    "position_ref": _TEXT,
                    "role_ref": _TEXT,
                    "conclusion": _TEXT,
                    "evidence_directness": {"enum": ["asserted", "proxy", "direct"]},
                    "support_refs": _TEXTS,
                },
            },
        },
        "arbiter_role_ref": _TEXT,
    },
}

TOPOLOGY_SELECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "task_ref",
        "branch_count",
        "branch_coupling",
        "independence_required",
        "shared_mutable_graph",
        "context_size",
        "modality_count",
        "budget_units",
        "coordination_cost_units",
        "requested_topology",
        "merge_owner_refs",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "task_ref": _TEXT,
        "branch_count": {"type": "integer", "minimum": 1},
        "branch_coupling": {"enum": ["low", "medium", "high"]},
        "independence_required": {"type": "boolean"},
        "shared_mutable_graph": {"type": "boolean"},
        "context_size": {"enum": ["small", "medium", "large"]},
        "modality_count": {"type": "integer", "minimum": 1},
        "budget_units": {"type": "integer", "minimum": 0},
        "coordination_cost_units": {"type": "integer", "minimum": 0},
        "requested_topology": {"enum": ["single_agent", "multi_agent", "swarm"]},
        "merge_owner_refs": _TEXTS,
    },
}

MODALITY_PLAN_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "plan_ref", "items"],
    "properties": {
        "schema_version": {"const": 1},
        "plan_ref": _TEXT,
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "item_ref",
                    "modality",
                    "original_ref",
                    "original_locator",
                    "transformations",
                    "quality_receipt_ref",
                    "losses",
                    "result_ref",
                ],
                "properties": {
                    "item_ref": _TEXT,
                    "modality": _TEXT,
                    "original_ref": _TEXT,
                    "original_locator": _TEXT,
                    "transformations": {
                        "type": "array",
                        "maxItems": 100,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "step",
                                "operation",
                                "tool_or_model_ref",
                                "version",
                                "input_ref",
                                "output_ref",
                            ],
                            "properties": {
                                "step": {"type": "integer", "minimum": 1},
                                "operation": _TEXT,
                                "tool_or_model_ref": _TEXT,
                                "version": _TEXT,
                                "input_ref": _TEXT,
                                "output_ref": _TEXT,
                            },
                        },
                    },
                    "quality_receipt_ref": _TEXT,
                    "losses": _TEXTS,
                    "result_ref": _TEXT,
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


def assess_role_profile(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    allowed = _ROLE_FIELDS | {"schema_version"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        fail("unknown_field", f"request.{unknown[0]}", "Неизвестное поле.")
    if data.get("schema_version") != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается schema_version=1.",
        )
    role_ref = require_string(data.get("role_ref"), "request.role_ref")
    missing = sorted(f"request.{field}" for field in _ROLE_FIELDS - set(data))
    empty_fields: list[str] = []
    for field in sorted(_ROLE_FIELDS - {"role_ref"} & set(data)):
        value = data[field]
        if field in {
            "competence",
            "success_criteria",
            "input_refs",
            "allowed_actions",
            "prohibited_actions",
            "biases",
            "mandatory_objections",
        }:
            if not _strings(value, f"request.{field}"):
                empty_fields.append(f"request.{field}")
        else:
            require_string(value, f"request.{field}")
    missing.extend(empty_fields)
    payload = {
        "schema_version": 1,
        "contract": "DeepRoleProfileDecisionReceipt",
        "status": "role_ready" if not missing else "blocked",
        "role_ref": role_ref,
        "missing_fields": sorted(missing),
        "role_name_implies_independence": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def assess_role_independence(request: object) -> dict[str, Any]:
    data = _schema(request, set(ROLE_INDEPENDENCE_ASSESS_SCHEMA["required"]))
    roles = []
    refs: set[str] = set()
    signatures: dict[tuple[str, str, str], list[str]] = {}
    for index, raw in enumerate(require_list(data["roles"], "request.roles")):
        path = f"request.roles[{index}]"
        row = require_mapping(raw, path)
        fields = {
            "role_ref",
            "model_family",
            "corpus_ref",
            "method_ref",
            "context_hash",
            "independence_group",
        }
        require_exact_keys(row, fields, path)
        record = {key: require_string(row[key], f"{path}.{key}") for key in fields}
        if record["role_ref"] in refs:
            fail("duplicate_role", f"{path}.role_ref", "Повтор роли.")
        refs.add(record["role_ref"])
        signature = (
            record["corpus_ref"],
            record["method_ref"],
            record["context_hash"],
        )
        signatures.setdefault(signature, []).append(record["role_ref"])
        roles.append(record)
    correlated = sorted(
        sorted(group) for group in signatures.values() if len(group) > 1
    )
    payload = {
        "schema_version": 1,
        "contract": "RoleIndependenceDecisionReceipt",
        "status": "correlated_roles" if correlated else "independent_processes",
        "roles": roles,
        "correlated_role_groups": correlated,
        "independent_judgement_count": len(signatures),
        "process_signature_count": len(signatures),
        "material_signature_count": len({r["corpus_ref"] for r in roles}),
        "model_family_count": len({r["model_family"] for r in roles}),
        "primary_evidence_independence_verified": False,
        "assessment_basis": "declared_process_and_material_signatures",
        "different_names_count_as_independence": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def assess_consilium_plan(request: object) -> dict[str, Any]:
    data = _schema(request, set(CONSILIUM_PLAN_ASSESS_SCHEMA["required"]))
    consilium_ref = require_string(data["consilium_ref"], "request.consilium_ref")
    roles = _strings(data["role_refs"], "request.role_refs")
    require_string(data["question_ref"], "request.question_ref")
    require_string(data["position_format_ref"], "request.position_format_ref")
    require_int(data["max_rounds"], "request.max_rounds", minimum=1)
    chair = require_string(data["chair_role_ref"], "request.chair_role_ref")
    arbiter = require_string(data["arbiter_role_ref"], "request.arbiter_role_ref")
    issues = []
    if chair not in roles or arbiter not in roles:
        issues.append("chair_or_arbiter_not_in_roles")
    isolated_roles = set()
    for index, raw in enumerate(
        require_list(data["isolated_inputs"], "request.isolated_inputs")
    ):
        path = f"request.isolated_inputs[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"role_ref", "input_refs"}, path)
        role = require_string(row["role_ref"], f"{path}.role_ref")
        _strings(row["input_refs"], f"{path}.input_refs")
        isolated_roles.add(role)
    if isolated_roles != set(roles):
        issues.append("isolated_inputs_incomplete")
    position_roles = set()
    position_refs = set()
    for index, raw in enumerate(
        require_list(data["first_positions"], "request.first_positions")
    ):
        path = f"request.first_positions[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "position_ref",
                "role_ref",
                "created_before_disclosure",
                "context_contains_other_positions",
            },
            path,
        )
        position_ref = require_string(row["position_ref"], f"{path}.position_ref")
        role_ref = require_string(row["role_ref"], f"{path}.role_ref")
        if position_ref in position_refs:
            fail("duplicate_position", f"{path}.position_ref", "Повтор позиции.")
        position_refs.add(position_ref)
        position_roles.add(role_ref)
        if not require_bool(
            row["created_before_disclosure"], f"{path}.created_before_disclosure"
        ):
            issues.append(f"position_created_after_disclosure:{role_ref}")
        if require_bool(
            row["context_contains_other_positions"],
            f"{path}.context_contains_other_positions",
        ):
            issues.append(f"position_context_contaminated:{role_ref}")
    if position_roles != set(roles):
        issues.append("first_positions_incomplete")
    payload = {
        "schema_version": 1,
        "contract": "ConsiliumPlanDecisionReceipt",
        "status": "first_round_ready" if not issues else "blocked",
        "consilium_ref": consilium_ref,
        "role_count": len(roles),
        "first_position_count": len(position_refs),
        "disclosure_allowed": not issues,
        "execution_started": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def assess_consilium_result(request: object) -> dict[str, Any]:
    data = _schema(request, set(CONSILIUM_RESULT_ASSESS_SCHEMA["required"]))
    consilium_ref = require_string(data["consilium_ref"], "request.consilium_ref")
    rounds = require_int(data["round_count"], "request.round_count", minimum=1)
    limit = require_int(data["max_rounds"], "request.max_rounds", minimum=1)
    if rounds > limit:
        fail("round_limit_exceeded", "request.round_count", "Превышен предел раундов.")
    positions = []
    conclusions: dict[str, list[str]] = {}
    direct_positions = []
    for index, raw in enumerate(require_list(data["positions"], "request.positions")):
        path = f"request.positions[{index}]"
        row = require_mapping(raw, path)
        fields = {
            "position_ref",
            "role_ref",
            "conclusion",
            "evidence_directness",
            "support_refs",
        }
        require_exact_keys(row, fields, path)
        record = {
            "position_ref": require_string(row["position_ref"], f"{path}.position_ref"),
            "role_ref": require_string(row["role_ref"], f"{path}.role_ref"),
            "conclusion": require_string(row["conclusion"], f"{path}.conclusion"),
            "evidence_directness": require_string(
                row["evidence_directness"], f"{path}.evidence_directness"
            ),
            "support_refs": _strings(row["support_refs"], f"{path}.support_refs"),
        }
        positions.append(record)
        conclusions.setdefault(record["conclusion"], []).append(record["role_ref"])
        if record["evidence_directness"] == "direct":
            direct_positions.append(record["position_ref"])
    disagreement = len(conclusions) > 1
    payload = {
        "schema_version": 1,
        "contract": "ConsiliumResultDecisionReceipt",
        "status": "arbitration_required" if disagreement else "consensus_recorded",
        "consilium_ref": consilium_ref,
        "positions": positions,
        "conclusion_groups": [
            {"conclusion": conclusion, "role_refs": sorted(role_refs)}
            for conclusion, role_refs in sorted(conclusions.items())
        ],
        "disagreement_preserved": disagreement,
        "direct_evidence_position_refs": sorted(direct_positions),
        "fact_determined_by_majority": False,
        "arbiter_role_ref": require_string(
            data["arbiter_role_ref"], "request.arbiter_role_ref"
        ),
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def select_topology(request: object) -> dict[str, Any]:
    data = _schema(request, set(TOPOLOGY_SELECT_SCHEMA["required"]))
    task_ref = require_string(data["task_ref"], "request.task_ref")
    branches = require_int(data["branch_count"], "request.branch_count", minimum=1)
    coupling = require_string(data["branch_coupling"], "request.branch_coupling")
    independence = require_bool(
        data["independence_required"], "request.independence_required"
    )
    shared_graph = require_bool(
        data["shared_mutable_graph"], "request.shared_mutable_graph"
    )
    context_size = require_string(data["context_size"], "request.context_size")
    modalities = require_int(
        data["modality_count"], "request.modality_count", minimum=1
    )
    budget = require_int(data["budget_units"], "request.budget_units")
    coordination = require_int(
        data["coordination_cost_units"], "request.coordination_cost_units"
    )
    requested = require_string(data["requested_topology"], "request.requested_topology")
    merge_owners = _strings(data["merge_owner_refs"], "request.merge_owner_refs")
    issues = []
    if len(merge_owners) != 1:
        issues.append("merge_owner_count_not_one")
    swarm_safe = (
        branches >= 4
        and coupling == "low"
        and not shared_graph
        and context_size != "large"
        and budget >= coordination
    )
    if independence and branches > 1:
        selected = "multi_agent"
    elif swarm_safe:
        selected = "swarm"
    else:
        selected = (
            "single_agent" if coupling == "high" or branches == 1 else "multi_agent"
        )
    if requested == "swarm" and not swarm_safe:
        issues.append("swarm_rejected")
    payload = {
        "schema_version": 1,
        "contract": "TopologyDecisionReceipt",
        "status": "topology_selected" if len(merge_owners) == 1 else "blocked",
        "task_ref": task_ref,
        "requested_topology": requested,
        "selected_topology": selected,
        "swarm_safe": swarm_safe,
        "merge_owner_ref": merge_owners[0] if len(merge_owners) == 1 else None,
        "selection_factors": {
            "branch_count": branches,
            "branch_coupling": coupling,
            "independence_required": independence,
            "shared_mutable_graph": shared_graph,
            "context_size": context_size,
            "modality_count": modalities,
            "budget_units": budget,
            "coordination_cost_units": coordination,
        },
        "more_agents_raise_evidence": False,
        "execution_started": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)


def assess_modality_plan(request: object) -> dict[str, Any]:
    data = _schema(request, set(MODALITY_PLAN_ASSESS_SCHEMA["required"]))
    plan_ref = require_string(data["plan_ref"], "request.plan_ref")
    records = []
    issues = []
    for index, raw in enumerate(require_list(data["items"], "request.items")):
        path = f"request.items[{index}]"
        row = require_mapping(raw, path)
        fields = {
            "item_ref",
            "modality",
            "original_ref",
            "original_locator",
            "transformations",
            "quality_receipt_ref",
            "losses",
            "result_ref",
        }
        require_exact_keys(row, fields, path)
        transformations = []
        prior_output = require_string(row["original_ref"], f"{path}.original_ref")
        for step_index, raw_step in enumerate(
            require_list(row["transformations"], f"{path}.transformations")
        ):
            step_path = f"{path}.transformations[{step_index}]"
            step = require_mapping(raw_step, step_path)
            step_fields = {
                "step",
                "operation",
                "tool_or_model_ref",
                "version",
                "input_ref",
                "output_ref",
            }
            require_exact_keys(step, step_fields, step_path)
            number = require_int(step["step"], f"{step_path}.step", minimum=1)
            input_ref = require_string(step["input_ref"], f"{step_path}.input_ref")
            output_ref = require_string(step["output_ref"], f"{step_path}.output_ref")
            if number != step_index + 1 or input_ref != prior_output:
                issues.append(f"transformation_chain_broken:{path}:{number}")
            prior_output = output_ref
            transformations.append(
                {
                    "step": number,
                    "operation": require_string(
                        step["operation"], f"{step_path}.operation"
                    ),
                    "tool_or_model_ref": require_string(
                        step["tool_or_model_ref"], f"{step_path}.tool_or_model_ref"
                    ),
                    "version": require_string(step["version"], f"{step_path}.version"),
                    "input_ref": input_ref,
                    "output_ref": output_ref,
                }
            )
        result_ref = require_string(row["result_ref"], f"{path}.result_ref")
        if transformations and prior_output != result_ref:
            issues.append(f"result_not_last_transformation:{path}")
        records.append(
            {
                "item_ref": require_string(row["item_ref"], f"{path}.item_ref"),
                "modality": require_string(row["modality"], f"{path}.modality"),
                "original_ref": require_string(
                    row["original_ref"], f"{path}.original_ref"
                ),
                "original_locator": require_string(
                    row["original_locator"], f"{path}.original_locator"
                ),
                "transformations": transformations,
                "quality_receipt_ref": require_string(
                    row["quality_receipt_ref"], f"{path}.quality_receipt_ref"
                ),
                "losses": _strings(row["losses"], f"{path}.losses"),
                "result_ref": result_ref,
            }
        )
    payload = {
        "schema_version": 1,
        "contract": "ModalityPlanDecisionReceipt",
        "status": "modality_plan_ready" if not issues else "blocked",
        "plan_ref": plan_ref,
        "items": records,
        "originals_preserved": True,
        "external_processing_performed": False,
        "persistence_applied": False,
        "issues": sorted(issues),
    }
    return with_receipt_hash(payload)
