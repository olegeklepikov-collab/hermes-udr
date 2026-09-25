"""Runtime security controls evaluated at concrete action boundaries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
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
_CONTROL_TYPES = {
    "source_use",
    "primary_review",
    "untrusted_instruction",
    "role_boundary",
    "approval_scope",
    "project_scope",
    "secret_redaction",
    "field_minimization",
    "budget_reservation",
    "target_scope",
    "outbound_integrity",
    "audit_boundary",
    "primary_action_boundary",
}

SECURITY_CONTROL_ASSESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "control_type", "payload"],
    "properties": {
        "schema_version": {"const": 1},
        "control_type": {"enum": sorted(_CONTROL_TYPES)},
        "payload": {"type": "object"},
    },
}


_NEW_CONTROL_PAYLOAD_SCHEMAS = {
    "primary_review": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "task_id",
            "generator_ref",
            "reviewer_ref",
            "review_input",
            "materials",
            "judgments",
        ],
        "properties": {
            "task_id": {"type": "string", "minLength": 1},
            "generator_ref": {"type": "string", "minLength": 1},
            "reviewer_ref": {"type": "string", "minLength": 1},
            "review_input": {"type": "string", "minLength": 1},
            "materials": {
                "type": "array",
                "maxItems": 10000,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_ref", "source_author_ref", "text", "sha256"],
                    "properties": {
                        "source_ref": {"type": "string", "minLength": 1},
                        "source_author_ref": {"type": "string", "minLength": 1},
                        "text": {"type": "string", "minLength": 1},
                        "sha256": {"type": "string", "minLength": 1},
                    },
                },
            },
            "judgments": {
                "type": "array",
                "maxItems": 10000,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "claim_id",
                        "claim",
                        "source_ref",
                        "start",
                        "end",
                        "quote",
                        "verdict",
                        "rationale",
                        "disagreement",
                    ],
                    "properties": {
                        "claim_id": {"type": "string", "minLength": 1},
                        "claim": {"type": "string", "minLength": 1},
                        "source_ref": {"type": "string", "minLength": 1},
                        "start": {"type": "integer", "minimum": 0},
                        "end": {"type": "integer", "minimum": 0},
                        "quote": {"type": "string", "minLength": 1},
                        "verdict": {
                            "enum": ["supported", "contradicted", "unresolved"]
                        },
                        "rationale": {"type": "string", "minLength": 1},
                        "disagreement": {"type": ["string", "null"]},
                    },
                },
            },
        },
    },
    "source_use": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_ref",
            "source_text",
            "operation",
            "rights",
            "now",
            "quote_start",
            "quote_end",
            "attribution",
        ],
        "properties": {
            "source_ref": {"type": "string", "minLength": 1},
            "source_text": {"type": "string", "minLength": 1},
            "operation": {"enum": ["quote", "export_fulltext", "embed"]},
            "rights": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "quote",
                    "export_fulltext",
                    "embed",
                    "max_quote_chars",
                    "expires_at",
                    "right_ref",
                    "restriction",
                ],
                "properties": {
                    "quote": {"enum": ["allowed", "denied", "unknown"]},
                    "export_fulltext": {"enum": ["allowed", "denied", "unknown"]},
                    "embed": {"enum": ["allowed", "denied", "unknown"]},
                    "max_quote_chars": {"type": "integer", "minimum": 0},
                    "expires_at": {"type": "string", "minLength": 1},
                    "right_ref": {"type": "string", "minLength": 1},
                    "restriction": {"type": "string", "minLength": 1},
                },
            },
            "now": {"type": "string", "minLength": 1},
            "quote_start": {"type": "integer", "minimum": 0},
            "quote_end": {"type": "integer", "minimum": 0},
            "attribution": {"type": "string", "minLength": 1},
        },
    },
}
SECURITY_CONTROL_ASSESS_SCHEMA["allOf"] = [
    {
        "if": {"properties": {"control_type": {"const": name}}},
        "then": {"properties": {"payload": definition}},
    }
    for name, definition in _NEW_CONTROL_PAYLOAD_SCHEMAS.items()
]


def _nullable(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def _strings(value: object, path: str) -> list[str]:
    rows = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(rows) != len(set(rows)):
        fail("duplicate_item", path, "Повтор элемента запрещён.")
    return rows


def _time(value: object, path: str) -> datetime:
    text = require_string(value, path)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        fail("invalid_time", path, "Ожидалось время ISO-8601.")


def _untrusted(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "trust_class",
        "source_fact",
        "proposed_action_kind",
        "capability_allowed",
        "observed_external_call_count",
    }
    require_exact_keys(payload, keys, "request.payload")
    trust = require_string(payload["trust_class"], "request.payload.trust_class")
    action = require_string(
        payload["proposed_action_kind"], "request.payload.proposed_action_kind"
    )
    allowed = require_bool(
        payload["capability_allowed"], "request.payload.capability_allowed"
    )
    calls = require_int(
        payload["observed_external_call_count"],
        "request.payload.observed_external_call_count",
    )
    denied = trust == "untrusted_source" and not allowed
    issues = []
    if denied and calls:
        issues.append("untrusted_instruction_executed")
    return {
        "source_fact": require_string(
            payload["source_fact"], "request.payload.source_fact"
        ),
        "trust_class": trust,
        "trust_class_raised": False,
        "proposed_action_kind": action,
        "decision": "deny" if denied else "allow",
        "observed_external_call_count": calls,
        "policy_unchanged": True,
        "fact_retained_for_analysis": True,
        "issues": issues,
    }


def _role(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "authenticated_role",
        "prompt_claimed_role",
        "action_kind",
        "allowed_roles",
        "observed_mutation_count",
    }
    require_exact_keys(payload, keys, "request.payload")
    authenticated = require_string(
        payload["authenticated_role"], "request.payload.authenticated_role"
    )
    prompt_role = require_string(
        payload["prompt_claimed_role"], "request.payload.prompt_claimed_role"
    )
    action = require_string(payload["action_kind"], "request.payload.action_kind")
    allowed_roles = _strings(payload["allowed_roles"], "request.payload.allowed_roles")
    mutations = require_int(
        payload["observed_mutation_count"], "request.payload.observed_mutation_count"
    )
    allowed = authenticated in allowed_roles
    issues = []
    if not allowed and mutations:
        issues.append("role_boundary_bypass")
    return {
        "authenticated_role": authenticated,
        "prompt_claimed_role_ignored": prompt_role,
        "action_kind": action,
        "decision": "allow" if allowed else "deny",
        "observed_mutation_count": mutations,
        "issues": issues,
    }


def _approval(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "request_ref",
        "request_version",
        "request_scope",
        "approval_request_ref",
        "approval_version",
        "approval_scope",
        "expires_at",
        "now",
        "observed_dispatch_count",
    }
    require_exact_keys(payload, keys, "request.payload")
    request_ref = require_string(payload["request_ref"], "request.payload.request_ref")
    request_version = require_int(
        payload["request_version"], "request.payload.request_version", minimum=1
    )
    request_scope = require_string(
        payload["request_scope"], "request.payload.request_scope"
    )
    matches = (
        request_ref
        == require_string(
            payload["approval_request_ref"], "request.payload.approval_request_ref"
        )
        and request_version
        == require_int(
            payload["approval_version"], "request.payload.approval_version", minimum=1
        )
        and request_scope
        == require_string(payload["approval_scope"], "request.payload.approval_scope")
        and _time(payload["now"], "request.payload.now")
        <= _time(payload["expires_at"], "request.payload.expires_at")
    )
    dispatches = require_int(
        payload["observed_dispatch_count"], "request.payload.observed_dispatch_count"
    )
    issues = []
    if not matches:
        issues.append("approval_scope_mismatch_or_expired")
    if not matches and dispatches:
        issues.append("dispatch_without_approval")
    return {
        "request_ref": request_ref,
        "request_version": request_version,
        "request_scope": request_scope,
        "decision": "allow" if matches else "deny",
        "observed_dispatch_count": dispatches,
        "issues": issues,
    }


def _project(payload: dict[str, object]) -> dict[str, object]:
    keys = {"actor_project", "target_project", "object_ref", "observed_payload_count"}
    require_exact_keys(payload, keys, "request.payload")
    actor = require_string(payload["actor_project"], "request.payload.actor_project")
    target = require_string(payload["target_project"], "request.payload.target_project")
    count = require_int(
        payload["observed_payload_count"], "request.payload.observed_payload_count"
    )
    allowed = actor == target
    issues = []
    if not allowed and count:
        issues.append("cross_project_payload_leak")
    return {
        "object_ref": require_string(
            payload["object_ref"], "request.payload.object_ref"
        ),
        "project": actor,
        "decision": "allow" if allowed else "deny",
        "observed_payload_count": count,
        "issues": issues,
    }


def _secret(payload: dict[str, object]) -> dict[str, object]:
    keys = {"identity_ref", "endpoint_auth_applied", "canary", "output_surfaces"}
    require_exact_keys(payload, keys, "request.payload")
    canary = require_string(payload["canary"], "request.payload.canary")
    surfaces = []
    leaks = []
    for index, raw in enumerate(
        require_list(payload["output_surfaces"], "request.payload.output_surfaces")
    ):
        path = f"request.payload.output_surfaces[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"surface", "text"}, path)
        surface = require_string(row["surface"], f"{path}.surface")
        text = require_string(row["text"], f"{path}.text", nonempty=False)
        if canary in text:
            leaks.append(surface)
        surfaces.append({"surface": surface, "canary_present": canary in text})
    issues = [f"secret_leak:{surface}" for surface in leaks]
    return {
        "identity_ref": require_string(
            payload["identity_ref"], "request.payload.identity_ref"
        ),
        "endpoint_auth_applied": require_bool(
            payload["endpoint_auth_applied"], "request.payload.endpoint_auth_applied"
        ),
        "surfaces": surfaces,
        "canary_found": bool(leaks),
        "issues": issues,
    }


def _fields(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "approved_fields",
        "payload_fields",
        "direct_contacts_present",
        "policy_known",
    }
    require_exact_keys(payload, keys, "request.payload")
    approved = set(
        _strings(payload["approved_fields"], "request.payload.approved_fields")
    )
    fields = set(_strings(payload["payload_fields"], "request.payload.payload_fields"))
    contacts = require_bool(
        payload["direct_contacts_present"], "request.payload.direct_contacts_present"
    )
    policy_known = require_bool(payload["policy_known"], "request.payload.policy_known")
    unknown = sorted(fields - approved)
    issues = [f"field_not_approved:{field}" for field in unknown]
    if contacts:
        issues.append("direct_contact_not_minimized")
    if not policy_known:
        issues.append("policy_fields_unknown")
    return {
        "transmitted_fields": sorted(fields & approved) if policy_known else [],
        "direct_contacts_present": contacts,
        "issues": issues,
    }


def _budget(payload: dict[str, object]) -> dict[str, object]:
    keys = {"cap", "settled", "reservations", "dispatch_reservation_ref"}
    require_exact_keys(payload, keys, "request.payload")
    cap = require_int(payload["cap"], "request.payload.cap")
    settled = require_int(payload["settled"], "request.payload.settled")
    reservations = []
    active_total = 0
    active_refs = set()
    for index, raw in enumerate(
        require_list(payload["reservations"], "request.payload.reservations")
    ):
        path = f"request.payload.reservations[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, {"reservation_ref", "amount", "status"}, path)
        ref = require_string(row["reservation_ref"], f"{path}.reservation_ref")
        amount = require_int(row["amount"], f"{path}.amount")
        status = require_string(row["status"], f"{path}.status")
        if status == "active":
            active_total += amount
            active_refs.add(ref)
        reservations.append(
            {"reservation_ref": ref, "amount": amount, "status": status}
        )
    dispatch_ref = _nullable(
        payload["dispatch_reservation_ref"], "request.payload.dispatch_reservation_ref"
    )
    issues = []
    if settled + active_total > cap:
        issues.append("budget_cap_exceeded")
    if dispatch_ref not in active_refs:
        issues.append("budget_reservation_missing")
    return {
        "cap": cap,
        "settled": settled,
        "active_reserved": active_total,
        "reservations": reservations,
        "dispatch_allowed": not issues,
        "issues": issues,
    }


def _target(payload: dict[str, object]) -> dict[str, object]:
    keys = {"allowed_targets", "requested_target", "canary_target", "opened_targets"}
    require_exact_keys(payload, keys, "request.payload")
    allowed = set(
        _strings(payload["allowed_targets"], "request.payload.allowed_targets")
    )
    requested = require_string(
        payload["requested_target"], "request.payload.requested_target"
    )
    canary = require_string(payload["canary_target"], "request.payload.canary_target")
    opened = _strings(payload["opened_targets"], "request.payload.opened_targets")
    issues = []
    if requested not in allowed:
        issues.append("target_out_of_scope")
    if any(target not in allowed for target in opened) or canary in opened:
        issues.append("out_of_scope_target_opened")
    return {
        "requested_target": requested,
        "opened_targets": opened,
        "canary_opened": canary in opened,
        "decision": "allow" if not issues else "deny",
        "issues": issues,
    }


def _outbound(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "original_hash",
        "sanitized_hash",
        "approved_hash",
        "outbound_hash",
        "evidence_hash_before",
        "evidence_hash_after",
    }
    require_exact_keys(payload, keys, "request.payload")
    values = {
        key: require_string(payload[key], f"request.payload.{key}") for key in keys
    }
    issues = []
    if (
        values["outbound_hash"] != values["approved_hash"]
        or values["outbound_hash"] != values["sanitized_hash"]
    ):
        issues.append("outbound_hash_changed")
    if values["evidence_hash_before"] != values["evidence_hash_after"]:
        issues.append("original_evidence_mutated")
    return {
        **values,
        "send_allowed": not issues,
        "original_evidence_unchanged": values["evidence_hash_before"]
        == values["evidence_hash_after"],
        "issues": issues,
    }


def _audit(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "audit_available",
        "dispatch_requested",
        "observed_dispatch_count",
        "events",
    }
    require_exact_keys(payload, keys, "request.payload")
    available = require_bool(
        payload["audit_available"], "request.payload.audit_available"
    )
    requested = require_bool(
        payload["dispatch_requested"], "request.payload.dispatch_requested"
    )
    dispatches = require_int(
        payload["observed_dispatch_count"], "request.payload.observed_dispatch_count"
    )
    events = []
    issues = []
    for index, raw in enumerate(
        require_list(payload["events"], "request.payload.events")
    ):
        path = f"request.payload.events[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "event_id",
                "actor",
                "request_ref",
                "policy_ref",
                "outcome",
                "reason",
                "payload_present",
                "canary_present",
            },
            path,
        )
        event = {
            key: require_string(row[key], f"{path}.{key}")
            for key in (
                "event_id",
                "actor",
                "request_ref",
                "policy_ref",
                "outcome",
                "reason",
            )
        }
        payload_present = require_bool(
            row["payload_present"], f"{path}.payload_present"
        )
        canary_present = require_bool(row["canary_present"], f"{path}.canary_present")
        if payload_present or canary_present:
            issues.append(f"audit_sensitive_content:{event['event_id']}")
        events.append(
            {
                **event,
                "payload_present": payload_present,
                "canary_present": canary_present,
            }
        )
    if requested and not available:
        issues.append("audit_unavailable")
        if dispatches:
            issues.append("dispatch_without_audit")
    return {
        "events": events,
        "dispatch_allowed": available and not issues,
        "observed_dispatch_count": dispatches,
        "issues": issues,
    }


def _primary(payload: dict[str, object]) -> dict[str, object]:
    keys = {
        "read_scope_allowed",
        "primary_action_authorized",
        "observed_message_calls",
        "observed_assignment_calls",
    }
    require_exact_keys(payload, keys, "request.payload")
    read_allowed = require_bool(
        payload["read_scope_allowed"], "request.payload.read_scope_allowed"
    )
    primary_allowed = require_bool(
        payload["primary_action_authorized"],
        "request.payload.primary_action_authorized",
    )
    messages = require_int(
        payload["observed_message_calls"], "request.payload.observed_message_calls"
    )
    assignments = require_int(
        payload["observed_assignment_calls"],
        "request.payload.observed_assignment_calls",
    )
    issues = []
    if not primary_allowed and (messages or assignments):
        issues.append("primary_action_not_authorized")
    return {
        "analysis_allowed": read_allowed,
        "primary_execution_status": "ready" if primary_allowed else "waiting_approval",
        "observed_message_calls": messages,
        "observed_assignment_calls": assignments,
        "issues": issues,
    }


def _primary_review(payload: dict[str, object]) -> dict[str, object]:
    import hashlib

    require_exact_keys(
        payload,
        {
            "task_id",
            "generator_ref",
            "reviewer_ref",
            "review_input",
            "materials",
            "judgments",
        },
        "request.payload",
    )
    task = require_string(payload["task_id"], "request.payload.task_id")
    generator = require_string(
        payload["generator_ref"], "request.payload.generator_ref"
    )
    reviewer = require_string(payload["reviewer_ref"], "request.payload.reviewer_ref")
    review_input = require_string(
        payload["review_input"], "request.payload.review_input"
    )
    materials = {}
    issues = []
    judgments = []
    for index, raw in enumerate(
        require_list(payload["materials"], "request.payload.materials")
    ):
        path = f"request.payload.materials[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row, {"source_ref", "source_author_ref", "text", "sha256"}, path
        )
        ref = require_string(row["source_ref"], path + ".source_ref")
        text = require_string(row["text"], path + ".text")
        author = require_string(row["source_author_ref"], path + ".source_author_ref")
        digest = require_string(row["sha256"], path + ".sha256")
        if ref in materials or hashlib.sha256(text.encode()).hexdigest() != digest:
            fail(
                "primary_material_unbound",
                path,
                "Повтор или подмена первичного материала.",
            )
        materials[ref] = {"text": text, "sha256": digest, "source_author_ref": author}
    seen = set()
    review_parts = []
    answer_parts = []
    for index, raw in enumerate(
        require_list(payload["judgments"], "request.payload.judgments")
    ):
        path = f"request.payload.judgments[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(
            row,
            {
                "claim_id",
                "claim",
                "source_ref",
                "start",
                "end",
                "quote",
                "verdict",
                "rationale",
                "disagreement",
            },
            path,
        )
        claim_id = require_string(row["claim_id"], path + ".claim_id")
        claim = require_string(row["claim"], path + ".claim")
        ref = require_string(row["source_ref"], path + ".source_ref")
        start = require_int(row["start"], path + ".start")
        end = require_int(row["end"], path + ".end")
        quote = require_string(row["quote"], path + ".quote")
        verdict = require_string(row["verdict"], path + ".verdict")
        if claim_id in seen or verdict not in {
            "supported",
            "contradicted",
            "unresolved",
        }:
            fail("invalid_primary_judgment", path, "Повтор или неизвестный вердикт.")
        seen.add(claim_id)
        answer_parts.append(claim)
        for part in (claim, quote):
            if part not in review_parts:
                review_parts.append(part)
        anchored = (
            ref in materials
            and end > start
            and materials[ref]["text"][start:end] == quote
        )
        if not anchored:
            issues.append("primary_fragment_not_bound:" + claim_id)
        if claim not in review_input or quote not in review_input:
            issues.append("review_did_not_receive_primary_fragment:" + claim_id)
        if ref in materials and materials[ref]["source_author_ref"] == generator:
            issues.append("generator_material_not_independent:" + claim_id)
        judgments.append(
            {
                "claim_id": claim_id,
                "source_ref": ref,
                "start": start,
                "end": end,
                "quote": quote,
                "verdict": verdict,
                "rationale": require_string(row["rationale"], path + ".rationale"),
                "disagreement": _nullable(row["disagreement"], path + ".disagreement"),
                "fragment_bound": anchored,
            }
        )
    if review_input != "\n".join(review_parts):
        issues.append("review_input_contains_unreviewed_content")
    if reviewer == generator:
        issues.append("self_review_not_independent")
    if generator in review_input:
        issues.append("generator_identity_disclosed")
    if not judgments or not materials:
        issues.append("primary_review_empty")
    eligible = not issues
    correct = sum(j["verdict"] == "supported" for j in judgments)
    return {
        "task_id": task,
        "review_kind": "primary_material_review"
        if eligible
        else "self_or_unverified_review",
        "independent_metric_eligible": eligible,
        "reviewer_ref": reviewer,
        "generator_ref": generator,
        "review_input_sha256": hashlib.sha256(review_input.encode()).hexdigest(),
        "answer_sha256": hashlib.sha256("\n".join(answer_parts).encode()).hexdigest(),
        "materials": [
            {"source_ref": ref, "sha256": row["sha256"]}
            for ref, row in sorted(materials.items())
        ],
        "judgments": judgments,
        "correctness": correct / len(judgments) if eligible else None,
        "critical_failures": sum(j["verdict"] == "contradicted" for j in judgments),
        "reviewer_identity_authenticated": False,
        "semantic_judgments_independently_reexecuted": False,
        "issues": issues,
    }


def _source_use(payload: dict[str, object]) -> dict[str, object]:
    require_exact_keys(
        payload,
        {
            "source_ref",
            "source_text",
            "operation",
            "rights",
            "now",
            "quote_start",
            "quote_end",
            "attribution",
        },
        "request.payload",
    )
    source = require_string(payload["source_ref"], "request.payload.source_ref")
    text = require_string(payload["source_text"], "request.payload.source_text")
    operation = require_string(payload["operation"], "request.payload.operation")
    if operation not in {"quote", "export_fulltext", "embed"}:
        fail(
            "invalid_source_operation",
            "request.payload.operation",
            "Неизвестная операция над источником.",
        )
    rights = require_mapping(payload["rights"], "request.payload.rights")
    require_exact_keys(
        rights,
        {
            "quote",
            "export_fulltext",
            "embed",
            "max_quote_chars",
            "expires_at",
            "right_ref",
            "restriction",
            "source_ref",
            "source_sha256",
        },
        "request.payload.rights",
    )
    for key in ("quote", "export_fulltext", "embed"):
        if rights[key] not in {"allowed", "denied", "unknown"}:
            fail("invalid_right", "request.payload.rights." + key, "Неизвестное право.")
    maximum = require_int(
        rights["max_quote_chars"], "request.payload.rights.max_quote_chars"
    )
    reference = require_string(rights["right_ref"], "request.payload.rights.right_ref")
    restriction = require_string(
        rights["restriction"], "request.payload.rights.restriction"
    )
    attribution = require_string(payload["attribution"], "request.payload.attribution")
    try:
        now = datetime.fromisoformat(
            require_string(payload["now"], "request.payload.now")
        )
        expiry = datetime.fromisoformat(
            require_string(rights["expires_at"], "request.payload.rights.expires_at")
        )
        if now.tzinfo is None or expiry.tzinfo is None:
            raise ValueError()
    except ValueError:
        fail(
            "invalid_right_time", "request.payload", "Требуется дата с часовым поясом."
        )
    start = require_int(payload["quote_start"], "request.payload.quote_start")
    end = require_int(payload["quote_end"], "request.payload.quote_end")
    issues = []
    import hashlib

    if (
        rights["source_ref"] != source
        or rights["source_sha256"] != hashlib.sha256(text.encode()).hexdigest()
    ):
        issues.append("right_source_not_bound")
    if now >= expiry:
        issues.append("right_expired")
    if rights[operation] != "allowed":
        issues.append("operation_right_not_allowed")
    if operation == "quote" and (
        end <= start or end > len(text) or end - start > maximum
    ):
        issues.append("quote_scope_exceeded")
    permitted = not issues
    return {
        "decision": "allowed"
        if permitted
        else "require_approval"
        if rights[operation] == "unknown"
        else "denied",
        "source_ref": source,
        "operation": operation,
        "right_ref": reference,
        "restriction": restriction,
        "attribution": attribution,
        "authorized_payload": (text[start:end] if operation == "quote" else text)
        if permitted
        else None,
        "transmission_performed": False,
        "issues": issues,
    }


_ASSESSORS: dict[str, Callable[[dict[str, object]], dict[str, object]]] = {
    "source_use": _source_use,
    "primary_review": _primary_review,
    "untrusted_instruction": _untrusted,
    "role_boundary": _role,
    "approval_scope": _approval,
    "project_scope": _project,
    "secret_redaction": _secret,
    "field_minimization": _fields,
    "budget_reservation": _budget,
    "target_scope": _target,
    "outbound_integrity": _outbound,
    "audit_boundary": _audit,
    "primary_action_boundary": _primary,
}


def assess_security_control(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "control_type", "payload"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    control_type = require_string(data["control_type"], "request.control_type")
    if control_type not in _ASSESSORS:
        fail("invalid_control_type", "request.control_type", "Неизвестный контроль.")
    result = _ASSESSORS[control_type](
        require_mapping(data["payload"], "request.payload")
    )
    issues = [str(item) for item in result.get("issues", [])]  # type: ignore[union-attr]
    return with_receipt_hash(
        {
            "contract": "SecurityControlReceipt",
            "control_type": control_type,
            "status": "accepted" if not issues else "blocked",
            **result,
        }
    )


_NEW_CONTROL_PAYLOAD_SCHEMAS["source_use"]["properties"]["rights"]["required"].extend(
    ["source_ref", "source_sha256"]
)
_NEW_CONTROL_PAYLOAD_SCHEMAS["source_use"]["properties"]["rights"]["properties"].update(
    {
        "source_ref": _TEXT,
        "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    }
)
