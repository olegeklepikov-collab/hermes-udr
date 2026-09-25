"""Stable public contract errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn, cast


@dataclass(frozen=True)
class ContractError(ValueError):
    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


def fail(code: str, path: str, message: str) -> NoReturn:
    raise ContractError(code=code, path=path, message=message)


def require_mapping(value: object, path: str) -> dict[str, object]:
    if type(value) is not dict:
        fail("invalid_type", path, "Ожидался объект.")
    return cast(dict[str, object], value)


def require_list(value: object, path: str) -> list[object]:
    if type(value) is not list:
        fail("invalid_type", path, "Ожидался массив.")
    return cast(list[object], value)


def require_exact_keys(value: dict[str, object], keys: set[str], path: str) -> None:
    missing = sorted(keys - set(value))
    unknown = sorted(set(value) - keys)
    if missing:
        fail("missing_field", f"{path}.{missing[0]}", "Отсутствует обязательное поле.")
    if unknown:
        fail("unknown_field", f"{path}.{unknown[0]}", "Неизвестное поле запрещено.")


def require_string(value: object, path: str, *, nonempty: bool = True) -> str:
    if type(value) is not str:
        fail("invalid_type", path, "Ожидалась строка.")
    text = cast(str, value)
    if nonempty and not text.strip():
        fail("empty_string", path, "Пустая строка запрещена.")
    return text


def require_bool(value: object, path: str) -> bool:
    if type(value) is not bool:
        fail("invalid_type", path, "Ожидалось логическое значение.")
    return cast(bool, value)


def require_int(value: object, path: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        fail("invalid_integer", path, f"Ожидалось целое число не меньше {minimum}.")
    return cast(int, value)
