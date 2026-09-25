"""Independent review, result acceptance, release, and correction gates."""

from __future__ import annotations

import re
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

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_TEXT = {"type": "string", "minLength": 1}
_NULLABLE_TEXT = {"type": ["string", "null"]}
_STRING_ARRAY = {
    "type": "array",
    "maxItems": 1000,
    "uniqueItems": True,
    "items": _TEXT,
}
_OBJECT_REF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "revision", "content_hash", "scope"],
    "properties": {
        "id": _TEXT,
        "revision": {"type": "integer", "minimum": 1},
        "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "scope": _TEXT,
    },
}
REVIEW_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "artifact_ref",
        "requirement",
        "reviewer",
        "aspect_results",
        "reviewed_at",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "artifact_ref": _OBJECT_REF_SCHEMA,
        "requirement": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "required",
                "reviewer_role",
                "required_aspects",
                "criteria_version",
            ],
            "properties": {
                "required": {"type": "boolean"},
                "reviewer_role": _TEXT,
                "required_aspects": _STRING_ARRAY,
                "criteria_version": _TEXT,
            },
        },
        "reviewer": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "author_id",
                "assigned_id",
                "actual_id",
                "available",
                "admissible",
                "independence_basis",
            ],
            "properties": {
                "author_id": _TEXT,
                "assigned_id": _TEXT,
                "actual_id": _NULLABLE_TEXT,
                "available": {"type": "boolean"},
                "admissible": {"type": "boolean"},
                "independence_basis": _NULLABLE_TEXT,
            },
        },
        "aspect_results": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["aspect", "status", "finding_refs"],
                "properties": {
                    "aspect": _TEXT,
                    "status": {"enum": ["pass", "fail", "unable"]},
                    "finding_refs": _STRING_ARRAY,
                },
            },
        },
        "reviewed_at": _NULLABLE_TEXT,
    },
}

ACCEPTANCE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "result_ref",
        "execution_status",
        "claims",
        "original_obligations",
        "obligation_receipts",
        "required_review_count",
        "reviews",
        "acceptor",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "result_ref": _OBJECT_REF_SCHEMA,
        "execution_status": {"enum": ["planned", "running", "succeeded", "failed"]},
        "claims": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim_ref", "status", "central", "current"],
                "properties": {
                    "claim_ref": _TEXT,
                    "status": {
                        "enum": [
                            "unresolved",
                            "supported",
                            "qualified",
                            "contradicted",
                            "withdrawn",
                        ]
                    },
                    "central": {"type": "boolean"},
                    "current": {"type": "boolean"},
                },
            },
        },
        "original_obligations": _STRING_ARRAY,
        "obligation_receipts": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["obligation", "status", "current", "receipt_ref"],
                "properties": {
                    "obligation": _TEXT,
                    "status": {"enum": ["pass", "partial", "fail", "not_run"]},
                    "current": {"type": "boolean"},
                    "receipt_ref": _TEXT,
                },
            },
        },
        "required_review_count": {"type": "integer", "minimum": 0},
        "reviews": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "review_ref",
                    "artifact_id",
                    "artifact_revision",
                    "artifact_hash",
                    "scope",
                    "decision",
                    "current",
                ],
                "properties": {
                    "review_ref": _TEXT,
                    "artifact_id": _TEXT,
                    "artifact_revision": {"type": "integer", "minimum": 1},
                    "artifact_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "scope": _TEXT,
                    "decision": {
                        "enum": [
                            "accepted",
                            "changes_required",
                            "rejected",
                            "unable_to_review",
                        ]
                    },
                    "current": {"type": "boolean"},
                },
            },
        },
        "acceptor": {
            "type": "object",
            "additionalProperties": False,
            "required": ["acceptor_id", "role", "authorized"],
            "properties": {
                "acceptor_id": _TEXT,
                "role": _TEXT,
                "authorized": {"type": "boolean"},
            },
        },
    },
}

