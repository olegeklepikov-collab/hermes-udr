"""Bounded JSON input and atomic exclusive output for skill scripts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 4_000_000


def read_private_bytes(path: Path, *, maximum: int = 250_000) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o077
            or metadata.st_size > maximum
        ):
            raise ValueError("private_artifact_invalid")
        return stream.read(maximum + 1)


def new_private_directory(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("output_path_invalid")
    ancestor = path.parent
    while ancestor != ancestor.parent:
        if ancestor.is_symlink():
            raise ValueError("output_path_invalid")
        ancestor = ancestor.parent
    parent_stat = path.parent.stat()
    if not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_mode & 0o022:
        raise ValueError("output_parent_untrusted")
    os.mkdir(path, mode=0o700)


def write_exclusive_bytes(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Повтор поля JSON: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Недопустимая константа JSON: {value}")


def load_json(path: Path) -> tuple[object, str]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Вход должен быть обычным файлом.")
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Файл превышает ограничение входа.")
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    digest = hashlib.sha256(raw).hexdigest()
    from hermes_research_report.turn_trace import artifact_read

    artifact_read(path, value, digest)
    return value, digest


def write_exclusive_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        linked = True
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if linked:
            path.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(encoded).hexdigest()
    # Existing artifacts remain authoritative. The optional inherited turn journal
    # stores only references and hashes after the exclusive file commit succeeds.
    from hermes_research_report.turn_trace import artifact_written

    artifact_written(path, value, digest)
    return digest
