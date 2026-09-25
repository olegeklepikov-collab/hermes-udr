"""Versioned Zvec FTS index rebuilt from an immutable derived-source ledger."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt, sha256_json
from .config import child
from .errors import BridgeError, fail
from .validation import (
    ID_RE,
    boolean,
    digest,
    exact,
    identifier,
    integer,
    mapping,
    string,
)

INDEX_MANIFEST = {
    "schema_version": 1,
    "index_id": "retrieval-fragments-v2",
    "source_ledger_id": "retrieval-source-ledger-v2",
    "rebuild_authority": "accepted_derived_source_ledger",
    "collection_class": "retrieval_fragments",
    "zvec_version": "0.7.0",
    "embedding_model": "none",
    "dimension": 0,
    "tokenizer": "standard",
    "token_filters": ["lowercase", "ascii_folding"],
    "chunking": "upstream_exact_fragment",
    "sparse_retrieval": "fts_bm25",
    "reranker": "none",
    "locale": "multilingual_unicode",
    "writer_count": 1,
    "reader_mode": "read_only",
}
_SENSITIVE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|secret|authorization|bearer)[\s:=]"
)
_ORIGINAL_REF = re.compile(r"^originals/([0-9a-f]{64})$")
_MAX_CONTENT_BYTES = 65536
_MAX_ORIGINAL_BYTES = 64 * 1024 * 1024


def _exclusive_bytes(path: Path, payload: bytes) -> None:
    """Publish one immutable ledger file before derived-index effects."""
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _zvec() -> Any:
    try:
        import zvec  # type: ignore[import-not-found]
    except ImportError as error:
        raise BridgeError(
            "zvec_unavailable", "runtime.zvec", "Zvec 0.7.0 недоступен."
        ) from error
    if getattr(zvec, "__version__", None) != "0.7.0":
        fail("zvec_version_mismatch", "runtime.zvec", "Требуется Zvec 0.7.0.")
    return zvec


class ZvecIndexer:
    def __init__(self, root: Path):
        self.foundation = root
        self.root = child(root, "zvec")
        self.collection_path = child(self.root, INDEX_MANIFEST["index_id"])
        self.manifest_path = child(self.root, "index-manifest.json")
        self.lock_path = child(self.root, ".writer.lock")
        self.source_root = child(self.root, INDEX_MANIFEST["source_ledger_id"])
        self.originals = child(root, "artifacts", "originals")
        self.tombstones = child(root, "artifacts", "tombstones")
        self._generation_override = False

    def _refresh_generation(self) -> Path:
        if not self._generation_override:
            from .zvec_generations import selected_collection

            self.collection_path = selected_collection(self.root)
        return self.collection_path

    def _source_path(self, document_id: str) -> Path:
        return child(self.source_root, f"{document_id}.json")

    def _accepted_path(self, document_id: str) -> Path:
        return child(self.source_root, f"{document_id}.accepted")

    def _tombstone_path(self, document_id: str) -> Path:
        return child(self.source_root, f"{document_id}.tombstone")

    def _original(self, source_ref: str, artifact_id: str) -> tuple[Path, str]:
        match = _ORIGINAL_REF.fullmatch(source_ref)
        if match is None:
            fail(
                "source_ref_invalid",
                "request.source_ref",
                "Требуется точная ссылка на original.",
            )
        original_hash = match.group(1)
        if artifact_id != f"ART-{original_hash[:24]}":
            fail(
                "artifact_ref_mismatch",
                "request.artifact_id",
                "Идентификатор артефакта не совпадает.",
            )
        path = child(self.originals, original_hash)
        if path.is_symlink() or not path.is_file():
            fail(
                "original_unavailable",
                "request.source_ref",
                "Исходный артефакт отсутствует.",
            )
        computed = hashlib.sha256()
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as error:
            raise BridgeError(
                "original_unavailable",
                "request.source_ref",
                "Исходный артефакт недоступен.",
            ) from error
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_ORIGINAL_BYTES:
                fail(
                    "original_unavailable",
                    "request.source_ref",
                    "Исходный артефакт недоступен.",
                )
            while chunk_data := os.read(descriptor, 65536):
                computed.update(chunk_data)
        finally:
            os.close(descriptor)
        if computed.hexdigest() != original_hash:
            fail(
                "original_hash_mismatch",
                "request.source_ref",
                "Хеш исходного артефакта не совпадает.",
            )
        metadata_root = child(self.foundation, "artifacts", "metadata")
        linked = False
        if metadata_root.is_dir() and not metadata_root.is_symlink():
            for metadata_path in metadata_root.glob("*.json"):
                if (
                    metadata_path.is_symlink()
                    or not metadata_path.is_file()
                    or metadata_path.stat().st_size > 8192
                ):
                    continue
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    continue
                if (
                    isinstance(metadata, dict)
                    and metadata.get("artifact_id") == artifact_id
                    and metadata.get("content_hash") == original_hash
                ):
                    linked = True
                    break
        if not linked:
            fail(
                "artifact_metadata_missing",
                "request.artifact_id",
                "Метаданные приёмки отсутствуют.",
            )
        if (self.tombstones / f"{artifact_id}.json").exists():
            fail(
                "source_tombstoned", "request.artifact_id", "Исходный артефакт удалён."
            )
        return path, original_hash

    def _ledger_record(self, document_id: str) -> dict[str, Any]:
        path = self._source_path(document_id)
        if path.is_symlink() or not path.is_file():
            fail(
                "source_ledger_missing",
                "zvec.source_ledger",
                "Запись источника отсутствует.",
            )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            fail(
                "source_ledger_corrupt",
                "zvec.source_ledger",
                "Запись источника повреждена.",
            )
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "document_id",
            "artifact_id",
            "source_ref",
            "original_hash",
            "content",
            "content_hash",
            "evidence_status",
        }:
            fail(
                "source_ledger_corrupt",
                "zvec.source_ledger",
                "Запись источника повреждена.",
            )
        if value["document_id"] != document_id or value["schema_version"] != 1:
            fail(
                "source_ledger_corrupt",
                "zvec.source_ledger",
                "Идентификатор не совпадает.",
            )
        if (
            not isinstance(value["artifact_id"], str)
            or not ID_RE.fullmatch(value["artifact_id"])
            or not isinstance(value["original_hash"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["original_hash"])
            or not isinstance(value["content_hash"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["content_hash"])
        ):
            fail(
                "source_ledger_corrupt", "zvec.source_ledger", "Поля хешей повреждены."
            )
        content = value["content"]
        if (
            not isinstance(content, str)
            or not content
            or len(content.encode("utf-8")) > _MAX_CONTENT_BYTES
            or hashlib.sha256(content.encode()).hexdigest() != value["content_hash"]
            or _SENSITIVE.search(content)
        ):
            fail(
                "source_ledger_corrupt",
                "zvec.source_ledger",
                "Хеш содержимого не совпадает.",
            )
        if (
            not isinstance(value["source_ref"], str)
            or _ORIGINAL_REF.fullmatch(value["source_ref"]) is None
            or value["original_hash"] != value["source_ref"].split("/", 1)[1]
            or value["artifact_id"] != f"ART-{value['original_hash'][:24]}"
        ):
            fail(
                "source_ledger_corrupt",
                "zvec.source_ledger",
                "Связь с original недействительна.",
            )
        if value["evidence_status"] != "derived_candidate":
            fail(
                "source_ledger_corrupt",
                "zvec.source_ledger",
                "Класс происхождения недействителен.",
            )
        return value

    def _accepted(self, document_id: str, content_hash: str) -> bool:
        path = self._accepted_path(document_id)
        if path.is_symlink() or not path.is_file():
            return False
        try:
            return path.read_text(encoding="ascii") == content_hash + "\n"
        except (OSError, UnicodeError):
            return False

    @contextmanager
    def _writer(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._refresh_generation()
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def migrate(self, *, apply: bool, _already_locked: bool = False) -> dict[str, Any]:
        zvec = _zvec()
        if not apply:
            return receipt(
                {
                    "schema_version": 1,
                    "contract": "ZvecMigrationReceipt",
                    "status": "dry_run_ready",
                    "manifest": INDEX_MANIFEST,
                    "manifest_hash": sha256_json(INDEX_MANIFEST),
                    "apply_requested": False,
                }
            )
        with nullcontext() if _already_locked else self._writer():
            if self.manifest_path.exists():
                existing = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if existing != INDEX_MANIFEST:
                    fail(
                        "index_manifest_conflict",
                        "zvec.manifest",
                        "Манифест индекса отличается.",
                    )
            else:
                payload = canonical_bytes(INDEX_MANIFEST) + b"\n"
                descriptor = os.open(
                    self.manifest_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                try:
                    os.write(descriptor, payload)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            if not self.collection_path.exists():
                schema = zvec.CollectionSchema(
                    name=INDEX_MANIFEST["index_id"],
                    fields=[
                        zvec.FieldSchema(
                            "content",
                            zvec.DataType.STRING,
                            index_param=zvec.FtsIndexParam(
                                tokenizer_name="standard",
                                filters=["lowercase", "ascii_folding"],
                            ),
                        ),
                        zvec.FieldSchema("source_ref", zvec.DataType.STRING),
                        zvec.FieldSchema("artifact_id", zvec.DataType.STRING),
                        zvec.FieldSchema("content_hash", zvec.DataType.STRING),
                        zvec.FieldSchema(
                            "active",
                            zvec.DataType.BOOL,
                            index_param=zvec.InvertIndexParam(),
                        ),
                    ],
                )
                collection = zvec.create_and_open(str(self.collection_path), schema)
                collection.flush()
                collection.close()
            if self.source_root.is_symlink():
                fail(
                    "source_ledger_invalid",
                    "zvec.source_ledger",
                    "Небезопасный каталог источников.",
                )
            self.source_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return receipt(
            {
                "schema_version": 1,
                "contract": "ZvecMigrationReceipt",
                "status": "applied",
                "manifest": INDEX_MANIFEST,
                "manifest_hash": sha256_json(INDEX_MANIFEST),
                "apply_requested": True,
                "readback_verified": self.collection_path.is_dir()
                and json.loads(self.manifest_path.read_text()) == INDEX_MANIFEST
                and self.source_root.is_dir(),
            }
        )

    def _ensure_ready(self) -> None:
        self._refresh_generation()
        if not self.collection_path.is_dir() or not self.manifest_path.is_file():
            fail("zvec_index_unavailable", "runtime.zvec", "Индекс не подготовлен.")
        if json.loads(self.manifest_path.read_text(encoding="utf-8")) != INDEX_MANIFEST:
            fail(
                "index_manifest_conflict",
                "zvec.manifest",
                "Манифест индекса отличается.",
            )

    def upsert(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(
            data,
            {
                "schema_version",
                "document_id",
                "artifact_id",
                "source_ref",
                "content",
                "content_hash",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        document_id = identifier(data["document_id"], "request.document_id")
        artifact_id = identifier(data["artifact_id"], "request.artifact_id")
        source_ref = string(data["source_ref"], "request.source_ref")
        content = string(data["content"], "request.content")
        if len(content.encode("utf-8")) > _MAX_CONTENT_BYTES:
            fail("content_too_large", "request.content", "Фрагмент превышает 64 КиБ.")
        content_hash = digest(data["content_hash"], "request.content_hash")
        if hashlib.sha256(content.encode()).hexdigest() != content_hash:
            fail(
                "content_hash_mismatch",
                "request.content_hash",
                "Хеш текста не совпадает.",
            )
        if _SENSITIVE.search(content) or _SENSITIVE.search(source_ref):
            fail(
                "secret_scan_failed",
                "request.content",
                "Потенциальный секрет запрещён.",
            )
        self._ensure_ready()
        _original_path, original_hash = self._original(source_ref, artifact_id)
        source_record = {
            "schema_version": 1,
            "document_id": document_id,
            "artifact_id": artifact_id,
            "source_ref": source_ref,
            "original_hash": original_hash,
            "content": content,
            "content_hash": content_hash,
            "evidence_status": "derived_candidate",
        }
        zvec = _zvec()
        with self._writer():
            source_path = self._source_path(document_id)
            if source_path.exists():
                if self._ledger_record(document_id) != source_record:
                    fail(
                        "source_ledger_conflict",
                        "request.document_id",
                        "Идентификатор уже связан с другим фрагментом.",
                    )
                ledger_status = "idempotent_existing"
            else:
                _exclusive_bytes(source_path, canonical_bytes(source_record) + b"\n")
                ledger_status = "created"
            collection = zvec.open(str(self.collection_path))
            try:
                collection.upsert(
                    zvec.Doc(
                        document_id,
                        fields={
                            "content": content,
                            "source_ref": source_ref,
                            "artifact_id": artifact_id,
                            "content_hash": content_hash,
                            "active": True,
                        },
                    )
                )
                collection.flush()
                row = collection.fetch(
                    document_id,
                    output_fields=[
                        "source_ref",
                        "artifact_id",
                        "content_hash",
                        "active",
                    ],
                    include_vector=False,
                ).get(document_id)
            finally:
                collection.close()
            verified = bool(
                row
                and row.fields.get("content_hash") == content_hash
                and row.fields.get("artifact_id") == artifact_id
                and row.fields.get("source_ref") == source_ref
                and row.fields.get("active") is True
            )
            if verified:
                accepted_path = self._accepted_path(document_id)
                if accepted_path.exists():
                    if not self._accepted(document_id, content_hash):
                        fail(
                            "source_acceptance_conflict",
                            "zvec.source_ledger",
                            "Маркер принятия не совпадает.",
                        )
                else:
                    _exclusive_bytes(
                        accepted_path, (content_hash + "\n").encode("ascii")
                    )
        return receipt(
            {
                "schema_version": 1,
                "contract": "ZvecIndexWriteReceipt",
                "status": "indexed" if verified else "blocked",
                "document_id": document_id,
                "artifact_id": artifact_id,
                "source_ref": source_ref,
                "content_hash": content_hash,
                "readback_verified": verified,
                "source_ledger_status": ledger_status,
                "source_ledger_hash": sha256_json(source_record),
                "rebuildable_from_ledger": verified,
                "evidence_status": "derived_candidate",
                "writer_count": 1,
            }
        )

    def rebuild_from_sources(
        self, request: object, *, _already_locked: bool = False
    ) -> dict[str, Any]:
        data = mapping(request, "request")
        if "generation_action" in data or "generation_id" in data:
            from .zvec_generations import transition

            return transition(self, data)
        exact(
            data,
            {
                "schema_version",
                "apply",
                "expected_document_count",
                "expected_active_count",
            },
            "request",
        )
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        apply = boolean(data["apply"], "request.apply")
        expected_documents = integer(
            data["expected_document_count"], "request.expected_document_count"
        )
        expected_active = integer(
            data["expected_active_count"], "request.expected_active_count"
        )
        if expected_active > expected_documents:
            fail(
                "rebuild_count_invalid",
                "request.expected_active_count",
                "Число активных записей превышает исходное.",
            )
        if not apply:
            return receipt(
                {
                    "schema_version": 1,
                    "contract": "ZvecSourceRebuildReceipt",
                    "status": "dry_run_ready",
                    "apply_requested": False,
                    "expected_document_count": expected_documents,
                    "expected_active_count": expected_active,
                    "source_ledger_id": INDEX_MANIFEST["source_ledger_id"],
                    "index_bytes_used_as_source": False,
                    "evidence_promoted": False,
                }
            )
        self._ensure_ready()
        zvec = _zvec()
        with nullcontext() if _already_locked else self._writer():
            source_paths = sorted(self.source_root.glob("*.json"))
            if len(source_paths) != expected_documents:
                fail(
                    "rebuild_source_count_mismatch",
                    "zvec.source_ledger",
                    "Число источников не совпадает.",
                )
            active_records: list[dict[str, Any]] = []
            for path in source_paths:
                document_id = path.stem
                if not ID_RE.fullmatch(document_id):
                    fail(
                        "source_ledger_corrupt",
                        "zvec.source_ledger",
                        "Идентификатор повреждён.",
                    )
                record = self._ledger_record(document_id)
                if not self._accepted(document_id, record["content_hash"]):
                    fail(
                        "source_acceptance_missing",
                        "zvec.source_ledger",
                        "Запись не была принята для индексирования.",
                    )
                marker = self._tombstone_path(document_id)
                if marker.exists():
                    try:
                        marker_valid = (
                            not marker.is_symlink()
                            and marker.read_text(encoding="ascii")
                            == record["content_hash"] + "\n"
                        )
                    except (OSError, UnicodeError):
                        marker_valid = False
                    if not marker_valid:
                        fail(
                            "source_tombstone_corrupt",
                            "zvec.source_ledger",
                            "Маркер удаления повреждён.",
                        )
                    continue
                if (self.tombstones / f"{record['artifact_id']}.json").exists():
                    continue
                self._original(record["source_ref"], record["artifact_id"])
                active_records.append(record)
            if len(active_records) != expected_active:
                fail(
                    "rebuild_active_count_mismatch",
                    "zvec.source_ledger",
                    "Число активных записей не совпадает.",
                )
            collection = zvec.open(str(self.collection_path))
            try:
                if any(
                    collection.iter_docs(output_fields=["active"], include_vector=False)
                ):
                    fail(
                        "rebuild_target_not_empty",
                        "zvec.collection",
                        "Целевой индекс не пуст.",
                    )
                for record in active_records:
                    collection.upsert(
                        zvec.Doc(
                            record["document_id"],
                            fields={
                                "content": record["content"],
                                "source_ref": record["source_ref"],
                                "artifact_id": record["artifact_id"],
                                "content_hash": record["content_hash"],
                                "active": True,
                            },
                        )
                    )
                collection.flush()
                readback = (
                    collection.fetch(
                        [record["document_id"] for record in active_records],
                        output_fields=[
                            "content",
                            "source_ref",
                            "artifact_id",
                            "content_hash",
                            "active",
                        ],
                        include_vector=False,
                    )
                    if active_records
                    else {}
                )
                verified = all(
                    record["document_id"] in readback
                    and readback[record["document_id"]].fields
                    == {
                        "content": record["content"],
                        "source_ref": record["source_ref"],
                        "artifact_id": record["artifact_id"],
                        "content_hash": record["content_hash"],
                        "active": True,
                    }
                    for record in active_records
                )
            finally:
                collection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "ZvecSourceRebuildReceipt",
                "status": "rebuild_verified" if verified else "blocked",
                "apply_requested": True,
                "document_count": len(source_paths),
                "active_count": len(active_records),
                "source_record_set_hash": sha256_json(
                    [
                        {
                            "document_id": record["document_id"],
                            "content_hash": record["content_hash"],
                        }
                        for record in active_records
                    ]
                ),
                "source_ledger_id": INDEX_MANIFEST["source_ledger_id"],
                "index_bytes_used_as_source": False,
                "original_hashes_readback": True,
                "evidence_promoted": False,
                "production_activation_allowed": False,
            }
        )

    def query(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "query", "limit"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        query = string(data["query"], "request.query")
        limit = integer(data["limit"], "request.limit", minimum=1)
        if limit > 100:
            fail("limit_too_large", "request.limit", "Предел превышает 100.")
        self._ensure_ready()
        zvec = _zvec()
        collection_path = self._refresh_generation()
        collection = zvec.open(
            str(collection_path), zvec.CollectionOption(read_only=True)
        )
        try:
            rows = collection.query(
                zvec.Query("content", fts=zvec.Fts(match_string=query)),
                topk=limit * 5,
                filter="active = true",
                include_vector=False,
                output_fields=["content", "source_ref", "artifact_id", "content_hash"],
            )
            results = []
            for row in rows:
                document_id = row.id
                content_hash = row.fields.get("content_hash")
                artifact_id = row.fields.get("artifact_id")
                if (
                    not isinstance(document_id, str)
                    or not ID_RE.fullmatch(document_id)
                    or not isinstance(content_hash, str)
                    or not isinstance(artifact_id, str)
                    or not ID_RE.fullmatch(artifact_id)
                    or not self._accepted(document_id, content_hash)
                    or self._tombstone_path(document_id).exists()
                    or (self.tombstones / f"{artifact_id}.json").exists()
                ):
                    continue
                try:
                    source = self._ledger_record(document_id)
                except BridgeError:
                    continue
                if (
                    source["content_hash"] != content_hash
                    or source["content"] != row.fields.get("content")
                    or source["artifact_id"] != artifact_id
                    or source["source_ref"] != row.fields.get("source_ref")
                ):
                    continue
                results.append(
                    {
                        "document_id": document_id,
                        "score": row.score,
                        "content": row.fields.get("content"),
                        "source_ref": row.fields.get("source_ref"),
                        "artifact_id": artifact_id,
                        "content_hash": content_hash,
                    }
                )
                if len(results) >= limit:
                    break
        finally:
            collection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "ZvecQueryReceipt",
                "collection_ref": collection_path.relative_to(self.root).as_posix(),
                "status": "queried",
                "manifest_hash": sha256_json(INDEX_MANIFEST),
                "reader_mode": "read_only",
                "result_count": len(results),
                "results": results,
            }
        )

    def tombstone(self, request: object) -> dict[str, Any]:
        data = mapping(request, "request")
        exact(data, {"schema_version", "artifact_id"}, "request")
        if data["schema_version"] != 1:
            fail(
                "unsupported_schema",
                "request.schema_version",
                "Поддерживается версия 1.",
            )
        artifact_id = identifier(data["artifact_id"], "request.artifact_id")
        self._ensure_ready()
        zvec = _zvec()
        changed = 0
        with self._writer():
            source_markers = 0
            for path in sorted(self.source_root.glob("*.json")):
                document_id = path.stem
                if not ID_RE.fullmatch(document_id):
                    fail(
                        "source_ledger_corrupt",
                        "zvec.source_ledger",
                        "Идентификатор повреждён.",
                    )
                source = self._ledger_record(document_id)
                if source["artifact_id"] == artifact_id:
                    marker = self._tombstone_path(document_id)
                    if not marker.exists():
                        _exclusive_bytes(
                            marker, (source["content_hash"] + "\n").encode("ascii")
                        )
                        source_markers += 1
            collection = zvec.open(str(self.collection_path))
            try:
                for row in collection.iter_docs(
                    output_fields=[
                        "content",
                        "source_ref",
                        "artifact_id",
                        "content_hash",
                        "active",
                    ],
                    include_vector=False,
                ):
                    if (
                        row.fields.get("artifact_id") == artifact_id
                        and row.fields.get("active") is True
                    ):
                        row.fields["active"] = False
                        collection.update(row)
                        changed += 1
                collection.flush()
                remaining = sum(
                    1
                    for row in collection.iter_docs(
                        output_fields=["artifact_id", "active"],
                        include_vector=False,
                    )
                    if row.fields.get("artifact_id") == artifact_id
                    and row.fields.get("active") is True
                )
            finally:
                collection.close()
        return receipt(
            {
                "schema_version": 1,
                "contract": "ZvecTombstoneReceipt",
                "status": "propagated" if remaining == 0 else "blocked",
                "artifact_id": artifact_id,
                "deactivated_count": changed,
                "source_tombstone_marker_count": source_markers,
                "active_query_visibility": remaining != 0,
                "restore_view_active": False,
            }
        )


def migrate_request(request: object, indexer: ZvecIndexer) -> dict[str, Any]:
    data = mapping(request, "request")
    exact(data, {"schema_version", "apply"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    return indexer.migrate(apply=boolean(data["apply"], "request.apply"))
