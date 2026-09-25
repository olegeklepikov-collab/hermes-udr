"""Single-authority map for the greenfield foundation."""

from __future__ import annotations

from typing import Any

from .canonical import receipt
from .validation import exact, mapping

AUTHORITIES = {
    "hermes_sessions": ("hermes_profile_state", "public_api"),
    "work_graph": ("beads", "public_api"),
    "subject_state": ("dolt", "adapter"),
    "runtime_state": ("runtime_coordinator", "adapter"),
    "source_code": ("git", "public_api"),
    "artifacts": ("artifact_service", "adapter"),
    "long_term_memory": ("agentmemory", "adapter"),
    "temporal_graph": ("graphiti", "adapter"),
    "retrieval_index": ("zvec_indexer", "read_only"),
    "datasets": ("artifact_parquet", "adapter"),
    "configuration_secrets": ("hermes_host", "host_only"),
}


def authority_map(request: object) -> dict[str, Any]:
    data = mapping(request, "request")
    exact(data, {"schema_version"}, "request")
    if data["schema_version"] != 1:
        from .errors import fail

        fail("unsupported_schema", "request.schema_version", "Поддерживается версия 1.")
    rows = [
        {
            "state_type": state_type,
            "authority": authority,
            "writer_count": 1,
            "access_mode": access_mode,
        }
        for state_type, (authority, access_mode) in sorted(AUTHORITIES.items())
    ]
    return receipt(
        {
            "schema_version": 1,
            "contract": "FoundationAuthorityMapReceipt",
            "status": "declared",
            "authority_map": rows,
            "authority_count": len(rows),
            "single_writer_count": len(rows),
        }
    )
