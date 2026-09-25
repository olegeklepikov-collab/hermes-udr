"""One bounded Hermes call with durable attempt and tool-free trace."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

try:
    from .file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from .loaded_runtime import RUNTIME_FAILURE_CODES
except ImportError:
    from file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        read_private_bytes,
        write_exclusive_bytes,
        write_exclusive_json,
    )
    from loaded_runtime import RUNTIME_FAILURE_CODES

from hermes_research_report.beta_model import (
    MAX_TOTAL_TOKENS,
    validate_tool_free_observation,
)
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import sha256_json, verify_receipt_hash, with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import verify_runtime

_CLASS_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_PROVIDER_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}$")
_REASONING = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
_MODEL_CLASS_ENV = "HERMES_RESEARCH_MODEL_CLASS"
MAX_WALL_SECONDS = 240
MAX_MODEL_RESPONSE_BYTES = 1_048_576
MAX_MODEL_TRACE_BYTES = 4_000_000
_SESSION_ID = re.compile(r"^[0-9]{8}_[0-9]{6}_[0-9a-f]+$")
_RESERVED = {
    "runtime_snapshot_hash",
    "schema_version",
    "status",
    "run_id",
    "plan_receipt_hash",
    "bootstrap_budget_hash",
    "prompt_sha256",
    "image_sha256",
    "provider",
    "model",
    "reasoning",
    "requested_model_class",
    "model_class_selection_source",
    "model_route_source",
    "model_class_mapping_hash",
    "max_total_tokens",
    "max_estimated_cost_usd",
    "model_calls_limit",
    "retry_allowed",
}


class ModelCallError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _model_selection(config: object, requested_class: object) -> dict[str, Any]:
    """Resolve a named research class, or the operator's Hermes default route."""
    if type(config) is not dict:
        raise ValueError("model_route_invalid")
    research = config.get("research", {})
    if type(research) is not dict:
        raise ValueError("model_class_config_invalid")
    classes = research.get("model_classes")
    default_class = research.get("default_model_class")
    if requested_class is not None and (
        type(requested_class) is not str or not _CLASS_NAME.fullmatch(requested_class)
    ):
        raise ValueError("model_class_invalid")
    if classes is None:
        if requested_class is not None or default_class is not None:
            raise ValueError("model_class_not_configured")
        model_config = config.get("model")
        if type(model_config) is not dict:
            raise ValueError("model_route_invalid")
        provider, model = model_config.get("provider"), model_config.get("default")
        agent = config.get("agent", {})
        if type(agent) is not dict:
            raise ValueError("model_route_invalid")
        configured_reasoning = agent.get("reasoning_effort")
        reasoning = (
            "none"
            if configured_reasoning in (None, "", False)
            else configured_reasoning
        )
        selected_class = None
        source = "hermes_model_default"
        class_source = "not_applicable"
        mapping_hash = None
    else:
        if type(classes) is not dict or not classes:
            raise ValueError("model_class_config_invalid")
        if default_class is not None and (
            type(default_class) is not str or not _CLASS_NAME.fullmatch(default_class)
        ):
            raise ValueError("model_class_config_invalid")
        if any(type(name) is not str or not _CLASS_NAME.fullmatch(name) for name in classes):
            raise ValueError("model_class_config_invalid")
        for entry in classes.values():
            if (
                type(entry) is not dict
                or set(entry) != {"provider", "model", "reasoning"}
                or not _valid_route(entry["provider"], entry["model"], entry["reasoning"])
            ):
                raise ValueError("model_class_config_invalid")
        selected_class = requested_class or default_class
        if selected_class is None:
            raise ValueError("model_class_required")
        if selected_class not in classes:
            raise ValueError("model_class_unknown")
        entry = classes[selected_class]
        provider, model, reasoning = entry["provider"], entry["model"], entry["reasoning"]
        source = "research_model_class"
        class_source = "environment" if requested_class is not None else "configured_default"
        mapping_hash = sha256_json({"model_classes": classes, "default_model_class": default_class})
    if not _valid_route(provider, model, reasoning):
        raise ValueError("model_route_invalid")
    return {
        "provider": provider,
        "model": model,
        "reasoning": reasoning,
        "requested_model_class": selected_class,
        "model_class_selection_source": class_source,
        "model_route_source": source,
        "model_class_mapping_hash": mapping_hash,
    }


