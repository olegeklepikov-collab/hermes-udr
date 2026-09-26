"""Native routing is explicit, local, private, and never invokes Docker."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from hermes_foundation_bridge.agentmemory_adapter import AgentMemoryAdapter
from hermes_foundation_bridge.errors import BridgeError
from hermes_foundation_bridge.graphiti_adapter import GraphitiAdapter
from hermes_foundation_bridge.native_runtime import load_native_runtime
from tests.common import native_runtime_fixture


class NativeRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "foundation"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_missing_config_fails_without_container_fallback(self) -> None:
        with patch("hermes_foundation_bridge.native_runtime.subprocess.run") as dispatched:
            for adapter in (AgentMemoryAdapter(self.root), GraphitiAdapter(self.root)):
                with self.assertRaises(BridgeError) as error:
                    adapter._invoke("health")
                self.assertEqual(error.exception.code, "native_runtime_missing")
        dispatched.assert_not_called()

    def test_rejects_remote_targets_embedded_password_and_public_secret(self) -> None:
        config = native_runtime_fixture(self.root)
        path = self.root / "native-runtime.json"
        for change in (
            {"agentmemory_url": "http://192.0.2.1:3111"},
            {"neo4j_uri": "bolt://example.com:7687"},
            {"neo4j_uri": "bolt://neo4j:password@127.0.0.1:7687"},
            {"neo4j_password": "plaintext"},
            {"mode": "docker"},
        ):
            with self.subTest(change=change):
                path.write_text(json.dumps({**config, **change}))
                with self.assertRaises(BridgeError) as error:
                    load_native_runtime(self.root)
                self.assertEqual(error.exception.code, "native_runtime_invalid")
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        secret = Path(config["neo4j_password_file"])
        if os.name != "nt":
            secret.chmod(0o644)
            with self.assertRaises(BridgeError) as error:
                load_native_runtime(self.root)
            self.assertEqual(error.exception.code, "native_runtime_invalid")
        # The real Windows Everyone-ACE rejection is covered in test_platform_io.

    def test_native_dispatch_uses_fixed_worker_and_stdin_connection(self) -> None:
        config = native_runtime_fixture(self.root)
        graph = GraphitiAdapter(self.root)
        memory = AgentMemoryAdapter(self.root)
        result = CompletedProcess([], 0, '{"status":"healthy"}', "")
        with patch("hermes_foundation_bridge.native_runtime.subprocess.run", return_value=result) as dispatched:
            graph._invoke("health")
            graph_call = dispatched.call_args
            memory._invoke("health")
            memory_call = dispatched.call_args
        self.assertEqual(graph_call.args[0][0], sys.executable)
        self.assertEqual(memory_call.args[0][0], sys.executable)
        self.assertEqual(Path(graph_call.args[0][1]).name, "graphiti_worker.py")
        self.assertEqual(Path(memory_call.args[0][1]).name, "agentmemory_worker.mjs")
        self.assertEqual(len(graph_call.args[0]), 2)
        self.assertEqual(len(memory_call.args[0]), 2)
        self.assertEqual(json.loads(graph_call.kwargs["input"])["connection"]["neo4j_password_file"], config["neo4j_password_file"])
        self.assertNotIn("test-only-password", graph_call.kwargs["input"])


if __name__ == "__main__":
    unittest.main()
