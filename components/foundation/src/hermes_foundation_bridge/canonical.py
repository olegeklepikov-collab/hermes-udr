"""Canonical JSON and receipt hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def receipt(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["receipt_hash"] = sha256_json(result)
    return result
