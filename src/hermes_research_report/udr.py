"""Minimal UDR architecture, finite-loop, gate, and dashboard contracts."""

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
_LOOP_IDS = tuple(f"L{index}" for index in range(13))
_GATE_STATUSES = {"pass", "soft_fail", "hard_fail", "kill_fail", "waived"}
_DURABLE_ARTIFACT_TYPES = {
    "run_contract",
    "coverage_map",
    "search_ledger",
    "source_pool",
    "claim_set",
    "challenge_record",
    "review_receipt",
    "decision_envelope",
    "debrief",
}

UDR_ARCHITECTURE_SELECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "task_ref",
        "question_scope",
        "corpus_scale",
        "risk",
        "object_dynamics",
        "evidence_level",
        "branch_count",
        "modalities",
        "model_or_tool_selection_started",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "task_ref": _TEXT,
        "question_scope": {"enum": ["narrow", "bounded", "broad"]},
        "corpus_scale": {"enum": ["small", "medium", "large"]},
        "risk": {"enum": ["low", "medium", "high"]},
        "object_dynamics": {"enum": ["static", "changing", "dynamic"]},
        "evidence_level": {"enum": ["E0", "E1", "E2", "E3", "E4", "E5"]},
        "branch_count": {"type": "integer", "minimum": 1},
        "modalities": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "uniqueItems": True,
            "items": _TEXT,
        },
        "model_or_tool_selection_started": {"type": "boolean"},
    },
}

UDR_PLAN_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "architecture_ref",
        "packets",
        "loops",
        "gates",
        "required_artifact_types",
        "durable_artifacts",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "architecture_ref": _TEXT,
        "packets": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "packet_ref",
                    "output_ref",
                    "acceptor_role",
                    "depends_on",
                ],
                "properties": {
                    "packet_ref": _TEXT,
                    "output_ref": _TEXT,
                    "acceptor_role": _NULLABLE_TEXT,
                    "depends_on": {
                        "type": "array",
                        "maxItems": 1000,
                        "uniqueItems": True,
                        "items": _TEXT,
                    },
                },
            },
        },
        "loops": {
            "type": "array",
            "minItems": 13,
            "maxItems": 13,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "loop_id",
                    "applicable",
                    "input_ref",
                    "operation",
                    "artifact_ref",
                    "gate_ref",
                    "iteration_limit",
                    "no_delta_iterations",
                    "repair_or_escalation",
                    "exit_condition",
                ],
                "properties": {
                    "loop_id": {"enum": list(_LOOP_IDS)},
                    "applicable": {"type": "boolean"},
                    "input_ref": _NULLABLE_TEXT,
                    "operation": _NULLABLE_TEXT,
                    "artifact_ref": _NULLABLE_TEXT,
                    "gate_ref": _NULLABLE_TEXT,
                    "iteration_limit": {"type": ["integer", "null"], "minimum": 1},
                    "no_delta_iterations": {"type": "integer", "minimum": 0},
                    "repair_or_escalation": _NULLABLE_TEXT,
                    "exit_condition": _NULLABLE_TEXT,
                },
            },
        },
        "gates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "gate_ref",
                    "status",
                    "evaluation_ref",
                    "waived_by",
                    "status_source_gate_ref",
                ],
                "properties": {
                    "gate_ref": _TEXT,
                    "status": {"enum": sorted(_GATE_STATUSES)},
                    "evaluation_ref": _TEXT,
                    "waived_by": _NULLABLE_TEXT,
                    "status_source_gate_ref": _NULLABLE_TEXT,
                },
            },
        },
        "required_artifact_types": {
            "type": "array",
            "minItems": 1,
            "maxItems": len(_DURABLE_ARTIFACT_TYPES),
            "uniqueItems": True,
            "items": {"enum": sorted(_DURABLE_ARTIFACT_TYPES)},
        },
        "durable_artifacts": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["artifact_type", "logical_ref", "file_ref"],
                "properties": {
                    "artifact_type": {"enum": sorted(_DURABLE_ARTIFACT_TYPES)},
                    "logical_ref": _TEXT,
                    "file_ref": _TEXT,
                },
            },
        },
    },
}

