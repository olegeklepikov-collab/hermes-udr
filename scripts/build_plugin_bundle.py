"""Build a deterministic Hermes plugin ZIP with an internal file manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _runtime_files() -> list[Path]:
    files = [
        ROOT / "LICENSE",
        ROOT / "RELEASE_README.md",
        ROOT / "__init__.py",
        ROOT / "plugin.py",
        ROOT / "plugin.yaml",
        ROOT / "src" / "__init__.py",
    ]
    files.extend(
        path
        for path in sorted((ROOT / "src" / "hermes_research_report").glob("*.py"))
        if path.name not in {"__main__.py", "cli.py", "secret_import.py"}
    )
    files.append(ROOT / "src" / "hermes_research_report" / "py.typed")
    files.extend(
        path
        for path in sorted((ROOT / "skills").rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    return files


def _zip_write(
    archive: zipfile.ZipFile, name: str, data: bytes, mode: int = 0o644
) -> None:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = mode << 16
    archive.writestr(info, data)


def build_bundle(output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = pyproject["project"]["version"]
    plugin_text = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    manifest_version = re.search(r"^version:\s*(\S+)$", plugin_text, re.MULTILINE)
    if not manifest_version or manifest_version.group(1) != package_version:
        raise ValueError("plugin.yaml and pyproject.toml versions differ")

    entries: list[tuple[str, bytes]] = []
    for path in _runtime_files():
        if not path.is_file():
            raise FileNotFoundError(path)
        name = (
            "README.md"
            if path.name == "RELEASE_README.md"
            else path.relative_to(ROOT).as_posix()
        )
        entries.append((name, path.read_bytes()))

    file_manifest = [
        {"path": name, "sha256": _sha256(data), "bytes": len(data)}
        for name, data in entries
    ]
    manifest = {
        "schema_version": 1,
        "bundle_type": "hermes-plugin",
        "name": "ultra-deep-research",
        "version": package_version,
        "entry_point": "plugin.py",
        "deployment_mode": "greenfield",
        "release_status": "unsigned_native_candidate",
        "license": "Apache-2.0",
        "files": file_manifest,
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    with zipfile.ZipFile(output, "x") as archive:
        for name, data in entries:
            _zip_write(archive, name, data)
        _zip_write(archive, "bundle-manifest.json", manifest_bytes)

    result = {
        "status": "built",
        "output": str(output),
        "version": package_version,
        "file_count": len(entries) + 1,
        "bundle_sha256": _sha256(output.read_bytes()),
        "bundle_bytes": output.stat().st_size,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = build_bundle(args.output)
    except (OSError, ValueError) as error:
        print(
            json.dumps(
                {"status": "error", "error": type(error).__name__}, sort_keys=True
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
