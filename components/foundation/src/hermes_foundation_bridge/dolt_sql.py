"""Authenticated, branch-limited Dolt SQL authority for the foundation writer."""

from __future__ import annotations

import importlib.metadata
import json
import stat
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt, sha256_json
from .config import child
from .native_runtime import assert_private_file
from .dolt_state import DATABASES, _now
from .errors import BridgeError, fail
from .instance_endpoints import instance_endpoints
from .validation import digest, exact, identifier, integer, mapping

AUTHORITY_MANIFEST = {
    "schema_version": 1,
    "mode": "sql_server",
    "host": "127.0.0.1",
    "port": 3317,
    "writer_user": "foundation_writer",
    "writer_credential_ref": ".secrets/writer.password",
    "privilege_file_ref": ".doltcfg/privileges.db",
    "branch_control_file_ref": ".doltcfg/branch_control.db",
    "database_ids": sorted(DATABASES),
    "branch": "main",
    "published_endpoints": [],
    "root_login_allowed_for_bridge": False,
}


def authority_manifest(root: Path) -> dict[str, Any]:
    endpoints = instance_endpoints(root)
    manifest = dict(AUTHORITY_MANIFEST)
    if endpoints["custom"]:
        manifest.update(host=endpoints["dolt_sql_host"], port=endpoints["dolt_sql_port"])
    return manifest


def _pymysql() -> Any:
    try:
        import pymysql  # type: ignore[import-not-found]
    except ImportError as error:
        raise BridgeError(
            "dolt_sql_client_unavailable", "runtime.dolt", "SQL-клиент недоступен."
        ) from error
    if importlib.metadata.version("PyMySQL") != "1.1.2":
        fail(
            "dolt_sql_client_version",
            "runtime.dolt",
            "Версия SQL-клиента не совпадает.",
        )
    return pymysql