RELEASE_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "artifact",
        "acceptance",
        "required_review_refs",
        "current_review_refs",
        "delivery",
        "policy",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "artifact": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "id",
                "revision",
                "scope",
                "accepted_content_hash",
                "current_bytes_hash",
                "format",
                "archived",
                "previewed",
            ],
            "properties": {
                "id": _TEXT,
                "revision": {"type": "integer", "minimum": 1},
                "scope": _TEXT,
                "accepted_content_hash": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "current_bytes_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "format": _TEXT,
                "archived": {"type": "boolean"},
                "previewed": {"type": "boolean"},
            },
        },
        "acceptance": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "decision_ref",
                "status",
                "artifact_id",
                "artifact_revision",
                "artifact_hash",
                "scope",
                "current",
            ],
            "properties": {
                "decision_ref": _TEXT,
                "status": {
                    "enum": [
                        "accepted_for_scope",
                        "partial",
                        "review_required",
                        "blocked",
                    ]
                },
                "artifact_id": _TEXT,
                "artifact_revision": {"type": "integer", "minimum": 1},
                "artifact_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "scope": _TEXT,
                "current": {"type": "boolean"},
            },
        },
        "required_review_refs": _STRING_ARRAY,
        "current_review_refs": _STRING_ARRAY,
        "delivery": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "recipient",
                "planned_recipient",
                "data_class",
                "allowed_data_classes",
            ],
            "properties": {
                "recipient": _TEXT,
                "planned_recipient": _TEXT,
                "data_class": _TEXT,
                "allowed_data_classes": _STRING_ARRAY,
            },
        },
        "policy": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "delivery_allowed",
                "required_acceptor_role",
                "actual_acceptor_role",
            ],
            "properties": {
                "delivery_allowed": {"type": "boolean"},
                "required_acceptor_role": _TEXT,
                "actual_acceptor_role": _TEXT,
            },
        },
    },
}