QUALITY_DASHBOARD_PROJECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "registries", "manual_override"],
    "properties": {
        "schema_version": {"const": 1},
        "registries": {
            "type": "object",
            "additionalProperties": False,
            "required": ["questions", "answers", "sources", "origin_clusters"],
            "properties": {
                "questions": {
                    "type": "array",
                    "maxItems": 10000,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["question_ref", "status"],
                        "properties": {"question_ref": _TEXT, "status": _TEXT},
                    },
                },
                "answers": {
                    "type": "array",
                    "maxItems": 10000,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["answer_ref", "question_ref", "status"],
                        "properties": {
                            "answer_ref": _TEXT,
                            "question_ref": _TEXT,
                            "status": _TEXT,
                        },
                    },
                },
                "sources": {
                    "type": "array",
                    "maxItems": 10000,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["source_ref", "status"],
                        "properties": {"source_ref": _TEXT, "status": _TEXT},
                    },
                },
                "origin_clusters": {
                    "type": "array",
                    "maxItems": 10000,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["cluster_ref", "source_refs"],
                        "properties": {
                            "cluster_ref": _TEXT,
                            "source_refs": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 10000,
                                "uniqueItems": True,
                                "items": _TEXT,
                            },
                        },
                    },
                },
            },
        },
        "manual_override": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "question_count",
                        "answer_count",
                        "source_count",
                        "origin_cluster_count",
                    ],
                    "properties": {
                        "question_count": {"type": "integer", "minimum": 0},
                        "answer_count": {"type": "integer", "minimum": 0},
                        "source_count": {"type": "integer", "minimum": 0},
                        "origin_cluster_count": {"type": "integer", "minimum": 0},
                    },
                },
            ]
        },
    },
}


