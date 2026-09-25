"""Validate the signed-release source package without claiming product readiness."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Context:
    def __init__(self) -> None:
        self.tools: list[dict[str, object]] = []
        self.hooks: list[tuple[str, object]] = []

    def register_tool(self, **kwargs: object) -> None:
        self.tools.append(kwargs)

    def register_hook(self, name: str, callback: object) -> None:
        self.hooks.append((name, callback))


def main() -> int:
    errors: list[str] = []
    for relative in (
        "README.md",
        "LICENSE",
        "ROLLBACK.md",
        "RELEASE.md",
        "RECOVERY.md",
        "DOLT_SQL.md",
        "src/hermes_foundation_bridge/dolt_sql.py",
        "LICENSE_STATUS.md",
        "SBOM.json",
        "bridge-lock.json",
        "release-signing.pub",
        "plugin.yaml",
        "plugin.py",
        "scripts/provision_dolt_sql.py",
        "scripts/manage_dolt_sql.py",
        "migrations/001_runtime.sql",
        "migrations/002_dolt.sql",
        "migrations/003_profile_transport.sql",
        "migrations/004_observability.sql",
        "docker/Graphiti.Dockerfile",
    ):
        if not (ROOT / relative).is_file():
            errors.append(f"missing: {relative}")
    lock = json.loads((ROOT / "bridge-lock.json").read_text(encoding="utf-8"))
    if "latest" in json.dumps(lock).lower():
        errors.append("floating latest in lock")
    if lock["bridge"]["production_activation_allowed"]:
        errors.append("bridge marked production-ready before G0-G8")
    if lock["bridge"]["signature_status"] != "minisign_external":
        errors.append("unexpected signature status")
    if lock["bridge"]["license_status"] != "Apache-2.0":
        errors.append("unexpected license status")
    if lock["bridge"]["source_commit_binding"] != "bundle-manifest.json#source_commit":
        errors.append("unexpected source commit binding")
    if (
        lock["bridge"]["source_tree_binding"]
        != "bundle-manifest.json#source_tree_clean"
    ):
        errors.append("unexpected source tree binding")

    sys.path[:0] = [
        str(ROOT),
        str(ROOT / "src"),
        str(ROOT.parent / "hermes-research-report" / "src"),
    ]
    spec = importlib.util.spec_from_file_location("bridge_plugin", ROOT / "plugin.py")
    if spec is None or spec.loader is None:
        errors.append("plugin import spec unavailable")
    else:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        context = Context()
        module.register(context)
        declared_tools = [
            line.strip()[2:]
            for line in (ROOT / "plugin.yaml").read_text().splitlines()
            if line.startswith("  - foundation_")
        ]
        registered_tools = [str(item["name"]) for item in context.tools]
        if declared_tools != registered_tools:
            errors.append("declared tools differ from registration")
        if len(registered_tools) != 64:
            errors.append("unexpected tool count")
        if len(context.hooks) != 5:
            errors.append("unexpected hook count")
        for item in context.tools:
            schema = item.get("schema")
            if (
                not isinstance(schema, dict)
                or schema.get("additionalProperties") is not False
            ):
                errors.append(f"open schema: {item.get('name')}")

    forbidden_import_roots = {"hermes_cli", "agent", "tools", "model_tools"}
    paths = [
        ROOT / "plugin.py",
        *(ROOT / "src" / "hermes_foundation_bridge").glob("*.py"),
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            roots: set[str] = set()
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".", 1)[0]}
            if roots & forbidden_import_roots:
                errors.append(f"private Hermes import in {path.name}")

    print(
        json.dumps(
            {
                "status": "pass" if not errors else "fail",
                "tool_count": 64,
                "hook_count": 5,
                "production_activation_allowed": False,
                "errors": errors,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