CORRECTION_ASSESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "prior_release",
        "error",
        "correction",
        "notification_plan",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "run_id": _TEXT,
        "prior_release": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "release_ref",
                "decision",
                "artifact_id",
                "artifact_revision",
                "artifact_hash",
            ],
            "properties": {
                "release_ref": _TEXT,
                "decision": {"enum": ["approved", "denied", "not_requested"]},
                "artifact_id": _TEXT,
                "artifact_revision": {"type": "integer", "minimum": 1},
                "artifact_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
        },
        "error": {
            "type": "object",
            "additionalProperties": False,
            "required": ["error_id", "material", "description", "affected_claim_refs"],
            "properties": {
                "error_id": _TEXT,
                "material": {"type": "boolean"},
                "description": _TEXT,
                "affected_claim_refs": _STRING_ARRAY,
            },
        },
        "correction": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "artifact_id",
                "revision",
                "content_hash",
                "supersedes_release_ref",
                "review_refs",
            ],
            "properties": {
                "artifact_id": _TEXT,
                "revision": {"type": "integer", "minimum": 1},
                "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "supersedes_release_ref": _TEXT,
                "review_refs": _STRING_ARRAY,
            },
        },
        "notification_plan": {
            "type": "object",
            "additionalProperties": False,
            "required": ["recipient_refs", "recall_required"],
            "properties": {
                "recipient_refs": _STRING_ARRAY,
                "recall_required": {"type": "boolean"},
            },
        },
    },
}


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def _strings(value: object, path: str, *, maximum: int = 1000) -> list[str]:
    rows = require_list(value, path)
    if len(rows) > maximum:
        fail("size_limit", path, "Массив превышает предел.")
    result = [
        require_string(item, f"{path}[{index}]") for index, item in enumerate(rows)
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повторный элемент запрещён.")
    return result


def _object_ref(value: object, path: str) -> dict[str, Any]:
    row = require_mapping(value, path)
    require_exact_keys(row, {"id", "revision", "content_hash", "scope"}, path)
    return {
        "id": require_string(row["id"], f"{path}.id"),
        "revision": require_int(row["revision"], f"{path}.revision", minimum=1),
        "content_hash": _hash(row["content_hash"], f"{path}.content_hash"),
        "scope": require_string(row["scope"], f"{path}.scope"),
    }


def assess_review(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(REVIEW_ASSESS_SCHEMA["required"]), "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    artifact = _object_ref(data["artifact_ref"], "request.artifact_ref")
    requirement = require_mapping(data["requirement"], "request.requirement")
    require_exact_keys(
        requirement,
        {"required", "reviewer_role", "required_aspects", "criteria_version"},
        "request.requirement",
    )
    review_required = require_bool(
        requirement["required"], "request.requirement.required"
    )
    required_aspects = _strings(
        requirement["required_aspects"],
        "request.requirement.required_aspects",
        maximum=100,
    )
    reviewer = require_mapping(data["reviewer"], "request.reviewer")
    require_exact_keys(
        reviewer,
        {
            "author_id",
            "assigned_id",
            "actual_id",
            "available",
            "admissible",
            "independence_basis",
        },
        "request.reviewer",
    )
    author_id = require_string(reviewer["author_id"], "request.reviewer.author_id")
    assigned_id = require_string(
        reviewer["assigned_id"], "request.reviewer.assigned_id"
    )
    actual_id = reviewer["actual_id"]
    if actual_id is not None:
        actual_id = require_string(actual_id, "request.reviewer.actual_id")
    available = require_bool(reviewer["available"], "request.reviewer.available")
    admissible = require_bool(reviewer["admissible"], "request.reviewer.admissible")
    independence = reviewer["independence_basis"]
    if independence is not None:
        independence = require_string(
            independence, "request.reviewer.independence_basis"
        )
    reviewed_at = data["reviewed_at"]
    if reviewed_at is not None:
        reviewed_at = require_string(reviewed_at, "request.reviewed_at")
    if not available:
        payload = {
            "schema_version": 1,
            "contract": "ReviewDecisionReceipt",
            "status": "review_required" if review_required else "review_not_required",
            "run_id": run_id,
            "artifact_ref": artifact,
            "review_receipt": None,
            "empty_receipt_created": False,
            "result_status_ceiling": "review_required" if review_required else "draft",
            "persistence_applied": False,
        }
        return with_receipt_hash(payload)
    blockers: list[str] = []
    if actual_id is None:
        blockers.append("actual_reviewer_missing")
    if not admissible:
        blockers.append("reviewer_not_admissible")
    if actual_id == author_id:
        blockers.append("reviewer_not_independent")
    if not independence:
        blockers.append("independence_basis_missing")
    aspect_rows = require_list(data["aspect_results"], "request.aspect_results")
    aspects: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(aspect_rows):
        path = f"request.aspect_results[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"aspect", "status", "finding_refs"}, path)
        aspect = require_string(row["aspect"], f"{path}.aspect")
        if aspect in aspects:
            fail(
                "duplicate_review_aspect",
                f"{path}.aspect",
                "Повторный аспект проверки.",
            )
        status = require_string(row["status"], f"{path}.status")
        if status not in {"pass", "fail", "unable"}:
            fail("invalid_review_status", f"{path}.status", "Неверный статус аспекта.")
        aspects[aspect] = {
            "status": status,
            "finding_refs": _strings(row["finding_refs"], f"{path}.finding_refs"),
        }
    if set(aspects) != set(required_aspects):
        blockers.append("required_review_aspects_incomplete")
    if reviewed_at is None:
        blockers.append("reviewed_at_missing")
    if blockers:
        decision = "unable_to_review"
    elif any(row["status"] == "fail" for row in aspects.values()):
        decision = "changes_required"
    elif any(row["status"] == "unable" for row in aspects.values()):
        decision = "unable_to_review"
    else:
        decision = "accepted"
    review_body: dict[str, Any] = {
        "schema_version": 1,
        "contract": "ReviewReceipt",
        "artifact_ref": artifact,
        "assigned_reviewer": assigned_id,
        "actual_reviewer": actual_id,
        "reviewer_role": require_string(
            requirement["reviewer_role"], "request.requirement.reviewer_role"
        ),
        "independence_basis": independence,
        "criteria_version": require_string(
            requirement["criteria_version"], "request.requirement.criteria_version"
        ),
        "reviewed_at": reviewed_at,
        "aspects": [{"aspect": key, **aspects[key]} for key in sorted(aspects)],
        "decision": decision,
    }
    nested_receipt = with_receipt_hash(review_body) if not blockers else None
    payload = {
        "schema_version": 1,
        "contract": "ReviewDecisionReceipt",
        "status": "reviewed" if nested_receipt else "blocked",
        "run_id": run_id,
        "artifact_ref": artifact,
        "review_receipt": nested_receipt,
        "empty_receipt_created": False,
        "result_status_ceiling": "accepted_for_scope"
        if decision == "accepted"
        else "review_required",
        "blocking_issues": sorted(set(blockers)),
        "persistence_applied": False,
    }
    return with_receipt_hash(payload)


def assess_acceptance(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(ACCEPTANCE_ASSESS_SCHEMA["required"]), "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    result_ref = _object_ref(data["result_ref"], "request.result_ref")
    execution = require_string(data["execution_status"], "request.execution_status")
    if execution not in {"planned", "running", "succeeded", "failed"}:
        fail(
            "invalid_execution_status",
            "request.execution_status",
            "Неверный статус исполнения.",
        )
    issues: list[str] = []
    if execution != "succeeded":
        issues.append("execution_not_succeeded")
    claim_rows = require_list(data["claims"], "request.claims")
    central_claims = 0
    for index, raw in enumerate(claim_rows):
        path = f"request.claims[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"claim_ref", "status", "central", "current"}, path)
        require_string(row["claim_ref"], f"{path}.claim_ref")
        status = require_string(row["status"], f"{path}.status")
        central = require_bool(row["central"], f"{path}.central")
        current = require_bool(row["current"], f"{path}.current")
        if central:
            central_claims += 1
            if not current or status not in {"supported", "qualified"}:
                issues.append("central_claim_not_ready")
    if not central_claims:
        issues.append("central_claim_missing")
    obligations = _strings(data["original_obligations"], "request.original_obligations")
    receipt_rows = require_list(
        data["obligation_receipts"], "request.obligation_receipts"
    )
    receipts: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(receipt_rows):
        path = f"request.obligation_receipts[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"obligation", "status", "current", "receipt_ref"}, path
        )
        obligation = require_string(row["obligation"], f"{path}.obligation")
        if obligation in receipts:
            fail(
                "duplicate_obligation_receipt",
                f"{path}.obligation",
                "Повторная квитанция обязательства.",
            )
        status = require_string(row["status"], f"{path}.status")
        if status not in {"pass", "partial", "fail", "not_run"}:
            fail(
                "invalid_obligation_status",
                f"{path}.status",
                "Неверный статус обязательства.",
            )
        receipts[obligation] = {
            "status": status,
            "current": require_bool(row["current"], f"{path}.current"),
            "receipt_ref": require_string(row["receipt_ref"], f"{path}.receipt_ref"),
        }
    missing_obligations = sorted(
        obligation
        for obligation in obligations
        if obligation not in receipts
        or receipts[obligation]["status"] != "pass"
        or not receipts[obligation]["current"]
    )
    if set(receipts) - set(obligations):
        fail(
            "unknown_obligation_receipt",
            "request.obligation_receipts",
            "Квитанция не относится к исходному профилю.",
        )
    if missing_obligations:
        issues.append("original_obligations_incomplete")
    required_review_count = require_int(
        data["required_review_count"], "request.required_review_count"
    )
    review_rows = require_list(data["reviews"], "request.reviews")
    valid_reviews = 0
    review_refs: list[str] = []
    for index, raw in enumerate(review_rows):
        path = f"request.reviews[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "review_ref",
                "artifact_id",
                "artifact_revision",
                "artifact_hash",
                "scope",
                "decision",
                "current",
            },
            path,
        )
        review_refs.append(require_string(row["review_ref"], f"{path}.review_ref"))
        exact = (
            row["artifact_id"] == result_ref["id"]
            and row["artifact_revision"] == result_ref["revision"]
            and row["artifact_hash"] == result_ref["content_hash"]
            and row["scope"] == result_ref["scope"]
        )
        decision = require_string(row["decision"], f"{path}.decision")
        current = require_bool(row["current"], f"{path}.current")
        if exact and current and decision == "accepted":
            valid_reviews += 1
    if len(review_refs) != len(set(review_refs)):
        fail("duplicate_review_ref", "request.reviews", "Повторная рецензия.")
    if valid_reviews < required_review_count:
        issues.append("required_reviews_incomplete")
    acceptor = require_mapping(data["acceptor"], "request.acceptor")
    require_exact_keys(
        acceptor, {"acceptor_id", "role", "authorized"}, "request.acceptor"
    )
    acceptor_id = require_string(
        acceptor["acceptor_id"], "request.acceptor.acceptor_id"
    )
    acceptor_role = require_string(acceptor["role"], "request.acceptor.role")
    if not require_bool(acceptor["authorized"], "request.acceptor.authorized"):
        issues.append("acceptor_not_authorized")
    issues = sorted(set(issues))
    if not issues:
        result_status = "accepted_for_scope"
    elif "required_reviews_incomplete" in issues:
        result_status = "review_required"
    elif execution == "succeeded":
        result_status = "partial"
    else:
        result_status = "blocked"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "AcceptanceDecisionReceipt",
        "status": result_status,
        "run_id": run_id,
        "result_ref": result_ref,
        "execution_status": execution,
        "claim_status_summary": "ready"
        if "central_claim_not_ready" not in issues
        else "not_ready",
        "result_status": result_status,
        "release_decision": "not_requested",
        "original_obligations": obligations,
        "missing_obligations": missing_obligations,
        "valid_review_refs": review_refs[:valid_reviews],
        "acceptor": {"id": acceptor_id, "role": acceptor_role},
        "persistence_applied": False,
        "issues": issues,
    }
    return with_receipt_hash(payload)


