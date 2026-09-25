"""Least-privilege-shaped Dolt state adapter using the public Dolt CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt, sha256_json
from .config import child
from .errors import BridgeError, fail
from .validation import digest, exact, identifier, integer, mapping

DATABASES = {"kw_core", "kw_context", "kw_quant", "kw_registry"}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _literal(value: str) -> str:
    return "CONVERT(X'" + value.encode("utf-8").hex() + "' USING utf8mb4)"


class DoltStateAdapter:
    def __init__(self, root: Path, executable: str = "dolt"):
        self.root = child(root, "dolt")
        self.executable = executable

    @staticmethod
    def migration_path() -> Path:
        return Path(__file__).resolve().parents[2] / "migrations" / "002_dolt.sql"

    def _run(self, database_root: Path, *arguments: str) -> str:
        executable = shutil.which(self.executable)
        if not executable:
            fail("dolt_unavailable", "runtime.dolt", "Dolt CLI недоступен.")
        completed = subprocess.run(
            [executable, *arguments],
            cwd=database_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise BridgeError(
                "dolt_command_failed", "runtime.dolt", "Операция Dolt отклонена."
            )
        return completed.stdout

    def _database_root(self, name: str) -> Path:
        if name not in DATABASES:
            fail("unknown_database", "request.database", "Неизвестна предметная база.")
        return child(self.root, name)

    def migrate(self, *, apply: bool) -> dict[str, Any]:
        path = self.migration_path()
        if not path.is_file() or path.is_symlink():
            fail("migration_missing", "migrations.002_dolt", "Миграция недоступна.")
        sql = path.read_text(encoding="utf-8")
        applied: list[str] = []
        if apply:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.root.chmod(0o700)
            for name in sorted(DATABASES):
                database_root = self._database_root(name)
                database_root.mkdir(mode=0o700, exist_ok=True)
                database_root.chmod(0o700)
                if not child(database_root, ".dolt").is_dir():
                    self._run(
                        database_root,
                        "init",
                        "--name",
                        "hermes-foundation",
                        "--email",
                        "foundation@localhost.invalid",
                    )
                self._run(database_root, "sql", "-q", sql)
                changes = self._run(database_root, "diff", "--summary")
                if changes.strip():
                    self._run(database_root, "add", ".")
                    self._run(database_root, "commit", "-m", "migration:002_dolt")
                applied.append(name)
        return receipt(
            {
                "schema_version": 1,
                "contract": "DoltMigrationReceipt",
                "status": "applied" if apply else "dry_run_ready",
                "migration_id": "002_dolt",
                "migration_hash": sha256_json({"sql": sql}),
                "database_ids": sorted(DATABASES),
                "applied_database_ids": applied,
                "named_user_policy": "one_writer_per_database",
                "direct_plugin_database_access": False,
            }
        )

    def _select(
        self, database_root: Path, project_id: str, object_id: str
    ) -> dict[str, Any] | None:
        query = (
            "SELECT project_id, object_id, revision, content_hash, schema_id, "
            "object_json, updated_at FROM objects WHERE project_id="
            f"{_literal(project_id)} AND object_id={_literal(object_id)}"
        )
        output = self._run(database_root, "sql", "-r", "json", "-q", query)
        try:
            rows = json.loads(output).get("rows", [])
        except (json.JSONDecodeError, AttributeError) as error:
            raise BridgeError(
                "dolt_readback_invalid", "runtime.dolt", "Ответ Dolt поврежден."
            ) from error
        if not rows:
            return None
        row = dict(rows[0])
        if isinstance(row.get("object_json"), str):
            row["object_json"] = json.loads(row["object_json"])
        return row

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
        database_root = self._database_root(database)
        if not child(database_root, ".dolt").is_dir():
            fail(
                "dolt_database_unavailable", "request.database", "База не подготовлена."
            )
        project_id = identifier(data["project_id"], "request.project_id")
        object_id = identifier(data["object_id"], "request.object_id")
        expected = integer(data["expected_revision"], "request.expected_revision")
        content_hash = digest(data["content_hash"], "request.content_hash")
        schema_id = identifier(data["schema_id"], "request.schema_id")
        body = mapping(data["object"], "request.object")
        operation_id = identifier(data["operation_id"], "request.operation_id")
        run_id = identifier(data["run_id"], "request.run_id")
        computed_hash = sha256_json(body)
        if content_hash != computed_hash:
            fail(
                "object_hash_mismatch",
                "request.content_hash",
                "Хеш объекта не совпадает.",
            )
        current = self._select(database_root, project_id, object_id)
        current_revision = int(current["revision"]) if current else 0
        if current_revision != expected:
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
                }
            )
        if (
            current is not None
            and current["content_hash"] == content_hash
            and current["schema_id"] == schema_id
            and current["object_json"] == body
        ):
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
                }
            )
        new_revision = current_revision + 1
        body_text = canonical_bytes(body).decode("utf-8")
        if current is None:
            statement = (
                "INSERT INTO objects(project_id,object_id,revision,content_hash,schema_id,object_json,updated_at) VALUES ("
                f"{_literal(project_id)},{_literal(object_id)},{new_revision},{_literal(content_hash)},"
                f"{_literal(schema_id)},{_literal(body_text)},{_literal(_now())})"
            )
        else:
            statement = (
                "UPDATE objects SET "
                f"revision={new_revision},content_hash={_literal(content_hash)},schema_id={_literal(schema_id)},"
                f"object_json={_literal(body_text)},updated_at={_literal(_now())} "
                f"WHERE project_id={_literal(project_id)} AND object_id={_literal(object_id)} "
                f"AND revision={current_revision}"
            )
        self._run(
            database_root, "sql", "-q", f"START TRANSACTION; {statement}; COMMIT;"
        )
        readback = self._select(database_root, project_id, object_id)
        if (
            readback is None
            or int(readback["revision"]) != new_revision
            or readback["content_hash"] != content_hash
            or readback["object_json"] != body
        ):
            fail("dolt_readback_failed", "runtime.dolt", "Обратное чтение не совпало.")
        self._run(database_root, "add", ".")
        message = (
            f"op:{operation_id} run:{run_id} object:{object_id} rev:{new_revision}"
        )
        self._run(database_root, "commit", "-m", message)
        head = json.loads(self._run(database_root, "sql", "-r", "json", "-q",
                                    "SELECT DOLT_HASHOF('HEAD') AS commit_ref"))
        commit_ref = head.get("rows", [{}])[0].get("commit_ref", "")
        if not commit_ref:
            fail("dolt_commit_missing", "runtime.dolt", "Commit не найден.")
        return receipt(
            {
                "schema_version": 1,
                "contract": "DoltStateWriteReceipt",
                "status": "committed",
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
                "readback_verified": True,
                "partial_write": False,
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
        row = self._select(self._database_root(database), project_id, object_id)
        if row is not None and sha256_json(row["object_json"]) != row["content_hash"]:
            fail("dolt_content_hash_mismatch", "runtime.dolt", "Канонический объект повреждён; требуется восстановление.")
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
            }
        )
