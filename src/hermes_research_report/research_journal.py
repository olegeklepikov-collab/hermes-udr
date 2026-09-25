"""Append actual search, loop and decision events to one research workspace."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .canonical import canonical_json
from .research_workspace import connect, root_for, write_json, write_text

_KINDS = {"search", "loop", "decision"}
_VOLATILE_FIELDS = {
    "id", "event_id", "run_id", "temp_filename", "output_path", "path",
    "created_at", "timestamp", "attempt", "iteration", "attempt_id",
}


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _substance(value: object) -> object:
    if type(value) is dict:
        return {
            key: _substance(item)
            for key, item in value.items()
            if key not in _VOLATILE_FIELDS
        }
    if type(value) is list:
        return [_substance(item) for item in value]
    return value


def _state_hashes(event: dict) -> set[str]:
    delta = event.get("state_delta")
    if delta is None:
        return set()
    if type(delta) is not dict:
        raise ValueError("state_delta must be an object")
    hashes: set[str] = set()
    for field, value in delta.items():
        if field in _VOLATILE_FIELDS:
            continue
        if value is None:
            continue
        items = value if type(value) is list else [value]
        for item in items:
            normalized = _substance(item)
            if normalized not in (None, "", [], {}):
                hashes.add(_digest({field: normalized}))
    return hashes


def _output_hashes(root: Path, event: dict) -> set[str]:
    paths = event.get("output_paths", [])
    if type(paths) is not list or any(type(path) is not str for path in paths):
        raise ValueError("output_paths must be a list of paths")
    hashes: set[str] = set()
    base = root.resolve()
    for item in paths:
        path = Path(item)
        if not path.is_absolute():
            path = root / path
        if path.is_symlink():
            raise ValueError("output_path must be a regular workspace file")
        resolved = path.resolve()
        if not resolved.is_relative_to(base) or not resolved.is_file():
            raise ValueError("output_path must be a regular workspace file")
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            while block := stream.read(65536):
                digest.update(block)
        hashes.add(digest.hexdigest())
    return hashes


def _prior_loop(db, loop_id: str) -> dict | None:
    for row in db.execute("SELECT document FROM journal ORDER BY seq DESC"):
        document = json.loads(row[0])
        event = document.get("event", {})
        if event.get("kind") == "loop" and event.get("loop_id") == loop_id:
            return document.get("loop_progress")
    return None


def _loop_progress(db, root: Path, event: dict) -> dict:
    loop_id = event.get("loop_id")
    if type(loop_id) is not str or not loop_id.strip():
        raise ValueError("loop_id is required for loop events")
    source_ids = event.get("source_ids", [])
    if type(source_ids) is not list or any(type(sid) is not str for sid in source_ids):
        raise ValueError("source_ids must be a list of identifiers")
    known = {row[0] for row in db.execute("SELECT id FROM sources")}
    if set(source_ids) - known:
        raise ValueError("loop references an unknown source_id")
    previous = _prior_loop(db, loop_id)
    cumulative_sources = set(source_ids) | set(previous.get("source_ids", []) if previous else [])
    cumulative_outputs = _output_hashes(root, event) | set(
        previous.get("output_sha256", []) if previous else []
    )
    cumulative_state = _state_hashes(event) | set(
        previous.get("state_sha256", []) if previous else []
    )
    fingerprint = _digest({
        "source_ids": sorted(cumulative_sources),
        "output_sha256": sorted(cumulative_outputs),
        "state_sha256": sorted(cumulative_state),
    })
    repeated_without_change = previous is not None and fingerprint == previous["fingerprint"]
    return {
        "loop_id": loop_id,
        "source_ids": sorted(cumulative_sources),
        "output_sha256": sorted(cumulative_outputs),
        "state_sha256": sorted(cumulative_state),
        "fingerprint": fingerprint,
        "recorded_change": previous is not None and not repeated_without_change,
        "recommendation": "change_route_or_stop_this_loop" if repeated_without_change else None,
        "whole_investigation_blocked": False,
        "semantic_progress_verified": False,
    }


def _render_narrative(documents: list[dict]) -> str:
    lines = ["# Research chronology / Хронология исследования", ""]
    for document in documents:
        lines.append(
            f"## {document['seq']}. {document['recorded_at']} — "
            f"{document['event']['kind']} ({document['event_id']})"
        )
        lines.append("Recorded by: " + document.get("recorded_by", "unknown"))
        event_json = json.dumps(document["event"], ensure_ascii=False, indent=2)
        fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", event_json)), default=0))
        lines += ["", fence + "json", event_json, fence, ""]
        if document.get("loop_progress") is not None:
            lines += ["```json", json.dumps(document["loop_progress"], ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines)


def _export(root: Path, run_id: str) -> None:
    # Serialize exports with writers so a late older export cannot replace a newer one.
    with connect(root) as db:
        db.execute("BEGIN IMMEDIATE")
        documents = []
        for row in db.execute("SELECT seq, document FROM journal ORDER BY seq"):
            documents.append({"seq": row[0], **json.loads(row[1])})
        write_json(root / "narrative.json", {"run_id": run_id, "events": documents})
        write_text(root / "narrative.md", _render_narrative(documents))
        db.commit()


def record(args: dict, *, observed_native_call: bool = False) -> dict:
    """Record one factual event; never start searches, agent loops or external calls."""
    if type(args) is not dict or type(args.get("run_id")) is not str:
        raise ValueError("run_id is required")
    event = args.get("event")
    if type(event) is not dict or type(event.get("kind")) is not str or event["kind"] not in _KINDS:
        raise ValueError("event.kind must be search, loop or decision")
    if set(event) & {"seq", "event_id", "recorded_at", "loop_progress"}:
        raise ValueError("event contains server-owned fields")
    # Keep the supplied event exactly, including negative search and planned-vs-executed data.
    event = json.loads(json.dumps(event, ensure_ascii=False, allow_nan=False))
    run_id = args["run_id"]
    root = root_for(run_id)
    document = {
        "event_id": "J-" + uuid4().hex,
        "recorded_by": "native_hook" if observed_native_call else "analyst",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "declared_stop_reason": event.get("declared_stop_reason", event.get("stopping_reason", event.get("stop_reason"))),
        "verified_saturation": False,
    }
    with connect(root) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY, document TEXT NOT NULL)")
        if event["kind"] == "loop":
            document["loop_progress"] = _loop_progress(db, root, event)
        cursor = db.execute(
            "INSERT INTO journal(document) VALUES (?)",
            (json.dumps(document, ensure_ascii=False, separators=(",", ":")),),
        )
        seq = cursor.lastrowid
        db.commit()
    _export(root, run_id)
    return {
        "run_id": run_id,
        "seq": seq,
        "event_id": document["event_id"],
        "recorded_at": document["recorded_at"],
        "kind": event["kind"],
        "declared_stop_reason": document["declared_stop_reason"],
        "verified_saturation": False,
        "loop_progress": document.get("loop_progress"),
        "narrative_json": str(root / "narrative.json"),
        "narrative_md": str(root / "narrative.md"),
    }


def capture_search(**kwargs):
    """Observe real native web calls in the isolated CLI run; no synthetic reconstruction."""
    import os
    import sys
    run_id = os.environ.get("HERMES_RESEARCH_RUN_ID")
    name = kwargs.get("tool_name")
    if not run_id or name not in ("web_search", "web_extract"):
        return
    args = kwargs.get("args") or {}
    response = kwargs.get("result")
    response_bytes = str(response).encode()
    try:
        value = json.loads(response) if isinstance(response, str) else response
    except ValueError:
        value = None
    event = {"kind": "search", "execution_status": "executed", "record_origin": "native_post_tool_call",
             "tool_route": name, "query_or_method": args.get("query", args.get("urls")),
             "tool_call_id": kwargs.get("tool_call_id"), "session_id": kwargs.get("session_id"),
             "tool_status": kwargs.get("status"), "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
             "response_bytes": len(response_bytes), "tool_reported_error": bool(value.get("error")) if isinstance(value, dict) else None,
             "source_family": "unclassified; analyst annotates", "why_next": "not yet interpreted"}
    try:
        record({"run_id": run_id, "event": event}, observed_native_call=True)
    except Exception as error:
        # Provenance failure must be visible but must not erase successful retrieval.
        print("research_search_journal_failed:" + type(error).__name__, file=sys.stderr)
