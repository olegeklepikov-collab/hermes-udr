"""Canonical JSON and content hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def with_receipt_hash(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["receipt_hash"] = sha256_json(payload)
    return result


def verify_receipt_hash(payload: dict[str, Any]) -> bool:
    supplied = payload.get("receipt_hash")
    if type(supplied) is not str:
        return False
    body = {key: value for key, value in payload.items() if key != "receipt_hash"}
    return supplied == sha256_json(body)
