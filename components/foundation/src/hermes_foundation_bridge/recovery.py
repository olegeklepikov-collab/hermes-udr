"""Fail-closed inventory and per-system recovery objectives."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical import receipt, sha256_json
from .config import child
from .errors import fail
from .validation import boolean, digest, exact, identifier, integer, mapping, string

SYSTEM_CLASSES = (
    "profiles_gateway",
    "beads",
    "dolt_databases",
    "dolt_privileges_branch_control",
    "runtime_sqlite",
    "agentmemory",
    "graphiti_falkordb",
    "zvec_source_rebuild",
    "artifacts",
    "git_repositories",
    "dependency_locks",
    "configuration_manifests",
)
_ARCHIVE_NAME = re.compile(r"^[a-z][a-z0-9_]*\.age$")
_AGE_HEADER = b"age-encryption.org/v1\n"
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_GIT_ARCHIVE_BYTES = 1024 * 1024 * 1024


def _archive_limit(system: str) -> int:
    return (
        _MAX_GIT_ARCHIVE_BYTES if system == "git_repositories" else _MAX_ARCHIVE_BYTES
    )


def _file_sha256(path: Path) -> str:
    computed = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            computed.update(chunk)
    return computed.hexdigest()


def _timestamp(value: object, path: str) -> datetime:
    raw = string(value, path)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        fail("invalid_timestamp", path, "Метка времени недействительна.")
    if parsed.tzinfo is None:
        fail("invalid_timestamp", path, "Требуется часовой пояс.")
    return parsed.astimezone(UTC)


def _rows(value: object, path: str, required: set[str]) -> dict[str, dict[str, object]]:
    if type(value) is not list:
        fail("invalid_type", path, "Ожидался массив.")
    rows: dict[str, dict[str, object]] = {}
    for index, item in enumerate(value):
        row = mapping(item, f"{path}[{index}]")
        exact(row, required, f"{path}[{index}]")
        system = string(row["system_class"], f"{path}[{index}].system_class")
        if system not in SYSTEM_CLASSES or system in rows:
            fail(
                "system_class_invalid",
                f"{path}[{index}].system_class",
                "Класс отсутствует или повторяется.",
            )
        rows[system] = row
    if set(rows) != set(SYSTEM_CLASSES):
        fail("backup_inventory_incomplete", path, "Ожидались все 12 классов.")
    return rows


class RecoveryService:
    def __init__(self, root: Path):
        self.root = root
        self.backups = child(root, "backup-archives")
        self.drills = child(root, "restore-drills")

    def inventory(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "snapshot_id",
                "created_at",
                "max_age_seconds",
                "archive_receipts",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        snapshot_id = identifier(data["snapshot_id"], "request.snapshot_id")
        created_at = _timestamp(data["created_at"], "request.created_at")
        max_age = integer(data["max_age_seconds"], "request.max_age_seconds", minimum=1)
        if max_age > 30 * 24 * 3600:
            fail(
                "backup_freshness_invalid",
                "request.max_age_seconds",
                "Порог превышает 30 суток.",
            )
        directory = child(self.backups, snapshot_id)
        if directory.is_symlink() or not directory.is_dir():
            fail("backup_directory_missing", "backup", "Каталог копии отсутствует.")
        rows = _rows(
            data["archive_receipts"],
            "request.archive_receipts",
            {
                "system_class",
                "archive_name",
                "archive_sha256",
                "source_quiesced",
                "encrypted",
                "snapshot_readback",
                "source_version_ref",
            },
        )
        now = datetime.now(UTC)
        freshness = 0 <= (now - created_at).total_seconds() <= max_age
        results: list[dict[str, object]] = []
        for system in SYSTEM_CLASSES:
            row = rows[system]
            name = string(row["archive_name"], f"{system}.archive_name")
            if name != f"{system}.age" or not _ARCHIVE_NAME.fullmatch(name):
                fail(
                    "backup_archive_name_invalid",
                    f"{system}.archive_name",
                    "Имя архива недействительно.",
                )
            expected = digest(row["archive_sha256"], f"{system}.archive_sha256")
            quiesced = boolean(row["source_quiesced"], f"{system}.source_quiesced")
            encrypted = boolean(row["encrypted"], f"{system}.encrypted")
            readback = boolean(row["snapshot_readback"], f"{system}.snapshot_readback")
            source_version = identifier(
                row["source_version_ref"], f"{system}.source_version_ref"
            )
            path = child(directory, name)
            safe = (
                path.is_file()
                and not path.is_symlink()
                and 0 < path.stat().st_size <= _archive_limit(system)
            )
            actual = ""
            header = False
            if safe:
                computed = hashlib.sha256()
                with path.open("rb") as stream:
                    header = stream.read(len(_AGE_HEADER)) == _AGE_HEADER
                    stream.seek(0)
                    for chunk in iter(lambda: stream.read(65536), b""):
                        computed.update(chunk)
                actual = computed.hexdigest()
            verified = (
                safe
                and header
                and actual == expected
                and quiesced
                and encrypted
                and readback
                and freshness
            )
            results.append(
                {
                    "system_class": system,
                    "status": "checksum_checked" if verified else "blocked",
                    "archive_sha256": actual if safe else None,
                    "source_version_ref": source_version,
                    "source_quiesced": quiesced,
                    "encryption_header_present": header,
                    "authenticated_decryption_verified": False,
                    "snapshot_readback_reported": readback,
                    "fresh": freshness,
                }
            )
        complete = all(item["status"] == "checksum_checked" for item in results)
        return receipt(
            {
                "schema_version": 1,
                "contract": "BackupInventoryReceipt",
                "status": "archive_inventory_candidate" if complete else "blocked",
                "snapshot_id": snapshot_id,
                "system_count": len(results),
                "checksum_checked_system_count": sum(
                    item["status"] == "checksum_checked" for item in results
                ),
                "systems": results,
                "authenticated_decryption_verified": False,
                "actual_restore_verified": False,
                "production_activation_allowed": False,
            }
        )

    def objectives(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "snapshot_id", "measurements"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        snapshot_id = identifier(data["snapshot_id"], "request.snapshot_id")
        rows = _rows(
            data["measurements"],
            "request.measurements",
            {
                "system_class",
                "rpo_seconds",
                "rto_seconds",
                "measured_rpo_seconds",
                "measured_rto_seconds",
                "readback_verified",
                "source_sequence_ref",
            },
        )
        results = []
        for system in SYSTEM_CLASSES:
            row = rows[system]
            rpo = integer(row["rpo_seconds"], f"{system}.rpo_seconds")
            rto = integer(row["rto_seconds"], f"{system}.rto_seconds")
            measured_rpo = integer(
                row["measured_rpo_seconds"], f"{system}.measured_rpo_seconds"
            )
            measured_rto = integer(
                row["measured_rto_seconds"], f"{system}.measured_rto_seconds"
            )
            readback = boolean(row["readback_verified"], f"{system}.readback_verified")
            sequence = identifier(
                row["source_sequence_ref"], f"{system}.source_sequence_ref"
            )
            passed = readback and measured_rpo <= rpo and measured_rto <= rto
            results.append(
                {
                    "system_class": system,
                    "status": "pass" if passed else "fail",
                    "rpo_seconds": rpo,
                    "rto_seconds": rto,
                    "measured_rpo_seconds": measured_rpo,
                    "measured_rto_seconds": measured_rto,
                    "readback_verified": readback,
                    "source_sequence_ref": sequence,
                }
            )
        return receipt(
            {
                "schema_version": 1,
                "contract": "RecoveryObjectiveReceipt",
                "status": "within_objectives"
                if all(row["status"] == "pass" for row in results)
                else "blocked",
                "snapshot_id": snapshot_id,
                "system_count": len(results),
                "failed_systems": [
                    row["system_class"] for row in results if row["status"] == "fail"
                ],
                "systems": results,
                "averaging_applied": False,
                "production_activation_allowed": False,
            }
        )

    def restore_assess(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "snapshot_id",
                "alternate_root_id",
                "gateway_autostart",
                "restore_receipts",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        snapshot_id = identifier(data["snapshot_id"], "request.snapshot_id")
        alternate_id = identifier(
            data["alternate_root_id"], "request.alternate_root_id"
        )
        gateway_autostart = boolean(
            data["gateway_autostart"], "request.gateway_autostart"
        )
        alt = child(self.drills, alternate_id)
        if alt.is_symlink() or not alt.is_dir():
            fail(
                "alternate_root_missing",
                "restore.alternate_root",
                "Альтернативный корень отсутствует.",
            )
        if (alt / "gateway.pid").exists() or gateway_autostart:
            fail("restore_gateway_running", "restore.gateway", "Запуск шлюза запрещён.")
        rows = _rows(
            data["restore_receipts"],
            "request.restore_receipts",
            {
                "system_class",
                "snapshot_id",
                "restored_ref",
                "content_hash",
                "readback_hash",
                "semantic_probe",
                "secret_boundary_verified",
            },
        )
        results = []
        for system in SYSTEM_CLASSES:
            row = rows[system]
            if identifier(row["snapshot_id"], f"{system}.snapshot_id") != snapshot_id:
                fail(
                    "restore_snapshot_mismatch",
                    f"{system}.snapshot_id",
                    "Снимки различаются.",
                )
            ref = string(row["restored_ref"], f"{system}.restored_ref")
            if ref != f"{system}.restored" or "/" in ref or "\\" in ref:
                fail(
                    "restore_ref_invalid",
                    f"{system}.restored_ref",
                    "Ссылка недействительна.",
                )
            expected = digest(row["content_hash"], f"{system}.content_hash")
            declared = digest(row["readback_hash"], f"{system}.readback_hash")
            semantic = boolean(row["semantic_probe"], f"{system}.semantic_probe")
            secret = boolean(
                row["secret_boundary_verified"], f"{system}.secret_boundary_verified"
            )
            path = child(alt, ref)
            safe = (
                path.is_file()
                and not path.is_symlink()
                and path.stat().st_size <= _archive_limit(system)
            )
            actual = _file_sha256(path) if safe else None
            verified = safe and actual == expected == declared and semantic and secret
            results.append(
                {
                    "system_class": system,
                    "status": "readback_verified" if verified else "blocked",
                    "actual_hash": actual,
                    "semantic_probe": semantic,
                    "secret_boundary_verified": secret,
                }
            )
        complete = all(row["status"] == "readback_verified" for row in results)
        return receipt(
            {
                "schema_version": 1,
                "contract": "AlternateRootRestoreAssessment",
                "status": "fixture_readback_pass" if complete else "blocked",
                "snapshot_id": snapshot_id,
                "alternate_root_id": alternate_id,
                "system_count": len(results),
                "verified_system_count": sum(
                    row["status"] == "readback_verified" for row in results
                ),
                "gateway_autostart": False,
                "systems": results,
                "production_restore_qualified": False,
                "production_activation_allowed": False,
            }
        )

    def checkpoint_assess(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "checkpoint_id",
                "max_age_seconds",
                "max_capture_window_seconds",
                "barrier",
                "systems",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        checkpoint_id = identifier(data["checkpoint_id"], "request.checkpoint_id")
        max_age = integer(data["max_age_seconds"], "request.max_age_seconds", minimum=1)
        max_window = integer(
            data["max_capture_window_seconds"],
            "request.max_capture_window_seconds",
            minimum=1,
        )
        if max_age > 30 * 24 * 3600 or max_window > 3600:
            fail(
                "checkpoint_time_limit_invalid",
                "request",
                "Временной предел недействителен.",
            )
        barrier = mapping(data["barrier"], "request.barrier")
        exact(
            barrier,
            {
                "owner_id",
                "gateway_off",
                "sql_server_off",
                "docker_writers_off",
                "active_tool_invocations",
                "write_lease_count",
                "before_sequence_hash",
                "after_sequence_hash",
                "started_at",
                "released_at",
            },
            "request.barrier",
        )
        owner = identifier(barrier["owner_id"], "request.barrier.owner_id")
        started = _timestamp(barrier["started_at"], "request.barrier.started_at")
        released = _timestamp(barrier["released_at"], "request.barrier.released_at")
        before = digest(
            barrier["before_sequence_hash"], "request.barrier.before_sequence_hash"
        )
        after = digest(
            barrier["after_sequence_hash"], "request.barrier.after_sequence_hash"
        )
        barrier_issues = []
        for field in ("gateway_off", "sql_server_off", "docker_writers_off"):
            if not boolean(barrier[field], f"request.barrier.{field}"):
                barrier_issues.append(f"{field}_missing")
        for field in ("active_tool_invocations", "write_lease_count"):
            if integer(barrier[field], f"request.barrier.{field}") != 0:
                barrier_issues.append(f"{field}_nonzero")
        if before != after:
            barrier_issues.append("sequence_changed_during_snapshot")
        if released < started or (released - started).total_seconds() > max_window:
            barrier_issues.append("capture_window_invalid")
        if not 0 <= (datetime.now(UTC) - released).total_seconds() <= max_age:
            barrier_issues.append("checkpoint_stale")
        rows = _rows(
            data["systems"],
            "request.systems",
            {
                "system_class",
                "checkpoint_id",
                "archive_sha256",
                "captured_at",
                "source_sequence_ref",
                "restored_sequence_ref",
                "authenticated_decryption",
                "alternate_readback",
                "semantic_probe",
                "secret_boundary",
                "rpo_limit_seconds",
                "rto_limit_seconds",
                "measured_rpo_seconds",
                "measured_rto_seconds",
            },
        )
        sequence_hash = sha256_json(
            {
                system: identifier(
                    rows[system]["source_sequence_ref"],
                    f"{system}.source_sequence_ref",
                )
                for system in SYSTEM_CLASSES
            }
        )
        if before != sequence_hash:
            barrier_issues.append("sequence_commitment_mismatch")
        directory = child(self.backups, checkpoint_id)
        systems: list[dict[str, Any]] = []
        for system in SYSTEM_CLASSES:
            row = rows[system]
            row_checkpoint = identifier(row["checkpoint_id"], f"{system}.checkpoint_id")
            expected_hash = digest(row["archive_sha256"], f"{system}.archive_sha256")
            captured = _timestamp(row["captured_at"], f"{system}.captured_at")
            source_sequence = identifier(
                row["source_sequence_ref"], f"{system}.source_sequence_ref"
            )
            restored_sequence = identifier(
                row["restored_sequence_ref"], f"{system}.restored_sequence_ref"
            )
            evidence = {
                field: boolean(row[field], f"{system}.{field}")
                for field in (
                    "authenticated_decryption",
                    "alternate_readback",
                    "semantic_probe",
                    "secret_boundary",
                )
            }
            rpo_limit = integer(row["rpo_limit_seconds"], f"{system}.rpo_limit_seconds")
            rto_limit = integer(row["rto_limit_seconds"], f"{system}.rto_limit_seconds")
            measured_rpo = integer(
                row["measured_rpo_seconds"], f"{system}.measured_rpo_seconds"
            )
            measured_rto = integer(
                row["measured_rto_seconds"], f"{system}.measured_rto_seconds"
            )
            archive = child(directory, f"{system}.age")
            archive_safe = (
                directory.is_dir()
                and not directory.is_symlink()
                and archive.is_file()
                and not archive.is_symlink()
                and 0 < archive.stat().st_size <= _archive_limit(system)
            )
            actual_hash = None
            header = False
            if archive_safe:
                computed = hashlib.sha256()
                with archive.open("rb") as stream:
                    header = stream.read(len(_AGE_HEADER)) == _AGE_HEADER
                    stream.seek(0)
                    for chunk in iter(lambda: stream.read(65536), b""):
                        computed.update(chunk)
                actual_hash = computed.hexdigest()
            issues = []
            if row_checkpoint != checkpoint_id:
                issues.append("checkpoint_id_mismatch")
            if not started <= captured <= released:
                issues.append("capture_outside_barrier")
            if not archive_safe or not header or actual_hash != expected_hash:
                issues.append("archive_integrity_unverified")
            if source_sequence != restored_sequence:
                issues.append("sequence_readback_mismatch")
            issues.extend(
                f"{field}_missing" for field, valid in evidence.items() if not valid
            )
            if measured_rpo > rpo_limit:
                issues.append("rpo_exceeded")
            if measured_rto > rto_limit:
                issues.append("rto_exceeded")
            systems.append(
                {
                    "system_class": system,
                    "status": "candidate" if not issues else "blocked",
                    "issues": issues,
                    "archive_sha256": actual_hash,
                    "source_sequence_ref": source_sequence,
                    "restored_sequence_ref": restored_sequence,
                    "measured_rpo_seconds": measured_rpo,
                    "rpo_limit_seconds": rpo_limit,
                    "measured_rto_seconds": measured_rto,
                    "rto_limit_seconds": rto_limit,
                }
            )
        complete = not barrier_issues and all(
            row["status"] == "candidate" for row in systems
        )
        return receipt(
            {
                "schema_version": 1,
                "contract": "FoundationCheckpointAssessment",
                "status": "checkpoint_candidate" if complete else "blocked",
                "checkpoint_id": checkpoint_id,
                "barrier_owner": owner,
                "barrier_issues": barrier_issues,
                "source_sequence_hash": sequence_hash,
                "system_count": len(systems),
                "candidate_system_count": sum(
                    row["status"] == "candidate" for row in systems
                ),
                "failed_systems": [
                    row["system_class"] for row in systems if row["status"] == "blocked"
                ],
                "systems": systems,
                "averaging_applied": False,
                "host_observations_independently_attested": False,
                "production_restore_qualified": False,
                "production_activation_allowed": False,
            }
        )