class DoltSQLAdapter:
    def __init__(self, root: Path):
        self.foundation = root
        self.expected_manifest = authority_manifest(root)
        self.root = child(root, "dolt")
        self.manifest_path = child(self.root, "sql-authority.json")
        self.credential_path = child(self.root, ".secrets", "writer.password")
        self.privilege_path = child(self.root, ".doltcfg", "privileges.db")
        self.branch_control_path = child(self.root, ".doltcfg", "branch_control.db")

    def _configuration(self) -> str:
        if authority_manifest(self.foundation) != self.expected_manifest:
            fail(
                "instance_endpoints_changed",
                "instance_endpoints",
                "Адреса экземпляра изменились.",
            )
        if self.manifest_path.is_symlink() or not self.manifest_path.is_file():
            fail(
                "dolt_sql_manifest_missing",
                "runtime.dolt",
                "Манифест SQL-службы отсутствует.",
            )
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            fail(
                "dolt_sql_manifest_invalid",
                "runtime.dolt",
                "Манифест SQL-службы повреждён.",
            )
        if manifest != self.expected_manifest:
            fail(
                "dolt_sql_manifest_invalid",
                "runtime.dolt",
                "Манифест SQL-службы не совпадает.",
            )
        for path in (
            self.credential_path,
            self.privilege_path,
            self.branch_control_path,
        ):
            if (
                path.is_symlink()
                or not path.is_file()
                or not stat.S_ISREG(path.stat().st_mode)

            ):
                fail(
                    "dolt_sql_secret_boundary",
                    "runtime.dolt",
                    "Права файла SQL-службы недействительны.",
                )
            try:
                assert_private_file(path)
            except (ValueError, OSError):
                fail("dolt_sql_secret_boundary", "runtime.dolt", "Права файла SQL-службы недействительны.")
        password = self.credential_path.read_text(encoding="ascii").strip()
        if len(password) < 32 or len(password) > 256:
            fail(
                "dolt_sql_credential_invalid",
                "runtime.dolt",
                "Служебный секрет недействителен.",
            )
        return password

    def _connect(self, database: str) -> Any:
        if database not in DATABASES:
            fail("unknown_database", "request.database", "Неизвестна предметная база.")
        password = self._configuration()
        pymysql = _pymysql()
        try:
            return pymysql.connect(
                host=self.expected_manifest["host"],
                port=self.expected_manifest["port"],
                user=self.expected_manifest["writer_user"],
                password=password,
                database=database,
                charset="utf8mb4",
                autocommit=False,
                connect_timeout=5,
                read_timeout=10,
                write_timeout=10,
                cursorclass=pymysql.cursors.DictCursor,
            )
        except pymysql.MySQLError as error:
            raise BridgeError(
                "dolt_sql_unavailable", "runtime.dolt", "SQL-служба недоступна."
            ) from error

    @staticmethod
    def _row(value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        row = dict(value)
        body = row.get("object_json")
        if isinstance(body, str):
            try:
                row["object_json"] = json.loads(body)
            except json.JSONDecodeError:
                fail("dolt_readback_invalid", "runtime.dolt", "JSON объекта повреждён.")
        return row

    def _select(
        self, database: str, project_id: str, object_id: str
    ) -> dict[str, Any] | None:
        connection = self._connect(database)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT project_id,object_id,revision,content_hash,schema_id,object_json,updated_at "
                    "FROM objects WHERE project_id=%s AND object_id=%s",
                    (project_id, object_id),
                )
                return self._row(cursor.fetchone())
        except _pymysql().MySQLError as error:
            raise BridgeError(
                "dolt_sql_read_failed", "runtime.dolt", "SQL-чтение отклонено."
            ) from error
        finally:
            connection.close()

    def health(self, request: object | None = None) -> dict[str, Any]:
        if request is not None:
            data = mapping(request, "request")
            exact(data, {"schema_version"}, "request")
            if data["schema_version"] != 1:
                fail(
                    "unsupported_schema",
                    "request.schema_version",
                    "Поддерживается версия 1.",
                )
        self._configuration()
        databases = []
        for database in sorted(DATABASES):
            connection = self._connect(database)
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT CURRENT_USER() AS principal")
                    principal = cursor.fetchone()["principal"]
                    cursor.execute("SELECT COUNT(*) AS n FROM objects")
                    cursor.fetchone()
                if not str(principal).startswith("foundation_writer@"):
                    fail(
                        "dolt_sql_principal_mismatch",
                        "runtime.dolt",
                        "Подключена неверная учётная запись.",
                    )
                databases.append(database)
            except _pymysql().MySQLError as error:
                raise BridgeError(
                    "dolt_sql_health_failed",
                    "runtime.dolt",
                    "Проверка SQL-службы не прошла.",
                ) from error
            finally:
                connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "DoltSQLAuthorityHealthReceipt",
                "status": "healthy",
                "mode": "sql_server",
                "loopback_only": True,
                "database_ids": databases,
                "database_count": len(databases),
                "writer_user": "foundation_writer",
                "privilege_file_mode": "0600",
                "branch_control_file_mode": "0600",
                "root_login_used": False,
                "credential_value_in_receipt": False,
            }
        )

    def migrate(self, *, apply: bool) -> dict[str, Any]:
        if not apply:
            self._configuration()
            status = "dry_run_ready"
        else:
            status = "applied" if self.health()["status"] == "healthy" else "blocked"
        return receipt(
            {
                "schema_version": 1,
                "contract": "DoltSQLMigrationReceipt",
                "status": status,
                "migration_id": "002_dolt",
                "database_ids": sorted(DATABASES),
                "schema_ddl_performed": False,
                "authority_mode": "sql_server",
                "root_login_used": False,
            }
        )

    def put(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "database",
                "project_id",
                "object_id",
                "expected_revision",
                "content_hash",
                "schema_id",
                "object",
                "operation_id",
                "run_id",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        database = identifier(data["database"], "request.database")
        if database not in DATABASES:
            fail("unknown_database", "request.database", "Неизвестна предметная база.")
        project_id = identifier(data["project_id"], "request.project_id")
        object_id = identifier(data["object_id"], "request.object_id")
        expected = integer(data["expected_revision"], "request.expected_revision")
        content_hash = digest(data["content_hash"], "request.content_hash")
        schema_id = identifier(data["schema_id"], "request.schema_id")
        body = mapping(data["object"], "request.object")
        operation_id = identifier(data["operation_id"], "request.operation_id")
        run_id = identifier(data["run_id"], "request.run_id")
        if content_hash != sha256_json(body):
            fail(
                "object_hash_mismatch",
                "request.content_hash",
                "Хеш объекта не совпадает.",
            )
        connection = self._connect(database)
        pymysql = _pymysql()
        new_revision = expected + 1
        message = (
            f"op:{operation_id} run:{run_id} object:{object_id} rev:{new_revision}"
        )
        try:
            connection.begin()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT revision,content_hash,schema_id,object_json FROM objects "
                    "WHERE project_id=%s AND object_id=%s FOR UPDATE",
                    (project_id, object_id),
                )
                current = self._row(cursor.fetchone())
                current_revision = int(current["revision"]) if current else 0
                if current_revision != expected:
                    connection.rollback()
                    return receipt(
                        {
                            "schema_version": 1,
                            "contract": "DoltStateWriteReceipt",
                            "status": "stale_revision",
                            "database": database,
                            "project_id": project_id,
                            "object_id": object_id,
                            "expected_revision": expected,
                            "current_revision": current_revision,
                            "commit_created": False,
                            "partial_write": False,
                            "authority_mode": "sql_server",
                        }
                    )
                if (
                    current
                    and current["content_hash"] == content_hash
                    and current["schema_id"] == schema_id
                    and current["object_json"] == body
                ):
                    connection.rollback()
                    return receipt(
                        {
                            "schema_version": 1,
                            "contract": "DoltStateWriteReceipt",
                            "status": "no_op",
                            "database": database,
                            "project_id": project_id,
                            "object_id": object_id,
                            "expected_revision": expected,
                            "current_revision": current_revision,
                            "content_hash": content_hash,
                            "schema_id": schema_id,
                            "commit_created": False,
                            "readback_verified": True,
                            "partial_write": False,
                            "authority_mode": "sql_server",
                        }
                    )
                encoded = canonical_bytes(body).decode("utf-8")
                if current is None:
                    cursor.execute(
                        "INSERT INTO objects(project_id,object_id,revision,content_hash,schema_id,object_json,updated_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (
                            project_id,
                            object_id,
                            new_revision,
                            content_hash,
                            schema_id,
                            encoded,
                            _now(),
                        ),
                    )
                else:
                    changed = cursor.execute(
                        "UPDATE objects SET revision=%s,content_hash=%s,schema_id=%s,object_json=%s,updated_at=%s "
                        "WHERE project_id=%s AND object_id=%s AND revision=%s",
                        (
                            new_revision,
                            content_hash,
                            schema_id,
                            encoded,
                            _now(),
                            project_id,
                            object_id,
                            expected,
                        ),
                    )
                    if changed != 1:
                        connection.rollback()
                        fail(
                            "dolt_cas_conflict",
                            "runtime.dolt",
                            "Редакция изменилась при записи.",
                        )
                cursor.execute("CALL DOLT_COMMIT(%s,%s)", ("-am", message))
                result = cursor.fetchone()
                commit_ref = (
                    str(result.get("hash", "")) if isinstance(result, dict) else ""
                )
                if not commit_ref:
                    fail("dolt_commit_missing", "runtime.dolt", "Commit не найден.")
        except BridgeError:
            connection.rollback()
            raise
        except pymysql.MySQLError as error:
            try:
                connection.rollback()
            except pymysql.MySQLError:
                pass
            try:
                observed = self._select(database, project_id, object_id)
            except BridgeError:
                observed = None
            if (
                observed is not None
                and int(observed["revision"]) > expected
                and observed["content_hash"] != content_hash
            ):
                return receipt(
                    {
                        "schema_version": 1,
                        "contract": "DoltStateWriteReceipt",
                        "status": "stale_revision",
                        "database": database,
                        "project_id": project_id,
                        "object_id": object_id,
                        "expected_revision": expected,
                        "current_revision": int(observed["revision"]),
                        "commit_created": False,
                        "partial_write": False,
                        "authority_mode": "sql_server",
                        "post_conflict_readback_verified": True,
                    }
                )
            raise BridgeError(
                "dolt_sql_write_unknown",
                "runtime.dolt",
                "Исход SQL-записи требует сверки.",
            ) from error
        finally:
            connection.close()
        readback = self._select(database, project_id, object_id)
        verified = bool(
            readback
            and int(readback["revision"]) == new_revision
            and readback["content_hash"] == content_hash
            and readback["object_json"] == body
        )
        return receipt(
            {
                "schema_version": 1,
                "contract": "DoltStateWriteReceipt",
                "status": "committed" if verified else "unknown_outcome",
                "database": database,
                "project_id": project_id,
                "object_id": object_id,
                "expected_revision": expected,
                "current_revision": new_revision,
                "content_hash": content_hash,
                "schema_id": schema_id,
                "commit_ref": commit_ref,
                "commit_message": message,
                "commit_created": True,
                "readback_verified": verified,
                "partial_write": not verified,
                "authority_mode": "sql_server",
                "root_login_used": False,
            }
        )

    def get(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data, {"schema_version", "database", "project_id", "object_id"}, "request"
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        database = identifier(data["database"], "request.database")
        project_id = identifier(data["project_id"], "request.project_id")
        object_id = identifier(data["object_id"], "request.object_id")
        row = self._select(database, project_id, object_id)
        return receipt(
            {
                "schema_version": 1,
                "contract": "DoltStateReadReceipt",
                "status": "found" if row else "not_found",
                "database": database,
                "project_id": project_id,
                "object_id": object_id,
                "object_ref": (
                    {
                        "revision": int(row["revision"]),
                        "content_hash": row["content_hash"],
                        "schema_id": row["schema_id"],
                    }
                    if row
                    else None
                ),
                "object": row["object_json"] if row else None,
                "commit_created": False,
                "authority_mode": "sql_server",
            }
        )
