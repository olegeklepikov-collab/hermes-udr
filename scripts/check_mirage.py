"""Smoke-check Mirage 0.0.6's read-only disk mount over real MCP stdio.

Run this script with the isolated Python 3.12 environment containing
mirage-ai==0.0.6 and mcp==1.30.0. It starts no daemon and uses only a
temporary local directory.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import sys
import tempfile
from pathlib import Path


def require_versions() -> None:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("check_mirage requires Python 3.12")
    for package, expected in (("mirage-ai", "0.0.6"), ("mcp", "1.30.0")):
        actual = importlib.metadata.version(package)
        if actual != expected:
            raise RuntimeError(f"{package} must be {expected}; found {actual}")


def response_text(result: object) -> str:
    return "\n".join(
        block.text for block in getattr(result, "content", ())
        if getattr(block, "type", None) == "text"
    )


async def check(config: Path, disk_root: Path) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.shared.exceptions import McpError

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mirage.cli.main", "mcp", str(config)],
    )
    async with asyncio.timeout(30):
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                initialized = await client.initialize()
                if initialized.serverInfo.name != "mirage":
                    raise AssertionError("unexpected MCP server")
                listed = await client.list_tools()
                names = {tool.name for tool in listed.tools}
                if not {"read", "write"} <= names:
                    raise AssertionError("Mirage MCP read/write tools missing")

                read = await client.call_tool("read", {"path": "/disk/example.txt"})
                if getattr(read, "isError", False) or "mirage-read-example" not in response_text(read):
                    raise AssertionError("MCP read did not return the example")

                denied = False
                try:
                    write = await client.call_tool(
                        "write", {"path": "/disk/forbidden.txt", "content": "should-not-exist"}
                    )
                    message = response_text(write).lower()
                    denied = bool(getattr(write, "isError", False)) and any(
                        word in message for word in ("permission", "denied", "read-only", "read only")
                    )
                except McpError as error:
                    message = str(error).lower()
                    denied = any(word in message for word in ("permission", "denied", "read-only", "read only"))
                if not denied:
                    raise AssertionError("MCP write was not denied by READ policy")
    if (disk_root / "forbidden.txt").exists():
        raise AssertionError("denied write changed the disk mount")


def main() -> None:
    require_versions()
    with tempfile.TemporaryDirectory(prefix="mirage-mcp-smoke-") as temporary:
        root = Path(temporary)
        disk = root / "disk"
        disk.mkdir()
        (disk / "example.txt").write_text("mirage-read-example\n", encoding="utf-8")
        config = root / "workspace.yaml"
        config.write_text(
            "mode: READ\n"
            "runtimes:\n"
            "  - vfs\n"
            "mounts:\n"
            "  /disk:\n"
            "    resource: disk\n"
            "    mode: READ\n"
            "    config:\n"
            f"      root: {json.dumps(str(disk))}\n",
            encoding="utf-8",
        )
        asyncio.run(check(config, disk))
    print("Mirage MCP stdio READ smoke passed")


if __name__ == "__main__":
    main()
