"""Citation attribution, source influence, and material narrative-diff gates."""

from __future__ import annotations

import math
from typing import Any

from .canonical import sha256_json, with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_list,
    require_mapping,
    require_string,
)

_TEXT = {"type": "string", "minLength": 1}


def _closed_schema(required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": {
            "schema_version": {"const": 1},
            **{
                field: {"type": "object"}
                for field in required
                if field != "schema_version"
            },
        },
    }


ATTRIBUTION_ASSESS_SCHEMA = _closed_schema(
    ["schema_version", "claim", "citation", "generation", "verifier", "counterfactual"]
)
SOURCE_INFLUENCE_ASSESS_SCHEMA = _closed_schema(
    ["schema_version", "base_conclusions", "origins", "families", "leaveouts", "policy"]
)
for _field in ("base_conclusions", "origins", "families", "leaveouts"):
    SOURCE_INFLUENCE_ASSESS_SCHEMA["properties"][_field] = {
        "type": "array",
        "items": {"type": "object"}
        if _field in {"base_conclusions", "leaveouts"}
        else _TEXT,
    }
NARRATIVE_DIFF_ASSESS_SCHEMA = _closed_schema(["schema_version", "stages"])
NARRATIVE_DIFF_ASSESS_SCHEMA["properties"]["stages"] = {
    "type": "array",
    "minItems": 4,
    "maxItems": 4,
    "items": {"type": "object"},
}

_DECISIONS = {"verified", "not_verified", "failed"}


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


def _decision(value: object, path: str) -> str:
    text = require_string(value, path)
    if text not in _DECISIONS:
        fail("invalid_verification_status", path, "Неизвестен статус проверки.")
    return text


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
    minimum: float = 0,
    maximum: float = 1,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < minimum
        or value > maximum
    ):
        fail("invalid_number", path, "Число находится вне допустимого диапазона.")
    return float(value)


def assess_attribution(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "claim",
            "citation",
            "generation",
            "verifier",
            "counterfactual",
        },
        "request",
    )
    _version(data)
    claim = require_mapping(data["claim"], "request.claim")
    require_exact_keys(claim, {"claim_id", "truth_status"}, "request.claim")
    claim_id = require_string(claim["claim_id"], "request.claim.claim_id")
    truth_status = require_string(claim["truth_status"], "request.claim.truth_status")
    citation = require_mapping(data["citation"], "request.citation")
    require_exact_keys(
        citation,
        {
            "citation_id",
            "fragment_ref",
            "locator_accuracy",
            "semantic_support",
            "citation_correctness",
        },
        "request.citation",
    )
    locator = _decision(
        citation["locator_accuracy"], "request.citation.locator_accuracy"
    )
    support = _decision(
        citation["semantic_support"], "request.citation.semantic_support"
    )
    correctness = _decision(
        citation["citation_correctness"], "request.citation.citation_correctness"
    )
    generation = require_mapping(data["generation"], "request.generation")
    require_exact_keys(
        generation,
        {
            "generator_id",
            "context_hash",
            "claim_created_at",
            "citation_selected_at",
            "selection_phase",
        },
        "request.generation",
    )
    generator_context = _hash(
        generation["context_hash"], "request.generation.context_hash"
    )
    selection_phase = require_string(
        generation["selection_phase"], "request.generation.selection_phase"
    )
    if selection_phase not in {"during_generation", "post_hoc", "unknown"}:
        fail(
            "invalid_selection_phase",
            "request.generation.selection_phase",
            "Неизвестна фаза.",
        )
    citation_selected_at = _nullable(
        generation["citation_selected_at"], "request.generation.citation_selected_at"
    )
    verifier = require_mapping(data["verifier"], "request.verifier")
    require_exact_keys(
        verifier,
        {
            "verifier_id",
            "context_hash",
            "independent",
            "saw_generation",
            "verification_receipt_ref",
        },
        "request.verifier",
    )
    verifier_context = _hash(verifier["context_hash"], "request.verifier.context_hash")
    declared_independent = require_bool(
        verifier["independent"], "request.verifier.independent"
    )
    saw_generation = require_bool(
        verifier["saw_generation"], "request.verifier.saw_generation"
    )
    process_independent = (
        declared_independent
        and verifier_context != generator_context
        and not saw_generation
    )
    counterfactual = require_mapping(data["counterfactual"], "request.counterfactual")
    require_exact_keys(
        counterfactual,
        {
            "performed",
            "citation_removed",
            "output_changed",
            "dependency_status",
            "receipt_ref",
        },
        "request.counterfactual",
    )
    performed = require_bool(
        counterfactual["performed"], "request.counterfactual.performed"
    )
    citation_removed = require_bool(
        counterfactual["citation_removed"], "request.counterfactual.citation_removed"
    )
    output_changed = require_bool(
        counterfactual["output_changed"], "request.counterfactual.output_changed"
    )
    dependency_status = require_string(
        counterfactual["dependency_status"],
        "request.counterfactual.dependency_status",
    )
    if dependency_status not in {"dependent", "independent", "unknown"}:
        fail(
            "invalid_dependency_status",
            "request.counterfactual.dependency_status",
            "Неизвестен статус.",
        )
    counterfactual_ref = _nullable(
        counterfactual["receipt_ref"], "request.counterfactual.receipt_ref"
    )
    counterfactual_valid = (
        performed
        and citation_removed
        and counterfactual_ref is not None
        and dependency_status != "unknown"
        and ((dependency_status == "dependent") == output_changed)
    )
    if selection_phase == "post_hoc":
        faithfulness = "failed"
        faithfulness_reason = "citation_selected_post_hoc"
    elif selection_phase == "during_generation" and citation_selected_at is not None:
        if process_independent or counterfactual_valid:
            faithfulness = "verified"
            faithfulness_reason = (
                "independent_trace_verification"
                if process_independent
                else "counterfactual_verification"
            )
        else:
            faithfulness = "not_verified"
            faithfulness_reason = "independent_or_counterfactual_check_missing"
    else:
        faithfulness = "not_verified"
        faithfulness_reason = "selection_phase_unknown"
    causal_dependency = dependency_status if counterfactual_valid else "unknown"
    dimensions = {
        "locator_accuracy": locator,
        "semantic_support": support,
        "citation_correctness": correctness,
        "citation_faithfulness": faithfulness,
        "causal_dependency": causal_dependency,
        "claim_truth_status": truth_status,
    }
    review_required = any(
        value != "verified"
        for key, value in dimensions.items()
        if key
        in {
            "locator_accuracy",
            "semantic_support",
            "citation_correctness",
            "citation_faithfulness",
        }
    )
    return with_receipt_hash(
        {
            "contract": "AttributionAssessmentReceipt",
            "status": "verified" if not review_required else "review_required",
            "claim_id": claim_id,
            "citation_id": require_string(
                citation["citation_id"], "request.citation.citation_id"
            ),
            "fragment_ref": require_string(
                citation["fragment_ref"], "request.citation.fragment_ref"
            ),
            "dimensions": dimensions,
            "process_independent": process_independent,
            "counterfactual_valid": counterfactual_valid,
            "faithfulness_reason": faithfulness_reason,
            "support_changes_truth_status": False,
            "correctness_masks_faithfulness": False,
            "aggregate_boolean": None,
        }
    )


