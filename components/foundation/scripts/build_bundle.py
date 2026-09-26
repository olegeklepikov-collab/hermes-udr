"""Build a deterministic bridge plugin bundle with an internal manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files() -> list[Path]:
    fixed = [
        ROOT / "LICENSE",
        ROOT / "README.md",
        ROOT / "ROLLBACK.md",
        ROOT / "RELEASE.md",
        ROOT / "RECOVERY.md",
        ROOT / "DOLT_SQL.md",
        ROOT / "LICENSE_STATUS.md",
        ROOT / "SBOM.json",
        ROOT / "bridge-lock.json",
        ROOT / "release-signing.pub",
        ROOT / "__init__.py",
        ROOT / "plugin.py",
        ROOT / "plugin.yaml",
        ROOT / "scripts" / "provision_dolt_sql.py",
        ROOT / "scripts" / "manage_dolt_sql.py",
        ROOT / "scripts" / "configure_native_runtime.py",
        ROOT / "src" / "__init__.py",
    ]
    fixed.extend(sorted((ROOT / "src" / "hermes_foundation_bridge").glob("*.py")))
    fixed.extend(sorted((ROOT / "src" / "hermes_foundation_bridge").glob("*.mjs")))
    fixed.extend(sorted((ROOT / "migrations").glob("*.sql")))
    fixed.extend(sorted((ROOT / "patches").glob("*.patch")))
    return fixed


def source_commit() -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("source commit is not an exact 40-character SHA-1")
    status = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if status.stdout:
        raise RuntimeError("source tree is not clean")
    return commit


def write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def build(output: Path) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(output)
    plugin_text = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*(\S+)$", plugin_text, re.MULTILINE)
    if not match:
        raise ValueError("plugin version missing")
    version = match.group(1)
    commit = source_commit()
    entries = [
        (path.relative_to(ROOT).as_posix(), path.read_bytes()) for path in files()
    ]
    manifest = {
        "schema_version": 1,
        "bundle_type": "hermes-plugin",
        "name": "hermes-foundation-bridge",
        "version": version,
        "release_status": "candidate" if "a" in version else "release",
        "signature_scheme": "minisign",
        "trusted_public_key_sha256": digest(
            (ROOT / "release-signing.pub").read_bytes()
        ),
        "source_commit": commit,
        "source_tree_clean": True,
        "license_status": "Apache-2.0",
        "production_activation_allowed": False,
        "files": [
            {"path": name, "sha256": digest(data), "bytes": len(data)}
            for name, data in entries
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x") as archive:
        for name, data in entries:
            write(archive, name, data)
        write(
            archive,
            "bundle-manifest.json",
            json.dumps(
                manifest,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
        )
    return {
        "status": "built",
        "version": version,
        "path": str(output),
        "sha256": digest(output.read_bytes()),
        "bytes": output.stat().st_size,
        "files": len(entries) + 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
