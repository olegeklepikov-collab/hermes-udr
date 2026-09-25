"""Hermes capability inventory keeps discovery, policy and execution distinct."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from hermes_research_report.research_capabilities import inventory, web_provider
from hermes_research_report.research_workspace import workspace


def entry(name, toolset):
    return SimpleNamespace(name=name, toolset=toolset,
                           description=f"{name} description",
                           schema={"name": name, "description": f"{name} description",
                                   "parameters": {"type": "object"}})


class CapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HERMES_HOME": self.temp.name})
        self.env.start()
        self.run_id = workspace({"action": "start", "question": "Inventory tools"})["run_id"]
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)

    def test_mcp_discovery_precedes_snapshot_and_disabled_server_stays_out(self):
        events = []
        entries = [entry("web_search", "web"), entry("web_extract", "web"),
                   entry("deep_research", "mcp-live"), entry("crawl", "mcp-off")]

        def definitions(*, enabled_toolsets, disabled_toolsets, quiet_mode,
                        skip_tool_search_assembly):
            events.append("full" if skip_tool_search_assembly else "visible")
            names = [row.name for row in entries if row.toolset in enabled_toolsets
                     and row.toolset not in disabled_toolsets]
            if not skip_tool_search_assembly:
                names = [name for name in names if name != "deep_research"] + ["tool_search"]
            return [{"type": "function", "function": {"name": name,
                     "description": name, "parameters": {"type": "object"}}} for name in names]

        fake = SimpleNamespace(
            discover_plugins=lambda: events.append("plugins"),
            load_config=lambda: {"agent": {"disabled_toolsets": ["mcp-off"]}},
            platform_toolsets=lambda _config, _platform: {"web", "mcp-live", "mcp-off"},
            parse_list=lambda value: value,
            enabled_mcp_names=lambda _config: {"mcp-live", "mcp-off"},
            discover_mcp=lambda allowed_mcp_names: events.append(("mcp", allowed_mcp_names)) or ["deep_research"],
            resolve_leaf=lambda parent, _requested, _role: (parent.enabled_toolsets, parent.disabled_toolsets),
            definitions=definitions,
            registry=SimpleNamespace(get_all_entries=lambda: entries),
            web_providers=lambda: [SimpleNamespace(name="configured", supports_search=lambda: True,
                                                    supports_extract=lambda: True)],
            active_search=lambda: SimpleNamespace(name="configured"),
            active_extract=lambda: SimpleNamespace(name="configured"),
        )
        with patch("hermes_research_report.research_capabilities._runtime", return_value=fake):
            result = inventory({"run_id": self.run_id, "summary_limit": 1})
        self.assertEqual(events, ["plugins", ("mcp", ["mcp-live"]), "full", "full", "visible"])
        self.assertEqual(result["exposed_count"], 3)
        self.assertTrue(result["summary_truncated"])
        full = json.loads(Path(result["full_snapshot_path"]).read_text())
        self.assertIn("deep_research", full["exposed_definition_names"])
        self.assertNotIn("crawl", full["exposed_definition_names"])
        self.assertNotIn("deep_research", full["pre_agent_visible_names"])
        self.assertFalse(full["actual_agent_tools_observed"])

    def test_native_web_does_not_imply_crawl_or_grant_missing_parent_toolset(self):
        entries = [entry("web_search", "web"), entry("web_extract", "web")]
        fake = SimpleNamespace(
            discover_plugins=lambda: None, load_config=lambda: {"agent": {}},
            platform_toolsets=lambda _config, _platform: {"web"},
            parse_list=lambda _value: [], enabled_mcp_names=lambda _config: set(),
            discover_mcp=lambda allowed_mcp_names: [],
            resolve_leaf=lambda parent, requested, _role: (
                [name for name in (requested or parent.enabled_toolsets)
                 if name in parent.enabled_toolsets], parent.disabled_toolsets),
            definitions=lambda **kw: [
                {"type": "function", "function": {"name": row.name,
                 "description": row.description, "parameters": {"type": "object"}}}
                for row in entries if row.toolset in kw["enabled_toolsets"]],
            registry=SimpleNamespace(get_all_entries=lambda: entries),
            web_providers=lambda: [],
            active_search=lambda: SimpleNamespace(name="configured-search"),
            active_extract=lambda: SimpleNamespace(name="configured-extract"),
        )
        with patch("hermes_research_report.research_capabilities._runtime", return_value=fake):
            web = inventory({"run_id": self.run_id, "requested_toolsets": ["web"]})
            denied = inventory({"run_id": self.run_id, "requested_toolsets": ["crawl"]})
        self.assertEqual(web["native_web"]["search"]["operation"], "search_only")
        self.assertEqual(web["native_web"]["extract"]["selected_backend"], "configured-extract")
        self.assertEqual(web["native_web"]["other_modes"], "not_implied_by_native_web_tools")
        self.assertEqual(denied["requested_not_in_parent"], ["crawl"])
        self.assertEqual(denied["exposed_count"], 0)

    def test_web_provider_list_is_metadata_and_disabled_tool_prevents_call(self):
        calls = []
        provider = SimpleNamespace(
            name="dynamic-provider", supports_search=lambda: True,
            supports_extract=lambda: False, is_available=lambda: True,
            is_keyless_available=lambda: False,
            search=lambda *_args, **_kwargs: calls.append("search"),
        )
        fake = SimpleNamespace(
            discover_plugins=lambda: None, load_config=lambda: {"agent": {"disabled_toolsets": ["web"]}},
            platform_toolsets=lambda _config, _platform: {"web"},
            parse_list=lambda value: value, web_providers=lambda: [provider],
            web_provider=lambda name: provider if name == provider.name else None,
            definitions=lambda **kw: [] if "web" in kw["disabled_toolsets"] else [
                {"function": {"name": "web_search"}}],
        )
        with patch("hermes_research_report.research_capabilities._runtime", return_value=fake):
            listed = asyncio.run(web_provider({"run_id": self.run_id, "action": "list"}))
            with self.assertRaisesRegex(ValueError, "web_tool_disabled_by_policy"):
                asyncio.run(web_provider({"run_id": self.run_id, "action": "search",
                                          "provider": "dynamic-provider", "query": "topic"}))
        self.assertEqual(listed["providers"][0]["name"], "dynamic-provider")
        self.assertFalse(listed["native_web_search_exposed"])
        self.assertEqual(calls, [])

    def test_async_extract_retains_long_provider_response_without_fulltext_claim(self):
        async def extract(urls):
            return {"success": True, "data": [{"url": urls[0], "content": "X" * 60_000}]}

        provider = SimpleNamespace(
            name="new-service", supports_search=lambda: False,
            supports_extract=lambda: True, is_available=lambda: True,
            is_keyless_available=lambda: False, extract=extract,
        )
        fake = SimpleNamespace(
            discover_plugins=lambda: None, load_config=lambda: {"agent": {}},
            platform_toolsets=lambda _config, _platform: {"web"},
            parse_list=lambda _value: [], web_providers=lambda: [provider],
            web_provider=lambda name: provider if name == provider.name else None,
            definitions=lambda **kw: [{"function": {"name": "web_extract"}}],
        )
        with patch("hermes_research_report.research_capabilities._runtime", return_value=fake), patch("hermes_research_report.research_capabilities._extract_urls", new=AsyncMock(return_value=(["https://example.org/page?format=html"], []))):
            result = asyncio.run(web_provider({"run_id": self.run_id, "action": "extract",
                                               "provider": "new-service",
                                               "urls": ["https://example.org/page?format=html"]}))
        self.assertEqual(result["status"], "provider_response_recorded")
        self.assertEqual(result["text_files"][0]["characters"], 60_000)
        self.assertEqual(Path(result["text_files"][0]["path"]).read_text(), "X" * 60_000)
        self.assertFalse(result["full_text_verified"])
        denied = AsyncMock(return_value=([], [{"index": 0, "reason": "blocked_by_hermes_url_policy"}]))
        provider.extract = AsyncMock()
        with patch("hermes_research_report.research_capabilities._runtime", return_value=fake), patch("hermes_research_report.research_capabilities._extract_urls", new=denied):
            with self.assertRaises(ValueError):
                asyncio.run(web_provider({"run_id": self.run_id, "action": "extract", "provider": "new-service", "urls": ["http://127.0.0.1"]}))
        provider.extract.assert_not_called()



if __name__ == "__main__":
    unittest.main()
