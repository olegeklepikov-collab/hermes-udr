from __future__ import annotations

import importlib.util
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from hermes_foundation_bridge.bridge import services
from hermes_foundation_bridge.canonical import sha256_json
from hermes_foundation_bridge.dolt_sql import AUTHORITY_MANIFEST, DoltSQLAdapter
from hermes_foundation_bridge.dolt_state import DoltStateAdapter
from hermes_foundation_bridge.errors import BridgeError
from hermes_foundation_bridge.native_runtime import assert_private_file
from scripts.provision_dolt_sql import provision


@unittest.skipUnless(
    shutil.which("dolt") and importlib.util.find_spec("pymysql"),
    "Dolt and PyMySQL are required",
)
class DoltSQLAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "foundation"
        self.root.mkdir()
        self.admin_secrets = Path(self.directory.name) / "admin-secrets"
        DoltStateAdapter(self.root).migrate(apply=True)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.port_patch = patch.dict(AUTHORITY_MANIFEST, {"port": self.port})
        self.port_patch.start()
        self.process: subprocess.Popen[bytes] | None = None

    def tearDown(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
            if self.process.stdout is not None:
                self.process.stdout.close()
            if self.process.stderr is not None:
                self.process.stderr.close()
        self.port_patch.stop()
        self.directory.cleanup()

    def start_server(self) -> None:
        self.process = subprocess.Popen(
            [
                "dolt",
                "sql-server",
                "--config",
                str(self.root / "dolt" / "server.yaml"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _attempt in range(40):
            assert self.process is not None
            if self.process.poll() is not None:
                stdout = self.process.stdout
                stderr = self.process.stderr
                assert stdout is not None and stderr is not None
                detail = (stdout.read() + stderr.read()).decode(
                    "utf-8", errors="replace"
                )[-500:]
                self.fail(f"Dolt server exited: {detail}")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                if probe.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.25)
        self.fail("Dolt server did not start")

    def request(self, operation: str, expected: int, value: int) -> dict:
        body = {"value": value}
        return {
            "schema_version": 1,
            "database": "kw_core",
            "project_id": "SQL-TEST",
            "object_id": "OBJECT-1",
            "expected_revision": expected,
            "content_hash": sha256_json(body),
            "schema_id": "SQLFixture-v1",
            "object": body,
            "operation_id": operation,
            "run_id": "RUN-SQL",
        }

    def test_offline_provision_and_authenticated_cas_history(self) -> None:
        dry = provision(self.root, self.admin_secrets, apply=False)
        self.assertEqual(dry["status"], "dry_run_ready")
        self.assertFalse((self.root / "dolt" / ".doltcfg").exists())
        applied = provision(self.root, self.admin_secrets, apply=True)
        self.assertEqual(applied["status"], "provisioned_offline")
        self.assertFalse(applied["server_started"])
        self.assertIsInstance(services(self.root)[2], DoltSQLAdapter)
        assert_private_file(self.root / "dolt" / ".secrets" / "writer.password")
        assert_private_file(self.admin_secrets / "dolt-admin.password")
        self.start_server()
        adapter = DoltSQLAdapter(self.root)
        self.assertEqual(adapter.health()["status"], "healthy")
        import pymysql  # pyright: ignore[reportMissingModuleSource]

        with (
            adapter._connect("kw_core") as connection,
            connection.cursor() as cursor,
            self.assertRaises(pymysql.MySQLError),
        ):
            cursor.execute("SHOW GRANTS FOR CURRENT_USER")
        admin_password = (
            (self.admin_secrets / "dolt-admin.password").read_text().strip()
        )
        with (
            pymysql.connect(
                host="127.0.0.1",
                port=self.port,
                user="foundation_admin",
                password=admin_password,
                database="kw_core",
                connect_timeout=5,
            ) as admin,
            admin.cursor() as cursor,
        ):
            cursor.execute("SHOW GRANTS FOR 'foundation_writer'@'localhost'")
            grants = " ".join(str(value) for row in cursor.fetchall() for value in row)
        self.assertNotIn(" FILE ", f" {grants} ")
        self.assertNotIn(" SUPER ", f" {grants} ")
        self.assertNotIn(" CREATE ", f" {grants} ")
        self.assertNotIn(" DROP ", f" {grants} ")
        self.assertEqual(adapter.migrate(apply=True)["status"], "applied")
        first = adapter.put(self.request("OP-SQL-1", 0, 1))
        stale = adapter.put(self.request("OP-SQL-2", 0, 2))
        no_op = adapter.put(self.request("OP-SQL-3", 1, 1))
        read = adapter.get(
            {
                "schema_version": 1,
                "database": "kw_core",
                "project_id": "SQL-TEST",
                "object_id": "OBJECT-1",
            }
        )
        self.assertEqual(first["status"], "committed")
        self.assertTrue(first["readback_verified"])
        self.assertTrue(first["commit_ref"])
        self.assertEqual(stale["status"], "stale_revision")
        self.assertFalse(stale["partial_write"])
        self.assertEqual(no_op["status"], "no_op")
        self.assertEqual(read["object"], {"value": 1})
        self.assertEqual(read["authority_mode"], "sql_server")

    def test_manifest_and_credential_are_hard_gates(self) -> None:
        provision(self.root, self.admin_secrets, apply=True)
        adapter = DoltSQLAdapter(self.root)
        self.assertGreaterEqual(len(adapter._configuration()), 32)
        manifest = adapter.manifest_path
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["host"] = "0.0.0.0"
        manifest.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "не совпадает"):
            adapter._configuration()

    def test_sql_and_branch_denials_are_independent(self) -> None:
        import pymysql  # pyright: ignore[reportMissingModuleSource]

        provision(self.root, self.admin_secrets, apply=True)
        self.start_server()
        adapter = DoltSQLAdapter(self.root)
        with adapter._connect("kw_core") as writer, writer.cursor() as cursor:
            with self.assertRaises(pymysql.MySQLError):
                cursor.execute("CREATE TABLE forbidden_by_sql (id INT)")
            writer.rollback()
        admin_password = (
            (self.admin_secrets / "dolt-admin.password").read_text().strip()
        )
        with self.assertRaises(pymysql.err.OperationalError):
            pymysql.connect(
                host="127.0.0.1",
                port=self.port,
                user="root",
                password="",
                database="kw_core",
                connect_timeout=5,
            )
        branch_password = secrets.token_urlsafe(40)
        admin = pymysql.connect(
            host="127.0.0.1",
            port=self.port,
            user="foundation_admin",
            password=admin_password,
            database="kw_core",
            autocommit=True,
            connect_timeout=5,
        )
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    "CREATE USER 'fixture_branch_probe'@'localhost' IDENTIFIED BY %s",
                    (branch_password,),
                )
                cursor.execute(
                    "GRANT SELECT, INSERT ON kw_core.* TO 'fixture_branch_probe'@'localhost'"
                )
                cursor.execute(
                    "INSERT INTO dolt_branch_control (`database`,`branch`,`user`,`host`,`permissions`) "
                    "VALUES ('kw_core','main','fixture_branch_probe','localhost','read')"
                )
        finally:
            admin.close()
        probe = pymysql.connect(
            host="127.0.0.1",
            port=self.port,
            user="fixture_branch_probe",
            password=branch_password,
            database="kw_core",
            autocommit=False,
            connect_timeout=5,
        )
        try:
            with probe.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM objects")
                cursor.fetchone()
                with self.assertRaisesRegex(
                    pymysql.MySQLError, "permissions on branch"
                ):
                    cursor.execute(
                        "INSERT INTO objects(project_id,object_id,revision,content_hash,schema_id,object_json,updated_at) "
                        "VALUES (%s,%s,1,%s,%s,%s,%s)",
                        ("PROBE", "DENIED", "a" * 64, "Fixture-v1", "{}", "2026-09-16"),
                    )
            probe.rollback()
        finally:
            probe.close()
        if os.name != "nt":
            # Dolt rewrites its branch file with broad POSIX mode during this test.
            with self.assertRaisesRegex(ValueError, "Права файла SQL-службы"):
                adapter._configuration()
            adapter.branch_control_path.chmod(0o600)
        self.assertEqual(
            adapter.get(
                {
                    "schema_version": 1,
                    "database": "kw_core",
                    "project_id": "PROBE",
                    "object_id": "DENIED",
                }
            )["status"],
            "not_found",
        )

    def test_managed_staging_lifecycle(self) -> None:
        from scripts.manage_dolt_sql import manage

        provision(self.root, self.admin_secrets, apply=True)
        try:
            started = manage(self.root, "start")
            self.assertEqual(started["status"], "running")
            self.assertEqual(manage(self.root, "status")["status"], "running")
            self.assertEqual(DoltSQLAdapter(self.root).health()["status"], "healthy")
        finally:
            stopped = manage(self.root, "stop")
        self.assertEqual(stopped["status"], "stopped")
        self.assertFalse((self.root / "dolt" / "server.pid").exists())

    def test_concurrent_expected_revision_has_no_double_commit(self) -> None:
        provision(self.root, self.admin_secrets, apply=True)
        self.start_server()
        adapter = DoltSQLAdapter(self.root)

        def attempt(request: dict) -> str:
            try:
                return adapter.put(request)["status"]
            except BridgeError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    attempt,
                    [
                        self.request("OP-PARALLEL-A", 0, 1),
                        self.request("OP-PARALLEL-B", 0, 2),
                    ],
                )
            )
        self.assertEqual(sorted(outcomes), ["committed", "stale_revision"])
        read = adapter.get(
            {
                "schema_version": 1,
                "database": "kw_core",
                "project_id": "SQL-TEST",
                "object_id": "OBJECT-1",
            }
        )
        self.assertEqual(read["object_ref"]["revision"], 1)
        self.assertIn(read["object"]["value"], {1, 2})
        self.assertNotIn("unknown_outcome", outcomes)

    def test_concurrent_update_has_one_revision_two(self) -> None:
        provision(self.root, self.admin_secrets, apply=True)
        self.start_server()
        adapter = DoltSQLAdapter(self.root)
        self.assertEqual(
            adapter.put(self.request("OP-INITIAL", 0, 1))["status"], "committed"
        )

        def attempt(request: dict) -> str:
            try:
                return adapter.put(request)["status"]
            except BridgeError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    attempt,
                    [
                        self.request("OP-UPDATE-A", 1, 2),
                        self.request("OP-UPDATE-B", 1, 3),
                    ],
                )
            )
        self.assertEqual(sorted(outcomes), ["committed", "stale_revision"])
        read = adapter.get(
            {
                "schema_version": 1,
                "database": "kw_core",
                "project_id": "SQL-TEST",
                "object_id": "OBJECT-1",
            }
        )
        self.assertEqual(read["object_ref"]["revision"], 2)
        self.assertIn(read["object"]["value"], {2, 3})


if __name__ == "__main__":
    unittest.main()
