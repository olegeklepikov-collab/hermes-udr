"""Public-CLI-only Beads work-graph adapter for the greenfield workspace."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt, sha256_json
from .config import child
from .errors import BridgeError, fail
from .external_operations import guarded_external
from .validation import boolean, exact, identifier, integer, mapping, string

BEADS_MANIFEST = {
    "schema_version": 1,
    "bd_version": "1.1.0",
    "workspace_ref": "foundation/beads-workspace",
    "issue_prefix": "KWF",
    "backend": "embedded_dolt",
    "access": "public_cli_only",
    "raw_sql_exposed": False,
    "internal_tables_exposed": False,
}
_ISSUE_ID = re.compile(r"^KWF-[a-z0-9]+$")
_SENSITIVE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|secret|authorization|bearer)[\s:=]"
)


class BeadsAdapter:
    def __init__(self, root: Path):
        self.foundation = root
        self.root = child(root, "beads-workspace")
        self.manifest_path = child(root, "beads-manifest.json")

    def _run(self, arguments: list[str], *, actor: str = "foundation-bridge") -> object:
        executable = shutil.which("bd")
        if not executable or not child(self.root, ".beads").is_dir():
            fail("beads_unavailable", "runtime.beads", "Beads workspace недоступен.")
        environment = dict(os.environ)
        environment["BEADS_ACTOR"] = actor
        environment["BEADS_DIR"] = str(self.root / ".beads")
        try:
            completed = subprocess.run(
                [executable, "-C", str(self.root), *arguments, "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=30,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise BridgeError(
                "beads_operation_failed",
                "runtime.beads",
                "Операция Beads отклонена.",
            ) from error
        if completed.returncode != 0:
            raise BridgeError(
                "beads_operation_failed",
                "runtime.beads",
                "Операция Beads отклонена.",
            )
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise BridgeError(
                "beads_response_invalid",
                "runtime.beads",
                "Ответ Beads поврежден.",
            ) from error

    @staticmethod
    def _issue_id(value: object, path: str = "request.issue_id") -> str:
        text = string(value, path)
        if not _ISSUE_ID.fullmatch(text):
            fail("invalid_issue_id", path, "Недопустимый Beads ID.")
        return text

    def migrate(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "apply"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        apply = boolean(data["apply"], "request.apply")
        status = self._run(["status"])
        if apply:
            if self.manifest_path.exists():
                if (
                    json.loads(self.manifest_path.read_text(encoding="utf-8"))
                    != BEADS_MANIFEST
                ):
                    fail(
                        "beads_manifest_conflict",
                        "beads.manifest",
                        "Манифест Beads отличается.",
                    )
            else:
                temporary = self.manifest_path.with_suffix(".tmp")
                descriptor = os.open(
                    temporary,
                    os.O_CREAT | os.O_TRUNC | os.O_WRONLY,
                    0o600,
                )
                try:
                    payload = canonical_bytes(BEADS_MANIFEST) + b"\n"
                    written = 0
                    while written < len(payload):
                        written += os.write(descriptor, payload[written:])
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.replace(temporary, self.manifest_path)
        summary = status.get("summary", {}) if isinstance(status, dict) else {}
        return receipt(
            {
                "schema_version": 1,
                "contract": "BeadsMigrationReceipt",
                "status": "applied" if apply else "dry_run_ready",
                "apply_requested": apply,
                "manifest": BEADS_MANIFEST,
                "manifest_hash": sha256_json(BEADS_MANIFEST),
                "issue_count": summary.get("total_issues"),
            }
        )

    def _ready(self) -> None:
        if not self.manifest_path.is_file() or self.manifest_path.is_symlink():
            fail("beads_unavailable", "runtime.beads", "Beads adapter не подготовлен.")
        if json.loads(self.manifest_path.read_text(encoding="utf-8")) != BEADS_MANIFEST:
            fail(
                "beads_manifest_conflict",
                "beads.manifest",
                "Манифест Beads отличается.",
            )

    def health(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version"}, "request")
        self._ready()
        result = self._run(["status"])
        summary = result.get("summary", {}) if isinstance(result, dict) else {}
        return receipt(
            {
                "schema_version": 1,
                "contract": "BeadsHealthReceipt",
                "status": "healthy",
                "manifest_hash": sha256_json(BEADS_MANIFEST),
                "total_issues": summary.get("total_issues"),
                "open_issues": summary.get("open_issues"),
                "in_progress_issues": summary.get("in_progress_issues"),
                "closed_issues": summary.get("closed_issues"),
                "raw_sql_exposed": False,
                "internal_tables_exposed": False,
            }
        )

    def create(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {"schema_version", "title", "description", "priority", "issue_type"}
            | ({"operation_key"} if "operation_key" in data else set()),
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        title = string(data["title"], "request.title")
        description = string(data["description"], "request.description")
        priority = integer(data["priority"], "request.priority")
        issue_type = string(data["issue_type"], "request.issue_type")
        if priority > 4 or issue_type not in {"task", "feature", "bug", "chore"}:
            fail("invalid_issue_fields", "request", "Недопустимые поля работы.")
        if len(title) > 160 or len(description) > 4000:
            fail("issue_text_too_large", "request", "Текст работы превышает предел.")
        if _SENSITIVE.search(title) or _SENSITIVE.search(description):
            fail("secret_scan_failed", "request", "Потенциальный секрет запрещён.")
        operation_key = (
            identifier(data["operation_key"], "request.operation_key")
            if "operation_key" in data
            else sha256_json(data)
        )
        self._ready()
        return guarded_external(
            self.foundation,
            "beads_create",
            {"operation_key": operation_key},
            data,
            lambda: self._create_prepared(title, description, priority, issue_type),
            {"created"},
        )

    def _create_prepared(
        self, title: str, description: str, priority: int, issue_type: str
    ) -> dict[str, Any]:
        result = self._run(
            [
                "create",
                "--title",
                title,
                "--description",
                description,
                "--priority",
                f"P{priority}",
                "--type",
                issue_type,
            ]
        )
        if not isinstance(result, dict):
            fail("beads_response_invalid", "runtime.beads", "Ответ Beads поврежден.")
        issue_id = self._issue_id(result.get("id"), "response.id")
        return receipt(
            {
                "schema_version": 1,
                "contract": "BeadsCreateReceipt",
                "status": "created",
                "issue_id": issue_id,
                "work_status": result.get("status"),
                "priority": result.get("priority"),
                "issue_type": result.get("issue_type"),
            }
        )

    def get(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "issue_id"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        issue_id = self._issue_id(data["issue_id"])
        self._ready()
        result = self._run(["show", issue_id])
        if (
            not isinstance(result, list)
            or len(result) != 1
            or not isinstance(result[0], dict)
        ):
            fail("beads_response_invalid", "runtime.beads", "Ответ Beads поврежден.")
        row = result[0]
        return receipt(
            {
                "schema_version": 1,
                "contract": "BeadsReadReceipt",
                "status": "found",
                "issue": {
                    "id": self._issue_id(row.get("id"), "response.id"),
                    "status": row.get("status"),
                    "priority": row.get("priority"),
                    "issue_type": row.get("issue_type"),
                    "assignee": row.get("assignee"),
                },
            }
        )

    def claim(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {"schema_version", "issue_id", "worker_id"}
            | ({"operation_key"} if "operation_key" in data else set()),
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        issue_id = self._issue_id(data["issue_id"])
        worker_id = identifier(data["worker_id"], "request.worker_id")
        operation_key = (
            identifier(data["operation_key"], "request.operation_key")
            if "operation_key" in data
            else sha256_json(data)
        )
        self._ready()
        return guarded_external(
            self.foundation,
            "beads_claim",
            {"operation_key": operation_key},
            data,
            lambda: self._claim_prepared(issue_id, worker_id),
            {"claimed"},
        )

    def _claim_prepared(self, issue_id: str, worker_id: str) -> dict[str, Any]:
        result = self._run(["update", issue_id, "--claim"], actor=worker_id)
        if (
            not isinstance(result, list)
            or len(result) != 1
            or not isinstance(result[0], dict)
        ):
            fail("beads_response_invalid", "runtime.beads", "Ответ Beads поврежден.")
        row = result[0]
        if (
            row.get("id") != issue_id
            or row.get("status") != "in_progress"
            or row.get("assignee") != worker_id
        ):
            fail(
                "beads_response_invalid",
                "runtime.beads",
                "Обратное чтение назначения не подтверждено.",
            )
        return receipt(
            {
                "schema_version": 1,
                "contract": "BeadsClaimReceipt",
                "status": "claimed",
                "issue_id": issue_id,
                "work_status": row.get("status"),
                "assignee": row.get("assignee"),
                "worker_id": worker_id,
            }
        )

    def close(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {"schema_version", "issue_id", "reason_code", "worker_id"}
            | ({"operation_key"} if "operation_key" in data else set()),
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        issue_id = self._issue_id(data["issue_id"])
        reason = identifier(data["reason_code"], "request.reason_code")
        worker_id = identifier(data["worker_id"], "request.worker_id")
        operation_key = (
            identifier(data["operation_key"], "request.operation_key")
            if "operation_key" in data
            else sha256_json(data)
        )
        self._ready()
        return guarded_external(
            self.foundation,
            "beads_close",
            {"operation_key": operation_key},
            data,
            lambda: self._close_prepared(issue_id, reason, worker_id),
            {"closed"},
        )

    def _close_prepared(
        self, issue_id: str, reason: str, worker_id: str
    ) -> dict[str, Any]:
        self._run(["close", issue_id, "--reason", reason], actor=worker_id)
        read = self.get({"schema_version": 1, "issue_id": issue_id})
        if read["issue"]["status"] != "closed":
            fail(
                "beads_response_invalid",
                "runtime.beads",
                "Обратное чтение закрытия не подтверждено.",
            )
        return receipt(
            {
                "schema_version": 1,
                "contract": "BeadsCloseReceipt",
                "status": "closed",
                "issue_id": issue_id,
                "work_status": read["issue"]["status"],
                "acceptance_created": False,
                "release_allowed": False,
            }
        )

    def reconcile(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "issue_id",
                "lease_status",
                "artifact_status",
                "review_status",
                "dolt_commit_ref",
                "outbox_status",
                "writer_count",
                "expected_revision",
                "current_revision",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        issue_id = self._issue_id(data["issue_id"])
        work = self.get({"schema_version": 1, "issue_id": issue_id})
        status_map = {"open": "open", "in_progress": "claimed", "closed": "closed"}
        bead_status = status_map.get(work["issue"]["status"])
        if bead_status is None:
            fail(
                "unsupported_work_status", "beads.status", "Статус Beads не поддержан."
            )
        try:
            from hermes_research_report import reconcile_state
        except ImportError as error:
            raise RuntimeError("research contract package unavailable") from error
        return reconcile_state(
            {
                "schema_version": 1,
                "work_id": issue_id,
                "bead_status": bead_status,
                "lease_status": data["lease_status"],
                "artifact_status": data["artifact_status"],
                "review_status": data["review_status"],
                "dolt_commit_ref": data["dolt_commit_ref"],
                "outbox_status": data["outbox_status"],
                "writer_count": data["writer_count"],
                "expected_revision": data["expected_revision"],
                "current_revision": data["current_revision"],
            }
        )
