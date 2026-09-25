"""Verify one fixed, signed bridge release and persist a content-bound receipt."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import canonical_bytes, receipt, sha256_json
from .errors import BridgeError, fail
from .validation import exact, mapping, string

RELEASE_NAME = "hermes-foundation-bridge"
from . import __version__

RELEASE_VERSION = __version__
ARCHIVE_NAME = f"{RELEASE_NAME}-{RELEASE_VERSION}.zip"
SIGNATURE_NAME = f"{ARCHIVE_NAME}.minisig"
PUBLIC_KEY_NAME = "release-signing.pub"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 256
REQUIRED_MEMBERS = {
    "LICENSE",
    "LICENSE_STATUS.md",
    "RELEASE.md",
    "RECOVERY.md",
    "DOLT_SQL.md",
    "SBOM.json",
    "bridge-lock.json",
    "plugin.py",
    "plugin.yaml",
    PUBLIC_KEY_NAME,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def trusted_public_key_path() -> Path:
    return Path(__file__).resolve().parents[2] / PUBLIC_KEY_NAME


def verification_receipt_path(root: Path) -> Path:
    return root / "runtime" / "release-verification.json"


def _regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        fail("release_file_invalid", label, "Ожидался обычный файл выпуска.")


def _safe_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    path = PurePosixPath(name)
    mode = (info.external_attr >> 16) & 0o170000
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or ".." in path.parts
        or info.is_dir()
        or mode == stat.S_IFLNK
        or info.file_size > MAX_MEMBER_BYTES
    ):
        fail(
            "release_archive_invalid", "release.archive", "Небезопасный состав архива."
        )


def _write_receipt(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        fail(
            "release_receipt_path_invalid",
            "release.receipt",
            "Небезопасный путь квитанции.",
        )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".release-", dir=path.parent)
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


def _verify_signature(archive: Path, signature: Path, public_key: Path) -> None:
    executable = shutil.which("minisign")
    if executable is None:
        fail("minisign_unavailable", "release.signature", "Minisign недоступен.")
    try:
        result = subprocess.run(
            [
                executable,
                "-V",
                "-q",
                "-m",
                str(archive),
                "-x",
                str(signature),
                "-p",
                str(public_key),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        fail(
            "release_signature_check_failed",
            "release.signature",
            "Проверка подписи не выполнена.",
        )
    if result.returncode != 0:
        fail(
            "release_signature_invalid",
            "release.signature",
            "Подпись выпуска недействительна.",
        )


def _manifest(archive: Path, expected_commit: str, public_key: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if not infos or len(infos) > MAX_MEMBERS:
                fail(
                    "release_archive_invalid",
                    "release.archive",
                    "Недопустимое число файлов.",
                )
            names: list[str] = []
            total = 0
            for info in infos:
                _safe_member(info)
                total += info.file_size
                if total > MAX_TOTAL_BYTES or info.filename in names:
                    fail(
                        "release_archive_invalid",
                        "release.archive",
                        "Недопустимый состав архива.",
                    )
                names.append(info.filename)
            if names.count("bundle-manifest.json") != 1:
                fail(
                    "release_manifest_invalid",
                    "release.manifest",
                    "Манифест выпуска отсутствует.",
                )
            raw_manifest = json.loads(bundle.read("bundle-manifest.json"))
            if type(raw_manifest) is not dict:
                fail(
                    "release_manifest_invalid",
                    "release.manifest",
                    "Манифест выпуска недействителен.",
                )
            manifest = raw_manifest
            expected = {
                "schema_version": 1,
                "bundle_type": "hermes-plugin",
                "name": RELEASE_NAME,
                "version": RELEASE_VERSION,
                "release_status": "release",
                "signature_scheme": "minisign",
                "trusted_public_key_sha256": _sha256(public_key),
                "source_commit": expected_commit,
                "source_tree_clean": True,
                "license_status": "Apache-2.0",
                "production_activation_allowed": False,
            }
            if any(manifest.get(key) != value for key, value in expected.items()):
                fail(
                    "release_manifest_mismatch",
                    "release.manifest",
                    "Манифест не совпадает с ожиданиями.",
                )
            rows = manifest.get("files")
            if type(rows) is not list:
                fail(
                    "release_manifest_invalid",
                    "release.manifest.files",
                    "Список файлов недействителен.",
                )
            listed: set[str] = set()
            for row in rows:
                if type(row) is not dict or set(row) != {"path", "sha256", "bytes"}:
                    fail(
                        "release_manifest_invalid",
                        "release.manifest.files",
                        "Запись файла недействительна.",
                    )
                name = row.get("path")
                if (
                    type(name) is not str
                    or name in listed
                    or name == "bundle-manifest.json"
                ):
                    fail(
                        "release_manifest_invalid",
                        "release.manifest.files",
                        "Путь файла недействителен.",
                    )
                content = bundle.read(name)
                if row.get("sha256") != _sha256(content) or row.get("bytes") != len(
                    content
                ):
                    fail(
                        "release_file_hash_mismatch",
                        "release.manifest.files",
                        "Хэш файла не совпадает.",
                    )
                listed.add(name)
            if set(names) != listed | {"bundle-manifest.json"}:
                fail(
                    "release_manifest_invalid",
                    "release.manifest.files",
                    "Состав архива не совпадает.",
                )
            if not REQUIRED_MEMBERS <= listed:
                fail(
                    "release_manifest_invalid",
                    "release.manifest.files",
                    "Обязательные файлы отсутствуют.",
                )
            if bundle.read(PUBLIC_KEY_NAME) != public_key:
                fail(
                    "release_public_key_mismatch",
                    "release.public_key",
                    "Открытый ключ не совпадает.",
                )
            lock = json.loads(bundle.read("bridge-lock.json"))
            bridge = lock.get("bridge") if type(lock) is dict else None
            if not isinstance(bridge, dict) or any(
                bridge.get(key) != value
                for key, value in {
                    "version": RELEASE_VERSION,
                    "source_commit_binding": "bundle-manifest.json#source_commit",
                    "source_tree_binding": "bundle-manifest.json#source_tree_clean",
                    "signature_status": "minisign_external",
                    "trusted_public_key": PUBLIC_KEY_NAME,
                    "license_status": "Apache-2.0",
                    "production_activation_allowed": False,
                }.items()
            ):
                fail(
                    "release_lock_mismatch",
                    "release.bridge_lock",
                    "Фиксация выпуска недействительна.",
                )
            return manifest
    except BridgeError:
        raise
    except (KeyError, json.JSONDecodeError, OSError, ValueError, zipfile.BadZipFile):
        fail(
            "release_archive_invalid",
            "release.archive",
            "Архив выпуска недействителен.",
        )


def verify_release(request: object, root: Path) -> dict[str, Any]:
    data = mapping(request, "request")
    exact(data, {"schema_version", "expected_version", "expected_commit"}, "request")
    if data["schema_version"] != 1:
        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    version = string(data["expected_version"], "request.expected_version")
    commit = string(data["expected_commit"], "request.expected_commit")
    if version != RELEASE_VERSION:
        fail(
            "release_version_mismatch",
            "request.expected_version",
            "Версия выпуска не совпадает.",
        )
    if not COMMIT_RE.fullmatch(commit):
        fail(
            "release_commit_invalid",
            "request.expected_commit",
            "Ожидался точный 40-символьный коммит.",
        )
    release = root / "releases" / f"{RELEASE_NAME}-{RELEASE_VERSION}"
    if release.is_symlink() or not release.is_dir():
        fail(
            "release_directory_invalid",
            "release.directory",
            "Каталог выпуска недействителен.",
        )
    archive = release / ARCHIVE_NAME
    signature = release / SIGNATURE_NAME
    supplied_key = release / PUBLIC_KEY_NAME
    trusted_key = trusted_public_key_path()
    for path, label in (
        (archive, "release.archive"),
        (signature, "release.signature"),
        (supplied_key, "release.public_key"),
        (trusted_key, "release.trusted_public_key"),
    ):
        _regular_file(path, label)
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        fail("release_archive_too_large", "release.archive", "Архив превышает предел.")
    public_key = trusted_key.read_bytes()
    if supplied_key.read_bytes() != public_key:
        fail(
            "release_public_key_mismatch",
            "release.public_key",
            "Открытый ключ не совпадает.",
        )
    _verify_signature(archive, signature, trusted_key)
    manifest = _manifest(archive, commit, public_key)
    result = receipt(
        {
            "schema_version": 1,
            "contract": "FoundationReleaseVerificationReceipt",
            "status": "verified",
            "name": RELEASE_NAME,
            "version": RELEASE_VERSION,
            "source_commit": commit,
            "source_tree_clean": True,
            "archive_sha256": _sha256(archive.read_bytes()),
            "manifest_sha256": sha256_json(manifest),
            "public_key_sha256": _sha256(public_key),
            "signature_scheme": "minisign",
            "signature_verified": True,
            "license_status": "Apache-2.0",
            "production_activation_allowed": False,
        }
    )
    _write_receipt(verification_receipt_path(root), result)
    return result


def release_verified(root: Path) -> tuple[bool, dict[str, Any] | None]:
    path = verification_receipt_path(root)
    if path.is_symlink() or not path.is_file():
        return False, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if type(value) is not dict:
            return False, None
        stored_hash = value.get("receipt_hash")
        unhashed = {key: item for key, item in value.items() if key != "receipt_hash"}
        valid = (
            stored_hash == sha256_json(unhashed)
            and value.get("status") == "verified"
            and value.get("name") == RELEASE_NAME
            and value.get("version") == RELEASE_VERSION
            and value.get("source_tree_clean") is True
            and value.get("signature_scheme") == "minisign"
            and value.get("signature_verified") is True
            and value.get("license_status") == "Apache-2.0"
            and value.get("production_activation_allowed") is False
            and isinstance(value.get("source_commit"), str)
            and COMMIT_RE.fullmatch(value["source_commit"]) is not None
        )
        return valid, value if valid else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False, None