def _schema(request: object, required: set[str]) -> dict[str, object]:
    data = require_mapping(request, "request")
    require_exact_keys(data, required, "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    return data


def _optional_text(value: object, path: str) -> str | None:
    if value is None:
        return None
    return require_string(value, path)


def _unique_texts(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_reference", path, "Повтор ссылки запрещён.")
    return result


def select_udr_architecture(request: object) -> dict[str, Any]:
    data = _schema(request, set(UDR_ARCHITECTURE_SELECT_SCHEMA["required"]))
    task_ref = require_string(data["task_ref"], "request.task_ref")
    scope = require_string(data["question_scope"], "request.question_scope")
    corpus = require_string(data["corpus_scale"], "request.corpus_scale")
    risk = require_string(data["risk"], "request.risk")
    dynamics = require_string(data["object_dynamics"], "request.object_dynamics")
    evidence = require_string(data["evidence_level"], "request.evidence_level")
    branches = require_int(data["branch_count"], "request.branch_count", minimum=1)
    modalities = _unique_texts(data["modalities"], "request.modalities")
    if not modalities:
        fail(
            "empty_modalities", "request.modalities", "Нужна хотя бы одна модальность."
        )
    model_selection_started = require_bool(
        data["model_or_tool_selection_started"],
        "request.model_or_tool_selection_started",
    )
    issues = (
        ["functional_topology_not_selected_first"] if model_selection_started else []
    )

    modes = ["traceable_core", "source_selection", "challenge"]
    reasons = [
        "trace_and_receipts_required",
        "source_selection_required",
        "challenge_required",
    ]
    if corpus == "large":
        modes.append("corpus")
        reasons.append("large_corpus")
    if risk == "high" or evidence in {"E4", "E5"}:
        modes.append("adversarial")
        reasons.append("high_risk_or_evidence_level")
    if dynamics in {"changing", "dynamic"}:
        modes.append("longitudinal")
        reasons.append("changing_object")
    if len(modalities) > 1:
        modes.append("multimodal")
        reasons.append("multiple_modalities")

    single_sufficient = (
        scope == "narrow"
        and corpus == "small"
        and risk == "low"
        and evidence in {"E0", "E1", "E2"}
        and dynamics == "static"
        and branches == 1
        and len(modalities) == 1
    )
    topology = "single_agent" if single_sufficient else "multi_agent"
    independent_roles_required = risk == "high" or evidence in {"E4", "E5"}
    roles = [
        "controller",
        "producer",
        "source_selector",
        "challenger",
        "trace_auditor",
        "acceptor",
    ]
    role_execution = "sequential" if topology == "single_agent" else "separated"
    independence_requirements = (
        [
            ["producer", "challenger"],
            ["producer", "trace_auditor"],
            ["producer", "acceptor"],
        ]
        if independent_roles_required
        else []
    )
    loop_refs = ["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L8", "L10", "L12"]
    if "corpus" in modes:
        loop_refs.append("L7")
    if "adversarial" in modes:
        loop_refs.append("L9")
    if "longitudinal" in modes:
        loop_refs.append("L11")
    selected = {
        "execution_modes": sorted(modes),
        "executor_topology": topology,
        "functional_roles": roles,
        "role_execution": role_execution,
        "independence_requirements": independence_requirements,
        "loop_refs": sorted(loop_refs, key=lambda item: int(item[1:])),
        "gate_classes": [
            "coverage",
            "trace",
            "source_selection",
            "challenge",
            "acceptance",
            "closure",
        ],
        "required_artifact_types": sorted(_DURABLE_ARTIFACT_TYPES),
        "model_assignments": [],
        "tool_assignments": [],
    }
    payload = {
        "schema_version": 1,
        "contract": "UdrArchitectureDecisionReceipt",
        "status": "architecture_selected" if not issues else "blocked",
        "task_ref": task_ref,
        "selected_architecture": selected if not issues else None,
        "selection_reasons": sorted(reasons),
        "minimality_basis": {
            "single_agent_sufficient": single_sufficient,
            "independent_roles_required": independent_roles_required,
            "added_modes": sorted(
                set(modes) - {"traceable_core", "source_selection", "challenge"}
            ),
        },
        "functional_roles_selected_before_models_and_tools": not model_selection_started,
        "execution_started": False,
        "persistence_applied": False,
        "issues": issues,
    }
    return with_receipt_hash(payload)


def assess_udr_plan(request: object) -> dict[str, Any]:
    data = _schema(request, set(UDR_PLAN_ASSESS_SCHEMA["required"]))
    architecture_ref = require_string(
        data["architecture_ref"], "request.architecture_ref"
    )
    blocking_paths: list[str] = []
    issues: list[str] = []
    packets: list[dict[str, Any]] = []
    packet_refs: set[str] = set()
    for index, raw in enumerate(require_list(data["packets"], "request.packets")):
        path = f"request.packets[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"packet_ref", "output_ref", "acceptor_role", "depends_on"}, path
        )
        packet_ref = require_string(row["packet_ref"], f"{path}.packet_ref")
        if packet_ref in packet_refs:
            fail("duplicate_packet", f"{path}.packet_ref", "Повтор пакета запрещён.")
        packet_refs.add(packet_ref)
        acceptor = _optional_text(row["acceptor_role"], f"{path}.acceptor_role")
        if acceptor is None:
            blocking_paths.append(f"{path}.acceptor_role")
            issues.append(f"acceptor_role_missing:{packet_ref}")
        packets.append(
            {
                "packet_ref": packet_ref,
                "output_ref": require_string(row["output_ref"], f"{path}.output_ref"),
                "acceptor_role": acceptor,
                "depends_on": _unique_texts(row["depends_on"], f"{path}.depends_on"),
            }
        )

    loop_decisions: list[dict[str, Any]] = []
    loop_ids: set[str] = set()
    loop_gate_refs: set[str] = set()
    for index, raw in enumerate(require_list(data["loops"], "request.loops")):
        path = f"request.loops[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "loop_id",
                "applicable",
                "input_ref",
                "operation",
                "artifact_ref",
                "gate_ref",
                "iteration_limit",
                "no_delta_iterations",
                "repair_or_escalation",
                "exit_condition",
            },
            path,
        )
        loop_id = require_string(row["loop_id"], f"{path}.loop_id")
        if loop_id not in _LOOP_IDS:
            fail("invalid_loop_id", f"{path}.loop_id", "Неизвестный цикл.")
        if loop_id in loop_ids:
            fail("duplicate_loop", f"{path}.loop_id", "Повтор цикла запрещён.")
        loop_ids.add(loop_id)
        applicable = require_bool(row["applicable"], f"{path}.applicable")
        input_ref = _optional_text(row["input_ref"], f"{path}.input_ref")
        operation = _optional_text(row["operation"], f"{path}.operation")
        artifact_ref = _optional_text(row["artifact_ref"], f"{path}.artifact_ref")
        gate_ref = _optional_text(row["gate_ref"], f"{path}.gate_ref")
        limit_value = row["iteration_limit"]
        limit = (
            None
            if limit_value is None
            else require_int(limit_value, f"{path}.iteration_limit", minimum=1)
        )
        no_delta = require_int(
            row["no_delta_iterations"], f"{path}.no_delta_iterations"
        )
        repair = _optional_text(
            row["repair_or_escalation"], f"{path}.repair_or_escalation"
        )
        exit_condition = _optional_text(row["exit_condition"], f"{path}.exit_condition")
        if applicable:
            required_values = {
                "input_ref": input_ref,
                "operation": operation,
                "artifact_ref": artifact_ref,
                "gate_ref": gate_ref,
                "iteration_limit": limit,
                "repair_or_escalation": repair,
                "exit_condition": exit_condition,
            }
            for field, value in required_values.items():
                if value is None:
                    blocking_paths.append(f"{path}.{field}")
                    issues.append(f"applicable_loop_field_missing:{loop_id}:{field}")
            if gate_ref:
                loop_gate_refs.add(gate_ref)
        stop_required = applicable and no_delta >= 2
        loop_decisions.append(
            {
                "loop_id": loop_id,
                "applicable": applicable,
                "iteration_limit": limit,
                "no_delta_iterations": no_delta,
                "continue_allowed": applicable
                and not stop_required
                and limit is not None,
                "stop_or_escalate_required": stop_required,
                "repair_or_escalation": repair,
                "exit_condition": exit_condition,
            }
        )
    for missing in sorted(set(_LOOP_IDS) - loop_ids, key=lambda item: int(item[1:])):
        blocking_paths.append("request.loops")
        issues.append(f"loop_missing:{missing}")

    gate_records: list[dict[str, Any]] = []
    gate_refs: set[str] = set()
    for index, raw in enumerate(require_list(data["gates"], "request.gates")):
        path = f"request.gates[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "gate_ref",
                "status",
                "evaluation_ref",
                "waived_by",
                "status_source_gate_ref",
            },
            path,
        )
        gate_ref = require_string(row["gate_ref"], f"{path}.gate_ref")
        if gate_ref in gate_refs:
            fail("duplicate_gate", f"{path}.gate_ref", "Повтор шлюза запрещён.")
        gate_refs.add(gate_ref)
        status = require_string(row["status"], f"{path}.status")
        if status not in _GATE_STATUSES:
            fail("invalid_gate_status", f"{path}.status", "Неизвестный статус шлюза.")
        evaluation_ref = require_string(row["evaluation_ref"], f"{path}.evaluation_ref")
        waived_by = _optional_text(row["waived_by"], f"{path}.waived_by")
        source_gate = _optional_text(
            row["status_source_gate_ref"], f"{path}.status_source_gate_ref"
        )
        if status == "waived" and waived_by is None:
            blocking_paths.append(f"{path}.waived_by")
            issues.append(f"waiver_authority_missing:{gate_ref}")
        if source_gate is not None and source_gate != gate_ref:
            blocking_paths.append(f"{path}.status_source_gate_ref")
            issues.append(f"gate_status_transferred:{gate_ref}")
        gate_records.append(
            {
                "gate_ref": gate_ref,
                "status": status,
                "evaluation_ref": evaluation_ref,
                "waived_by": waived_by,
                "status_inherited": source_gate is not None and source_gate != gate_ref,
            }
        )
    for missing in sorted(loop_gate_refs - gate_refs):
        blocking_paths.append("request.gates")
        issues.append(f"loop_gate_missing:{missing}")

    required_types = _unique_texts(
        data["required_artifact_types"], "request.required_artifact_types"
    )
    if not set(required_types) <= _DURABLE_ARTIFACT_TYPES:
        fail(
            "invalid_artifact_type",
            "request.required_artifact_types",
            "Неизвестный тип артефакта.",
        )
    artifact_records: list[dict[str, str]] = []
    artifact_types: set[str] = set()
    logical_refs: set[str] = set()
    for index, raw in enumerate(
        require_list(data["durable_artifacts"], "request.durable_artifacts")
    ):
        path = f"request.durable_artifacts[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"artifact_type", "logical_ref", "file_ref"}, path)
        artifact_type = require_string(row["artifact_type"], f"{path}.artifact_type")
        if artifact_type not in _DURABLE_ARTIFACT_TYPES:
            fail("invalid_artifact_type", f"{path}.artifact_type", "Неизвестный тип.")
        logical_ref = require_string(row["logical_ref"], f"{path}.logical_ref")
        if logical_ref in logical_refs:
            fail("duplicate_artifact", f"{path}.logical_ref", "Повтор артефакта.")
        logical_refs.add(logical_ref)
        artifact_types.add(artifact_type)
        artifact_records.append(
            {
                "artifact_type": artifact_type,
                "logical_ref": logical_ref,
                "file_ref": require_string(row["file_ref"], f"{path}.file_ref"),
            }
        )
    missing_types = sorted(set(required_types) - artifact_types)
    for artifact_type in missing_types:
        blocking_paths.append("request.durable_artifacts")
        issues.append(f"durable_artifact_missing:{artifact_type}")
    unique_issues = sorted(set(issues))
    payload = {
        "schema_version": 1,
        "contract": "UdrPlanDecisionReceipt",
        "status": "plan_ready" if not unique_issues else "blocked",
        "architecture_ref": architecture_ref,
        "packets": packets,
        "loop_decisions": sorted(
            loop_decisions, key=lambda item: int(str(item["loop_id"])[1:])
        ),
        "gate_records": sorted(gate_records, key=lambda item: str(item["gate_ref"])),
        "durable_artifacts": artifact_records,
        "missing_artifact_types": missing_types,
        "blocking_paths": sorted(set(blocking_paths)),
        "execution_started": False,
        "persistence_applied": False,
        "issues": unique_issues,
    }
    return with_receipt_hash(payload)


