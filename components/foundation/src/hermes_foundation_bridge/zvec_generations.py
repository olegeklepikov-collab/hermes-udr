"""Parallel FTS index generations with atomic selection and source-fenced rollback."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, receipt, sha256_json
from .platform_io import private_directory, private_file, sync_directory
from .validation import boolean, exact, identifier, integer, mapping
from .zvec_index import INDEX_MANIFEST, ZvecIndexer, _exclusive_bytes


class GenerationError(ValueError):
    def as_dict(self) -> dict[str, str]:
        return {
            "code": str(self),
            "path": "zvec.generation",
            "message": "Операция с поколением индекса отклонена.",
        }


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise GenerationError("index_generation_record_invalid")
    value = json.loads(path.read_text())
    if type(value) is not dict:
        raise GenerationError("index_generation_record_invalid")
    return value


def _descriptor(root: Path, generation: str) -> dict[str, Any]:
    identifier(generation, "generation_id")
    if (root / "generations").is_symlink():
        raise GenerationError("index_generation_directory_invalid")
    value = _read(root / "generations" / (generation + ".json"))
    expected = (
        INDEX_MANIFEST["index_id"]
        if generation.startswith("legacy-")
        else f"generations/{generation}/index"
    )
    if (
        value.get("generation_id") != generation
        or value.get("collection_ref") != expected
        or value.get("manifest_hash") != sha256_json(INDEX_MANIFEST)
    ):
        raise GenerationError("index_generation_manifest_mismatch")
    collection = root / expected
    if (
        collection.is_symlink()
        or not collection.is_dir()
        or not collection.resolve().is_relative_to(root.resolve())
    ):
        raise GenerationError("index_generation_unavailable")
    return value


def _pointer(root: Path) -> dict[str, Any] | None:
    path = root / "active-generation.json"
    if not path.exists() and not path.is_symlink():
        return None
    value = _read(path)
    descriptor = _descriptor(root, value.get("active", ""))
    if value.get("schema_version") != 1 or value.get("descriptor_hash") != sha256_json(
        descriptor
    ):
        raise GenerationError("index_generation_pointer_invalid")
    return value


def selected_collection(root: Path) -> Path:
    pointer = _pointer(root)
    if pointer is None:
        return root / INDEX_MANIFEST["index_id"]
    return root / _descriptor(root, pointer["active"])["collection_ref"]


def _source_hash(indexer: ZvecIndexer) -> str:
    if not indexer.source_root.is_dir() or indexer.source_root.is_symlink():
        raise GenerationError("index_generation_source_missing")
    rows = {}
    for label, directory in (
        ("ledger", indexer.source_root),
        ("tombstones", indexer.tombstones),
    ):
        if directory.is_symlink():
            raise GenerationError("index_generation_source_invalid")
        if directory.is_dir():
            for path in sorted(directory.iterdir()):
                if path.is_symlink() or not path.is_file():
                    raise GenerationError("index_generation_source_invalid")
                rows[label + "/" + path.name] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return sha256_json(rows)


def _publish(root: Path, value: dict[str, Any]) -> None:
    fd, name = tempfile.mkstemp(prefix=".generation-", dir=root)
    try:
        private_file(fd)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(canonical_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if fd >= 0:
            os.close(fd)
        Path(name).unlink(missing_ok=True)
        raise
    os.replace(name, root / "active-generation.json")
    sync_directory(root)


def transition(indexer: ZvecIndexer, request: object) -> dict[str, Any]:
    data = mapping(request, "request")
    exact(
        data,
        {
            "schema_version",
            "apply",
            "expected_document_count",
            "expected_active_count",
            "generation_action",
            "generation_id",
        },
        "request",
    )
    if data["schema_version"] != 1 or data["generation_action"] not in {
        "replace",
        "rollback",
    }:
        raise GenerationError("index_generation_request_invalid")
    generation = identifier(data["generation_id"], "request.generation_id")
    documents = integer(
        data["expected_document_count"], "request.expected_document_count"
    )
    active = integer(data["expected_active_count"], "request.expected_active_count")
    if active > documents:
        raise GenerationError("index_generation_count_invalid")
    apply = boolean(data["apply"], "request.apply")
    if not apply:
        return receipt(
            {
                "contract": "ZvecGenerationReceipt",
                "status": "dry_run_ready",
                "generation_id": generation,
                "apply_requested": False,
            }
        )
    indexer._ensure_ready()
    with indexer._writer():
        fingerprint = _source_hash(indexer)
        pointer = _pointer(indexer.root)
        prior = pointer["active"] if pointer else "legacy-" + fingerprint[:24]
        directory = indexer.root / "generations"
        if directory.is_symlink():
            raise GenerationError("index_generation_directory_invalid")
        directory.mkdir(mode=0o700, exist_ok=True)
        private_directory(directory)
        if data["generation_action"] == "rollback":
            if pointer is None or pointer.get("previous") != generation:
                raise GenerationError("index_generation_not_previous")
            descriptor = _descriptor(indexer.root, generation)
            if descriptor["source_hash"] != fingerprint:
                raise GenerationError("index_generation_rollback_stale")
        elif pointer and pointer["active"] == generation:
            descriptor = _descriptor(indexer.root, generation)
            if descriptor["source_hash"] != fingerprint:
                raise GenerationError("index_generation_replay_stale")
        else:
            if generation.startswith("legacy-"):
                raise GenerationError("index_generation_reserved")
            if pointer is None:
                legacy = {
                    "generation_id": prior,
                    "collection_ref": INDEX_MANIFEST["index_id"],
                    "manifest_hash": sha256_json(INDEX_MANIFEST),
                    "source_hash": fingerprint,
                    "document_count": documents,
                    "active_count": active,
                }
                legacy_path = directory / (prior + ".json")
            target = directory / generation
            target.mkdir(mode=0o700)
            private_directory(target)
            builder = ZvecIndexer(indexer.foundation)
            builder._generation_override = True
            builder.collection_path = target / "index"
            builder.migrate(apply=True, _already_locked=True)
            result = builder.rebuild_from_sources(
                {
                    "schema_version": 1,
                    "apply": True,
                    "expected_document_count": documents,
                    "expected_active_count": active,
                },
                _already_locked=True,
            )
            if (
                result["status"] != "rebuild_verified"
                or _source_hash(indexer) != fingerprint
            ):
                raise GenerationError("index_generation_build_unverified")
            if pointer is None and not legacy_path.exists():
                _exclusive_bytes(legacy_path, canonical_bytes(legacy))
            descriptor = {
                "generation_id": generation,
                "collection_ref": f"generations/{generation}/index",
                "manifest_hash": sha256_json(INDEX_MANIFEST),
                "source_hash": fingerprint,
                "document_count": documents,
                "active_count": active,
            }
            _exclusive_bytes(
                directory / (generation + ".json"), canonical_bytes(descriptor)
            )
        if (
            descriptor["document_count"] != documents
            or descriptor["active_count"] != active
        ):
            raise GenerationError("index_generation_count_mismatch")
        if prior != generation:
            _publish(
                indexer.root,
                {
                    "schema_version": 1,
                    "active": generation,
                    "previous": prior,
                    "descriptor_hash": sha256_json(descriptor),
                },
            )
        indexer._refresh_generation()
    return receipt(
        {
            "contract": "ZvecGenerationReceipt",
            "status": "selected",
            "generation_id": generation,
            "previous_generation_id": pointer["previous"]
            if prior == generation and pointer
            else prior,
            "source_hash": fingerprint,
            "manifest_hash": sha256_json(INDEX_MANIFEST),
            "collection_ref": descriptor["collection_ref"],
            "atomic_pointer_switch": True,
            "switch_performed": prior != generation,
            "prior_index_retained": True,
            "embedding_model": "none",
            "dimension": 0,
            "production_activation_allowed": False,
        }
    )