def assess_source_influence(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {
            "schema_version",
            "base_conclusions",
            "origins",
            "families",
            "leaveouts",
            "policy",
        },
        "request",
    )
    _version(data)
    conclusions = []
    conclusion_ids = set()
    for index, raw in enumerate(
        require_list(data["base_conclusions"], "request.base_conclusions")
    ):
        path = f"request.base_conclusions[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"claim_id", "conclusion_hash", "truth_status"}, path)
        claim_id = require_string(item["claim_id"], f"{path}.claim_id")
        if claim_id in conclusion_ids:
            fail("duplicate_claim", path, "Повтор вывода запрещён.")
        conclusion_ids.add(claim_id)
        conclusions.append(
            {
                "claim_id": claim_id,
                "conclusion_hash": _hash(
                    item["conclusion_hash"], f"{path}.conclusion_hash"
                ),
                "truth_status": require_string(
                    item["truth_status"], f"{path}.truth_status"
                ),
            }
        )
    origins = _strings(data["origins"], "request.origins")
    families = _strings(data["families"], "request.families")
    policy = require_mapping(data["policy"], "request.policy")
    require_exact_keys(policy, {"high_influence_threshold"}, "request.policy")
    threshold = _finite(
        policy["high_influence_threshold"],
        "request.policy.high_influence_threshold",
    )
    leaveouts = []
    covered = {"origin": set(), "family": set()}
    for index, raw in enumerate(require_list(data["leaveouts"], "request.leaveouts")):
        path = f"request.leaveouts[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "kind",
                "removed_id",
                "rerun_hash",
                "changed_claim_ids",
                "change_magnitude",
                "receipt_ref",
            },
            path,
        )
        kind = require_string(item["kind"], f"{path}.kind")
        if kind not in {"origin", "family"}:
            fail("invalid_leaveout_kind", f"{path}.kind", "Неизвестен вид исключения.")
        removed_id = require_string(item["removed_id"], f"{path}.removed_id")
        universe = origins if kind == "origin" else families
        if removed_id not in universe:
            fail(
                "unknown_leaveout_target",
                f"{path}.removed_id",
                "Исключаемый объект отсутствует.",
            )
        covered[kind].add(removed_id)
        changed = _strings(item["changed_claim_ids"], f"{path}.changed_claim_ids")
        unknown_claims = sorted(set(changed) - conclusion_ids)
        if unknown_claims:
            fail(
                "unknown_claim",
                f"{path}.changed_claim_ids",
                f"Неизвестен тезис: {unknown_claims[0]}.",
            )
        magnitude = _finite(item["change_magnitude"], f"{path}.change_magnitude")
        leaveouts.append(
            {
                "kind": kind,
                "removed_id": removed_id,
                "rerun_hash": _hash(item["rerun_hash"], f"{path}.rerun_hash"),
                "changed_claim_ids": changed,
                "change_magnitude": magnitude,
                "influence": "high" if magnitude >= threshold or changed else "low",
                "receipt_ref": require_string(
                    item["receipt_ref"], f"{path}.receipt_ref"
                ),
            }
        )
    missing_origins = sorted(set(origins) - covered["origin"])
    missing_families = sorted(set(families) - covered["family"])
    high = [
        {"kind": row["kind"], "removed_id": row["removed_id"]}
        for row in leaveouts
        if row["influence"] == "high"
    ]
    complete = not missing_origins and not missing_families
    return with_receipt_hash(
        {
            "contract": "SourceInfluenceAssessmentReceipt",
            "status": "assessed" if complete else "incomplete",
            "base_conclusions": conclusions,
            "leaveouts": leaveouts,
            "missing_origin_leaveouts": missing_origins,
            "missing_family_leaveouts": missing_families,
            "high_influence_sources": high,
            "monoculture_sensitive": bool(high),
            "support_status_changed": False,
            "truth_status_changed": False,
            "influence_is_truth": False,
        }
    )


