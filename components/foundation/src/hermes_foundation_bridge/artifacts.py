"""Crash-aware immutable artifact service bound to one foundation root."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import canonical_bytes, receipt
from .config import child
from .errors import BridgeError, fail
from .validation import exact, identifier, integer, mapping, string


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _relative(value: object, path: str) -> str:
    text = string(value, path)
    candidate = PurePosixPath(text)
    if candidate.is_absolute() or ".." in candidate.parts or text in {".", ""}:
        fail("invalid_relative_path", path, "Требуется безопасный относительный путь.")
    return candidate.as_posix()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _exclusive_json(path: Path, value: object) -> None:
    payload = canonical_bytes(value) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".artifact-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise BridgeError(
                "metadata_exists", "artifact.metadata", "Метаданные уже существуют."
            ) from error
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


class ArtifactService:
    def __init__(self, root: Path):
        self.root = child(root, "artifacts")
        self.quarantine = child(self.root, "quarantine")
        self.originals = child(self.root, "originals")
        self.metadata = child(self.root, "metadata")
        self.tombstones = child(self.root, "tombstones")

    def prepare(self, *, dry_run: bool) -> dict[str, Any]:
        directories = (
            self.root,
            self.quarantine,
            self.originals,
            self.metadata,
            self.tombstones,
        )
        if not dry_run:
            for directory in directories:
                if directory.is_symlink():
                    fail(
                        "artifact_root_symlink",
                        "artifact_root",
                        "Ссылка вместо каталога запрещена.",
                    )
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                directory.chmod(0o700)
        return receipt(
            {
                "schema_version": 1,
                "contract": "ArtifactServiceMigrationReceipt",
                "status": "dry_run_ready" if dry_run else "applied",
                "directory_count": len(directories),
                "permission_mode": "0700",
                "apply_requested": not dry_run,
            }
        )

    def _read_source(self, relative: str, max_bytes: int) -> tuple[bytes, str]:
        parts = PurePosixPath(relative).parts
        source = self.quarantine
        info = self.quarantine.lstat()
        for index, part in enumerate(parts):
            source = child(source, part)
            try:
                info = source.lstat()
            except OSError as error:
                raise BridgeError(
                    "artifact_source_unavailable",
                    "request.relative_path",
                    "Вход недоступен.",
                ) from error
            if stat.S_ISLNK(info.st_mode):
                fail(
                    "artifact_symlink_rejected",
                    "request.relative_path",
                    "Символическая ссылка запрещена.",
                )
            if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                fail(
                    "artifact_parent_invalid",
                    "request.relative_path",
                    "Промежуточный путь не является каталогом.",
                )
        if not stat.S_ISREG(info.st_mode):
            fail(
                "artifact_non_regular_rejected",
                "request.relative_path",
                "Допустим только обычный файл.",
            )
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            descriptor = os.open(source, flags)
        except OSError as error:
            raise BridgeError(
                "artifact_source_unavailable",
                "request.relative_path",
                "Вход недоступен.",
            ) from error
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                fail(
                    "artifact_non_regular_rejected",
                    "request.relative_path",
                    "Допустим только обычный файл.",
                )
            if info.st_size > max_bytes:
                fail(
                    "artifact_size_exceeded",
                    "request.max_bytes",
                    "Размер превышает предел.",
                )
            chunks: list[bytes] = []
            total = 0
            digest = hashlib.sha256()
            while True:
                chunk_data = os.read(descriptor, min(65536, max_bytes + 1 - total))
                if not chunk_data:
                    break
                total += len(chunk_data)
                if total > max_bytes:
                    fail(
                        "artifact_size_exceeded",
                        "request.max_bytes",
                        "Размер превышает предел.",
                    )
                chunks.append(chunk_data)
                digest.update(chunk_data)
            return b"".join(chunks), digest.hexdigest()
        finally:
            os.close(descriptor)

    @contextmanager
    def _writer(self):
        descriptor = os.open(
            child(self.root, ".writer.lock"),
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                fail(
                    "artifact_writer_lock_invalid",
                    "artifact_root",
                    "Недопустимый файл блокировки.",
                )
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        fail(
                            "artifact_writer_busy",
                            "artifact_root",
                            "Писатель занят; повтор допустим после освобождения.",
                        )
                    time.sleep(0.02)
            yield
        finally:
            os.close(descriptor)

    def _reconcile_duplicate_temporaries(
        self, payload: bytes, metadata_path: Path
    ) -> list[str]:
        """Quarantine exact original duplicates and drafts of the same committed acquisition."""
        recovered = []
        metadata = metadata_path.read_bytes()
        for directory, pattern, expected in (
            (self.originals, ".original-*", payload),
            (self.metadata, ".artifact-*", metadata),
        ):
            for path in directory.glob(pattern):
                if path.is_symlink():
                    continue
                descriptor = os.open(
                    path,
                    os.O_RDONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0),
                )
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > (
                        65536 if directory == self.metadata else len(expected)
                    ):
                        continue
                    raw = stream.read(info.st_size + 1)
                    matches = raw == expected
                    if not matches and directory == self.metadata:
                        try:
                            draft = json.loads(raw)
                            committed = json.loads(expected)
                            matches = (
                                type(draft) is dict
                                and draft.keys() == committed.keys()
                                and all(
                                    draft[key] == committed[key]
                                    for key in committed
                                    if key != "created_at"
                                )
                                and datetime.fromisoformat(draft["created_at"]).tzinfo
                                is not None
                            )
                        except (ValueError, TypeError, KeyError):
                            matches = False
                    if not matches:
                        continue
                target_root = child(self.quarantine, "recovered-temporaries")
                if target_root.is_symlink():
                    fail(
                        "artifact_recovery_target_invalid",
                        "artifact_root",
                        "Ссылка вместо карантина запрещена.",
                    )
                target_root.mkdir(mode=0o700, exist_ok=True)
                target = child(target_root, directory.name + "-" + path.name[1:])
                try:
                    os.link(path, target)
                except FileExistsError:
                    # Resume a crash after link publication, without trusting a
                    # different pre-existing file or following a symbolic link.
                    prior = target.lstat()
                    current = path.lstat()
                    if not stat.S_ISREG(prior.st_mode) or (
                        prior.st_dev,
                        prior.st_ino,
                    ) != (current.st_dev, current.st_ino):
                        continue
                _fsync_directory(target_root)
                path.unlink()
                _fsync_directory(directory)
                recovered.append(str(target.relative_to(self.root)))
        return recovered

    def ingest(self, request: object) -> dict[str, Any]:
        if not self.root.is_dir() or self.root.is_symlink():
            fail(
                "artifact_service_unavailable",
                "artifact_root",
                "Artifact service не подготовлен.",
            )
        with self._writer():
            return self._ingest(request)

    def _ingest(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "acquisition_id",
                "relative_path",
                "media_type",
                "max_bytes",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        acquisition_id = identifier(data["acquisition_id"], "request.acquisition_id")
        relative = _relative(data["relative_path"], "request.relative_path")
        media_type = string(data["media_type"], "request.media_type")
        if len(media_type) > 128:
            fail(
                "artifact_media_type_invalid",
                "request.media_type",
                "Длина типа содержимого превышает контрактный предел.",
            )
        max_bytes = integer(data["max_bytes"], "request.max_bytes", minimum=1)
        if max_bytes > 64 * 1024 * 1024:
            fail(
                "artifact_limit_too_large",
                "request.max_bytes",
                "Предел превышает 64 МиБ.",
            )
        if not self.root.is_dir():
            fail(
                "artifact_service_unavailable",
                "artifact_root",
                "Artifact service не подготовлен.",
            )
        payload, content_hash = self._read_source(relative, max_bytes)
        destination = child(self.originals, content_hash)
        created = False
        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                fail(
                    "artifact_destination_invalid",
                    "artifact.original",
                    "Хранилище повреждено.",
                )
            if hashlib.sha256(destination.read_bytes()).hexdigest() != content_hash:
                fail(
                    "artifact_hash_conflict",
                    "artifact.original",
                    "Конфликт содержимого.",
                )
        else:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".original-", dir=self.originals
            )
            temporary = Path(temporary_name)
            try:
                os.fchmod(descriptor, 0o600)
                written = 0
                while written < len(payload):
                    written += os.write(descriptor, payload[written:])
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = -1
                try:
                    os.link(temporary, destination)
                    created = True
                except FileExistsError:
                    if (
                        hashlib.sha256(destination.read_bytes()).hexdigest()
                        != content_hash
                    ):
                        fail(
                            "artifact_hash_conflict",
                            "artifact.original",
                            "Конфликт содержимого.",
                        )
                _fsync_directory(self.originals)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                if temporary.exists():
                    temporary.unlink()
        artifact_id = f"ART-{content_hash[:24]}"
        metadata_path = child(self.metadata, f"{acquisition_id}.json")
        acquisition = {
            "schema_version": 1,
            "acquisition_id": acquisition_id,
            "artifact_id": artifact_id,
            "content_hash": content_hash,
            "byte_size": len(payload),
            "media_type": media_type,
            "original_ref": f"originals/{content_hash}",
            "created_at": _now(),
        }
        if metadata_path.exists():
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            same_acquisition = all(
                existing.get(key) == acquisition[key]
                for key in (
                    "acquisition_id",
                    "artifact_id",
                    "content_hash",
                    "byte_size",
                    "media_type",
                    "original_ref",
                )
            )
            if not same_acquisition:
                fail(
                    "acquisition_id_conflict",
                    "request.acquisition_id",
                    "Идентификатор уже использован.",
                )
            metadata_status = "idempotent_existing"
        else:
            _exclusive_json(metadata_path, acquisition)
            metadata_status = "created"
        readback_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
        accepted = readback_hash == content_hash
        recovered = (
            self._reconcile_duplicate_temporaries(payload, metadata_path)
            if accepted
            else []
        )
        return receipt(
            {
                "schema_version": 1,
                "contract": "ArtifactIngestReceipt",
                "status": "accepted" if accepted else "blocked",
                "artifact_id": artifact_id,
                "acquisition_id": acquisition_id,
                "content_hash": content_hash,
                "byte_size": len(payload),
                "media_type": media_type,
                "disposition": "verified_new_artifact"
                if created
                else "idempotent_existing",
                "metadata_status": metadata_status,
                "temporary_write": True,
                "file_fsync": True,
                "atomic_publish": True,
                "directory_fsync": True,
                "metadata_committed": True,
                "reconciled_temporary_refs": recovered,
                "readback_verified": accepted,
                "claim_status_changed": False,
                "release_changed": False,
            }
        )

    def recover(self) -> dict[str, Any]:
        if not self.originals.is_dir() or not self.metadata.is_dir():
            fail(
                "artifact_service_unavailable",
                "artifact_root",
                "Artifact service не подготовлен.",
            )
        referenced: set[str] = set()
        corrupt_metadata = 0
        for path in self.metadata.glob("*.json"):
            try:
                descriptor = os.open(
                    path,
                    os.O_RDONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0),
                )
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                        raise ValueError("invalid metadata file")
                    row = json.loads(stream.read(65537))
                if type(row) is not dict:
                    raise ValueError("invalid metadata object")
                referenced.add(string(row.get("content_hash"), "metadata.content_hash"))
            except (OSError, ValueError, BridgeError):
                corrupt_metadata += 1
        orphan_hashes = sorted(
            path.name
            for path in self.originals.iterdir()
            if path.is_file() and not path.is_symlink() and path.name not in referenced
        )
        pending_metadata = sorted(
            path.name for path in self.metadata.glob(".artifact-*")
        )
        return receipt(
            {
                "schema_version": 1,
                "contract": "ArtifactRecoveryReceipt",
                "status": "recovery_required"
                if orphan_hashes or corrupt_metadata or pending_metadata
                else "consistent",
                "orphan_count": len(orphan_hashes),
                "orphan_refs": [f"originals/{name}" for name in orphan_hashes],
                "corrupt_metadata_count": corrupt_metadata,
                "temporary_metadata_count": len(pending_metadata),
                "temporary_metadata_refs": [
                    f"metadata/{name}" for name in pending_metadata
                ],
                "orphans_accepted": False,
            }
        )

    def tombstone(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "artifact_id", "reason_code"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        artifact_id = identifier(data["artifact_id"], "request.artifact_id")
        reason = identifier(data["reason_code"], "request.reason_code")
        path = child(self.tombstones, f"{artifact_id}.json")
        body = {
            "schema_version": 1,
            "artifact_id": artifact_id,
            "reason_code": reason,
            "created_at": _now(),
            "propagation": {
                "derived_index": "pending",
                "graph": "pending",
                "restore_view": "blocked",
            },
        }
        if not path.exists():
            _exclusive_json(path, body)
            status = "recorded"
        else:
            status = "idempotent_existing"
        zvec_propagated = False
        try:
            from .zvec_index import ZvecIndexer

            indexer = ZvecIndexer(self.root.parent)
            if indexer.collection_path.is_dir() and indexer.manifest_path.is_file():
                zvec_receipt = indexer.tombstone(
                    {"schema_version": 1, "artifact_id": artifact_id}
                )
                zvec_propagated = zvec_receipt["status"] == "propagated"
        except (BridgeError, OSError, ValueError):
            zvec_propagated = False
        graph_propagated = False
        try:
            from .graphiti_adapter import GraphitiAdapter

            graph = GraphitiAdapter(self.root.parent)
            if graph.manifest_path.is_file():
                graph_receipt = graph.tombstone(artifact_id)
                graph_propagated = graph_receipt["status"] == "propagated"
        except (BridgeError, OSError, ValueError):
            graph_propagated = False
        propagation_complete = zvec_propagated and graph_propagated
        return receipt(
            {
                "schema_version": 1,
                "contract": "ArtifactTombstoneReceipt",
                "status": status,
                "artifact_id": artifact_id,
                "active": False,
                "restore_allowed": False,
                "zvec_propagated": zvec_propagated,
                "graph_propagated": graph_propagated,
                "propagation_complete": propagation_complete,
                "release_allowed": False,
            }
        )
