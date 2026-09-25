"""Inventory the configured Hermes research tool surface without invoking tools."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from .research_workspace import root_for, write_json, write_text
from .research_integration import settings as integration_settings


def _runtime():
    # Imports are delayed so this package remains inspectable outside Hermes.
    from hermes_cli.config import load_config_readonly
    from hermes_cli.plugins import discover_plugins
    from hermes_cli.tools_config import _get_platform_tools, enabled_mcp_server_names
    from agent.skill_utils import parse_config_string_list
    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.delegate_tool_toolsets import _resolve_child_toolsets
    from tools.registry import registry
    from model_tools import get_tool_definitions
    from agent.web_search_registry import (
        get_active_extract_provider,
        get_active_search_provider,
        get_provider,
        list_providers,
    )

    return SimpleNamespace(
        load_config=load_config_readonly, discover_plugins=discover_plugins,
        platform_toolsets=_get_platform_tools, enabled_mcp_names=enabled_mcp_server_names,
        discover_mcp=discover_mcp_tools, resolve_leaf=_resolve_child_toolsets,
        registry=registry, definitions=get_tool_definitions,
        parse_list=parse_config_string_list,
        web_providers=list_providers, active_search=get_active_search_provider,
        active_extract=get_active_extract_provider,
        web_provider=get_provider,
    )


def _names(definitions: list[dict]) -> list[str]:
    return [row["function"]["name"] for row in definitions]


def inventory(args: dict) -> dict:
    """Snapshot registered, exposed, and pre-agent-visible tools separately.

    MCP discovery precedes every schema snapshot. Discovery may contact only
    operator-configured MCP servers; this function never invokes a research tool.
    """
    if type(args) is not dict or type(args.get("run_id")) is not str:
        raise ValueError("capability_request_invalid")
    platform = args.get("platform", "cli")
    requested = args.get("requested_toolsets")
    parent_override = args.get("parent_enabled_toolsets")
    disabled_override = args.get("parent_disabled_toolsets")
    limit = args.get("summary_limit", 80)
    if (
        type(platform) is not str or not platform
        or type(limit) is not int or not 1 <= limit <= 200
        or any(value is not None and (type(value) is not list or any(type(item) is not str for item in value))
               for value in (requested, parent_override, disabled_override))
    ):
        raise ValueError("capability_request_invalid")
    root = root_for(args["run_id"])
    if not (root / "run.json").is_file():
        raise ValueError("unknown_research_run")

    runtime = _runtime()
    runtime.discover_plugins()
    config = runtime.load_config()
    parent_enabled = sorted(set(parent_override if parent_override is not None
                                else runtime.platform_toolsets(config, platform)))
    configured_disabled = (config.get("agent") or {}).get("disabled_toolsets", [])
    disabled_names = set(runtime.parse_list(configured_disabled))
    parent_disabled = sorted(disabled_names | set(disabled_override or ()))
    configured_mcp = set(runtime.enabled_mcp_names(config))
    # A disabled or unselected server is never started for this inventory.
    selected_mcp = sorted((configured_mcp & set(parent_enabled)) - set(parent_disabled))
    discovered_mcp_tools = runtime.discover_mcp(allowed_mcp_names=selected_mcp)
    parent = SimpleNamespace(enabled_toolsets=parent_enabled,
                             disabled_toolsets=parent_disabled)
    leaf_enabled, leaf_disabled = runtime.resolve_leaf(parent, requested, "leaf")
    leaf_enabled = list(dict.fromkeys(leaf_enabled))
    leaf_disabled = list(dict.fromkeys(leaf_disabled))

    # Raw definitions are the entire currently exposed surface. Ordinary
    # definitions may collapse plugin/MCP tools behind Hermes Tool Search.
    parent_defs = runtime.definitions(enabled_toolsets=parent_enabled, disabled_toolsets=parent_disabled, quiet_mode=True, skip_tool_search_assembly=True)
    full_defs = runtime.definitions(enabled_toolsets=leaf_enabled,
                                    disabled_toolsets=leaf_disabled,
                                    quiet_mode=True, skip_tool_search_assembly=True)
    visible_defs = runtime.definitions(enabled_toolsets=leaf_enabled,
                                       disabled_toolsets=leaf_disabled,
                                       quiet_mode=True, skip_tool_search_assembly=False)
    exposed = set(_names(full_defs))
    registered = sorted(runtime.registry.get_all_entries(), key=lambda row: row.name)
    rows = [{"name": row.name, "toolset": row.toolset,
             "description": row.description or row.schema.get("description", ""),
             "registered": True, "exposed_by_policy_and_check": row.name in exposed,
             "schema": row.schema} for row in registered]
    by_name = {row["name"]: row for row in rows}
    for definition in full_defs:
        name = definition["function"]["name"]
        if name not in by_name:
            rows.append({"name": name, "toolset": "agent_dynamic",
                         "description": definition["function"].get("description", ""),
                         "registered": False, "exposed_by_policy_and_check": True,
                         "schema": definition["function"]})

    providers = []
    for provider in runtime.web_providers():
        providers.append({"name": provider.name,
                          "declares_search": bool(provider.supports_search()),
                          "declares_extract": bool(provider.supports_extract()),
                          "availability": "not_probed", "effectiveness": "not_tested"})
    active_search = runtime.active_search() if "web_search" in exposed else None
    active_extract = runtime.active_extract() if "web_extract" in exposed else None
    native_web = {
        "search": {"tool_exposed": "web_search" in exposed,
                   "selected_backend": getattr(active_search, "name", None),
                   "operation": "search_only"},
        "extract": {"tool_exposed": "web_extract" in exposed,
                    "selected_backend": getattr(active_extract, "name", None),
                    "operation": "extract_only"},
        "other_modes": "not_implied_by_native_web_tools",
    }
    payload = {"schema_version": 1, "contract": "ResearchRuntimeCapabilityInventory",
               "run_id": args["run_id"], "platform": platform,
               "parent_enabled_toolsets": parent_enabled,
               "parent_disabled_toolsets": parent_disabled,
               "parent_definition_names": _names(parent_defs),
               "requested_leaf_toolsets": requested,
               "requested_not_in_parent": sorted(set(requested or ()) - set(leaf_enabled)),
               "leaf_enabled_toolsets": leaf_enabled,
               "leaf_disabled_toolsets": leaf_disabled,
               "configured_selected_mcp_servers": selected_mcp,
               "mcp_discovered_tool_names": sorted(set(discovered_mcp_tools or ())),
               "registered_count": len(registered),
               "exposed_definition_names": sorted(exposed),
               "pre_agent_visible_names": _names(visible_defs),
               "actual_agent_tools_observed": False,
               "service_effectiveness_tested": False,
               "native_web": native_web,
               "registered_web_provider_metadata": providers,
               "tools": sorted(rows, key=lambda row: row["name"])}
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > 20_000_000:
        raise ValueError("capability_snapshot_over_limit")
    directory = root / "capabilities"
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / (uuid4().hex + ".json")
    write_json(target, payload)
    target.chmod(0o600)
    index = [{"name": row["name"], "toolset": row["toolset"],
              "description": row["description"][:180],
              "exposed": row["exposed_by_policy_and_check"]}
             for row in payload["tools"] if row["exposed_by_policy_and_check"]]
    return {"status": "inventory_recorded", "run_id": args["run_id"],
            "registered_count": len(registered), "exposed_count": len(exposed),
            "parent_enabled_toolsets": parent_enabled, "parent_disabled_toolsets": parent_disabled,
            "parent_definition_names": _names(parent_defs),
            "summary": index[:limit], "summary_truncated": len(index) > limit,
            "native_web": native_web,
            "configured_selected_mcp_servers": selected_mcp,
            "requested_not_in_parent": payload["requested_not_in_parent"],
            "leaf_enabled_toolsets": leaf_enabled,
            "actual_agent_tools_observed": False,
            "service_effectiveness_tested": False,
            "full_snapshot_path": str(target)}


def _web_policy(runtime, config: dict, platform: str) -> set[str]:
    enabled = sorted(runtime.platform_toolsets(config, platform))
    disabled = runtime.parse_list((config.get("agent") or {}).get("disabled_toolsets", []))
    definitions = runtime.definitions(enabled_toolsets=enabled,
                                      disabled_toolsets=disabled,
                                      quiet_mode=True, skip_tool_search_assembly=True)
    return set(_names(definitions))


def _content_fields(value):
    """Find provider-returned text, without asserting it is a complete original."""
    if isinstance(value, list):
        for item in value:
            yield from _content_fields(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"content", "raw_content", "markdown", "text"} and isinstance(item, str):
                yield item
            elif isinstance(item, (dict, list)):
                yield from _content_fields(item)


async def _extract_urls(urls):
    # Use the host's URL/secret/SSRF policy, not a narrower or weaker UDR copy.
    from tools.web_tools_extract import _validate_extract_urls
    from tools.url_safety import async_is_safe_url
    normalized, indices, invalid, blocked = _validate_extract_urls(urls)
    if blocked is not None:
        raise ValueError("extract_urls_rejected_by_hermes")
    safe, rejected = [], [{"index": i, "reason": "invalid_or_sensitive_url"} for i in invalid]
    for index, url in zip(indices, normalized):
        if await async_is_safe_url(url):
            safe.append(url)
        else:
            rejected.append({"index": index, "reason": "blocked_by_hermes_url_policy"})
    return safe, rejected


async def web_provider(args: dict) -> dict:
    """Use one registered Hermes web provider ABI, never a vendor SDK.

    `list` is local metadata. `search` and `extract` use the operator's existing
    Hermes registration and policy; they perform network calls. Provider output
    is saved whole, never returned inline.
    """
    if type(args) is not dict or type(args.get("run_id")) is not str:
        raise ValueError("web_provider_request_invalid")
    action = args.get("action")
    platform = args.get("platform", "cli")
    if action not in {"list", "search", "extract"} or type(platform) is not str:
        raise ValueError("web_provider_request_invalid")
    root = root_for(args["run_id"])
    if not (root / "run.json").is_file():
        raise ValueError("unknown_research_run")
    runtime = _runtime()
    runtime.discover_plugins()
    config = runtime.load_config()
    exposed = _web_policy(runtime, config, platform)
    providers = runtime.web_providers()
    if action == "list":
        return {"status": "registered_provider_inventory", "run_id": args["run_id"],
                "native_web_search_exposed": "web_search" in exposed,
                "native_web_extract_exposed": "web_extract" in exposed,
                "providers": [{"name": p.name,
                               "search": bool(p.supports_search()),
                               "extract": bool(p.supports_extract()),
                               "keyed_available": bool(p.is_available()),
                               "keyless_available": bool(p.is_keyless_available()),
                               "effectiveness": "not_tested"} for p in providers]}
    native_name = "web_search" if action == "search" else "web_extract"
    if native_name not in exposed:
        raise ValueError("web_tool_disabled_by_policy")
    name = args.get("provider")
    if type(name) is not str or not name:
        raise ValueError("provider_name_missing")
    provider = runtime.web_provider(name)
    if provider is None or not (provider.supports_search() if action == "search"
                                else provider.supports_extract()):
        raise ValueError("provider_operation_not_registered")
    integration = integration_settings()
    allowed = integration.get("web_provider_allowlist")
    if integration["integration_mode"] == "foundation" and allowed is None:
        allowed = {}
    if allowed is not None and action not in allowed.get(name, []):
        raise ValueError("provider_operation_not_enabled_for_profile")
    keyed = bool(provider.is_available())
    keyless = bool(provider.is_keyless_available())
    if not keyed and not keyless:
        raise ValueError("provider_unavailable")
    rejected_urls = []
    if action == "search":
        query, limit = args.get("query"), args.get("limit", 5)
        if type(query) is not str or not query.strip() or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("search_request_invalid")
        request = {"query": query, "limit": limit}
        response = provider.search(query, limit=limit)
    else:
        urls = args.get("urls")
        if type(urls) is not list or not urls:
            raise ValueError("extract_request_invalid")
        urls, rejected_urls = await _extract_urls(urls)
        if not urls:
            raise ValueError("no_eligible_extract_urls")
        request = {"urls": urls}
        response = provider.extract(urls)
    if inspect.isawaitable(response):
        response = await response
    # The public ABI returns JSON-compatible data; a non-serializable result is
    # a provider contract failure, not a reason to omit or truncate material.
    encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode()
    folder = root / "provider-calls" / uuid4().hex
    folder.mkdir(parents=True, mode=0o700)
    response_path = folder / "response.json"
    write_json(response_path, response)
    response_path.chmod(0o600)
    text_rows = []
    for number, content in enumerate(_content_fields(response), 1):
        path = folder / f"content-{number:03d}.txt"
        write_text(path, content)
        path.chmod(0o600)
        text_rows.append({"path": str(path), "characters": len(content),
                          "sha256": hashlib.sha256(content.encode()).hexdigest()})
    metadata = {"schema_version": 1, "provider": name, "action": action,
                "request": request, "rejected_urls": rejected_urls, "response_sha256": hashlib.sha256(encoded).hexdigest(),
                "response_path": str(response_path), "text_files": text_rows,
                "provider_reported_success": response.get("success") if isinstance(response, dict) else None,
                "original_http_bytes_verified": False, "full_text_verified": False,
                "billing_status": "not_measured_by_this_adapter"}
    metadata_path = folder / "metadata.json"
    write_json(metadata_path, metadata)
    metadata_path.chmod(0o600)
    return {"status": "provider_response_recorded", "provider": name,
            "action": action, "rejected_urls": rejected_urls, "response_path": str(response_path),
            "response_sha256": metadata["response_sha256"],
            "text_files": text_rows[:5], "text_file_count": len(text_rows),
            "metadata_path": str(metadata_path),
            "provider_reported_success": metadata["provider_reported_success"],
            "original_http_bytes_verified": False, "full_text_verified": False}


def session_platform():
    from gateway.session_context import get_session_env
    return get_session_env("HERMES_SESSION_PLATFORM") or "cli"


async def provider_tool(args, **kwargs):
    # Platform is runtime-owned; a model must not select a more permissive channel.
    request = {k: v for k, v in args.items() if k in ("run_id", "action", "provider", "query", "limit", "urls")}
    request["platform"] = session_platform()
    try:
        result = await web_provider(request)
    except ValueError as error:
        result = {"status": "error", "code": str(error)}
    except Exception as error:
        result = {"status": "error", "code": "provider_call_failed", "error_type": type(error).__name__}
    return json.dumps(result, ensure_ascii=False, allow_nan=False)


PROVIDER_SCHEMA = {"name": "research_web_provider", "description": "List or explicitly use any registered, enabled Hermes web provider through its public search/extract interface, without changing the default backend. Calls may use provider quota. Other service modes are accessed through their dedicated connected plugin/MCP tools, not invented here. Whole provider responses are saved to workspace files.", "parameters": {"type": "object", "properties": {"run_id": {"type": "string"}, "action": {"type": "string", "enum": ["list", "search", "extract"]}, "provider": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "urls": {"type": "array", "items": {"type": "string"}}}, "required": ["run_id", "action"], "additionalProperties": False}}