def assess_narrative_diff(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "stages"}, "request")
    _version(data)
    expected_stages = ["plan", "draft", "edited", "release"]
    stages = []
    stage_maps: list[dict[str, dict[str, Any]]] = []
    for index, raw in enumerate(require_list(data["stages"], "request.stages")):
        path = f"request.stages[{index}]"
        stage = require_mapping(raw, path)
        require_exact_keys(stage, {"stage", "artifact_hash", "propositions"}, path)
        stage_name = require_string(stage["stage"], f"{path}.stage")
        if index >= len(expected_stages) or stage_name != expected_stages[index]:
            fail(
                "narrative_stage_order_invalid",
                f"{path}.stage",
                "Требуется plan→draft→edited→release.",
            )
        propositions = []
        proposition_map = {}
        for proposition_index, raw_proposition in enumerate(
            require_list(stage["propositions"], f"{path}.propositions")
        ):
            proposition_path = f"{path}.propositions[{proposition_index}]"
            proposition = require_mapping(raw_proposition, proposition_path)
            require_exact_keys(
                proposition,
                {
                    "proposition_id",
                    "text_hash",
                    "material",
                    "evidence_link_refs",
                    "verification_status",
                },
                proposition_path,
            )
            proposition_id = require_string(
                proposition["proposition_id"],
                f"{proposition_path}.proposition_id",
            )
            if proposition_id in proposition_map:
                fail(
                    "duplicate_proposition",
                    proposition_path,
                    "Повтор положения запрещён.",
                )
            record = {
                "proposition_id": proposition_id,
                "text_hash": _hash(
                    proposition["text_hash"], f"{proposition_path}.text_hash"
                ),
                "material": require_bool(
                    proposition["material"], f"{proposition_path}.material"
                ),
                "evidence_link_refs": _strings(
                    proposition["evidence_link_refs"],
                    f"{proposition_path}.evidence_link_refs",
                ),
                "verification_status": _decision(
                    proposition["verification_status"],
                    f"{proposition_path}.verification_status",
                ),
            }
            propositions.append(record)
            proposition_map[proposition_id] = record
        stage_record = {
            "stage": stage_name,
            "artifact_hash": _hash(stage["artifact_hash"], f"{path}.artifact_hash"),
            "propositions": propositions,
        }
        stages.append(stage_record)
        stage_maps.append(proposition_map)
    transitions = []
    blockers = []
    for index in range(1, len(stages)):
        prior = stage_maps[index - 1]
        current = stage_maps[index]
        added = sorted(set(current) - set(prior))
        removed = sorted(set(prior) - set(current))
        changed = sorted(
            proposition_id
            for proposition_id in set(prior) & set(current)
            if prior[proposition_id]["text_hash"]
            != current[proposition_id]["text_hash"]
        )
        material_deltas = [
            proposition_id
            for proposition_id in added + changed
            if current[proposition_id]["material"]
        ]
        unverified = [
            proposition_id
            for proposition_id in material_deltas
            if current[proposition_id]["verification_status"] != "verified"
            or not current[proposition_id]["evidence_link_refs"]
        ]
        blockers.extend(f"{stages[index]['stage']}:{item}" for item in unverified)
        transitions.append(
            {
                "from_stage": stages[index - 1]["stage"],
                "to_stage": stages[index]["stage"],
                "added_ids": added,
                "changed_ids": changed,
                "removed_ids": removed,
                "material_delta_ids": material_deltas,
                "unverified_material_delta_ids": unverified,
            }
        )
    return with_receipt_hash(
        {
            "contract": "NarrativeDiffDecisionReceipt",
            "status": "release_allowed" if not blockers else "release_blocked",
            "stages": stages,
            "transitions": transitions,
            "blocking_proposition_refs": blockers,
            "release_allowed": not blockers,
            "new_or_changed_material_requires_verification": True,
            "external_action_performed": False,
            "stage_set_hash": sha256_json(stages),
        }
    )
