"""Closed-request and identifier validation."""

from __future__ import annotations

import re
from typing import cast

from .errors import fail

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def mapping(value: object, path: str) -> dict[str, object]:
    if type(value) is not dict:
        fail("invalid_type", path, "Ожидался объект.")
    return cast(dict[str, object], value)


def exact(value: dict[str, object], keys: set[str], path: str) -> None:
    missing = sorted(keys - set(value))
    unknown = sorted(set(value) - keys)
    if missing:
        fail("missing_field", f"{path}.{missing[0]}", "Отсутствует поле.")
    if unknown:
        fail("unknown_field", f"{path}.{unknown[0]}", "Неизвестное поле.")


def string(value: object, path: str, *, nonempty: bool = True) -> str:
    if type(value) is not str:
        fail("invalid_type", path, "Ожидалась строка.")
    text = cast(str, value)
    if nonempty and not text:
        fail("empty_string", path, "Пустая строка запрещена.")
    return text


def identifier(value: object, path: str) -> str:
    text = string(value, path)
    if not ID_RE.fullmatch(text):
        fail("invalid_identifier", path, "Недопустимый идентификатор.")
    return text


def integer(value: object, path: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        fail("invalid_integer", path, f"Ожидалось целое число не меньше {minimum}.")
    return cast(int, value)


def boolean(value: object, path: str) -> bool:
    if type(value) is not bool:
        fail("invalid_type", path, "Ожидалось логическое значение.")
    return cast(bool, value)


def digest(value: object, path: str) -> str:
    text = string(value, path)
    if not HASH_RE.fullmatch(text):
        fail("invalid_hash", path, "Ожидался SHA-256 в нижнем регистре.")
    return text
