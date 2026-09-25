"""Stable bridge errors that never include secret values or file contents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn


@dataclass
class BridgeError(ValueError):
    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


def fail(code: str, path: str, message: str) -> NoReturn:
    raise BridgeError(code, path, message)
