"""Start, inspect and stop one loopback-only staging Dolt SQL server."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_foundation_bridge.dolt_sql import DoltSQLAdapter, authority_manifest

_CHILDREN: dict[int, subprocess.Popen[bytes]] = {}


def _paths(foundation: Path) -> tuple[Path, Path, Path]:
    if (
        not foundation.is_absolute()
        or foundation == Path("/")
        or foundation.is_symlink()
    ):
        raise ValueError("invalid foundation root")
    data_dir = foundation / "dolt"
    if data_dir.is_symlink() or not data_dir.is_dir():
        raise ValueError("Dolt data directory unavailable")
    return (
        data_dir / "server.yaml",
        data_dir / "server.pid",
        data_dir / "logs" / "server.log",
    )


def _pid(pidfile: Path, config: Path) -> int | None:
    if not pidfile.exists():
        return None
    if pidfile.is_symlink() or not pidfile.is_file() or pidfile.stat().st_mode & 0o077:
        raise RuntimeError("Dolt pidfile invalid")
    try:
        pid = int(pidfile.read_text(encoding="ascii").strip())
    except (OSError, UnicodeError, ValueError) as error:
        raise RuntimeError("Dolt pidfile corrupt") from error
    if pid < 2:
        raise RuntimeError("Dolt pid invalid")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    command = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout
    if "dolt sql-server" not in command or str(config) not in command:
        raise RuntimeError("pid belongs to another process")
    return pid


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def manage(foundation: Path, operation: str) -> dict[str, object]:
    config, pidfile, logfile = _paths(foundation)
    port = authority_manifest(foundation)["port"]
    current = _pid(pidfile, config)
    if operation == "status":
        return {
            "schema_version": 1,
            "status": "running" if current and _port_open(port) else "stopped",
            "loopback_port": port,
            "managed_pid_present": current is not None,
            "production_activation_allowed": False,
        }
    if operation == "start":
        if current:
            return manage(foundation, "status")
        if pidfile.exists() or _port_open(port):
            raise RuntimeError("stale pidfile or occupied loopback port")
        if config.is_symlink() or not config.is_file():
            raise RuntimeError("Dolt server configuration absent")
        DoltSQLAdapter(foundation)._configuration()
        logfile.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if logfile.parent.is_symlink() or logfile.is_symlink():
            raise RuntimeError("Dolt log path invalid")
        descriptor = os.open(logfile, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            process = subprocess.Popen(
                ["dolt", "sql-server", "--config", str(config)],
                stdin=subprocess.DEVNULL,
                stdout=descriptor,
                stderr=descriptor,
                start_new_session=True,
                close_fds=True,
            )
            _CHILDREN[process.pid] = process
        finally:
            os.close(descriptor)
        for _attempt in range(50):
            if process.poll() is not None:
                raise RuntimeError("Dolt SQL server exited during startup")
            if _port_open(port):
                break
            time.sleep(0.1)
        else:
            process.terminate()
            raise RuntimeError("Dolt SQL server startup timed out")
        descriptor = os.open(pidfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, f"{process.pid}\n".encode("ascii"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return {
            "schema_version": 1,
            "status": "running",
            "loopback_port": port,
            "managed_pid_present": True,
            "secret_values_recorded": False,
            "production_activation_allowed": False,
        }
    if operation == "stop":
        if current is None:
            return manage(foundation, "status")
        os.kill(current, signal.SIGTERM)
        for _attempt in range(100):
            status = subprocess.run(
                ["ps", "-p", str(current), "-o", "stat="],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            if not status or status.startswith("Z"):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Dolt SQL server did not stop")
        child = _CHILDREN.pop(current, None)
        if child is not None:
            child.wait(timeout=10)
        pidfile.unlink()
        return {
            "schema_version": 1,
            "status": "stopped",
            "loopback_port": port,
            "managed_pid_present": False,
            "production_activation_allowed": False,
        }
    raise ValueError("unknown operation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("start", "status", "stop"))
    parser.add_argument("--foundation-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(manage(args.foundation_root, args.operation), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