def assess_release(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(RELEASE_ASSESS_SCHEMA["required"]), "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    artifact = require_mapping(data["artifact"], "request.artifact")
    require_exact_keys(
        artifact,
        set(RELEASE_ASSESS_SCHEMA["properties"]["artifact"]["required"]),
        "request.artifact",
    )
    artifact_id = require_string(artifact["id"], "request.artifact.id")
    revision = require_int(artifact["revision"], "request.artifact.revision", minimum=1)
    scope = require_string(artifact["scope"], "request.artifact.scope")
    accepted_hash = _hash(
        artifact["accepted_content_hash"], "request.artifact.accepted_content_hash"
    )
    current_hash = _hash(
        artifact["current_bytes_hash"], "request.artifact.current_bytes_hash"
    )
    artifact_format = require_string(artifact["format"], "request.artifact.format")
    archived = require_bool(artifact["archived"], "request.artifact.archived")
    previewed = require_bool(artifact["previewed"], "request.artifact.previewed")
    acceptance = require_mapping(data["acceptance"], "request.acceptance")
    require_exact_keys(
        acceptance,
        set(RELEASE_ASSESS_SCHEMA["properties"]["acceptance"]["required"]),
        "request.acceptance",
    )
    issues: list[str] = []
    if acceptance["status"] != "accepted_for_scope" or not require_bool(
        acceptance["current"], "request.acceptance.current"
    ):
        issues.append("acceptance_not_current_or_accepted")
    if not (
        acceptance["artifact_id"] == artifact_id
        and acceptance["artifact_revision"] == revision
        and acceptance["artifact_hash"] == accepted_hash
        and acceptance["scope"] == scope
    ):
        issues.append("acceptance_artifact_mismatch")
    if current_hash != accepted_hash:
        issues.append("artifact_changed_after_acceptance")
    required_reviews = set(
        _strings(data["required_review_refs"], "request.required_review_refs")
    )
    current_reviews = set(
        _strings(data["current_review_refs"], "request.current_review_refs")
    )
    if not required_reviews.issubset(current_reviews):
        issues.append("required_reviews_not_current")
    delivery = require_mapping(data["delivery"], "request.delivery")
    require_exact_keys(
        delivery,
        {"recipient", "planned_recipient", "data_class", "allowed_data_classes"},
        "request.delivery",
    )
    recipient = require_string(delivery["recipient"], "request.delivery.recipient")
    planned_recipient = require_string(
        delivery["planned_recipient"], "request.delivery.planned_recipient"
    )
    data_class = require_string(delivery["data_class"], "request.delivery.data_class")
    allowed_classes = _strings(
        delivery["allowed_data_classes"], "request.delivery.allowed_data_classes"
    )
    if recipient != planned_recipient:
        issues.append("recipient_mismatch")
    if data_class not in allowed_classes:
        issues.append("data_class_not_allowed")
    policy = require_mapping(data["policy"], "request.policy")
    require_exact_keys(
        policy,
        {"delivery_allowed", "required_acceptor_role", "actual_acceptor_role"},
        "request.policy",
    )
    if not require_bool(policy["delivery_allowed"], "request.policy.delivery_allowed"):
        issues.append("delivery_policy_denied")
    required_role = require_string(
        policy["required_acceptor_role"], "request.policy.required_acceptor_role"
    )
    actual_role = require_string(
        policy["actual_acceptor_role"], "request.policy.actual_acceptor_role"
    )
    if actual_role != required_role:
        issues.append("acceptor_role_mismatch")
    issues = sorted(set(issues))
    decision = "approved" if not issues else "denied"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "ReleaseDecisionReceipt",
        "status": "release_ready" if decision == "approved" else "blocked",
        "run_id": run_id,
        "decision": decision,
        "artifact_ref": {
            "id": artifact_id,
            "revision": revision,
            "content_hash": current_hash,
            "scope": scope,
            "format": artifact_format,
        },
        "acceptance_ref": require_string(
            acceptance["decision_ref"], "request.acceptance.decision_ref"
        ),
        "review_refs": sorted(current_reviews),
        "recipient": recipient,
        "data_class": data_class,
        "archived": archived,
        "previewed": previewed,
        "archive_or_preview_changed_release": False,
        "transmission_performed": False,
        "persistence_applied": False,
        "issues": issues,
    }
    return with_receipt_hash(payload)


