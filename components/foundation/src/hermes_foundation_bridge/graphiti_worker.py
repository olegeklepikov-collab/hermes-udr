"""Narrow Graphiti/Neo4j worker; no caller-supplied query is accepted."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Any

from graphiti_core.driver.neo4j_driver import Neo4jDriver  # pyright: ignore[reportMissingImports]


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(record) for record in result.records]


def run(request: dict[str, Any]) -> dict[str, Any]:
    operation = request.get("operation")
    if operation not in {"health", "migrate", "put_fact", "search", "tombstone"}:
        raise ValueError("unsupported_operation")
    connection = request["connection"]
    password = Path(connection["neo4j_password_file"]).read_text(encoding="utf-8").rstrip("\r\n")
    # Graphiti creates its own indices when constructed inside an event loop.
    # Constructing here preserves health and dry-run migration as read-only.
    driver = Neo4jDriver(
        uri=connection["neo4j_uri"], user=connection["neo4j_user"],
        password=password, database="neo4j",
    )
    return asyncio.run(execute(request, driver))


async def execute(request: dict[str, Any], driver: Neo4jDriver) -> dict[str, Any]:
    operation = request["operation"]
    try:
        await driver.health_check()
        if operation == "health":
            result = await driver.execute_query(
                "CALL dbms.components() YIELD name, versions WHERE name = 'Neo4j Kernel' RETURN versions[0] AS version"
            )
            rows = _rows(result)
            return {
                "status": "healthy", "graphiti_version": importlib.metadata.version("graphiti-core"),
                "neo4j_version": rows[0]["version"] if len(rows) == 1 else "unknown",
            }
        if operation == "migrate":
            await driver.execute_query(
                "CREATE CONSTRAINT foundation_fact_key IF NOT EXISTS FOR (f:FoundationFact) REQUIRE f.key IS UNIQUE"
            )
            await driver.execute_query(
                "CREATE INDEX foundation_fact_project IF NOT EXISTS FOR (f:FoundationFact) ON (f.project_id)"
            )
            await driver.execute_query(
                "CREATE INDEX foundation_fact_artifact IF NOT EXISTS FOR (f:FoundationFact) ON (f.artifact_id)"
            )
            return {"status": "applied"}
        payload = request["payload"]
        if operation == "put_fact":
            key = hashlib.sha256(
                json.dumps([payload["project_id"], payload["fact_id"]], separators=(",", ":")).encode()
            ).hexdigest()
            await driver.execute_query(
                "MERGE (f:FoundationFact {key: $key}) "
                "SET f.project_id=$project_id, f.fact_id=$fact_id, f.text=$text, "
                "f.text_hash=$text_hash, f.source_ref=$source_ref, "
                "f.artifact_id=$artifact_id, f.active=true",
                params={"key": key, **payload},
            )
            readback = await driver.execute_query(
                "MATCH (f:FoundationFact {key: $key}) "
                "RETURN f.fact_id AS fact_id, f.text_hash AS text_hash, f.active AS active",
                params={"key": key},
            )
            return {"status": "written", "rows": _rows(readback)}
        if operation == "search":
            result = await driver.execute_query(
                "MATCH (f:FoundationFact {project_id: $project_id, active: true}) "
                "WHERE toLower(f.text) CONTAINS toLower($query) "
                "RETURN f.fact_id AS fact_id, f.text AS text, f.text_hash AS text_hash, "
                "f.source_ref AS source_ref, f.artifact_id AS artifact_id "
                "ORDER BY f.fact_id LIMIT $limit",
                params=payload,
            )
            return {"status": "queried", "rows": _rows(result)}
        result = await driver.execute_query(
            "MATCH (f:FoundationFact {artifact_id: $artifact_id, active: true}) "
            "SET f.active=false RETURN count(f) AS deactivated_count",
            params=payload,
        )
        rows = _rows(result)
        return {"status": "propagated", "deactivated_count": int(rows[0]["deactivated_count"]) if rows else 0}
    finally:
        await driver.close()


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        if not isinstance(request, dict):
            raise TypeError("invalid_request")
        result = run(request)
    except Exception as error:  # noqa: BLE001 - process boundary normalizes library errors
        result = {"status": "error", "code": type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") != "error" else 2


if __name__ == "__main__":
    raise SystemExit(main())
