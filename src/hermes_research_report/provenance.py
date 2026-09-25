"""W3C PROV, RO-Crate, replay, and living-review contracts."""

from __future__ import annotations

from typing import Any

from .canonical import sha256_json, with_receipt_hash
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


PROVENANCE_EXPORT_ASSESS_SCHEMA = _closed_schema(
    ["schema_version", "run_id", "granularity", "graph", "roundtrip_observation"]
)
PROVENANCE_EXPORT_ASSESS_SCHEMA["properties"]["run_id"] = _TEXT
PROVENANCE_EXPORT_ASSESS_SCHEMA["properties"]["granularity"] = {
    "enum": ["process", "workflow", "provenance"]
}
REPLAY_ASSESS_SCHEMA = _closed_schema(["schema_version", "manifest", "execution"])
LIVING_REVIEW_ASSESS_SCHEMA = _closed_schema(
    ["schema_version", "policy", "baseline", "events", "update"]
)
LIVING_REVIEW_ASSESS_SCHEMA["properties"]["events"] = {
    "type": "array",
    "items": {"type": "object"},
}
LIVING_REVIEW_ASSESS_SCHEMA["properties"]["update"] = {
    "oneOf": [{"type": "null"}, {"type": "object"}]
}

_PROV_RELATIONS = {
    "used",
    "wasGeneratedBy",
    "wasAssociatedWith",
    "wasDerivedFrom",
    "wasInformedBy",
    "actedOnBehalfOf",
}


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


def _strings(value: object, path: str) -> list[str]:
    result = [
        require_string(item, f"{path}[{index}]")
        for index, item in enumerate(require_list(value, path))
    ]
    if len(result) != len(set(result)):
        fail("duplicate_item", path, "Повтор элемента запрещён.")
    return result


def _nullable(value: object, path: str) -> str | None:
    return None if value is None else require_string(value, path)


