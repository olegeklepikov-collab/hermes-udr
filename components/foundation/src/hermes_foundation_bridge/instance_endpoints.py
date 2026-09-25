"""Optional fixed-shape endpoints for one isolated local foundation root."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

from .errors import fail

DEFAULT_PREFIX = "hermes-foundation"
DEFAULT_DOLT_SQL_PORT = 3317
_LOCAL_PREFIX = re.compile(r"e2e[0-9a-z](?:[0-9a-z-]{0,15}[0-9a-z])?\Z")


def instance_endpoints(root: Path) -> dict[str, object]:
    """Derive container names and a loopback port; never accept arbitrary hosts."""
    if not root.is_absolute() or root == Path("/") or root.is_symlink():
        fail("instance_root_invalid", "foundation_root", "Небезопасный корень.")
    path = root / "instance-endpoints.json"
    if not path.exists() and not path.is_symlink():
        prefix, port, custom = DEFAULT_PREFIX, DEFAULT_DOLT_SQL_PORT, False
    else:
        if path.is_symlink() or not path.is_file():
            fail(
                "instance_endpoints_invalid",
                "instance_endpoints",
                "Неверный файл адресов.",
            )
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode) or mode & 0o022 or path.stat().st_size > 256:
            fail(
                "instance_endpoints_invalid",
                "instance_endpoints",
                "Неверный файл адресов.",
            )

        def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    fail(
                        "instance_endpoints_invalid",
                        "instance_endpoints",
                        "Повтор поля.",
                    )
                result[key] = value
            return result

        try:
            value = json.loads(
                path.read_bytes().decode("utf-8"), object_pairs_hook=unique_pairs
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            fail("instance_endpoints_invalid", "instance_endpoints", "Неверный JSON.")
        if type(value) is not dict or set(value) != {
            "schema_version",
            "prefix",
            "dolt_sql_port",
        }:
            fail("instance_endpoints_invalid", "instance_endpoints", "Неверная схема.")
        prefix, port = value["prefix"], value["dolt_sql_port"]
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or type(prefix) is not str
            or not _LOCAL_PREFIX.fullmatch(prefix)
            or type(port) is not int
            or not 1024 <= port <= 65535
            or port == DEFAULT_DOLT_SQL_PORT
        ):
            fail(
                "instance_endpoints_invalid",
                "instance_endpoints",
                "Недопустимые адреса.",
            )
        custom = True
    return {
        "custom": custom,
        "prefix": prefix,
        "network": f"{prefix}-net",
        "graphiti_container": f"{prefix}-graphiti",
        "falkordb_container": f"{prefix}-falkordb",
        "agentmemory_container": f"{prefix}-agentmemory",
        "dolt_sql_host": "127.0.0.1",
        "dolt_sql_port": port,
    }
