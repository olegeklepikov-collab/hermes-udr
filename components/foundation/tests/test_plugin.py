from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import plugin
from tests.common import state_request


class Context:
    def __init__(self) -> None:
        self.tools: list[dict[str, object]] = []
        self.hooks: list[tuple[str, object]] = []

    def register_tool(self, **kwargs: object) -> None:
        self.tools.append(kwargs)

    def register_hook(self, name: str, callback: object) -> None:
        self.hooks.append((name, callback))


class PluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "foundation"
        self.environment = patch.dict(
            os.environ, {"HERMES_FOUNDATION_ROOT": str(self.root)}, clear=False
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.directory.cleanup()

    def test_exact_public_surface_and_hooks(self) -> None:
        context = Context()
        plugin.register(context)
        self.assertEqual(
            [item["name"] for item in context.tools],
            [
                "foundation_bridge_migrate",
                "foundation_bridge_health",
                "foundation_release_verify",
                "foundation_profiles_migrate",
                "foundation_profiles_health",
                "foundation_profile_get",
                "foundation_handoff_record",
                "foundation_review_position_record",
                "foundation_operator_effect_record",
                "foundation_checkpoint_resume",
                "foundation_merge_assess",
                "foundation_telegram_ingress",
                "foundation_telegram_media",
                "foundation_delivery_prepare",
                "foundation_delivery_reconcile",
                "foundation_delivery_redeliver",
                "foundation_telegram_route",
                "foundation_observability_migrate",
                "foundation_trace_record",
                "foundation_trace_reconcile",
                "foundation_trace_health",
                "foundation_backup_inventory",
                "foundation_recovery_objectives",
                "foundation_restore_assess",
                "foundation_checkpoint_assess",
                "foundation_authority_get",
                "foundation_runtime_lease",
                "foundation_outbox_enqueue",
                "foundation_effective_runtime_reconcile",
                "foundation_failure_suite_assess",
                "foundation_gate_vector_evaluate",
                "foundation_dolt_put",
                "foundation_dolt_get",
                "foundation_dolt_sql_health",
                "foundation_artifact_ingest",
                "foundation_artifact_recover",
                "foundation_artifact_tombstone",
                "foundation_index_migrate",
                "foundation_index_upsert",
                "foundation_index_query",
                "foundation_index_rebuild",
                "foundation_index_tombstone",
                "foundation_graph_migrate",
                "foundation_graph_health",
                "foundation_graph_circuit_get",
                "foundation_graph_fact_put",
                "foundation_graph_search",
                "foundation_graph_tombstone",
                "foundation_memory_migrate",
                "foundation_memory_health",
                "foundation_memory_scope_set",
                "foundation_memory_save",
                "foundation_memory_search",
                "foundation_memory_context",
                "foundation_beads_migrate",
                "foundation_beads_health",
                "foundation_beads_create",
                "foundation_beads_get",
                "foundation_beads_claim",
                "foundation_beads_close",
                "foundation_work_reconcile",
                "foundation_fragment_record",
                "foundation_fragment_promote",
                "foundation_state_reconcile",
            ],
        )
        self.assertEqual(
            [name for name, _callback in context.hooks],
            [
                "on_session_start",
                "pre_llm_call",
                "post_tool_call",
                "post_llm_call",
                "on_session_end",
            ],
        )
        for item in context.tools:
            schema = item["schema"]
            self.assertIsInstance(schema, dict)
            assert isinstance(schema, dict)
            self.assertIs(schema["additionalProperties"], False)

    def test_migration_handlers_dry_run_without_state(self) -> None:
        result = json.loads(
            plugin.handle_migrate({"schema_version": 1, "apply": False})
        )
        self.assertEqual(result["status"], "dry_run_ready")
        self.assertFalse(self.root.exists())

    def test_authority_map_has_eleven_single_writers(self) -> None:
        result = json.loads(plugin.handle_authority({"schema_version": 1}))
        self.assertEqual(result["authority_count"], 11)
        self.assertEqual(result["single_writer_count"], 11)

    def test_reconciliation_uses_public_contract(self) -> None:
        result = json.loads(plugin.handle_reconcile(state_request()))
        self.assertEqual(result["computed_state"], "running")
        self.assertFalse(result["release_allowed"])

    def test_errors_are_closed_and_do_not_echo_unknown_value(self) -> None:
        result = json.loads(
            plugin.handle_migrate(
                {"schema_version": 1, "apply": False, "secret": "must-not-reflect"}
            )
        )
        serialized = json.dumps(result)
        self.assertEqual(result["error"]["code"], "unknown_field")
        self.assertNotIn("must-not-reflect", serialized)


if __name__ == "__main__":
    unittest.main()
