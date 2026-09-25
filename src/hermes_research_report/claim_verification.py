"""Claim graph, verification-route, aspect, and invalidation contracts."""

from __future__ import annotations

import re
from collections import deque
from typing import Any

from .canonical import with_receipt_hash
from .errors import (
    fail,
    require_bool,
    require_exact_keys,
    require_list,
    require_mapping,
    require_string,
)

_TEXT = {"type": "string", "minLength": 1}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

CLAIM_VERIFICATION_GRAPH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "graph_ref",
        "claims",
        "changed_refs",
        "release_claim_ref",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "graph_ref": _TEXT,
        "claims": {"type": "array", "minItems": 1, "items": {"type": "object"}},
        "changed_refs": {"type": "array", "items": _TEXT},
        "release_claim_ref": _TEXT,
    },
}

_CLAIM_KEYS = {
    "claim_id",
    "version_hash",
    "material_number",
    "parent_claim_refs",
    "actual_input_refs",
    "dependency_refs",
    "completed_routes",
    "required_aspects",
    "aspect_receipts",
    "current",
}


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повтор элемента запрещён.")
    return result


def _hash(value: object, path: str) -> str:
    text = require_string(value, path)
    if not _HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text


def assess_claim_verification_graph(request: object) -> dict[str, Any]:
    """Assess a claim DAG and its exact verification obligations."""

    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {"schema_version", "graph_ref", "claims", "changed_refs", "release_claim_ref"},
        "request",
    )
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    graph_ref = require_string(data["graph_ref"], "request.graph_ref")
    release_claim_ref = require_string(
        data["release_claim_ref"], "request.release_claim_ref"
    )
    changed_refs = set(_strings(data["changed_refs"], "request.changed_refs"))
    claims: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for index, raw in enumerate(require_list(data["claims"], "request.claims")):
        path = f"request.claims[{index}]"
        row = require_mapping(raw, path)
        require_exact_keys(row, _CLAIM_KEYS, path)
        claim_id = require_string(row["claim_id"], f"{path}.claim_id")
        if claim_id in claims:
            fail("duplicate_claim", f"{path}.claim_id", "Повтор утверждения.")
        parents = _strings(row["parent_claim_refs"], f"{path}.parent_claim_refs")
        actual_inputs = _strings(row["actual_input_refs"], f"{path}.actual_input_refs")
        dependencies = _strings(row["dependency_refs"], f"{path}.dependency_refs")
        completed_routes = _strings(row["completed_routes"], f"{path}.completed_routes")
        required_aspects = _strings(row["required_aspects"], f"{path}.required_aspects")
        aspects: dict[str, str] = {}
        for offset, value in enumerate(
            require_list(row["aspect_receipts"], f"{path}.aspect_receipts")
        ):
            aspect_path = f"{path}.aspect_receipts[{offset}]"
            item = require_mapping(value, aspect_path)
            require_exact_keys(item, {"aspect", "status", "receipt_ref"}, aspect_path)
            aspect = require_string(item["aspect"], f"{aspect_path}.aspect")
            if aspect in aspects:
                fail("duplicate_aspect", f"{aspect_path}.aspect", "Повтор аспекта.")
            status = require_string(item["status"], f"{aspect_path}.status")
            if status not in {"pass", "fail", "not_checked"}:
                fail(
                    "invalid_aspect_status",
                    f"{aspect_path}.status",
                    "Неизвестный статус.",
                )
            require_string(item["receipt_ref"], f"{aspect_path}.receipt_ref")
            aspects[aspect] = status
        claims[claim_id] = {
            "claim_id": claim_id,
            "version_hash": _hash(row["version_hash"], f"{path}.version_hash"),
            "material_number": require_bool(
                row["material_number"], f"{path}.material_number"
            ),
            "parents": parents,
            "actual_inputs": actual_inputs,
            "dependencies": dependencies,
            "completed_routes": completed_routes,
            "required_aspects": required_aspects,
            "aspects": aspects,
            "current": require_bool(row["current"], f"{path}.current"),
        }
    if release_claim_ref not in claims:
        fail(
            "unknown_release_claim",
            "request.release_claim_ref",
            "Целевое утверждение отсутствует.",
        )

    indegree = {claim_id: 0 for claim_id in claims}
    children: dict[str, set[str]] = {claim_id: set() for claim_id in claims}
    for claim_id, claim in claims.items():
        for parent in claim["parents"]:
            if parent == claim_id:
                issues.append(f"derived_cycle:{claim_id}")
            elif parent not in claims:
                issues.append(f"unknown_parent:{claim_id}:{parent}")
            else:
                indegree[claim_id] += 1
                children[parent].add(claim_id)
        actual = set(claim["actual_inputs"])
        declared = set(claim["parents"])
        for parent in sorted(actual - declared):
            issues.append(f"undeclared_parent:{claim_id}:{parent}")
        for parent in sorted(declared - actual):
            issues.append(f"declared_parent_unused:{claim_id}:{parent}")
        required_routes = set()
        if claim["material_number"]:
            required_routes.add("numeric_trace")
        if claim["parents"]:
            required_routes.add("derived_claim")
        missing_routes = sorted(required_routes - set(claim["completed_routes"]))
        for route in missing_routes:
            issues.append(f"required_route_missing:{claim_id}:{route}")
        claim["computed_required_routes"] = sorted(required_routes)
        claim["missing_routes"] = missing_routes

    queue = deque(
        sorted(claim_id for claim_id, degree in indegree.items() if degree == 0)
    )
    topological_order: list[str] = []
    while queue:
        claim_id = queue.popleft()
        topological_order.append(claim_id)
        for child in sorted(children[claim_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(topological_order) != len(claims):
        issues.append("derived_cycle")

    stale_refs = set(changed_refs)
    changed = True
    while changed:
        changed = False
        for claim_id, claim in claims.items():
            if claim_id not in stale_refs and set(claim["dependencies"]) & stale_refs:
                stale_refs.add(claim_id)
                changed = True
    stale_claims = sorted(set(claims) & stale_refs)
    unaffected_claims = sorted(set(claims) - set(stale_claims))
    if release_claim_ref in stale_claims:
        issues.append("stale_transitive_dependency")

    claim_results = []
    for claim_id in sorted(claims):
        claim = claims[claim_id]
        aspect_statuses = {
            aspect: claim["aspects"].get(aspect, "not_checked")
            for aspect in claim["required_aspects"]
        }
        aspects_pass = all(status == "pass" for status in aspect_statuses.values())
        result_status = (
            "review_required"
            if not aspects_pass or claim["missing_routes"] or claim_id in stale_claims
            else "verified_for_scope"
        )
        claim_results.append(
            {
                "claim_id": claim_id,
                "version_hash": claim["version_hash"],
                "computed_required_routes": claim["computed_required_routes"],
                "missing_routes": claim["missing_routes"],
                "aspect_statuses": aspect_statuses,
                "result_status": result_status,
                "stale": claim_id in stale_claims,
            }
        )
    accepted = not issues and all(
        row["result_status"] == "verified_for_scope" for row in claim_results
    )
    return with_receipt_hash(
        {
            "contract": "ClaimVerificationGraphReceipt",
            "status": "accepted" if accepted else "review_required",
            "graph_ref": graph_ref,
            "topological_order": topological_order,
            "claims": claim_results,
            "stale_claim_refs": stale_claims,
            "unaffected_claim_refs": unaffected_claims,
            "release_claim_ref": release_claim_ref,
            "release_allowed": accepted,
            "issues": sorted(set(issues)),
        }
    )
