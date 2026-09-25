"""Resolve one explicit foundation root without reading another profile."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import fail


def foundation_root() -> Path:
    explicit = os.environ.get("HERMES_FOUNDATION_ROOT")
    hermes_home = os.environ.get("HERMES_HOME")
    raw = explicit or (str(Path(hermes_home) / "foundation") if hermes_home else "")
    if not raw:
        fail(
            "foundation_root_missing",
            "environment.HERMES_FOUNDATION_ROOT",
            "Корень основания не задан.",
        )
    root = Path(raw)
    if not root.is_absolute() or root == Path("/") or root.is_symlink():
        fail("foundation_root_invalid", "foundation_root", "Небезопасный корень.")
    return root


def child(root: Path, *parts: str) -> Path:
    candidate = root.joinpath(*parts)
    try:
        candidate.relative_to(root)
    except ValueError:
        fail("path_escape", "path", "Путь выходит за пределы основания.")
    return candidate