def assess_provenance_export(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {"schema_version", "run_id", "granularity", "graph", "roundtrip_observation"},
        "request",
    )
    _version(data)
    run_id = require_string(data["run_id"], "request.run_id")
    granularity = require_string(data["granularity"], "request.granularity")
    if granularity not in {"process", "workflow", "provenance"}:
        fail("invalid_granularity", "request.granularity", "Неизвестна гранулярность.")
    graph = require_mapping(data["graph"], "request.graph")
    require_exact_keys(
        graph, {"entities", "activities", "agents", "relations"}, "request.graph"
    )
    entities = []
    entity_index = {}
    protected_ids = []
    for index, raw in enumerate(
        require_list(graph["entities"], "request.graph.entities")
    ):
        path = f"request.graph.entities[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "entity_id",
                "entity_type",
                "version",
                "content_hash",
                "status",
                "protected_payload_included",
            },
            path,
        )
        entity_id = require_string(item["entity_id"], f"{path}.entity_id")
        if entity_id in entity_index:
            fail("duplicate_entity", path, "Повтор сущности запрещён.")
        protected = require_bool(
            item["protected_payload_included"], f"{path}.protected_payload_included"
        )
        if protected:
            protected_ids.append(entity_id)
        entity = {
            "entity_id": entity_id,
            "entity_type": require_string(item["entity_type"], f"{path}.entity_type"),
            "version": require_string(item["version"], f"{path}.version"),
            "content_hash": _hash(item["content_hash"], f"{path}.content_hash"),
            "status": require_string(item["status"], f"{path}.status"),
            "protected_payload_included": protected,
        }
        entities.append(entity)
        entity_index[entity_id] = entity
    activities = []
    activity_index = {}
    for index, raw in enumerate(
        require_list(graph["activities"], "request.graph.activities")
    ):
        path = f"request.graph.activities[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "activity_id",
                "activity_type",
                "version",
                "status",
                "input_entity_ids",
                "output_entity_ids",
                "agent_ids",
            },
            path,
        )
        activity_id = require_string(item["activity_id"], f"{path}.activity_id")
        if activity_id in activity_index:
            fail("duplicate_activity", path, "Повтор действия запрещён.")
        activity = {
            "activity_id": activity_id,
            "activity_type": require_string(
                item["activity_type"], f"{path}.activity_type"
            ),
            "version": require_string(item["version"], f"{path}.version"),
            "status": require_string(item["status"], f"{path}.status"),
            "input_entity_ids": _strings(
                item["input_entity_ids"], f"{path}.input_entity_ids"
            ),
            "output_entity_ids": _strings(
                item["output_entity_ids"], f"{path}.output_entity_ids"
            ),
            "agent_ids": _strings(item["agent_ids"], f"{path}.agent_ids"),
        }
        activities.append(activity)
        activity_index[activity_id] = activity
    agents = []
    agent_index = {}
    for index, raw in enumerate(require_list(graph["agents"], "request.graph.agents")):
        path = f"request.graph.agents[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"agent_id", "agent_type", "version", "roles"}, path)
        agent_id = require_string(item["agent_id"], f"{path}.agent_id")
        if agent_id in agent_index:
            fail("duplicate_agent", path, "Повтор исполнителя запрещён.")
        agent = {
            "agent_id": agent_id,
            "agent_type": require_string(item["agent_type"], f"{path}.agent_type"),
            "version": require_string(item["version"], f"{path}.version"),
            "roles": _strings(item["roles"], f"{path}.roles"),
        }
        agents.append(agent)
        agent_index[agent_id] = agent
    all_ids = set(entity_index) | set(activity_index) | set(agent_index)
    relations = []
    relation_ids = set()
    for index, raw in enumerate(
        require_list(graph["relations"], "request.graph.relations")
    ):
        path = f"request.graph.relations[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "relation_id",
                "relation",
                "from_id",
                "to_id",
                "negative_outcome",
                "dependency",
            },
            path,
        )
        relation_id = require_string(item["relation_id"], f"{path}.relation_id")
        if relation_id in relation_ids:
            fail("duplicate_relation", path, "Повтор ребра запрещён.")
        relation_ids.add(relation_id)
        relation = require_string(item["relation"], f"{path}.relation")
        if relation not in _PROV_RELATIONS:
            fail(
                "invalid_prov_relation",
                f"{path}.relation",
                "Неизвестное отношение PROV.",
            )
        source = require_string(item["from_id"], f"{path}.from_id")
        target = require_string(item["to_id"], f"{path}.to_id")
        if source not in all_ids or target not in all_ids:
            fail("unknown_prov_node", path, "Ребро ссылается на неизвестный объект.")
        relations.append(
            {
                "relation_id": relation_id,
                "relation": relation,
                "from_id": source,
                "to_id": target,
                "negative_outcome": require_bool(
                    item["negative_outcome"], f"{path}.negative_outcome"
                ),
                "dependency": require_bool(item["dependency"], f"{path}.dependency"),
            }
        )
    implicit_relations = []
    for activity in activities:
        for entity_id in activity["input_entity_ids"]:
            if entity_id not in entity_index:
                fail(
                    "unknown_activity_input",
                    "request.graph.activities",
                    "Вход отсутствует.",
                )
            implicit_relations.append(
                {
                    "relation": "used",
                    "from_id": activity["activity_id"],
                    "to_id": entity_id,
                }
            )
        for entity_id in activity["output_entity_ids"]:
            if entity_id not in entity_index:
                fail(
                    "unknown_activity_output",
                    "request.graph.activities",
                    "Выход отсутствует.",
                )
            implicit_relations.append(
                {
                    "relation": "wasGeneratedBy",
                    "from_id": entity_id,
                    "to_id": activity["activity_id"],
                }
            )
        for agent_id in activity["agent_ids"]:
            if agent_id not in agent_index:
                fail(
                    "unknown_activity_agent",
                    "request.graph.activities",
                    "Исполнитель отсутствует.",
                )
            implicit_relations.append(
                {
                    "relation": "wasAssociatedWith",
                    "from_id": activity["activity_id"],
                    "to_id": agent_id,
                }
            )
    prov = {
        "prefix": {"prov": "http://www.w3.org/ns/prov#", "hermes": "urn:hermes:"},
        "entity": [
            {
                "id": entity["entity_id"],
                "prov:type": entity["entity_type"],
                "hermes:version": entity["version"],
                "hermes:contentHash": entity["content_hash"],
                "hermes:status": entity["status"],
            }
            for entity in entities
        ],
        "activity": [
            {
                "id": activity["activity_id"],
                "prov:type": activity["activity_type"],
                "hermes:version": activity["version"],
                "hermes:status": activity["status"],
            }
            for activity in activities
        ],
        "agent": [
            {
                "id": agent["agent_id"],
                "prov:type": agent["agent_type"],
                "hermes:version": agent["version"],
                "hermes:roles": agent["roles"],
            }
            for agent in agents
        ],
        "relations": relations,
        "implicit_relations": implicit_relations,
    }
    profile = {
        "process": "Process Run Crate",
        "workflow": "Workflow Run Crate",
        "provenance": "Provenance Run Crate",
    }[granularity]
    signatures = {
        "entities": sorted(
            f"{item['entity_id']}|{item['version']}|{item['status']}"
            for item in entities
        ),
        "activities": sorted(
            f"{item['activity_id']}|{item['version']}|{item['status']}"
            for item in activities
        ),
        "agents": sorted(f"{item['agent_id']}|{item['version']}" for item in agents),
        "relations": sorted(
            f"{item['relation']}|{item['from_id']}|{item['to_id']}|{item['negative_outcome']}|{item['dependency']}"
            for item in relations
        ),
    }
    observation = require_mapping(
        data["roundtrip_observation"], "request.roundtrip_observation"
    )
    require_exact_keys(
        observation,
        {
            "validation_status",
            "entity_signatures",
            "activity_signatures",
            "agent_signatures",
            "relation_signatures",
        },
        "request.roundtrip_observation",
    )
    validation_status = require_string(
        observation["validation_status"],
        "request.roundtrip_observation.validation_status",
    )
    observed = {
        "entities": sorted(
            _strings(
                observation["entity_signatures"],
                "request.roundtrip_observation.entity_signatures",
            )
        ),
        "activities": sorted(
            _strings(
                observation["activity_signatures"],
                "request.roundtrip_observation.activity_signatures",
            )
        ),
        "agents": sorted(
            _strings(
                observation["agent_signatures"],
                "request.roundtrip_observation.agent_signatures",
            )
        ),
        "relations": sorted(
            _strings(
                observation["relation_signatures"],
                "request.roundtrip_observation.relation_signatures",
            )
        ),
    }
    roundtrip_match = validation_status == "pass" and observed == signatures
    status = (
        "blocked_protected_payload"
        if protected_ids
        else "export_verified"
        if roundtrip_match
        else "roundtrip_failed"
    )
    return with_receipt_hash(
        {
            "contract": "ProvenanceExportReceipt",
            "status": status,
            "run_id": run_id,
            "granularity": granularity,
            "ro_crate_profile": profile,
            "prov": prov,
            "prov_hash": sha256_json(prov),
            "semantic_signatures": signatures,
            "roundtrip_observation": observed,
            "roundtrip_match": roundtrip_match,
            "protected_payload_entity_ids": protected_ids,
            "negative_outcomes_preserved": all(
                any(
                    signature.startswith(
                        f"{relation['relation']}|{relation['from_id']}|"
                    )
                    for signature in signatures["relations"]
                )
                for relation in relations
                if relation["negative_outcome"]
            ),
            "export_performed_by_core": False,
        }
    )


