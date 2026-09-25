"""Import classified portable data as inert files; never restore runtime authority."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from .canonical import verify_receipt_hash, with_receipt_hash
from .portability import assess_bundle_import

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
_FORBIDDEN_FILES = {
    ".env",
    "auth.json",
    "credentials.json",
    "authorized_keys",
    ".netrc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    ".git",
    ".ssh",
    ".beads",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    value = json.loads(
        data,
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")),
    )
    if type(value) is not dict:
        raise ValueError("object_required")
    return value


def _parts(relative: object) -> list[str]:
    if (
        type(relative) is not str
        or len(relative) > 1024
        or "\\" in relative
        or "\0" in relative
    ):
        raise ValueError("nonportable_path")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts) or ":" in parts[0]:
        raise ValueError("nonportable_path")
    return parts


def _read(root: Path, relative: str, limit: int) -> bytes:
    if os.open not in os.supports_dir_fd or not all(
        hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    ):
        raise ValueError("portable_filesystem_unsupported")
    parts = _parts(relative)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        file_fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
        )
        with os.fdopen(file_fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("source_file_invalid_or_too_large")
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError("source_file_too_large")
            return data
    finally:
        os.close(fd)


def _identity(row: dict[str, Any]) -> str:
    if (
        type(row) is not dict
        or type(row.get("id")) is not str
        or not 1 <= len(row["id"]) <= 512
        or any(ord(c) < 32 for c in row["id"])
    ):
        raise ValueError("object_id_invalid")
    if type(row.get("revision")) is not int or not 1 <= row["revision"] <= 2**31 - 1:
        raise ValueError("object_revision_invalid")
    if type(row.get("content_hash")) is not str or not _HASH.fullmatch(
        row["content_hash"]
    ):
        raise ValueError("object_hash_invalid")
    return f"{row['id']}@{row['revision']}"


def _write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fchmod(stream.fileno(), 0o444)
        os.fsync(stream.fileno())


def _sync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def import_bundle(bundle: Path, output: Path) -> dict[str, Any]:
    manifest_bytes = _read(bundle, "manifest.json", 1024 * 1024)
    manifest = _json(manifest_bytes)
    if set(manifest) != {"schema_version", "bundle_id", "objects"} or (
        type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
    ):
        raise ValueError("bundle_manifest_invalid")
    if type(manifest["bundle_id"]) is not str or not _ID.fullmatch(
        manifest["bundle_id"]
    ):
        raise ValueError("bundle_id_invalid")
    rows = manifest["objects"]
    if type(rows) is not list or not 1 <= len(rows) <= 256:
        raise ValueError("bundle_objects_invalid")
    objects = {}
    payloads = {}
    total = 0
    planned = []
    paths = set()
    for row in rows:
        if type(row) is not dict or set(row) != {
            "id",
            "revision",
            "content_hash",
            "relative_path",
            "kind",
            "contains_secret",
        }:
            raise ValueError("bundle_object_invalid")
        key = _identity(row)
        if key in objects or row["relative_path"] in paths:
            raise ValueError("duplicate_object_or_path")
        parts = _parts(row["relative_path"])
        if (
            row["kind"] not in {"artifact", "history"}
            or row["contains_secret"] is not False
        ):
            raise ValueError("nonportable_object_class")
        if any(
            part.lower() in _FORBIDDEN_FILES or part.lower().startswith(".env.")
            for part in parts
        ) or parts[-1].lower().endswith((".key", ".pem", ".p12", ".pfx")):
            raise ValueError("credential_file_forbidden")
        data = _read(bundle, row["relative_path"], min(MAX_FILE, MAX_TOTAL - total))
        total += len(data)
        if _sha(data) != row["content_hash"]:
            raise ValueError("source_hash_mismatch")
        objects[key] = {
            "id": row["id"],
            "revision": row["revision"],
            "content_hash": row["content_hash"],
            "kind": row["kind"],
            "relative_path": "objects/" + row["content_hash"],
        }
        payloads[row["content_hash"]] = data
        paths.add(row["relative_path"])
        planned.append({key: value for key, value in row.items() if key != "kind"})
    decision = assess_bundle_import(
        {
            "schema_version": 1,
            "bundle_id": manifest["bundle_id"],
            "manifest_hash": _sha(manifest_bytes),
            "objects": planned,
            "target_inventory": [],
        }
    )
    if not decision["commit_allowed"]:
        raise ValueError("import_plan_blocked")
    output = output.parent.resolve(strict=True) / output.name
    if output == bundle.resolve() or bundle.resolve() in output.parents:
        raise ValueError("output_inside_source_bundle")
    output.mkdir(
        mode=0o700
    )  # Exclusive reservation; an existing target is never replaced.
    _sync(output.parent)
    (output / "objects").mkdir(mode=0o700)
    for digest, data in payloads.items():
        _write(output / "objects" / digest, data)
    _sync(output / "objects")
    _write(output / "manifest.json", manifest_bytes)
    _write(
        output / "import-decision.json",
        (json.dumps(decision, ensure_ascii=False, sort_keys=True) + "\n").encode(),
    )
    root_map = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "PortableDataRootMap",
            "bundle_id": manifest["bundle_id"],
            "source_manifest_sha256": _sha(manifest_bytes),
            "import_decision_receipt_hash": decision["receipt_hash"],
            "root": ".",
            "objects": objects,
            "authority_restored": False,
            "work_resumed": False,
            "product_qualified": False,
        }
    )
    # The map is the commit marker. Without it, a partial directory is not an import.
    _write(
        output / "root-map.json",
        (json.dumps(root_map, ensure_ascii=False, sort_keys=True) + "\n").encode(),
    )
    _sync(output)
    return root_map


def resolve_object(root: Path, object_id: str, revision: int) -> dict[str, Any]:
    root_map = _json(_read(root, "root-map.json", 1024 * 1024))
    if (
        type(root_map.get("objects")) is not dict
        or root_map.get("product_qualified") is not False
        or not verify_receipt_hash(root_map)
        or root_map.get("contract") != "PortableDataRootMap"
        or root_map.get("root") != "."
        or root_map.get("authority_restored") is not False
        or root_map.get("work_resumed") is not False
    ):
        raise ValueError("root_map_invalid")
    manifest_bytes = _read(root, "manifest.json", 1024 * 1024)
    manifest = _json(manifest_bytes)
    decision = _json(_read(root, "import-decision.json", 1024 * 1024))
    if (
        _sha(manifest_bytes) != root_map.get("source_manifest_sha256")
        or not verify_receipt_hash(decision)
        or decision.get("receipt_hash") != root_map.get("import_decision_receipt_hash")
        or decision.get("commit_allowed") is not True
        or decision.get("manifest_hash") != _sha(manifest_bytes)
        or set(decision.get("new_objects", [])) != set(root_map["objects"])
    ):
        raise ValueError("root_map_lineage_invalid")
    key = f"{object_id}@{revision}"
    row = root_map["objects"].get(key)
    if (
        type(row) is not dict
        or _identity(row) != key
        or row.get("kind") not in {"artifact", "history"}
    ):
        raise ValueError("object_not_resolvable")
    source_rows = [
        item for item in manifest.get("objects", []) if _identity(item) == key
    ]
    if len(source_rows) != 1 or any(
        source_rows[0].get(field) != row[field]
        for field in ("id", "revision", "content_hash", "kind")
    ):
        raise ValueError("object_lineage_invalid")
    relative = "objects/" + row["content_hash"]
    if row.get("relative_path") != relative:
        raise ValueError("root_map_path_invalid")
    data = _read(root, relative, MAX_FILE)
    if _sha(data) != row["content_hash"]:
        raise ValueError("resolved_hash_mismatch")
    return with_receipt_hash(
        {
            "contract": "PortableObjectResolution",
            "object_ref": key,
            "content_hash": row["content_hash"],
            "path": str(root.resolve() / relative),
            "root_map_receipt_hash": root_map["receipt_hash"],
            "read_scope": "inert_data",
            "verify_hash_on_subsequent_read": True,
            "authority_granted": False,
        }
    )
