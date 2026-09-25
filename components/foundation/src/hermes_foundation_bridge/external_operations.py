"""Durable guard for effects whose responses may be lost after provider acceptance."""

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .canonical import receipt, sha256_json
from .errors import BridgeError
from .runtime import RuntimeCoordinator


def guarded_external(
    root: Path,
    kind: str,
    identity: object,
    request: object,
    perform: Callable[[], dict[str, Any]],
    successful_statuses: set[str],
    target: object | None = None,
) -> dict[str, Any]:
    coordinator = RuntimeCoordinator(root)
    reservation = coordinator.begin_external(
        kind,
        sha256_json(identity),
        sha256_json(request),
        sha256_json(target) if target is not None else None,
    )

    def unresolved(attempted: bool) -> dict[str, Any]:
        return receipt(
            {
                "schema_version": 1,
                "contract": "ExternalOperationReceipt",
                "status": "unknown_outcome",
                "operation_id": reservation["operation_id"],
                "requires_reconciliation": True,
                "safe_to_retry": False,
                "external_call_attempted": attempted,
                "provider_effect_observed": None,
                "current_readback_verified": False,
            }
        )

    if reservation["status"] == "unknown_outcome":
        return unresolved(False)
    if reservation["status"] == "already_succeeded":
        return receipt(
            {
                "schema_version": 1,
                "contract": "ExternalOperationReceipt",
                "status": "already_succeeded",
                "operation_id": reservation["operation_id"],
                "previous_result_receipt_hash": reservation["result_receipt_hash"],
                "external_call_attempted": False,
                "requires_reconciliation": False,
                "current_readback_verified": False,
            }
        )
    try:
        result = perform()
        if not isinstance(result, dict):
            raise TypeError("external_response_invalid")
        verified = (
            result.get("status") in successful_statuses
            and result.get("readback_verified", True) is True
        )
        coordinator.finish_external(
            reservation["operation_id"],
            reservation["owner"],
            result["receipt_hash"] if verified else None,
        )
        return result if verified else unresolved(True)
    except (
        BridgeError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
        TypeError,
        KeyError,
    ):
        # Even an error response can follow an accepted effect. Never infer absence.
        coordinator.finish_external(
            reservation["operation_id"], reservation["owner"], None
        )
        return unresolved(True)