def assess_replay(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(data, {"schema_version", "manifest", "execution"}, "request")
    _version(data)
    manifest = require_mapping(data["manifest"], "request.manifest")
    require_exact_keys(
        manifest,
        {
            "replay_id",
            "requested_mode",
            "source_kind",
            "source_ref",
            "prior_source_hash",
            "current_source_hash",
            "materials",
            "delta",
        },
        "request.manifest",
    )
    requested = require_string(
        manifest["requested_mode"], "request.manifest.requested_mode"
    )
    if requested not in {"exact", "best_effort"}:
        fail(
            "invalid_replay_mode",
            "request.manifest.requested_mode",
            "Неизвестен режим.",
        )
    source_kind = require_string(
        manifest["source_kind"], "request.manifest.source_kind"
    )
    if source_kind not in {"immutable", "live"}:
        fail(
            "invalid_source_kind",
            "request.manifest.source_kind",
            "Неизвестен вид источника.",
        )
    prior_hash = _hash(
        manifest["prior_source_hash"], "request.manifest.prior_source_hash"
    )
    current_hash = _hash(
        manifest["current_source_hash"], "request.manifest.current_source_hash"
    )
    materials = require_mapping(manifest["materials"], "request.manifest.materials")
    material_fields = {
        "input_bytes",
        "code",
        "dependencies",
        "parameters",
        "random_seeds",
        "environment",
    }
    require_exact_keys(materials, material_fields, "request.manifest.materials")
    material_state = {
        field: require_bool(materials[field], f"request.manifest.materials.{field}")
        for field in sorted(material_fields)
    }
    delta = []
    for index, raw in enumerate(
        require_list(manifest["delta"], "request.manifest.delta")
    ):
        path = f"request.manifest.delta[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item, {"change_id", "kind", "prior_ref", "current_ref"}, path
        )
        delta.append(
            {
                "change_id": require_string(item["change_id"], f"{path}.change_id"),
                "kind": require_string(item["kind"], f"{path}.kind"),
                "prior_ref": require_string(item["prior_ref"], f"{path}.prior_ref"),
                "current_ref": require_string(
                    item["current_ref"], f"{path}.current_ref"
                ),
            }
        )
    source_changed = prior_hash != current_hash
    exact_possible = (
        source_kind == "immutable"
        and not source_changed
        and all(material_state.values())
    )
    effective_mode = (
        "exact" if requested == "exact" and exact_possible else "best_effort"
    )
    blockers = []
    if effective_mode == "best_effort" and source_changed and not delta:
        blockers.append("replay_delta_missing")
    if requested == "exact" and not exact_possible:
        blockers.append("exact_replay_impossible")
    execution = require_mapping(data["execution"], "request.execution")
    require_exact_keys(
        execution,
        {"performed", "source_hash_used", "output_hash", "receipt_ref"},
        "request.execution",
    )
    performed = require_bool(execution["performed"], "request.execution.performed")
    source_hash_used = _hash(
        execution["source_hash_used"], "request.execution.source_hash_used"
    )
    if performed and source_hash_used != current_hash:
        blockers.append("replay_source_hash_mismatch")
    return with_receipt_hash(
        {
            "contract": "ReplayDecisionReceipt",
            "status": "replay_recorded" if performed and not blockers else "blocked",
            "replay_id": require_string(
                manifest["replay_id"], "request.manifest.replay_id"
            ),
            "source_ref": require_string(
                manifest["source_ref"], "request.manifest.source_ref"
            ),
            "source_kind": source_kind,
            "requested_mode": requested,
            "effective_mode": effective_mode,
            "exact": effective_mode == "exact" and performed and not blockers,
            "source_changed": source_changed,
            "materials": material_state,
            "delta": delta,
            "blockers": blockers,
            "execution": {
                "performed": performed,
                "source_hash_used": source_hash_used,
                "output_hash": _hash(
                    execution["output_hash"], "request.execution.output_hash"
                ),
                "receipt_ref": require_string(
                    execution["receipt_ref"], "request.execution.receipt_ref"
                ),
            },
            "replay_executed_by_core": False,
        }
    )


