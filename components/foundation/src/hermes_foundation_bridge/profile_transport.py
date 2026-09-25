"""Isolated worker-profile and Telegram transport contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt, sha256_json
from .config import child
from .errors import fail
from .external_operations import guarded_external
from .validation import boolean, digest, exact, identifier, integer, mapping, string

SCHEMA_VERSION = 1
PROFILE_IDS = (
    "default",
    "academic",
    "engineering",
    "operator",
    "parser",
    "quantitative",
    "research",
    "review",
)
NAMED_PROFILE_IDS = tuple(item for item in PROFILE_IDS if item != "default")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

PROFILE_CONTRACTS: dict[str, dict[str, object]] = {
    "default": {
        "role": "controller",
        "allowed_toolsets": ["foundation", "research", "coordination"],
        "denied_authorities": ["self_review", "unreviewed_merge"],
        "mounts": [{"ref": "foundation", "mode": "adapter_only"}],
        "blind_first_pass": False,
        "effect_only": False,
    },
    "academic": {
        "role": "academic_researcher",
        "allowed_toolsets": ["research", "academic", "foundation_read"],
        "denied_authorities": ["acceptance", "merge", "operator_effect"],
        "mounts": [
            {"ref": "workspace", "mode": "read_write"},
            {"ref": "evidence", "mode": "adapter_only"},
        ],
        "blind_first_pass": False,
        "effect_only": False,
    },
    "engineering": {
        "role": "engineering_worker",
        "allowed_toolsets": ["shell", "files", "git", "tests", "foundation_read"],
        "denied_authorities": ["self_review", "merge", "acceptance", "operator_effect"],
        "mounts": [
            {"ref": "workspace", "mode": "read_write"},
            {"ref": "artifacts", "mode": "adapter_only"},
        ],
        "blind_first_pass": False,
        "effect_only": False,
    },
    "operator": {
        "role": "effect_operator",
        "allowed_toolsets": ["approved_effects", "foundation_read"],
        "denied_authorities": ["analysis_basis", "acceptance", "review", "merge"],
        "mounts": [
            {"ref": "approved_effects", "mode": "read_only"},
            {"ref": "effect_receipts", "mode": "append_only"},
        ],
        "blind_first_pass": False,
        "effect_only": True,
    },
    "parser": {
        "role": "parser_worker",
        "allowed_toolsets": ["parsing", "quarantine_read", "artifact_write"],
        "denied_authorities": [
            "evidence_promotion",
            "acceptance",
            "merge",
            "operator_effect",
        ],
        "mounts": [
            {"ref": "quarantine", "mode": "read_only"},
            {"ref": "derived_artifacts", "mode": "append_only"},
        ],
        "blind_first_pass": False,
        "effect_only": False,
    },
    "quantitative": {
        "role": "quantitative_worker",
        "allowed_toolsets": ["computation", "files", "tests", "foundation_read"],
        "denied_authorities": ["acceptance", "merge", "operator_effect"],
        "mounts": [
            {"ref": "workspace", "mode": "read_write"},
            {"ref": "quantitative_state", "mode": "adapter_only"},
        ],
        "blind_first_pass": False,
        "effect_only": False,
    },
    "research": {
        "role": "knowledge_researcher",
        "allowed_toolsets": ["research", "foundation_read"],
        "denied_authorities": ["acceptance", "merge", "operator_effect"],
        "mounts": [
            {"ref": "workspace", "mode": "read_write"},
            {"ref": "evidence", "mode": "adapter_only"},
        ],
        "blind_first_pass": False,
        "effect_only": False,
    },
    "review": {
        "role": "independent_reviewer",
        "allowed_toolsets": ["review", "foundation_read"],
        "denied_authorities": ["original_execution", "operator_effect", "self_merge"],
        "mounts": [
            {"ref": "submitted_artifacts", "mode": "read_only"},
            {"ref": "review_positions", "mode": "append_only"},
        ],
        "blind_first_pass": True,
        "effect_only": False,
    },
}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _strings(value: object, path: str, *, nonempty: bool = True) -> list[str]:
    if type(value) is not list:
        fail("invalid_type", path, "Ожидался массив.")
    result = [
        string(item, f"{path}[{index}]", nonempty=nonempty)
        for index, item in enumerate(value)
    ]
    if len(result) != len(set(result)):
        fail("duplicate_value", path, "Повторы запрещены.")
    return result


def _nullable_identifier(value: object, path: str) -> str | None:
    return None if value is None else identifier(value, path)


def _nullable_digest(value: object, path: str) -> str | None:
    return None if value is None else digest(value, path)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        fail(
            "profile_contract_path_invalid",
            "profile_contract",
            "Небезопасный путь договора.",
        )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".profile-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


class ProfileTransportService:
    def __init__(self, root: Path):
        self.foundation = root
        self.hermes_home = root.parent
        self.profile_root = child(self.hermes_home, "profiles")
        self.contract_root = child(root, "profile-contracts")
        self.database = child(root, "runtime", "profile-transport.sqlite3")

    @staticmethod
    def migration_path() -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "003_profile_transport.sql"
        )

    def _profile_home(self, profile_id: str) -> Path:
        return (
            self.hermes_home
            if profile_id == "default"
            else child(self.profile_root, profile_id)
        )

    @staticmethod
    def _assignment_count(path: Path) -> int:
        if path.is_symlink() or not path.is_file():
            return -1
        return sum(
            1
            for line in path.read_text(encoding="utf-8").splitlines()
            if _ASSIGNMENT.match(line.strip())
        )

    @staticmethod
    def _state_file_count(home: Path) -> int:
        count = 0
        for name in ("memories", "sessions", "cron", "plans"):
            root = home / name
            if root.is_symlink() or not root.is_dir():
                return -1
            count += sum(
                1
                for item in root.rglob("*")
                if item.is_file() and not item.name.startswith(".")
            )
        return count

    def _profile_snapshot(self, profile_id: str) -> dict[str, Any]:
        home = self._profile_home(profile_id)
        if home.is_symlink() or not home.is_dir():
            fail(
                "profile_home_missing",
                f"profiles.{profile_id}",
                "Дом профиля отсутствует.",
            )
        assignments = self._assignment_count(home / ".env")
        state_files = self._state_file_count(home)
        contract = PROFILE_CONTRACTS[profile_id]
        return {
            "schema_version": 1,
            "profile_id": profile_id,
            "role": contract["role"],
            "home_ref": "." if profile_id == "default" else f"profiles/{profile_id}",
            "native_home_isolated": profile_id != "default",
            "created_blank": profile_id != "default"
            and assignments == 0
            and state_files == 0,
            "cloned_from": None,
            "initial_secret_assignment_count": assignments,
            "initial_state_file_count": state_files,
            "allowed_toolsets": contract["allowed_toolsets"],
            "denied_authorities": contract["denied_authorities"],
            "mounts": contract["mounts"],
            "blind_first_pass": contract["blind_first_pass"],
            "effect_only": contract["effect_only"],
            "shell_secret_inheritance_allowed": False,
            "shared_writable_home_allowed": False,
            "qualification_status": "contract_verified",
        }

    def _verified_baseline(self, current: dict[str, Any]) -> dict[str, Any] | None:
        path = self.contract_root / f"{current['profile_id']}.json"
        if path.parent.is_symlink() or not path.is_file() or path.is_symlink():
            return None
        stored = json.loads(path.read_text(encoding="utf-8"))
        if type(stored) is not dict or set(stored) != set(current):
            return None
        historical = {"initial_secret_assignment_count", "initial_state_file_count"}
        if current["profile_id"] != "default":
            return stored if stored == current else None
        if any(
            (self.hermes_home / name).is_symlink()
            for name in (".env", "memories", "sessions", "cron", "plans")
        ):
            return None
        if any(
            type(value.get(key)) is not int or value[key] < -1
            for value in (stored, current)
            for key in historical
        ):
            return None
        return (
            stored
            if all(
                stored[key] == value
                for key, value in current.items()
                if key not in historical
            )
            else None
        )

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
        migration = self.migration_path()
        if migration.is_symlink() or not migration.is_file():
            fail(
                "migration_missing",
                "migrations.003_profile_transport",
                "Миграция отсутствует.",
            )
        snapshots = [self._profile_snapshot(profile_id) for profile_id in PROFILE_IDS]
        if any(
            not item["created_blank"]
            for item in snapshots
            if item["profile_id"] != "default"
        ):
            fail(
                "profile_not_blank",
                "profiles",
                "Именованный профиль не является пустым.",
            )
        for snapshot in snapshots:
            path = self.contract_root / f"{snapshot['profile_id']}.json"
            if (path.exists() or path.is_symlink()) and self._verified_baseline(
                snapshot
            ) is None:
                fail(
                    "profile_contract_conflict",
                    "profiles",
                    "Начальный договор отличается.",
                )
        if apply:
            self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            connection = sqlite3.connect(self.database)
            try:
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta(schema_version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _now()),
                )
                connection.commit()
            finally:
                connection.close()
            self.database.chmod(0o600)
            for snapshot in snapshots:
                path = self.contract_root / f"{snapshot['profile_id']}.json"
                if not path.exists():
                    _atomic_json(path, snapshot)
        return receipt(
            {
                "schema_version": 1,
                "contract": "ProfileTransportMigrationReceipt",
                "status": "applied" if apply else "dry_run_ready",
                "migration_id": "003_profile_transport",
                "profile_count": len(snapshots),
                "named_blank_profile_count": sum(
                    bool(item["created_blank"]) for item in snapshots
                ),
                "profile_ids": list(PROFILE_IDS),
                "secret_assignment_count": sum(
                    max(0, int(item["initial_secret_assignment_count"]))
                    for item in snapshots
                    if item["profile_id"] != "default"
                ),
                "state_file_count": sum(
                    max(0, int(item["initial_state_file_count"]))
                    for item in snapshots
                    if item["profile_id"] != "default"
                ),
                "cloned_profile_count": 0,
                "shared_writable_home_count": 0,
            }
        )

    def _connect(self) -> sqlite3.Connection:
        if self.database.is_symlink() or not self.database.is_file():
            fail(
                "profile_transport_unavailable",
                "runtime.profile_transport",
                "Служба не подготовлена.",
            )
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def health(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        connection = self._connect()
        try:
            version = connection.execute(
                "SELECT MAX(schema_version) FROM schema_meta"
            ).fetchone()[0]
        finally:
            connection.close()
        snapshots = [self._profile_snapshot(profile_id) for profile_id in PROFILE_IDS]
        baselines = {
            item["profile_id"]: self._verified_baseline(item) for item in snapshots
        }
        verified = sum(value is not None for value in baselines.values())
        default = next(item for item in snapshots if item["profile_id"] == "default")
        blank = sum(bool(item["created_blank"]) for item in snapshots)
        secret_assignments = sum(
            max(0, int(item["initial_secret_assignment_count"]))
            for item in snapshots
            if item["profile_id"] != "default"
        )
        healthy = (
            version == SCHEMA_VERSION
            and verified == len(PROFILE_IDS)
            and blank == len(NAMED_PROFILE_IDS)
            and secret_assignments == 0
            and (self.database.stat().st_mode & 0o777) == 0o600
        )
        return receipt(
            {
                "schema_version": 1,
                "contract": "ProfileTransportHealthReceipt",
                "status": "healthy" if healthy else "blocked",
                "installed_schema_version": version,
                "profile_count": len(snapshots),
                "verified_contract_count": verified,
                "default_current_observation": {
                    "assignment_count": default["initial_secret_assignment_count"],
                    "state_file_count": default["initial_state_file_count"],
                    "stored_initial_contract_used": baselines["default"] is not None,
                    "counts_changed_since_initial": baselines["default"] is not None
                    and any(
                        baselines["default"][key] != default[key]
                        for key in (
                            "initial_secret_assignment_count",
                            "initial_state_file_count",
                        )
                    ),
                },
                "named_blank_profile_count": blank,
                "secret_assignment_count": secret_assignments,
                "shared_writable_home_count": 0,
                "qualified_telegram_routes": ["dm_polling"],
                "unqualified_telegram_routes": [
                    "group",
                    "webhook",
                    "local_bot_api",
                ],
            }
        )

    def profile_get(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "profile_id"}, "request")
        profile_id = identifier(data["profile_id"], "request.profile_id")
        if profile_id not in PROFILE_CONTRACTS:
            fail("profile_unknown", "request.profile_id", "Профиль не зарегистрирован.")
        snapshot = self._profile_snapshot(profile_id)
        baseline = self._verified_baseline(snapshot)
        verified = baseline is not None
        return receipt(
            {
                **(baseline if baseline is not None else snapshot),
                "current_observation": {
                    "assignment_count": snapshot["initial_secret_assignment_count"],
                    "state_file_count": snapshot["initial_state_file_count"],
                },
                "contract": "ProfileDefinitionReceipt",
                "status": "verified" if verified else "unverified",
                "contract_readback_verified": verified,
            }
        )

    def handoff(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        keys = {
            "schema_version",
            "package_id",
            "revision",
            "from_profile",
            "to_profile",
            "artifact_refs",
            "test_refs",
            "computation_refs",
            "commit_refs",
            "checkpoint_ref",
            "accepted_effect_refs",
            "merge_owner",
        }
        exact(data, keys, "request")
        package_id = identifier(data["package_id"], "request.package_id")
        revision = integer(data["revision"], "request.revision", minimum=1)
        from_profile = identifier(data["from_profile"], "request.from_profile")
        to_profile = identifier(data["to_profile"], "request.to_profile")
        if (
            from_profile not in PROFILE_CONTRACTS
            or to_profile not in PROFILE_CONTRACTS
            or from_profile == to_profile
        ):
            fail(
                "handoff_profile_invalid",
                "request.to_profile",
                "Профили передачи недействительны.",
            )
        normalized = dict(data)
        for key in (
            "artifact_refs",
            "test_refs",
            "computation_refs",
            "commit_refs",
            "accepted_effect_refs",
        ):
            normalized[key] = _strings(data[key], f"request.{key}", nonempty=False)
        normalized["checkpoint_ref"] = _nullable_identifier(
            data["checkpoint_ref"], "request.checkpoint_ref"
        )
        normalized["merge_owner"] = identifier(
            data["merge_owner"], "request.merge_owner"
        )
        if from_profile == "engineering" and not normalized["commit_refs"]:
            fail(
                "handoff_incomplete",
                "request.commit_refs",
                "Engineering-передача требует commit ref.",
            )
        payload_hash = sha256_json(normalized)
        connection = self._connect()
        try:
            existing = connection.execute(
                "SELECT payload_hash FROM handoffs WHERE package_id=?", (package_id,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO handoffs VALUES (?,?,?,?,?,?)",
                    (
                        package_id,
                        revision,
                        from_profile,
                        to_profile,
                        payload_hash,
                        _now(),
                    ),
                )
                connection.commit()
                status = "recorded"
            elif existing["payload_hash"] == payload_hash:
                status = "idempotent_existing"
            else:
                fail(
                    "handoff_conflict",
                    "request.package_id",
                    "Передача уже существует с иным содержимым.",
                )
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "HandoffReceipt",
                "status": status,
                "package_id": package_id,
                "revision": revision,
                "from_profile": from_profile,
                "to_profile": to_profile,
                "payload_hash": payload_hash,
                "complete": True,
                "acceptance_changed": False,
                "merge_changed": False,
            }
        )

    def review_position(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "package_id",
                "reviewer_profile",
                "reviewer_id",
                "artifact_refs",
                "author_conclusion_excluded",
                "author_acceptance_excluded",
                "position",
                "position_hash",
            },
            "request",
        )
        package_id = identifier(data["package_id"], "request.package_id")
        reviewer_profile = identifier(
            data["reviewer_profile"], "request.reviewer_profile"
        )
        reviewer_id = identifier(data["reviewer_id"], "request.reviewer_id")
        artifacts = _strings(data["artifact_refs"], "request.artifact_refs")
        excluded_conclusion = boolean(
            data["author_conclusion_excluded"], "request.author_conclusion_excluded"
        )
        excluded_acceptance = boolean(
            data["author_acceptance_excluded"], "request.author_acceptance_excluded"
        )
        position = string(data["position"], "request.position")
        position_hash = digest(data["position_hash"], "request.position_hash")
        if (
            reviewer_profile != "review"
            or not excluded_conclusion
            or not excluded_acceptance
            or hashlib_sha256(position) != position_hash
        ):
            fail(
                "blind_review_invalid",
                "request",
                "Слепой первый просмотр недействителен.",
            )
        payload_hash = sha256_json(data)
        connection = self._connect()
        try:
            try:
                connection.execute(
                    "INSERT INTO review_positions VALUES (?,?,?,?,?)",
                    (package_id, reviewer_profile, position_hash, payload_hash, _now()),
                )
                connection.commit()
                status = "position_recorded"
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT payload_hash FROM review_positions WHERE package_id=?",
                    (package_id,),
                ).fetchone()
                if row is None or row["payload_hash"] != payload_hash:
                    fail(
                        "review_position_conflict",
                        "request.package_id",
                        "Первая позиция уже зафиксирована.",
                    )
                status = "idempotent_existing"
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "PositionRecord",
                "status": status,
                "package_id": package_id,
                "reviewer_profile": reviewer_profile,
                "reviewer_id": reviewer_id,
                "artifact_refs": artifacts,
                "position_hash": position_hash,
                "author_conclusion_visible": False,
                "author_acceptance_visible": False,
                "acceptance_changed": False,
            }
        )

    def operator_effect(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "operator_profile",
                "effect_ref",
                "signed_decision_hash",
                "basis_hash_before",
                "basis_hash_after",
                "acceptance_ref_before",
                "acceptance_ref_after",
                "output_hash",
                "idempotency_key",
            },
            "request",
        )
        if (
            identifier(data["operator_profile"], "request.operator_profile")
            != "operator"
        ):
            fail(
                "operator_profile_required",
                "request.operator_profile",
                "Требуется профиль operator.",
            )
        effect_ref = identifier(data["effect_ref"], "request.effect_ref")
        idempotency_key = identifier(data["idempotency_key"], "request.idempotency_key")
        for key in (
            "signed_decision_hash",
            "basis_hash_before",
            "basis_hash_after",
            "output_hash",
        ):
            digest(data[key], f"request.{key}")
        before = identifier(
            data["acceptance_ref_before"], "request.acceptance_ref_before"
        )
        after = identifier(data["acceptance_ref_after"], "request.acceptance_ref_after")
        if data["basis_hash_before"] != data["basis_hash_after"] or before != after:
            fail(
                "operator_authority_violation",
                "request",
                "Оператор изменил основание или приемку.",
            )
        payload_hash = sha256_json(data)
        connection = self._connect()
        try:
            try:
                connection.execute(
                    "INSERT INTO operator_effects VALUES (?,?,?,?)",
                    (effect_ref, idempotency_key, payload_hash, _now()),
                )
                connection.commit()
                status = "effect_recorded"
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT payload_hash FROM operator_effects WHERE effect_ref=? OR idempotency_key=?",
                    (effect_ref, idempotency_key),
                ).fetchone()
                if row is None or row["payload_hash"] != payload_hash:
                    fail(
                        "operator_effect_conflict",
                        "request.idempotency_key",
                        "Эффект уже существует.",
                    )
                status = "idempotent_existing"
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "OperatorEffectReceipt",
                "status": status,
                "effect_ref": effect_ref,
                "idempotency_key": idempotency_key,
                "basis_unchanged": True,
                "acceptance_unchanged": True,
                "analysis_created": False,
                "acceptance_changed": False,
            }
        )

    def resume(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "package_id",
                "checkpoint_ref",
                "prior_worker_id",
                "new_worker_id",
                "new_lease_ref",
                "accepted_effect_refs",
                "requested_effect_refs",
            },
            "request",
        )
        package_id = identifier(data["package_id"], "request.package_id")
        checkpoint = identifier(data["checkpoint_ref"], "request.checkpoint_ref")
        prior = identifier(data["prior_worker_id"], "request.prior_worker_id")
        new = identifier(data["new_worker_id"], "request.new_worker_id")
        lease = identifier(data["new_lease_ref"], "request.new_lease_ref")
        accepted = set(
            _strings(
                data["accepted_effect_refs"],
                "request.accepted_effect_refs",
                nonempty=False,
            )
        )
        requested = set(
            _strings(
                data["requested_effect_refs"],
                "request.requested_effect_refs",
                nonempty=False,
            )
        )
        repeated = sorted(accepted & requested)
        if prior == new or repeated:
            fail(
                "resume_repeats_effect",
                "request.requested_effect_refs",
                "Возобновление повторяет принятый эффект.",
            )
        payload_hash = sha256_json(data)
        connection = self._connect()
        try:
            connection.execute(
                "INSERT OR REPLACE INTO resumptions VALUES (?,?,?,?)",
                (package_id, new, payload_hash, _now()),
            )
            connection.commit()
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "CheckpointResumeReceipt",
                "status": "resumed",
                "package_id": package_id,
                "checkpoint_ref": checkpoint,
                "new_worker_id": new,
                "new_lease_ref": lease,
                "repeated_effect_refs": [],
                "accepted_effects_replayed": False,
            }
        )

    def merge_assess(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "writer_profile",
                "writer_id",
                "reviewer_profile",
                "reviewer_id",
                "worktree_ref",
                "commit_ref",
                "bead_ref",
                "review_ref",
                "review_status",
            },
            "request",
        )
        writer_profile = identifier(data["writer_profile"], "request.writer_profile")
        reviewer_profile = identifier(
            data["reviewer_profile"], "request.reviewer_profile"
        )
        writer_id = identifier(data["writer_id"], "request.writer_id")
        reviewer_id = identifier(data["reviewer_id"], "request.reviewer_id")
        refs = [
            identifier(data[key], f"request.{key}")
            for key in ("worktree_ref", "commit_ref", "bead_ref", "review_ref")
        ]
        review_status = string(data["review_status"], "request.review_status")
        allowed = (
            writer_profile == "engineering"
            and reviewer_profile == "review"
            and writer_id != reviewer_id
            and review_status == "accepted"
        )
        return receipt(
            {
                "schema_version": 1,
                "contract": "MergeReviewDecision",
                "status": "merge_allowed" if allowed else "blocked",
                "independent_review": writer_id != reviewer_id,
                "refs": refs,
                "merge_allowed": allowed,
            }
        )

    def telegram_ingress(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "route",
                "route_qualified",
                "user_allowed",
                "chat_allowed",
                "user_hash",
                "chat_hash",
                "project_id",
                "run_id",
                "bead_id",
                "profile_id",
            },
            "request",
        )
        route = string(data["route"], "request.route")
        qualified = boolean(data["route_qualified"], "request.route_qualified")
        user_allowed = boolean(data["user_allowed"], "request.user_allowed")
        chat_allowed = boolean(data["chat_allowed"], "request.chat_allowed")
        user_hash = digest(data["user_hash"], "request.user_hash")
        chat_hash = digest(data["chat_hash"], "request.chat_hash")
        project_id = identifier(data["project_id"], "request.project_id")
        run_id = identifier(data["run_id"], "request.run_id")
        bead_id = identifier(data["bead_id"], "request.bead_id")
        profile_id = identifier(data["profile_id"], "request.profile_id")
        if (
            route != "dm_polling"
            or not qualified
            or not user_allowed
            or not chat_allowed
            or profile_id not in PROFILE_CONTRACTS
        ):
            fail(
                "telegram_ingress_blocked",
                "request.route",
                "Вход Telegram не разрешён.",
            )
        binding_ref = f"TGB-{sha256_json(data)[:24]}"
        payload_hash = sha256_json(data)
        connection = self._connect()
        try:
            connection.execute(
                "INSERT OR IGNORE INTO telegram_bindings VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    binding_ref,
                    chat_hash,
                    user_hash,
                    project_id,
                    run_id,
                    bead_id,
                    profile_id,
                    payload_hash,
                    _now(),
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "TelegramSessionBindingReceipt",
                "status": "bound",
                "binding_ref": binding_ref,
                "route": route,
                "project_id": project_id,
                "run_id": run_id,
                "bead_id": bead_id,
                "profile_id": profile_id,
                "raw_identifiers_persisted": False,
            }
        )

    def media_ingest(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "media_ref",
                "binding_ref",
                "media_kind",
                "quarantined",
                "artifact_hash",
                "transcript_hash",
                "transformation_ref",
            },
            "request",
        )
        media_ref = identifier(data["media_ref"], "request.media_ref")
        binding_ref = identifier(data["binding_ref"], "request.binding_ref")
        media_kind = string(data["media_kind"], "request.media_kind")
        quarantined = boolean(data["quarantined"], "request.quarantined")
        artifact_hash = digest(data["artifact_hash"], "request.artifact_hash")
        transcript_hash = _nullable_digest(
            data["transcript_hash"], "request.transcript_hash"
        )
        transformation_ref = _nullable_identifier(
            data["transformation_ref"], "request.transformation_ref"
        )
        if media_kind not in {"file", "audio"} or not quarantined:
            fail(
                "telegram_media_blocked",
                "request.media_kind",
                "Медиа не прошло карантин.",
            )
        if media_kind == "audio" and (
            transcript_hash is None
            or transformation_ref is None
            or transcript_hash == artifact_hash
        ):
            fail(
                "telegram_audio_relation_invalid",
                "request.transcript_hash",
                "Связь аудио и расшифровки недействительна.",
            )
        if media_kind == "file" and (
            transcript_hash is not None or transformation_ref is not None
        ):
            fail(
                "telegram_file_relation_invalid",
                "request.transcript_hash",
                "Файл не должен содержать расшифровку.",
            )
        payload_hash = sha256_json(data)
        connection = self._connect()
        try:
            connection.execute(
                "INSERT OR IGNORE INTO media_receipts VALUES (?,?,?,?,?,?,?,?)",
                (
                    media_ref,
                    binding_ref,
                    media_kind,
                    artifact_hash,
                    transcript_hash,
                    transformation_ref,
                    payload_hash,
                    _now(),
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "TelegramMediaReceipt",
                "status": "quarantined",
                "media_ref": media_ref,
                "binding_ref": binding_ref,
                "media_kind": media_kind,
                "artifact_hash": artifact_hash,
                "transcript_hash": transcript_hash,
                "transformation_ref": transformation_ref,
                "separate_hashes": media_kind == "file"
                or transcript_hash != artifact_hash,
            }
        )

    def delivery_prepare(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "idempotency_key",
                "artifact_hash",
                "model_run_id",
                "host_visible_output",
                "accepted_artifact",
            },
            "request",
        )
        key = identifier(data["idempotency_key"], "request.idempotency_key")
        artifact_hash = digest(data["artifact_hash"], "request.artifact_hash")
        model_run_id = identifier(data["model_run_id"], "request.model_run_id")
        if not boolean(
            data["host_visible_output"], "request.host_visible_output"
        ) or not boolean(data["accepted_artifact"], "request.accepted_artifact"):
            fail(
                "delivery_output_blocked",
                "request.host_visible_output",
                "Выход не виден или не принят.",
            )
        payload_hash = sha256_json(data)
        connection = self._connect()
        try:
            existing = connection.execute(
                "SELECT artifact_hash,model_run_id,payload_hash,state FROM deliveries WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO deliveries VALUES (?,?,?,?,?,?,?)",
                    (
                        key,
                        artifact_hash,
                        model_run_id,
                        "prepared",
                        1,
                        payload_hash,
                        _now(),
                    ),
                )
                connection.commit()
                status = "prepared"
            elif existing["payload_hash"] == payload_hash:
                status = str(existing["state"])
            else:
                fail(
                    "delivery_idempotency_conflict",
                    "request.idempotency_key",
                    "Ключ доставки уже использован.",
                )
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "DeliveryPreparationReceipt",
                "status": status,
                "idempotency_key": key,
                "artifact_hash": artifact_hash,
                "model_run_id": model_run_id,
                "model_rerun": False,
            }
        )

    def delivery_reconcile(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "idempotency_key",
                "provider_status",
                "provider_accepted",
                "model_run_id",
            },
            "request",
        )
        key = identifier(data["idempotency_key"], "request.idempotency_key")
        provider_status = string(data["provider_status"], "request.provider_status")
        provider_accepted = boolean(
            data["provider_accepted"], "request.provider_accepted"
        )
        model_run_id = identifier(data["model_run_id"], "request.model_run_id")
        if provider_status not in {"delivered", "timeout", "rejected", "unknown"}:
            fail(
                "provider_status_invalid",
                "request.provider_status",
                "Неизвестный статус доставки.",
            )
        if provider_status == "delivered" and not provider_accepted:
            fail(
                "delivery_readback_conflict",
                "request.provider_accepted",
                "Подтверждение доставки противоречит статусу поставщика.",
            )
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM deliveries WHERE idempotency_key=?", (key,)
            ).fetchone()
            if row is None or row["model_run_id"] != model_run_id:
                fail(
                    "delivery_missing",
                    "request.idempotency_key",
                    "Подготовленная доставка не найдена.",
                )
            state = (
                "delivered"
                if provider_status == "delivered"
                else "ambiguous_delivery"
                if provider_accepted or provider_status in {"timeout", "unknown"}
                else "rejected"
            )
            connection.execute(
                "UPDATE deliveries SET state=?,updated_at=? WHERE idempotency_key=?",
                (state, _now(), key),
            )
            connection.commit()
            artifact_hash = str(row["artifact_hash"])
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "TransportReceipt",
                "status": state,
                "idempotency_key": key,
                "artifact_hash": artifact_hash,
                "model_run_id": model_run_id,
                "model_rerun": False,
                "redelivery_requires_approval": state == "ambiguous_delivery",
            }
        )

    def delivery_redeliver(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "idempotency_key",
                "artifact_hash",
                "user_approved",
                "duplicate_visible",
                "model_rerun",
            },
            "request",
        )
        key = identifier(data["idempotency_key"], "request.idempotency_key")
        artifact_hash = digest(data["artifact_hash"], "request.artifact_hash")
        approved = boolean(data["user_approved"], "request.user_approved")
        visible = boolean(data["duplicate_visible"], "request.duplicate_visible")
        rerun = boolean(data["model_rerun"], "request.model_rerun")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM deliveries WHERE idempotency_key=?", (key,)
            ).fetchone()
            if (
                row is None
                or row["state"] != "ambiguous_delivery"
                or row["artifact_hash"] != artifact_hash
                or not approved
                or not visible
                or rerun
            ):
                fail(
                    "redelivery_blocked", "request", "Повторная доставка не разрешена."
                )
            # Authorization is not a transport observation. Preserve the unknown
            # outcome until a separate provider readback is reconciled.
            attempts = int(row["attempts"])
        finally:
            connection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "RedeliveryAuthorizationReceipt",
                "status": "redelivery_authorized",
                "idempotency_key": key,
                "artifact_hash": artifact_hash,
                "attempts": attempts,
                "duplicate_visible": True,
                "user_notice": (
                    "Возможен повтор сообщения. Разрешено использовать только прежние "
                    f"байты артефакта. SHA-256: {artifact_hash}. "
                    "Исход предыдущей отправки не установлен. Повторная отправка только "
                    "разрешена; отправка и получение этой квитанцией не подтверждены."
                ),
                "model_rerun": False,
                "external_effect_performed": False,
                "delivery_observed": False,
            }
        )

    def present_redelivery(
        self, request: object, artifact: bytes, send_text: Callable[[str], object]
    ) -> dict[str, Any]:
        """Pass an authorized repeat, including its warning, to a text transport."""
        authorization = self.delivery_redeliver(request)
        if (
            authorization.get("contract") != "RedeliveryAuthorizationReceipt"
            or authorization.get("status") != "redelivery_authorized"
            or authorization.get("receipt_hash")
            != sha256_json(
                {k: v for k, v in authorization.items() if k != "receipt_hash"}
            )
            or authorization.get("duplicate_visible") is not True
        ):
            fail("redelivery_blocked", "authorization", "Недействительное разрешение.")
        if (
            type(artifact) is not bytes
            or hashlib.sha256(artifact).hexdigest() != authorization["artifact_hash"]
        ):
            fail("artifact_hash_mismatch", "artifact", "Байты артефакта изменены.")
        try:
            body = artifact.decode("utf-8")
        except UnicodeDecodeError:
            fail("artifact_not_text", "artifact", "Нужен текстовый артефакт.")
        presented_text = authorization["user_notice"] + "\n\n" + body
        binding = {
            "authorization_receipt_hash": authorization["receipt_hash"],
            "artifact_hash": authorization["artifact_hash"],
        }
        return guarded_external(
            self.foundation,
            "redelivery_present",
            binding,
            binding,
            lambda: self._present_authorized(authorization, presented_text, send_text),
            {"transport_invoked"},
        )

    def _present_authorized(
        self,
        authorization: dict[str, Any],
        presented_text: str,
        send_text: Callable[[str], object],
    ) -> dict[str, Any]:
        transport_result = send_text(presented_text)
        return receipt(
            {
                "schema_version": 1,
                "contract": "RedeliveryPresentationReceipt",
                "status": "transport_invoked",
                "artifact_hash": authorization["artifact_hash"],
                "authorization_receipt_hash": authorization["receipt_hash"],
                "presented_text_sha256": hashlib.sha256(
                    presented_text.encode("utf-8")
                ).hexdigest(),
                "transport_receipt": transport_result,
                "delivery_observed": False,
            }
        )

    def route_assess(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "route", "qualified"}, "request")
        route = string(data["route"], "request.route")
        qualified = boolean(data["qualified"], "request.qualified")
        if route not in {"dm_polling", "group", "webhook", "local_bot_api"}:
            fail("telegram_route_invalid", "request.route", "Неизвестный маршрут.")
        allowed = route == "dm_polling" and qualified
        return receipt(
            {
                "schema_version": 1,
                "contract": "TelegramRouteDecision",
                "status": "allowed" if allowed else "blocked",
                "route": route,
                "route_allowed": allowed,
                "dm_polling_baseline_intact": True,
            }
        )


def hashlib_sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
