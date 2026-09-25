"""Deterministic reconciliation of desired and observed Hermes runtime state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .canonical import receipt, sha256_json
from .errors import fail
from .validation import boolean, digest, exact, identifier, integer, mapping, string


def _instant(value: object, path: str) -> datetime:
    text = string(value, path)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        fail("invalid_timestamp", path, "Ожидалась временная метка ISO 8601.")
    if parsed.tzinfo is None:
        fail("timezone_required", path, "Временная зона обязательна.")
    return parsed.astimezone(UTC)


def _optional_instant(value: object, path: str) -> datetime | None:
    if value is None:
        return None
    return _instant(value, path)


def _enum(value: object, allowed: set[str], path: str) -> str:
    text = string(value, path)
    if text not in allowed:
        fail("invalid_enum", path, "Недопустимое состояние.")
    return text


def _age_seconds(captured_at: datetime, observed_at: datetime) -> int:
    if observed_at > captured_at:
        fail("future_observation", "request", "Наблюдение не может быть из будущего.")
    return int((captured_at - observed_at).total_seconds())


def _freshness(
    *, captured_at: datetime, observed_at: datetime, ttl_seconds: int
) -> dict[str, Any]:
    age = _age_seconds(captured_at, observed_at)
    return {"age_seconds": age, "ttl_seconds": ttl_seconds, "fresh": age <= ttl_seconds}


def _desired(value: object, index: int) -> dict[str, Any]:
    path = f"request.desired_configs[{index}]"
    data = mapping(value, path)
    exact(
        data,
        {
            "instance_id",
            "profile_id",
            "operation_id",
            "config_hash",
            "schema_fingerprint",
            "retry_budget",
            "open_after_failures",
            "observation_ttl_seconds",
        },
        path,
    )
    return {
        "instance_id": identifier(data["instance_id"], f"{path}.instance_id"),
        "profile_id": identifier(data["profile_id"], f"{path}.profile_id"),
        "operation_id": identifier(data["operation_id"], f"{path}.operation_id"),
        "config_hash": digest(data["config_hash"], f"{path}.config_hash"),
        "schema_fingerprint": digest(
            data["schema_fingerprint"], f"{path}.schema_fingerprint"
        ),
        "retry_budget": integer(data["retry_budget"], f"{path}.retry_budget"),
        "open_after_failures": integer(
            data["open_after_failures"], f"{path}.open_after_failures", minimum=1
        ),
        "observation_ttl_seconds": integer(
            data["observation_ttl_seconds"],
            f"{path}.observation_ttl_seconds",
            minimum=1,
        ),
    }


def _observation(
    value: object,
    *,
    path: str,
    allowed_statuses: set[str],
    extra: str | None = None,
) -> dict[str, Any]:
    data = mapping(value, path)
    keys = {"status", "observed_at", "ttl_seconds"}
    if extra:
        keys.add(extra)
    exact(data, keys, path)
    result = {
        "status": _enum(data["status"], allowed_statuses, f"{path}.status"),
        "observed_at": _instant(data["observed_at"], f"{path}.observed_at"),
        "ttl_seconds": integer(data["ttl_seconds"], f"{path}.ttl_seconds", minimum=1),
    }
    if extra:
        result[extra] = digest(data[extra], f"{path}.{extra}")
    return result


def _effective(value: object, index: int) -> dict[str, Any]:
    path = f"request.effective_runtimes[{index}]"
    data = mapping(value, path)
    exact(
        data,
        {
            "instance_id",
            "profile_id",
            "operation_id",
            "process_id",
            "loaded_config_hash",
            "loaded_at",
            "schema_cache",
            "live_connection",
            "characteristic_verification",
            "control",
        },
        path,
    )
    control_path = f"{path}.control"
    control = mapping(data["control"], control_path)
    exact(
        control,
        {
            "consecutive_failures",
            "failure_class",
            "retries_used",
            "circuit_state",
            "opened_until",
            "state_change_observed",
        },
        control_path,
    )
    return {
        "instance_id": identifier(data["instance_id"], f"{path}.instance_id"),
        "profile_id": identifier(data["profile_id"], f"{path}.profile_id"),
        "operation_id": identifier(data["operation_id"], f"{path}.operation_id"),
        "process_id": identifier(data["process_id"], f"{path}.process_id"),
        "loaded_config_hash": digest(
            data["loaded_config_hash"], f"{path}.loaded_config_hash"
        ),
        "loaded_at": _instant(data["loaded_at"], f"{path}.loaded_at"),
        "schema_cache": _observation(
            data["schema_cache"],
            path=f"{path}.schema_cache",
            allowed_statuses={"hit", "miss", "error"},
            extra="fingerprint",
        ),
        "live_connection": _observation(
            data["live_connection"],
            path=f"{path}.live_connection",
            allowed_statuses={"connected", "disconnected", "error", "unknown"},
        ),
        "characteristic_verification": _observation(
            data["characteristic_verification"],
            path=f"{path}.characteristic_verification",
            allowed_statuses={"pass", "fail", "not_run"},
        ),
        "control": {
            "consecutive_failures": integer(
                control["consecutive_failures"],
                f"{control_path}.consecutive_failures",
            ),
            "failure_class": _enum(
                control["failure_class"],
                {"none", "transient", "permanent", "auth", "config"},
                f"{control_path}.failure_class",
            ),
            "retries_used": integer(
                control["retries_used"], f"{control_path}.retries_used"
            ),
            "circuit_state": _enum(
                control["circuit_state"],
                {"closed", "open", "half_open"},
                f"{control_path}.circuit_state",
            ),
            "opened_until": _optional_instant(
                control["opened_until"], f"{control_path}.opened_until"
            ),
            "state_change_observed": boolean(
                control["state_change_observed"],
                f"{control_path}.state_change_observed",
            ),
        },
    }


def _key(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["instance_id"], row["profile_id"], row["operation_id"]


def _capability(
    desired: dict[str, Any], effective: dict[str, Any], captured_at: datetime
) -> dict[str, Any]:
    loaded_freshness = _freshness(
        captured_at=captured_at,
        observed_at=effective["loaded_at"],
        ttl_seconds=desired["observation_ttl_seconds"],
    )
    schema_freshness = _freshness(
        captured_at=captured_at,
        observed_at=effective["schema_cache"]["observed_at"],
        ttl_seconds=effective["schema_cache"]["ttl_seconds"],
    )
    connection_freshness = _freshness(
        captured_at=captured_at,
        observed_at=effective["live_connection"]["observed_at"],
        ttl_seconds=effective["live_connection"]["ttl_seconds"],
    )
    verification_freshness = _freshness(
        captured_at=captured_at,
        observed_at=effective["characteristic_verification"]["observed_at"],
        ttl_seconds=effective["characteristic_verification"]["ttl_seconds"],
    )
    config_matches = desired["config_hash"] == effective["loaded_config_hash"]
    schema_matches = (
        desired["schema_fingerprint"] == effective["schema_cache"]["fingerprint"]
    )
    stale_controls = [
        name
        for name, freshness in (
            ("loaded_process", loaded_freshness),
            ("schema_cache", schema_freshness),
            ("live_connection", connection_freshness),
            ("characteristic_verification", verification_freshness),
        )
        if not freshness["fresh"]
    ]
    control = effective["control"]
    permanent = control["failure_class"] in {"permanent", "auth", "config"}
    threshold_reached = (
        control["consecutive_failures"] >= desired["open_after_failures"]
    )
    circuit_open = control["circuit_state"] == "open" or threshold_reached or permanent
    if circuit_open:
        next_circuit = "open"
    elif control["circuit_state"] == "half_open":
        next_circuit = "half_open"
    else:
        next_circuit = "closed"
    retries_remaining = max(desired["retry_budget"] - control["retries_used"], 0)
    retry_allowed = (
        control["failure_class"] == "transient"
        and retries_remaining > 0
        and not circuit_open
    )
    if not config_matches:
        status = "misconfigured"
    elif stale_controls:
        status = "stale"
    elif circuit_open:
        status = "open_circuit"
    elif effective["schema_cache"]["status"] != "hit" or not schema_matches:
        status = "degraded"
    elif (
        effective["live_connection"]["status"] == "unknown"
        and effective["characteristic_verification"]["status"] == "not_run"
    ):
        status = "cache_only"
    elif (
        effective["live_connection"]["status"] != "connected"
        or effective["characteristic_verification"]["status"] != "pass"
    ):
        status = "failed"
    else:
        status = "ready"
    restart_allowed = (
        status == "misconfigured"
        and control["state_change_observed"]
        and not permanent
        and control["circuit_state"] != "open"
    )
    if status == "ready":
        action = "none"
    elif retry_allowed:
        action = "bounded_retry"
    elif restart_allowed:
        action = "single_restart_after_state_change"
    elif circuit_open or permanent:
        action = "wait_for_state_change_or_cooldown"
    else:
        action = "operator_diagnosis"
    return {
        "instance_id": desired["instance_id"],
        "profile_id": desired["profile_id"],
        "operation_id": desired["operation_id"],
        "status": status,
        "desired_config_hash": desired["config_hash"],
        "loaded_config_hash": effective["loaded_config_hash"],
        "config_matches": config_matches,
        "restart_required": not config_matches,
        "connected": effective["live_connection"]["status"] == "connected"
        and connection_freshness["fresh"],
        "desired_schema_fingerprint": desired["schema_fingerprint"],
        "cached_schema_fingerprint": effective["schema_cache"]["fingerprint"],
        "schema_matches": schema_matches,
        "schema_cache_status": effective["schema_cache"]["status"],
        "live_connection_status": effective["live_connection"]["status"],
        "characteristic_verification_status": effective["characteristic_verification"][
            "status"
        ],
        "freshness": {
            "loaded_process": loaded_freshness,
            "schema_cache": schema_freshness,
            "live_connection": connection_freshness,
            "characteristic_verification": verification_freshness,
        },
        "stale_controls": stale_controls,
        "failure_class": control["failure_class"],
        "consecutive_failures": control["consecutive_failures"],
        "retry_budget": desired["retry_budget"],
        "retries_used": control["retries_used"],
        "retries_remaining": retries_remaining,
        "retry_allowed": retry_allowed,
        "reported_circuit_state": control["circuit_state"],
        "next_circuit_state": next_circuit,
        "restart_allowed": restart_allowed,
        "next_action": action,
    }


def _schedule(value: object, index: int, captured_at: datetime) -> dict[str, Any]:
    path = f"request.schedules[{index}]"
    data = mapping(value, path)
    exact(
        data,
        {
            "schedule_id",
            "configured_enabled",
            "next_run_at",
            "last_run_at",
            "last_status",
            "last_success_at",
            "freshness_ttl_seconds",
        },
        path,
    )
    schedule_id = identifier(data["schedule_id"], f"{path}.schedule_id")
    enabled = boolean(data["configured_enabled"], f"{path}.configured_enabled")
    next_run = _optional_instant(data["next_run_at"], f"{path}.next_run_at")
    last_run = _optional_instant(data["last_run_at"], f"{path}.last_run_at")
    last_success = _optional_instant(data["last_success_at"], f"{path}.last_success_at")
    last_status = _enum(
        data["last_status"],
        {"never", "success", "failure", "running"},
        f"{path}.last_status",
    )
    ttl = integer(
        data["freshness_ttl_seconds"], f"{path}.freshness_ttl_seconds", minimum=1
    )
    if not enabled:
        status = "disabled"
    elif next_run is None:
        status = "not_scheduled"
    elif last_status == "running":
        status = "running"
    elif last_status == "failure":
        status = "failed"
    elif last_success is None:
        status = "never_succeeded"
    elif _age_seconds(captured_at, last_success) > ttl:
        status = "stale"
    else:
        status = "healthy"
    return {
        "schedule_id": schedule_id,
        "computed_status": status,
        "configured_enabled": enabled,
        "next_run_at": next_run.isoformat() if next_run else None,
        "last_run_at": last_run.isoformat() if last_run else None,
        "last_status": last_status,
        "last_success_at": last_success.isoformat() if last_success else None,
    }


def _backup(value: object, index: int, captured_at: datetime) -> dict[str, Any]:
    path = f"request.backups[{index}]"
    data = mapping(value, path)
    exact(
        data,
        {
            "backup_id",
            "expected_enabled",
            "last_attempt_at",
            "last_verified_success_at",
            "integrity_status",
            "max_age_seconds",
        },
        path,
    )
    backup_id = identifier(data["backup_id"], f"{path}.backup_id")
    enabled = boolean(data["expected_enabled"], f"{path}.expected_enabled")
    last_attempt = _optional_instant(data["last_attempt_at"], f"{path}.last_attempt_at")
    last_success = _optional_instant(
        data["last_verified_success_at"], f"{path}.last_verified_success_at"
    )
    integrity = _enum(
        data["integrity_status"],
        {"pass", "fail", "unknown"},
        f"{path}.integrity_status",
    )
    max_age = integer(data["max_age_seconds"], f"{path}.max_age_seconds", minimum=1)
    if not enabled:
        status = "disabled"
    elif integrity == "fail":
        status = "failed"
    elif last_success is None:
        status = "never_verified"
    elif _age_seconds(captured_at, last_success) > max_age:
        status = "stale"
    elif integrity != "pass":
        status = "unverified"
    else:
        status = "healthy"
    return {
        "backup_id": backup_id,
        "computed_status": status,
        "expected_enabled": enabled,
        "last_attempt_at": last_attempt.isoformat() if last_attempt else None,
        "last_verified_success_at": last_success.isoformat() if last_success else None,
        "integrity_status": integrity,
    }


def reconcile_effective_runtime(request: object) -> dict[str, Any]:
    data = mapping(request, "request")
    exact(
        data,
        {
            "schema_version",
            "captured_at",
            "desired_configs",
            "effective_runtimes",
            "schedules",
            "backups",
        },
        "request",
    )
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    captured_at = _instant(data["captured_at"], "request.captured_at")
    if type(data["desired_configs"]) is not list or not data["desired_configs"]:
        fail("invalid_list", "request.desired_configs", "Требуется непустой список.")
    if type(data["effective_runtimes"]) is not list or not data["effective_runtimes"]:
        fail("invalid_list", "request.effective_runtimes", "Требуется непустой список.")
    if type(data["schedules"]) is not list or type(data["backups"]) is not list:
        fail("invalid_list", "request", "Расписания и копии должны быть списками.")
    desired_rows = [
        _desired(value, index) for index, value in enumerate(data["desired_configs"])
    ]
    effective_rows = [
        _effective(value, index)
        for index, value in enumerate(data["effective_runtimes"])
    ]
    desired_by_key = {_key(row): row for row in desired_rows}
    effective_by_key = {_key(row): row for row in effective_rows}
    if len(desired_by_key) != len(desired_rows):
        fail(
            "duplicate_desired_capability",
            "request.desired_configs",
            "Повтор capability запрещён.",
        )
    if len(effective_by_key) != len(effective_rows):
        fail(
            "duplicate_effective_capability",
            "request.effective_runtimes",
            "Повтор capability запрещён.",
        )
    if set(desired_by_key) != set(effective_by_key):
        fail(
            "capability_set_mismatch",
            "request.effective_runtimes",
            "Наблюдения не совпадают с конфигурацией.",
        )
    capabilities = [
        _capability(desired_by_key[key], effective_by_key[key], captured_at)
        for key in sorted(desired_by_key)
    ]
    profile_contracts: dict[tuple[str, str], dict[str, str]] = {}
    for row in desired_rows:
        profile_contracts.setdefault((row["instance_id"], row["profile_id"]), {})[
            row["operation_id"]
        ] = row["schema_fingerprint"]
    contract_hashes = {
        f"{instance}:{profile}": sha256_json(contract)
        for (instance, profile), contract in sorted(profile_contracts.items())
    }
    parity = len(set(contract_hashes.values())) <= 1
    schedules = [
        _schedule(value, index, captured_at)
        for index, value in enumerate(data["schedules"])
    ]
    backups = [
        _backup(value, index, captured_at)
        for index, value in enumerate(data["backups"])
    ]
    control_failures = [row for row in capabilities if row["status"] != "ready"]
    supporting_failures = [
        {"kind": "schedule", "id": row["schedule_id"], "status": row["computed_status"]}
        for row in schedules
        if row["computed_status"]
        in {"not_scheduled", "failed", "never_succeeded", "stale"}
    ] + [
        {"kind": "backup", "id": row["backup_id"], "status": row["computed_status"]}
        for row in backups
        if row["computed_status"] in {"failed", "never_verified", "stale", "unverified"}
    ]
    if any(
        row["status"] in {"misconfigured", "failed", "open_circuit"}
        for row in capabilities
    ):
        overall = "blocked"
    elif control_failures or supporting_failures or not parity:
        overall = "degraded"
    else:
        overall = "ready"
    return receipt(
        {
            "schema_version": 1,
            "contract": "EffectiveRuntimeReconciliationReceipt",
            "status": overall,
            "captured_at": captured_at.isoformat(),
            "desired_config_snapshot_count": len(desired_rows),
            "effective_runtime_snapshot_count": len(effective_rows),
            "capabilities": capabilities,
            "profile_parity": {
                "status": "pass" if parity else "mismatch",
                "contract_hashes": contract_hashes,
            },
            "schedules": schedules,
            "backups": backups,
            "supporting_control_failures": supporting_failures,
            "restart_storm_prevented": all(
                not row["restart_allowed"]
                for row in capabilities
                if row["failure_class"] in {"permanent", "auth", "config"}
            ),
        }
    )
