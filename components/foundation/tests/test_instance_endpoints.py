"""Isolated local endpoint mapping without starting containers or SQL."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from hermes_foundation_bridge.agentmemory_adapter import (
    MEMORY_MANIFEST,
    AgentMemoryAdapter,
    memory_manifest,
)
from hermes_foundation_bridge.dolt_sql import (
    AUTHORITY_MANIFEST,
    DoltSQLAdapter,
    authority_manifest,
)
from hermes_foundation_bridge.errors import BridgeError
from hermes_foundation_bridge.graphiti_adapter import (
    GRAPH_MANIFEST,
    GraphitiAdapter,
    graph_manifest,
)
from hermes_foundation_bridge.instance_endpoints import instance_endpoints
from scripts.manage_dolt_sql import manage
from scripts.provision_dolt_sql import provision
from tests.common import native_runtime_fixture


class InstanceEndpointsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "foundation"
        self.root.mkdir()
        native_runtime_fixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def custom(self) -> None:
        path = self.root / "instance-endpoints.json"
        path.write_text(
            json.dumps({"schema_version": 1, "prefix": "e2e44", "dolt_sql_port": 43317})
        )
        path.chmod(0o600)

    def test_default_manifests_remain_byte_equivalent(self) -> None:
        self.assertEqual(graph_manifest(self.root), GRAPH_MANIFEST)
        self.assertEqual(memory_manifest(self.root), MEMORY_MANIFEST)
        self.assertEqual(authority_manifest(self.root), AUTHORITY_MANIFEST)

    def test_custom_manifest_and_loopback_port_are_root_bound(self) -> None:
        self.custom()
        endpoints = instance_endpoints(self.root)
        self.assertEqual(endpoints["network"], "e2e44-net")
        self.assertEqual(graph_manifest(self.root)["graph_backend"], "neo4j")
        self.assertEqual(memory_manifest(self.root)["runtime_kind"], "native")
        self.assertEqual(authority_manifest(self.root)["host"], "127.0.0.1")
        self.assertEqual(authority_manifest(self.root)["port"], 43317)
        for name in AUTHORITY_MANIFEST["database_ids"]:
            (self.root / "dolt" / name / ".dolt").mkdir(parents=True)
        admin = Path(self.temporary.name) / "admin"
        self.assertEqual(provision(self.root, admin, apply=False)["port"], 43317)
        self.assertEqual(manage(self.root, "status")["loopback_port"], 43317)

    def test_custom_endpoints_do_not_change_native_worker_routing(self) -> None:
        self.custom()
        graph = GraphitiAdapter(self.root)
        with patch("hermes_foundation_bridge.graphiti_adapter.invoke_worker", return_value={"status":"healthy"}) as dispatched:
            graph._invoke("health")
        self.assertEqual(dispatched.call_args.args[2]["connection"]["neo4j_uri"], "bolt://127.0.0.1:7687")
        memory = AgentMemoryAdapter(self.root)
        with patch("hermes_foundation_bridge.agentmemory_adapter.invoke_worker", return_value={"status":"healthy"}) as dispatched:
            memory._invoke("health")
        self.assertEqual(dispatched.call_args.args[2]["connection"]["agentmemory_url"], "http://127.0.0.1:3111")

    def test_offline_provision_writes_custom_port_and_exact_manifest(self) -> None:
        self.custom()
        for name in AUTHORITY_MANIFEST["database_ids"]:
            (self.root / "dolt" / name / ".dolt").mkdir(parents=True)

        def offline_dolt(*args, **_kwargs):
            self.assertEqual(args[0][0], "dolt")
            config = self.root / "dolt/.doltcfg"
            config.mkdir(mode=0o700)
            for name in ("privileges.db", "branch_control.db"):
                target = config / name
                target.write_bytes(b"controlled offline authority")
                target.chmod(0o600)
            return CompletedProcess(args[0], 0, "", "")

        with patch(
            "scripts.provision_dolt_sql.subprocess.run", side_effect=offline_dolt
        ):
            result = provision(
                self.root, Path(self.temporary.name) / "admin", apply=True
            )
        self.assertEqual(result["status"], "provisioned_offline")
        self.assertEqual(result["port"], 43317)
        self.assertIn("port: 43317", (self.root / "dolt/server.yaml").read_text())
        self.assertEqual(
            json.loads((self.root / "dolt/sql-authority.json").read_text()),
            authority_manifest(self.root),
        )
        self.assertNotEqual(authority_manifest(self.root), AUTHORITY_MANIFEST)

    def test_manifest_mismatch_and_unsafe_config_are_rejected(self) -> None:
        self.custom()
        graph = GraphitiAdapter(self.root)
        graph.manifest_path.parent.mkdir()
        graph.manifest_path.write_text(json.dumps({**GRAPH_MANIFEST, "graph_backend": "falkordb"}))
        with self.assertRaises(BridgeError) as error:
            graph._ready()
        self.assertEqual(error.exception.code, "graph_manifest_conflict")
        memory = AgentMemoryAdapter(self.root)
        memory.manifest_path.parent.mkdir()
        memory.manifest_path.write_text(json.dumps({**MEMORY_MANIFEST, "runtime_kind": "container"}))
        with self.assertRaises(BridgeError) as error:
            memory._ready()
        self.assertEqual(error.exception.code, "memory_manifest_conflict")
        dolt = DoltSQLAdapter(self.root)
        dolt.manifest_path.parent.mkdir()
        dolt.manifest_path.write_text(json.dumps(AUTHORITY_MANIFEST))
        with self.assertRaises(BridgeError) as error:
            dolt._configuration()
        self.assertEqual(error.exception.code, "dolt_sql_manifest_invalid")
        path = self.root / "instance-endpoints.json"
        for value in (
            {
                "schema_version": 1,
                "prefix": "hermes-foundation",
                "dolt_sql_port": 43317,
            },
            {"schema_version": 1, "prefix": "e2e44", "dolt_sql_port": 3317},
            {"schema_version": 1, "prefix": "e2e44", "dolt_sql_port": True},
            {"schema_version": 1.0, "prefix": "e2e44", "dolt_sql_port": 43317},
        ):
            path.write_text(json.dumps(value))
            with self.assertRaises(BridgeError) as error:
                instance_endpoints(self.root)
            self.assertEqual(error.exception.code, "instance_endpoints_invalid")
        path.write_text(
            json.dumps({"schema_version": 1, "prefix": "e2e45", "dolt_sql_port": 43318})
        )
        for operation, code in ((graph._ready, "graph_manifest_conflict"),
                                (memory._ready, "memory_manifest_conflict"),
                                (dolt._configuration, "instance_endpoints_changed")):
            with self.assertRaises(BridgeError) as error:
                operation()
            self.assertEqual(error.exception.code, code)