def assess_correction(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, set(CORRECTION_ASSESS_SCHEMA["required"]), "request")
    if data["schema_version"] != 1:
        fail(
            "unsupported_schema",
            "request.schema_version",
            "Поддерживается только schema_version=1.",
        )
    run_id = require_string(data["run_id"], "request.run_id")
    prior = require_mapping(data["prior_release"], "request.prior_release")
    require_exact_keys(
        prior,
        set(CORRECTION_ASSESS_SCHEMA["properties"]["prior_release"]["required"]),
        "request.prior_release",
    )
    prior_ref = require_string(
        prior["release_ref"], "request.prior_release.release_ref"
    )
    prior_decision = require_string(prior["decision"], "request.prior_release.decision")
    _hash(prior["artifact_hash"], "request.prior_release.artifact_hash")
    error = require_mapping(data["error"], "request.error")
    require_exact_keys(
        error,
        {"error_id", "material", "description", "affected_claim_refs"},
        "request.error",
    )
    material = require_bool(error["material"], "request.error.material")
    correction = require_mapping(data["correction"], "request.correction")
    require_exact_keys(
        correction,
        {
            "artifact_id",
            "revision",
            "content_hash",
            "supersedes_release_ref",
            "review_refs",
        },
        "request.correction",
    )
    correction_hash = _hash(
        correction["content_hash"], "request.correction.content_hash"
    )
    review_refs = _strings(correction["review_refs"], "request.correction.review_refs")
    notification = require_mapping(
        data["notification_plan"], "request.notification_plan"
    )
    require_exact_keys(
        notification, {"recipient_refs", "recall_required"}, "request.notification_plan"
    )
    recipients = _strings(
        notification["recipient_refs"], "request.notification_plan.recipient_refs"
    )
    recall_required = require_bool(
        notification["recall_required"], "request.notification_plan.recall_required"
    )
    issues: list[str] = []
    if material and prior_decision != "approved":
        issues.append("no_approved_release_to_correct")
    if correction["supersedes_release_ref"] != prior_ref:
        issues.append("correction_supersedes_mismatch")
    if material and not review_refs:
        issues.append("correction_review_missing")
    if material and not recipients:
        issues.append("affected_recipients_missing")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "CorrectionDecisionReceipt",
        "status": "correction_required"
        if material and not issues
        else ("no_material_correction" if not material else "blocked"),
        "run_id": run_id,
        "prior_release_ref": prior_ref,
        "prior_release_revocation_proposed": material and not issues,
        "error_id": require_string(error["error_id"], "request.error.error_id"),
        "affected_claim_refs": _strings(
            error["affected_claim_refs"], "request.error.affected_claim_refs"
        ),
        "correction_artifact_ref": {
            "id": require_string(
                correction["artifact_id"], "request.correction.artifact_id"
            ),
            "revision": require_int(
                correction["revision"], "request.correction.revision", minimum=1
            ),
            "content_hash": correction_hash,
        },
        "review_refs": review_refs,
        "recipient_refs": recipients,
        "recall_required": recall_required,
        "notification_performed": False,
        "recall_performed": False,
        "release_performed": False,
        "persistence_applied": False,
        "issues": sorted(set(issues)),
    }
    return with_receipt_hash(payload)