def project_quality_dashboard(request: object) -> dict[str, Any]:
    data = _schema(request, set(QUALITY_DASHBOARD_PROJECT_SCHEMA["required"]))
    registries = require_mapping(data["registries"], "request.registries")
    require_exact_keys(
        registries,
        {"questions", "answers", "sources", "origin_clusters"},
        "request.registries",
    )

    question_statuses: dict[str, str] = {}
    for index, raw in enumerate(
        require_list(registries["questions"], "request.registries.questions")
    ):
        path = f"request.registries.questions[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"question_ref", "status"}, path)
        ref = require_string(row["question_ref"], f"{path}.question_ref")
        if ref in question_statuses:
            fail("duplicate_question", f"{path}.question_ref", "Повтор вопроса.")
        question_statuses[ref] = require_string(row["status"], f"{path}.status")

    answer_statuses: dict[str, str] = {}
    answered_questions: set[str] = set()
    for index, raw in enumerate(
        require_list(registries["answers"], "request.registries.answers")
    ):
        path = f"request.registries.answers[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"answer_ref", "question_ref", "status"}, path)
        ref = require_string(row["answer_ref"], f"{path}.answer_ref")
        if ref in answer_statuses:
            fail("duplicate_answer", f"{path}.answer_ref", "Повтор ответа.")
        question_ref = require_string(row["question_ref"], f"{path}.question_ref")
        if question_ref not in question_statuses:
            fail("unknown_question", f"{path}.question_ref", "Неизвестный вопрос.")
        answer_statuses[ref] = require_string(row["status"], f"{path}.status")
        answered_questions.add(question_ref)

    source_statuses: dict[str, str] = {}
    for index, raw in enumerate(
        require_list(registries["sources"], "request.registries.sources")
    ):
        path = f"request.registries.sources[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"source_ref", "status"}, path)
        ref = require_string(row["source_ref"], f"{path}.source_ref")
        if ref in source_statuses:
            fail("duplicate_source", f"{path}.source_ref", "Повтор источника.")
        source_statuses[ref] = require_string(row["status"], f"{path}.status")

    cluster_refs: set[str] = set()
    for index, raw in enumerate(
        require_list(
            registries["origin_clusters"], "request.registries.origin_clusters"
        )
    ):
        path = f"request.registries.origin_clusters[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"cluster_ref", "source_refs"}, path)
        ref = require_string(row["cluster_ref"], f"{path}.cluster_ref")
        if ref in cluster_refs:
            fail("duplicate_cluster", f"{path}.cluster_ref", "Повтор кластера.")
        cluster_refs.add(ref)
        members = _unique_texts(row["source_refs"], f"{path}.source_refs")
        unknown = sorted(set(members) - set(source_statuses))
        if unknown:
            fail(
                "unknown_source",
                f"{path}.source_refs",
                f"Неизвестный источник: {unknown[0]}.",
            )

    computed = {
        "question_count": len(question_statuses),
        "answer_count": len(answer_statuses),
        "answered_question_count": len(answered_questions),
        "source_count": len(source_statuses),
        "origin_cluster_count": len(cluster_refs),
    }
    override = data["manual_override"]
    override_rejected = False
    if override is not None:
        manual = require_mapping(override, "request.manual_override")
        require_exact_keys(
            manual,
            {
                "question_count",
                "answer_count",
                "source_count",
                "origin_cluster_count",
            },
            "request.manual_override",
        )
        supplied = {
            key: require_int(manual[key], f"request.manual_override.{key}")
            for key in (
                "question_count",
                "answer_count",
                "source_count",
                "origin_cluster_count",
            )
        }
        override_rejected = any(supplied[key] != computed[key] for key in supplied)
    payload = {
        "schema_version": 1,
        "contract": "QualityDashboardProjectionReceipt",
        "status": "projected_with_rejected_override"
        if override_rejected
        else "projected",
        "computed_counts": computed,
        "manual_override_accepted": False,
        "manual_override_rejected": override_rejected,
        "question_statuses_changed": False,
        "answer_statuses_changed": False,
        "source_statuses_changed": False,
        "origin_clusters_changed": False,
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)
