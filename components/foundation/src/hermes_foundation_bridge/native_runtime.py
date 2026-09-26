"""Validated host-owned routing for the local AgentMemory and Neo4j workers."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from .errors import BridgeError, fail

_FIELDS = {
    "schema_version", "mode", "node_path", "python_path", "agentmemory_url",
    "neo4j_uri", "neo4j_user", "neo4j_password_file",
}
_USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")


def _invalid() -> None:
    fail("native_runtime_invalid", "native_runtime", "Неверная настройка локальных служб.")


def assert_private_file(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        _invalid()
    try:
        info = path.stat()
    except OSError:
        _invalid()
    if not stat.S_ISREG(info.st_mode):
        _invalid()
    if os.name == "nt":
        from .platform_io import windows_private_file_allowed
        if not windows_private_file_allowed(path):
            _invalid()
    elif info.st_uid != os.getuid() or info.st_mode & 0o077:
        _invalid()


def _loopback(value: object, schemes: set[str]) -> str:
    if type(value) is not str:
        _invalid()
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in schemes and parsed.hostname in {"127.0.0.1", "::1"}
                 and parsed.username is None and parsed.password is None
                 and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
                 and parsed.port is not None and 1 <= parsed.port <= 65535)
    except ValueError:
        valid = False
    if not valid:
        _invalid()
    return value.rstrip("/")


def load_native_runtime(root: Path) -> dict[str, object]:
    path = root / "native-runtime.json"
    if not path.exists() and not path.is_symlink():
        fail("native_runtime_missing", "native_runtime", "Укажите native-runtime.json для локальных служб.")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        _invalid()
    assert_private_file(path)

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                _invalid()
            result[key] = value
        return result

    try:
        config = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _invalid()
    if (type(config) is not dict or set(config) != _FIELDS
            or type(config["schema_version"]) is not int or config["schema_version"] != 1
            or config["mode"] != "native"):
        _invalid()
    for name in ("node_path", "python_path"):
        value = config[name]
        if type(value) is not str or not Path(value).is_absolute() or not Path(value).is_file():
            _invalid()
    config["agentmemory_url"] = _loopback(config["agentmemory_url"], {"http"})
    config["neo4j_uri"] = _loopback(config["neo4j_uri"], {"bolt"})
    if type(config["neo4j_user"]) is not str or not _USER.fullmatch(config["neo4j_user"]):
        _invalid()
    secret = config["neo4j_password_file"]
    if type(secret) is not str:
        _invalid()
    assert_private_file(Path(secret))
    return config


def invoke_worker(executable: str, worker: Path, request: dict[str, object], *, failure_code: str, response_code: str, error_path: str) -> dict[str, object]:
    try:
        completed = subprocess.run(
            [executable, str(worker)], input=json.dumps(request), capture_output=True,
            text=True, encoding="utf-8", check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BridgeError(failure_code, error_path, "Операция локальной службы отклонена.") from error
    if completed.returncode != 0:
        raise BridgeError(failure_code, error_path, "Операция локальной службы отклонена.")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise BridgeError(response_code, error_path, "Ответ локальной службы поврежден.") from error
    if not isinstance(result, dict):
        raise BridgeError(response_code, error_path, "Ответ локальной службы поврежден.")
    if result.get("status") == "error":
        raise BridgeError(failure_code, error_path, "Операция локальной службы отклонена.")
    return result