def _valid_route(provider: object, model: object, reasoning: object) -> bool:
    return bool(
        type(provider) is str
        and _PROVIDER_NAME.fullmatch(provider)
        and provider != "auto"
        and type(model) is str
        and _MODEL_NAME.fullmatch(model)
        and "://" not in model
        and type(reasoning) is str
        and reasoning in _REASONING
    )


def configured_model_route(
    config: object, requested_class: str | None = None
) -> tuple[str, str, str]:
    selection = _model_selection(config, requested_class)
    return selection["provider"], selection["model"], selection["reasoning"]


def _startup_model_selection() -> dict[str, Any]:
    """Freeze the operator route once for existing module-level consumers."""
    unresolved = {
        "provider": "", "model": "", "reasoning": "",
        "requested_model_class": None, "model_route_source": "unresolved",
        "model_class_selection_source": "unresolved",
        "model_class_mapping_hash": None,
    }
    if not os.environ.get("HERMES_HOME"):
        return unresolved
    try:
        config_module = importlib.import_module("hermes_cli.config")
        return _model_selection(config_module.load_config(), os.environ.get(_MODEL_CLASS_ENV))
    except (ImportError, ValueError, OSError):
        # The call preflight will report the precise failure before any model request.
        return unresolved


def _startup_model_route() -> tuple[str, str, str]:
    selection = _startup_model_selection()
    return selection["provider"], selection["model"], selection["reasoning"]


_STARTUP_SELECTION = _startup_model_selection()
PROVIDER = _STARTUP_SELECTION["provider"]
MODEL = _STARTUP_SELECTION["model"]
REASONING = _STARTUP_SELECTION["reasoning"]