def assess_living_review(request: object) -> dict[str, Any]:
    data = require_mapping(request, "request")
    require_exact_keys(
        data,
        {"schema_version", "policy", "baseline", "events", "update"},
        "request",
    )
    _version(data)
    policy = require_mapping(data["policy"], "request.policy")
    require_exact_keys(
        policy,
        {"policy_id", "version", "channels", "triggers", "validity_days"},
        "request.policy",
    )
    channels = []
    channel_ids = set()
    for index, raw in enumerate(
        require_list(policy["channels"], "request.policy.channels")
    ):
        path = f"request.policy.channels[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(item, {"channel_id", "frequency"}, path)
        channel_id = require_string(item["channel_id"], f"{path}.channel_id")
        if channel_id in channel_ids:
            fail("duplicate_channel", path, "Повтор канала запрещён.")
        channel_ids.add(channel_id)
        channels.append(
            {
                "channel_id": channel_id,
                "frequency": require_string(item["frequency"], f"{path}.frequency"),
            }
        )
    triggers = _strings(policy["triggers"], "request.policy.triggers")
    baseline = require_mapping(data["baseline"], "request.baseline")
    require_exact_keys(
        baseline,
        {"review_id", "revision", "valid_until", "update_state"},
        "request.baseline",
    )
    revision = require_int(baseline["revision"], "request.baseline.revision", minimum=1)
    events = []
    triggering_events = []
    for index, raw in enumerate(require_list(data["events"], "request.events")):
        path = f"request.events[{index}]"
        item = require_mapping(raw, path)
        require_exact_keys(
            item,
            {
                "event_id",
                "channel_id",
                "trigger",
                "relevant",
                "includable",
                "object_ref",
                "found_at",
            },
            path,
        )
        channel_id = require_string(item["channel_id"], f"{path}.channel_id")
        if channel_id not in channel_ids:
            fail("unknown_living_channel", f"{path}.channel_id", "Канал отсутствует.")
        trigger = require_string(item["trigger"], f"{path}.trigger")
        relevant = require_bool(item["relevant"], f"{path}.relevant")
        includable = require_bool(item["includable"], f"{path}.includable")
        event = {
            "event_id": require_string(item["event_id"], f"{path}.event_id"),
            "channel_id": channel_id,
            "trigger": trigger,
            "relevant": relevant,
            "includable": includable,
            "object_ref": require_string(item["object_ref"], f"{path}.object_ref"),
            "found_at": require_string(item["found_at"], f"{path}.found_at"),
        }
        events.append(event)
        if trigger in triggers and relevant and includable:
            triggering_events.append(event["event_id"])
    update_required = bool(triggering_events)
    update = data["update"]
    update_record = None
    valid_update = not update_required
    if update is not None:
        item = require_mapping(update, "request.update")
        require_exact_keys(
            item,
            {
                "new_revision",
                "created_at",
                "flow_ref",
                "invalidation_refs",
                "prior_revision_preserved",
            },
            "request.update",
        )
        update_record = {
            "new_revision": require_int(
                item["new_revision"], "request.update.new_revision", minimum=2
            ),
            "created_at": require_string(
                item["created_at"], "request.update.created_at"
            ),
            "flow_ref": require_string(item["flow_ref"], "request.update.flow_ref"),
            "invalidation_refs": _strings(
                item["invalidation_refs"], "request.update.invalidation_refs"
            ),
            "prior_revision_preserved": require_bool(
                item["prior_revision_preserved"],
                "request.update.prior_revision_preserved",
            ),
        }
        valid_update = (
            update_record["new_revision"] == revision + 1
            and bool(update_record["invalidation_refs"])
            and update_record["prior_revision_preserved"]
        )
    status = (
        "update_ready"
        if update_required and valid_update
        else "update_required"
        if update_required
        else "current"
    )
    return with_receipt_hash(
        {
            "contract": "LivingReviewDecisionReceipt",
            "status": status,
            "policy": {
                "policy_id": require_string(
                    policy["policy_id"], "request.policy.policy_id"
                ),
                "version": require_string(policy["version"], "request.policy.version"),
                "channels": channels,
                "triggers": triggers,
                "validity_days": require_int(
                    policy["validity_days"], "request.policy.validity_days", minimum=1
                ),
            },
            "baseline": {
                "review_id": require_string(
                    baseline["review_id"], "request.baseline.review_id"
                ),
                "revision": revision,
                "valid_until": require_string(
                    baseline["valid_until"], "request.baseline.valid_until"
                ),
                "update_state": require_string(
                    baseline["update_state"], "request.baseline.update_state"
                ),
            },
            "events": events,
            "triggering_event_ids": triggering_events,
            "update_required": update_required,
            "update": update_record,
            "new_revision_ready": update_required and valid_update,
            "prior_revision_preserved": bool(
                update_record and update_record["prior_revision_preserved"]
            ),
            "external_action_performed": False,
        }
    )
