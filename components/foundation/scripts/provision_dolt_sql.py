"""Provision an offline loopback Dolt SQL authority without printing credentials."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_foundation_bridge.canonical import canonical_bytes
from hermes_foundation_bridge.platform_io import private_file, private_directory, secure_file
from hermes_foundation_bridge.dolt_sql import AUTHORITY_MANIFEST, authority_manifest


def _write_exclusive(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        private_file(descriptor)
        written = 0
        while written < len(content):
            written += os.write(descriptor, content[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _provision_sql(writer_password: str, admin_password: str) -> str:
    statements = [
        "CREATE USER 'foundation_writer'@'localhost' IDENTIFIED BY '"
        + writer_password
        + "'",
        "CREATE USER 'foundation_admin'@'localhost' IDENTIFIED BY '"
        + admin_password
        + "'",
        "GRANT ALL PRIVILEGES ON *.* TO 'foundation_admin'@'localhost' WITH GRANT OPTION",
    ]
    for database in AUTHORITY_MANIFEST["database_ids"]:
        statements.append(
            f"GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON `{database}`.* "
            "TO 'foundation_writer'@'localhost'"
        )
    statements.extend(
        [
            (
                "DELETE FROM dolt_branch_control WHERE `database`='%' AND `branch`='%' "
                "AND `user`='%' AND `host`='%'"
            ),
            (
                "INSERT INTO dolt_branch_control (`database`,`branch`,`user`,`host`,`permissions`) "
                "VALUES ('%','%','root','localhost','admin,write,merge,read')"
            ),
            (
                "INSERT INTO dolt_branch_control (`database`,`branch`,`user`,`host`,`permissions`) "
                "VALUES ('%','%','foundation_admin','localhost','admin,write,merge,read')"
            ),
        ]
    )
    for database in AUTHORITY_MANIFEST["database_ids"]:
        statements.append(
            "INSERT INTO dolt_branch_control (`database`,`branch`,`user`,`host`,`permissions`) "
            f"VALUES ('{database}','main','foundation_writer','localhost','write,read')"
        )
    statements.append(
        "ALTER USER 'root'@'localhost' IDENTIFIED BY '" + admin_password + "'"
    )
    return ";\n".join(statements) + ";\n"


def provision(
    foundation: Path, admin_secret_dir: Path, *, apply: bool
) -> dict[str, object]:
    if (
        not foundation.is_absolute()
        or foundation == Path("/")
        or foundation.is_symlink()
    ):
        raise ValueError("invalid foundation root")
    if not admin_secret_dir.is_absolute() or admin_secret_dir == Path("/"):
        raise ValueError("invalid admin secret directory")
    if admin_secret_dir == foundation or foundation in admin_secret_dir.parents:
        raise ValueError("admin secret directory must be outside foundation")
    authority = authority_manifest(foundation)
    data_dir = foundation / "dolt"
    if data_dir.is_symlink() or not data_dir.is_dir():
        raise ValueError("Dolt data directory unavailable")
    databases = AUTHORITY_MANIFEST["database_ids"]
    if any(not (data_dir / name / ".dolt").is_dir() for name in databases):
        raise ValueError("four Dolt databases are required")
    cfg_dir = data_dir / ".doltcfg"
    manifest = data_dir / "sql-authority.json"
    credential_dir = data_dir / ".secrets"
    credential = credential_dir / "writer.password"
    admin_secret = admin_secret_dir / "dolt-admin.password"
    targets_exist = any(
        path.exists() for path in (cfg_dir, manifest, credential, admin_secret)
    )
    if targets_exist:
        raise FileExistsError(
            "SQL authority already provisioned or partially provisioned"
        )
    if not apply:
        return {
            "schema_version": 1,
            "status": "dry_run_ready",
            "database_count": len(databases),
            "host": "127.0.0.1",
            "port": authority["port"],
            "secret_values_recorded": False,
            "production_activation_allowed": False,
        }
    admin_secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_directory(admin_secret_dir)
    if admin_secret_dir.is_symlink() or (os.name != "nt" and admin_secret_dir.stat().st_mode & 0o077):
        raise ValueError("admin secret directory permissions too broad")
    credential_dir.mkdir(parents=True, mode=0o700)
    private_directory(credential_dir)
    writer_password = secrets.token_urlsafe(32)
    admin_password = secrets.token_urlsafe(32)
    _write_exclusive(credential, (writer_password + "\n").encode("ascii"))
    _write_exclusive(admin_secret, (admin_password + "\n").encode("ascii"))
    query = _provision_sql(writer_password, admin_password)
    completed = subprocess.run(
        ["dolt", "--data-dir", str(data_dir), "sql"],
        input=query,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if (
        completed.returncode != 0
        or "error on line" in completed.stdout.lower()
        or "error on line" in completed.stderr.lower()
    ):
        raise RuntimeError(
            "offline Dolt authority provisioning failed; inspect restricted state"
        )
    if cfg_dir.is_symlink() or not cfg_dir.is_dir():
        raise RuntimeError("Dolt configuration directory not created")
    private_directory(cfg_dir)
    for name in ("privileges.db", "branch_control.db"):
        path = cfg_dir / name
        if (
            path.is_symlink()
            or not path.is_file()
            or not stat.S_ISREG(path.stat().st_mode)
        ):
            raise RuntimeError("Dolt authority file not created")
        secure_file(path)
    secure_files = data_dir / "secure-file-exports"
    secure_files.mkdir(mode=0o700)
    config = data_dir / "server.yaml"
    yaml = (
        "log_level: error\n"
        "behavior:\n"
        "  read_only: false\n"
        "  dolt_transaction_commit: false\n"
        '  event_scheduler: "OFF"\n'
        "listener:\n"
        "  host: 127.0.0.1\n"
        f"  port: {authority['port']}\n"
        "  max_connections: 32\n"
        f"data_dir: {json.dumps(str(data_dir))}\n"
        f"cfg_dir: {json.dumps(str(cfg_dir))}\n"
        f"privilege_file: {json.dumps(str(cfg_dir / 'privileges.db'))}\n"
        f"branch_control_file: {json.dumps(str(cfg_dir / 'branch_control.db'))}\n"
        "system_variables:\n"
        f"  secure_file_priv: {json.dumps(str(secure_files))}\n"
        "metrics:\n"
        "  port: -1\n"
    )
    _write_exclusive(config, yaml.encode("utf-8"))
    _write_exclusive(manifest, canonical_bytes(authority) + b"\n")
    return {
        "schema_version": 1,
        "status": "provisioned_offline",
        "database_count": len(databases),
        "host": "127.0.0.1",
        "port": authority["port"],
        "writer_user": "foundation_writer",
        "admin_user": "foundation_admin",
        "credential_file_mode": "0600",
        "admin_secret_file_mode": "0600",
        "privilege_file_mode": "0600",
        "branch_control_file_mode": "0600",
        "root_password_initialized_before_server_start": True,
        "secret_values_recorded": False,
        "secret_values_in_cli_args": False,
        "server_started": False,
        "production_activation_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--foundation-root", type=Path, required=True)
    parser.add_argument("--admin-secret-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = provision(args.foundation_root, args.admin_secret_dir, apply=args.apply)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