def cost_accounting(
    usage: dict[str, Any], provider: str, selection: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Preserve subscription inclusion without treating zero as a cash price."""
    status, source = usage.get("cost_status"), usage.get("cost_source")
    estimate = usage.get("estimated_cost_usd")
    included = (
        status == "included"
        and source == "none"
        and type(estimate) in (int, float)
        and estimate == 0
    )
    scope = (
        "subscription_included_not_cash_price"
        if included
        else "provider_reported_estimate"
        if type(estimate) in (int, float) and source not in (None, "", "none")
        else "legacy_numeric_estimate"
        if type(estimate) in (int, float) and estimate > 0 and status is None and source is None
        else "unverified"
    )
    return with_receipt_hash(
        {
            "contract": "BetaModelCostAccounting",
            "provider": provider,
            "model": usage.get("model"),
            "requested_model_class": selection.get("requested_model_class") if selection else None,
            "model_class_selection_source": selection.get("model_class_selection_source") if selection else None,
            "model_route_source": selection.get("model_route_source") if selection else None,
            "model_class_mapping_hash": selection.get("model_class_mapping_hash") if selection else None,
            "session_id": usage.get("session_id"),
            "estimated_cost_usd": estimate,
            "cost_status": status,
            "cost_source": source,
            "accounting_scope": scope,
            "numeric_budget_guard_retained": True,
            "cash_price_or_net_value_verified": False,
        }
    )


def _code(error: BaseException) -> str:
    if isinstance(error, ContractError):
        return error.code
    if isinstance(error, subprocess.TimeoutExpired):
        return "model_outcome_unknown_reconcile_first"
    if (
        isinstance(error, ValueError)
        and str(error).replace("_", "").isalnum()
        and len(str(error)) < 80
    ):
        return str(error)
    return "model_input_or_storage_failed"


def _response_bytes(stdout: str) -> tuple[str, bytes]:
    raw = stdout.strip()
    payload = (raw + "\n").encode("utf-8")
    if not raw or len(payload) > MAX_MODEL_RESPONSE_BYTES:
        raise ValueError("model_response_invalid")
    return raw, payload


def prompt_binding_matches(
    content, prompt: str, image_sha256: str | None = None
) -> bool:
    if image_sha256 is None:
        return content == prompt
    if type(content) is not list or len(content) != 2:
        return False
    texts = [
        p.get("text") for p in content if type(p) is dict and p.get("type") == "text"
    ]
    images = []
    for part in content:
        if type(part) is dict and part.get("type") == "image_url":
            if (
                type(part.get("image_url")) is not dict
                or type(part["image_url"].get("url")) is not str
            ):
                return False
            images.append(part["image_url"]["url"])
    if (
        texts != [prompt]
        or len(images) != 1
        or not images[0].startswith("data:image/png;base64,")
    ):
        return False
    try:
        return (
            hashlib.sha256(
                base64.b64decode(images[0].split(",", 1)[1], validate=True)
            ).hexdigest()
            == image_sha256
        )
    except ValueError:
        return False


def vision_binding_matches(
    output: Path, trace: dict, prompt: str, image_sha: str, raw: str,
    provider: str = PROVIDER, model: str = MODEL,
    selection: dict[str, Any] | None = None,
) -> bool:
    content = trace["messages"][0].get("content")
    if prompt_binding_matches(content, prompt, image_sha):
        return True
    try:
        sent, _ = load_json(output / "vision-input.json")
        observed, _ = load_json(output / "vision-observation.json")
        return (
            content in (prompt, prompt + "\n[screenshot]")
            and verify_receipt_hash(sent)
            and verify_receipt_hash(observed)
            and sent.get("image_sha256") == image_sha
            and sent.get("prompt_sha256") == hashlib.sha256(prompt.encode()).hexdigest()
            and sent.get("content_types") == ["text", "image_url"]
            and sent.get("provider") == provider
            and sent.get("model") == model
            and (
                selection is None
                or (
                    sent.get("requested_model_class") == selection["requested_model_class"]
                    and sent.get("model_class_selection_source") == selection["model_class_selection_source"]
                    and sent.get("model_class_mapping_hash") == selection["model_class_mapping_hash"]
                )
            )
            and observed.get("input_receipt_hash") == sent["receipt_hash"]
            and observed.get("session_id") == trace.get("session_id", trace.get("id"))
            and observed.get("response_sha256")
            == hashlib.sha256(raw.encode()).hexdigest()
        )
    except (OSError, ValueError, TypeError):
        return False


def run_tool_free_model(
    *,
    prompt: str,
    hermes: Path,
    output: Path,
    attempt_binding: dict[str, object],
    plan: object | None = None,
    bootstrap_budget: dict[str, object] | None = None,
    preserve_completed_cost_overrun: bool = False,
    image_path: Path | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if type(preserve_completed_cost_overrun) is not bool or (
        preserve_completed_cost_overrun and bootstrap_budget is None
    ):
        raise ModelCallError("model_attempt_binding_invalid")
    if (plan is None) == (bootstrap_budget is None) or set(attempt_binding) & _RESERVED:
        raise ModelCallError("model_attempt_binding_invalid")
    verified = verify_beta_mode_plan(plan) if plan is not None else None
    if verified is not None:
        if verified["schema_version"] != 2:
            raise ModelCallError("model_attempt_binding_invalid")
        run_id = verified["run_id"]
        limit = float(verified["limits"]["max_estimated_cost_usd"])
        wall_seconds = verified["limits"]["wall_seconds"]
        model_calls = verified["limits"]["model_calls"]
        binding = {"plan_receipt_hash": verified["receipt_hash"]}
    else:
        budget = bootstrap_budget
        budget_cost = (
            budget.get("max_estimated_cost_usd") if type(budget) is dict else None
        )
        if (
            type(budget) is not dict
            or set(budget)
            != {
                "schema_version",
                "run_id",
                "wall_seconds",
                "max_estimated_cost_usd",
                "model_calls",
            }
            or budget["schema_version"] != 1
            or type(budget["run_id"]) is not str
            or not re.fullmatch(r"^[A-Z][A-Z0-9-]{2,63}$", budget["run_id"])
            or type(budget["wall_seconds"]) is not int
            or not 1 <= budget["wall_seconds"] <= MAX_WALL_SECONDS
            or type(budget_cost) not in (int, float)
            or not 0 < cast(float, budget_cost) <= 0.02
            or type(budget["model_calls"]) is not int
            or budget["model_calls"] != 1
        ):
            raise ModelCallError("planning_budget_invalid")
        run_id = budget["run_id"]
        limit = float(cast(float, budget_cost))
        wall_seconds = budget["wall_seconds"]
        model_calls = 1
        binding = {"bootstrap_budget_hash": sha256_json(budget)}
    if (
        not hermes.is_absolute()
        or not hermes.is_file()
        or hermes.is_symlink()
        or not os.access(hermes, os.X_OK)
    ):
        raise ModelCallError("hermes_executable_invalid")
    if (
        hermes.name != "hermes"
        or hermes.parent.resolve() != Path(sys.executable).parent.resolve()
    ):
        raise ModelCallError("hermes_python_entrypoint_required")
    token_limit = MAX_TOTAL_TOKENS
    runtime_hash = verify_runtime()
    home = Path(os.environ.get("HERMES_HOME", ""))
    if not home.is_absolute() or not home.is_dir() or home.is_symlink():
        raise ModelCallError("hermes_home_invalid")
    try:
        config_module = importlib.import_module("hermes_cli.config")
        configured = config_module.load_config()
        if configured.get("fallback_model") or configured.get("fallback_providers"):
            raise ValueError("model_fallback_route_not_bounded")
        selection = _model_selection(configured, os.environ.get(_MODEL_CLASS_ENV))
        provider, model, reasoning = (
            selection["provider"], selection["model"], selection["reasoning"]
        )
        if selection != _STARTUP_SELECTION:
            raise ValueError("model_route_changed_since_import")
        model_tools = importlib.import_module("model_tools")
        if model_tools.get_tool_definitions(
            enabled_toolsets=["context_engine"], quiet_mode=True
        ):
            raise ValueError("model_tool_surface_not_empty")
    except (ImportError, ValueError) as error:
        raise ModelCallError(_code(error)) from None
    created = False
    try:
        new_private_directory(output)
        created = True
        image_sha = None
        if image_path is not None:
            image_bytes = read_private_bytes(image_path, maximum=8_000_000)
            if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("vision_png_required")
            image_sha = hashlib.sha256(image_bytes).hexdigest()
        attempt = {
            "schema_version": 1,
            "status": "started_unknown_until_reconciled",
            "run_id": run_id,
            **binding,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "provider": provider,
            "model": model,
            "reasoning": reasoning,
            "requested_model_class": selection["requested_model_class"],
            "model_class_selection_source": selection["model_class_selection_source"],
            "model_route_source": selection["model_route_source"],
            "model_class_mapping_hash": selection["model_class_mapping_hash"],
            "max_total_tokens": token_limit,
            "max_estimated_cost_usd": limit,
            "model_calls_limit": model_calls,
            "retry_allowed": False,
            "runtime_snapshot_hash": runtime_hash,
            **attempt_binding,
            **({"image_sha256": image_sha} if image_sha else {}),
        }
        write_exclusive_json(output / "attempt.json", attempt)
        usage_file = output / "model-usage.json"
        command = [
            str(hermes),
            "-z",
            prompt,
            "--provider",
            provider,
            "-m",
            model,
            "--reasoning",
            reasoning,
            "-t",
            "context_engine",
            "--safe-mode",
            "--usage-file",
            str(usage_file),
        ]
        if image_path is not None:
            request_file = output / "vision-request.json"
            write_exclusive_json(
                request_file,
                {
                    "prompt": prompt,
                    "image": str(image_path),
                    "provider": provider,
                    "model": model,
                    "reasoning": reasoning,
                    "requested_model_class": selection["requested_model_class"],
                    "model_class_selection_source": selection["model_class_selection_source"],
                    "model_class_mapping_hash": selection["model_class_mapping_hash"],
                    "model_route_source": selection["model_route_source"],
                    "usage_file": str(usage_file),
                },
            )
            command = [
                sys.executable,
                str(Path(__file__).with_name("vision_model_worker.py")),
                str(request_file),
            ]
        else:
            command = [
                sys.executable,
                str(Path(__file__).with_name("runtime_model_worker.py")),
                str(output),
                *command,
            ]
        if verify_runtime() != runtime_hash:
            raise ValueError("runtime_configuration_changed")
        completed = subprocess.run(
            command,
            cwd=home,
            capture_output=True,
            text=True,
            check=False,
            timeout=min(wall_seconds, MAX_WALL_SECONDS),
            env={**os.environ, "HERMES_HOME": str(home)},
        )
        if usage_file.is_file():
            usage_file.chmod(0o600)
        if completed.returncode != 0 or not usage_file.is_file():
            runtime_failure = output / "effective-runtime-failure.json"
            if runtime_failure.is_file():
                failure, _ = load_json(runtime_failure)
                if (
                    type(failure) is dict
                    and verify_receipt_hash(failure)
                    and failure.get("reason_code") in RUNTIME_FAILURE_CODES
                ):
                    raise ValueError(failure["reason_code"])
            raise ValueError("model_call_failed_reconcile_first")
        usage_value, _ = load_json(usage_file)
        if type(usage_value) is not dict:
            raise ValueError("model_usage_invalid")
        usage = usage_value
        session_id = usage.get("session_id")
        if type(session_id) is not str or not _SESSION_ID.fullmatch(session_id):
            raise ValueError("model_session_id_invalid")
        raw, payload = _response_bytes(completed.stdout)
        write_exclusive_bytes(output / "model.raw.json", payload)
        try:
            effective, _ = load_json(output / "effective-runtime.json")
            entry, _ = load_json(output / "effective-model-entry.json")
        except (OSError, ValueError):
            raise ValueError("model_effective_runtime_unbound") from None
        if not (
            type(effective) is dict
            and type(entry) is dict
            and verify_receipt_hash(effective)
            and verify_receipt_hash(entry)
            and effective.get("contract") == "LoadedHermesRuntimeSnapshot"
            and entry.get("contract") == "LoadedHermesModelEntry"
            and effective.get("initial_runtime_hash") == runtime_hash
            and entry.get("initial_runtime_hash") == runtime_hash
            and entry.get("runtime_receipt_hash") == effective.get("receipt_hash")
            and entry.get("loaded_config_hash") == effective.get("loaded_config_hash")
        ):
            raise ValueError("model_effective_runtime_unbound")
        exported = subprocess.run(
            [
                str(hermes),
                "sessions",
                "export",
                "--format",
                "jsonl",
                "--session-id",
                session_id,
                "-",
                "--dry-run",
            ],
            cwd=home,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env={**os.environ, "HERMES_HOME": str(home)},
        )
        if (
            exported.returncode != 0
            or len(exported.stdout.encode()) > MAX_MODEL_TRACE_BYTES
        ):
            raise ValueError("model_trace_unavailable")
        trace = json.loads(exported.stdout)
        if type(trace) is not dict:
            raise ValueError("model_trace_invalid")
        write_exclusive_json(output / "model-trace.json", trace)
        if image_sha and not vision_binding_matches(
            output, trace, prompt, image_sha, raw, provider, model, selection
        ):
            raise ValueError("vision_trace_image_not_bound")
        validate_tool_free_observation(
            plan=verified,
            max_estimated_cost_usd=limit if verified is None else None,
            usage=usage,
            trace=trace,
            provider=provider,
            model=model,
            max_total_tokens=token_limit,
            preserve_completed_cost_overrun=preserve_completed_cost_overrun,
        )
        accounting = cost_accounting(usage, provider, selection)
        write_exclusive_json(output / "cost-accounting.json", accounting)
        if accounting["accounting_scope"] == "unverified":
            raise ValueError("model_cost_status_unverified")
        if preserve_completed_cost_overrun:
            write_exclusive_json(
                output / "budget-observation.json",
                {
                    "run_id": run_id,
                    "declared_cost_limit_usd": limit,
                    "observed_cost_usd": usage["estimated_cost_usd"],
                    "cost_limit_exceeded": usage["estimated_cost_usd"] > limit,
                    "completed_response_preserved": True,
                    "additional_calls_authorized": False,
                },
            )
        fsync_directory(output)
        return raw, usage, trace
    except (
        ContractError,
        ImportError,
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
    ) as error:
        code = _code(error)
        if created:
            try:
                write_exclusive_json(
                    output / "failure.json",
                    {
                        "schema_version": 1,
                        "status": "failed_or_unknown",
                        "reason_code": code,
                        "reconciliation_required": True,
                        "retry_allowed": False,
                    },
                )
            except (OSError, ValueError):
                pass
        raise ModelCallError(code) from None
