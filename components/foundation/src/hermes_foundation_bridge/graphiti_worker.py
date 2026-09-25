"""Narrow Graphiti/FalkorDB worker; no raw query operation is exposed."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import sys
from typing import Any

from graphiti_core.driver.falkordb_driver import (  # pyright: ignore[reportMissingImports]
    FalkorDriver,
)


async def execute(request: dict[str, Any]) -> dict[str, Any]:
    operation = request.get("operation")
    driver = FalkorDriver(
        host="hermes-foundation-falkordb",
        port=6379,
        database="hermes_foundation",
    )
    try:
        await driver.health_check()
        if operation == "health":
            return {
                "status": "healthy",
                "graphiti_version": importlib.metadata.version("graphiti-core"),
                "falkordb_client_version": importlib.metadata.version("falkordb"),
            }
        if operation == "migrate":
            await driver.build_indices_and_constraints()
            return {"status": "applied"}
        if operation == "put_fact":
            rows, _columns, _stats = await driver.execute_query(
                "MERGE (f:FoundationFact {project_id: $project_id, fact_id: $fact_id}) "
                "SET f.text=$text, f.text_hash=$text_hash, f.source_ref=$source_ref, "
                "f.artifact_id=$artifact_id, f.active=true "
                "RETURN f.fact_id AS fact_id, f.text_hash AS text_hash, f.active AS active",
                **request["payload"],
            )
            return {"status": "written", "rows": rows}
        if operation == "search":
            rows, _columns, _stats = await driver.execute_query(
                "MATCH (f:FoundationFact {project_id: $project_id, active: true}) "
                "WHERE toLower(f.text) CONTAINS toLower($query) "
                "RETURN f.fact_id AS fact_id, f.text AS text, f.text_hash AS text_hash, "
                "f.source_ref AS source_ref, f.artifact_id AS artifact_id "
                "ORDER BY f.fact_id LIMIT $limit",
                **request["payload"],
            )
            return {"status": "queried", "rows": rows}
        if operation == "tombstone":
            rows, _columns, _stats = await driver.execute_query(
                "MATCH (f:FoundationFact {artifact_id: $artifact_id, active: true}) "
                "SET f.active=false RETURN count(f) AS deactivated_count",
                **request["payload"],
            )
            count = int(rows[0]["deactivated_count"]) if rows else 0
            return {"status": "propagated", "deactivated_count": count}
        raise ValueError("unsupported_operation")
    finally:
        await driver.close()


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        if not isinstance(request, dict):
            raise TypeError("invalid_request")
        result = asyncio.run(execute(request))
    except Exception as error:  # noqa: BLE001 - process boundary normalizes library errors
        result = {
            "status": "error",
            "code": type(error).__name__,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") != "error" else 2


if __name__ == "__main__":
    raise SystemExit(main())
