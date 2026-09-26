from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def native_runtime_fixture(root: Path, *, node_path: str | None = None, python_path: str | None = None) -> dict:
    from hermes_foundation_bridge.platform_io import private_directory, secure_file
    root.mkdir(parents=True, exist_ok=True)
    private_directory(root)
    secret = root / "neo4j-password"
    secret.write_text("test-only-password", encoding="utf-8")
    secure_file(secret)
    config = {
        "schema_version": 1, "mode": "native",
        "node_path": node_path or sys.executable, "python_path": python_path or sys.executable,
        "agentmemory_url": "http://127.0.0.1:3111", "neo4j_uri": "bolt://127.0.0.1:7687",
        "neo4j_user": "neo4j", "neo4j_password_file": str(secret),
    }
    path = root / "native-runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    secure_file(path)
    return config


def fragment_request(text: str = "verified fragment") -> dict:
    return {
        "schema_version": 1,
        "event_key": "EVENT-1",
        "fragment": {
            "fragment_id": "FRAG-1",
            "run_id": "RUN-1",
            "source_system": "file",
            "source_ref": "ART-1",
            "source_version": "v1",
            "locator": "page:1",
            "exact_fragment": text,
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            "transformation_refs": [],
            "retrieval_query": "query",
            "rank_or_score": 1.0,
        },
    }


def promotion_request(text: str = "verified fragment") -> dict:
    request = fragment_request(text)
    return {
        "schema_version": 1,
        "fragment": request["fragment"],
        "checks": {
            "source_resolved": True,
            "version_resolved": True,
            "locator_verified": True,
            "exact_hash_verified": True,
            "within_limits": True,
            "secret_scan_pass": True,
            "transformations_resolved": True,
            "primary_readback": True,
        },
        "requested_evidence_class": "primary_source_evidence",
    }


def state_request(**changes: object) -> dict:
    value = {
        "schema_version": 1,
        "work_id": "WORK-1",
        "bead_status": "claimed",
        "lease_status": "active",
        "artifact_status": "draft",
        "review_status": "absent",
        "dolt_commit_ref": None,
        "outbox_status": "pending",
        "writer_count": 1,
        "expected_revision": 1,
        "current_revision": 1,
    }
    value.update(changes)
    return value
