"""Small, concurrent research notebook. Records material; never certifies truth."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlsplit
from .research_modes import profile, normalize_mode
from .research_integration import settings as integration_settings, host_context


def root_for(run_id: str) -> Path:
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", run_id):
        raise ValueError("Invalid run_id")
    try:
        from hermes_constants import get_hermes_home
        home = Path(get_hermes_home())
    except ImportError:
        home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    configured = integration_settings()["workspace_root"]
    base = Path(configured) if configured is not None else home / "research-runs"
    root = base / run_id
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("Research workspace must be a directory, not a link")
    return root


@contextmanager
def connect(root: Path):
    if not (root / "run.json").is_file():
        raise ValueError("Unknown run; call research_workspace action=start first")
    db = sqlite3.connect(root / "corpus.sqlite", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    try:
        with db:
            yield db
    finally:
        db.close()


def write_text(path: Path, text: str):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def merge_plan(previous, update):
    """Status updates retain earlier questions, methods and dependencies."""
    if isinstance(previous, dict) and isinstance(update, dict):
        return {**previous, **{k: merge_plan(previous.get(k), v) for k, v in update.items()}}
    if isinstance(previous, list) and isinstance(update, list) and update and all(
        isinstance(x, dict) and 'id' in x for x in previous + update
    ):
        by_id = {x['id']: x for x in previous}
        for row in update:
            by_id[row['id']] = merge_plan(by_id.get(row['id']), row)
        return list(by_id.values())
    return update


def workspace(args):
    action = args.get("action", "status")
    run_id = args.get("run_id") or "r-" + uuid4().hex[:16]
    root = root_for(run_id)
    if action == "handoff":
        from .research_handoff import export_handoff
        return export_handoff({"run_id": run_id})
    if action == "capabilities":
        from .research_capabilities import inventory, session_platform
        return inventory({"run_id": run_id, "platform": session_platform()})
    if action == "record":
        from .research_journal import record
        return record(args)
    if action == "start":
        question = args.get("question", "").strip()
        if not question:
            raise ValueError("A research question is required")
        integration = integration_settings()
        binding = host_context(args.get("host_context"), required=integration["integration_mode"] == "foundation")
        normalize_mode(args.get("mode", "deep"))
        root.mkdir(parents=True, exist_ok=False)
        (root / "materials").mkdir()
        (root / "notes").mkdir()
        write_json(root / "run.json", {"run_id": run_id, "question": question,
                   "integration_mode": integration["integration_mode"], "host_context": binding,
                   "host_context_validation": "references_only", "platform_acceptance": "not_requested",
                   "mode": normalize_mode(args.get("mode", "deep")), "depth_profile": profile(args.get("mode", "deep")), "created_at": datetime.now(timezone.utc).isoformat()})
        with connect(root) as db:
            db.executescript("""CREATE TABLE sources (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
                path TEXT NOT NULL, sha256 TEXT NOT NULL, chars INTEGER NOT NULL,
                extent TEXT NOT NULL, stream TEXT NOT NULL, acquired_at TEXT NOT NULL);
                CREATE TABLE notes (id TEXT PRIMARY KEY, path TEXT NOT NULL, source_ids TEXT NOT NULL);
            """)
    elif action not in ("status", "plan", "dispatch", "complete_step"):
        raise ValueError("Unknown workspace action")
    run_record = json.loads((root / "run.json").read_text(encoding="utf-8"))
    depth = run_record.get("depth_profile") or profile(run_record.get("mode", "deep"))
    with connect(root) as db:
        workflow = {}
        if action in ("plan", "dispatch", "complete_step") or "plan" in args:
            from .research_roadmap import dispatch, complete_step, inspect, normalize_plan
            db.execute("CREATE TABLE IF NOT EXISTS plans (revision INTEGER PRIMARY KEY, document TEXT NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT document FROM plans ORDER BY revision DESC LIMIT 1").fetchone()
            plan = normalize_plan(json.loads(prior[0])) if prior else {}
            if action == "plan" or "plan" in args:
                if not isinstance(args.get("plan"), dict):
                    raise ValueError("plan must be an object")
                plan = merge_plan(plan, normalize_plan(args["plan"]))
                _, issues = inspect(plan)
                workflow = {"planning_issues": issues}
            plan["mode"] = depth["mode"]
            plan["depth_profile"] = depth
            if action == "dispatch":
                workflow = dispatch(plan, root, limit=args.get("limit", 3), wave=args.get("wave"))
            elif action == "complete_step":
                workflow = complete_step(plan, root, args.get("step_id"), args.get("result_paths"), status=args.get("step_status", "done"))
            db.execute("INSERT INTO plans(document) VALUES (?)", (json.dumps(plan, ensure_ascii=False),))
            revision = db.execute("SELECT max(revision) FROM plans").fetchone()[0]
            write_json(root / "plan.json", {**plan, "revision": revision})
        offset = max(0, int(args.get("offset", 0)))
        limit = min(200, max(1, int(args.get("limit", 25))))
        rows = [dict(r) for r in db.execute("SELECT * FROM sources ORDER BY rowid LIMIT ? OFFSET ?", (limit, offset))]
        counts = db.execute("SELECT count(*),count(DISTINCT url),coalesce(sum(chars),0) FROM sources").fetchone()
        notes = db.execute("SELECT count(*) FROM notes").fetchone()[0]
    return {"run_id": run_id, "root": str(root), "source_records": counts[0],
            "unique_sources": counts[1], "stored_characters": counts[2], "notes": notes,
            "sources": rows, "next_offset": offset + len(rows) if offset + len(rows) < counts[0] else None,
            "plan_path": str(root / "plan.json"), "report_path": str(root / "report.md"), "depth_profile": depth, **workflow}


def source(args):
    root = root_for(args["run_id"])
    url = args["url"]
    source_links = {key: args[key] for key in ("origin_ref", "parse_receipt_ref") if key in args}
    if any(not isinstance(v, str) or not v.strip() for v in source_links.values()):
        raise ValueError("Source provenance links must be nonempty identifiers")
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Source URL must be HTTP(S) without embedded credentials")
    if ("text" in args) == ("text_path" in args):
        raise ValueError("Provide text or text_path, exactly one")
    if "text_path" in args:
        path = Path(args["text_path"])
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("text_path must be an existing file inside this workspace")
        text = path.read_text(encoding="utf-8")
    else:
        text = args["text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty material; preserve retrieval failure in a research_note instead")
    extent = args.get("extent", "excerpt")
    truncated = bool(re.search(r"(?i)(?:content has been truncated|\[.{0,20}truncated.{0,20}\]|omitted middle)", text))
    if extent == "full_text" and truncated:
        extent = "excerpt"
    digest = hashlib.sha256(text.encode()).hexdigest()
    sid = "S-" + hashlib.sha256((url + "\n" + digest).encode()).hexdigest()[:16]
    rel = "materials/" + sid + ".txt"
    with connect(root) as db:
        db.execute("BEGIN IMMEDIATE")
        # Same bytes/URL from concurrent agents coalesce; original content is never truncated.
        identical = [r[0] for r in db.execute("SELECT id FROM sources WHERE sha256=? AND id!=?", (digest, sid))]
        existing = db.execute("SELECT id FROM sources WHERE id=?", (sid,)).fetchone()
        if existing and hashlib.sha256((root / rel).read_bytes()).hexdigest() != digest:
            raise ValueError("Stored source integrity mismatch")
        if not existing:
            # Atomic replacement also heals an uncommitted orphan from an interrupted write.
            write_text(root / rel, text)
        db.execute("INSERT OR IGNORE INTO sources VALUES (?,?,?,?,?,?,?,?,?)", (
            sid, url, args.get("title", url), rel, digest, len(text), extent,
            args.get("stream", ""), datetime.now(timezone.utc).isoformat()))
        if source_links:
            write_json(root / "materials" / (sid + ".provenance.json"), {"source_id": sid, "content_sha256": digest,
                       "host_refs": source_links, "validation": "references_only_not_host_acceptance"})
    return {"source_id": sid, "path": str(root / rel), "characters": len(text), "sha256": digest,
            "extent": extent, "truncation_detected": truncated, "identical_text_records": identical, "meaning_verified": False}


def note(args):
    root = root_for(args["run_id"])
    text = args["text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("A substantive note is required")
    ids = args.get("source_ids", [])
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise ValueError("source_ids must be a list of source identifiers")
    nid = "N-" + uuid4().hex[:16]
    rel = "notes/" + nid + ".md"
    with connect(root) as db:
        known = {r[0] for r in db.execute("SELECT id FROM sources")}
        missing = sorted(set(ids) - known)
        write_text(root / rel, text)
        if "data" in args and not isinstance(args["data"], dict):
            raise ValueError("Note data must be an object")
        write_json(root / "notes" / (nid + ".json"), {"note_id": nid, "kind": args.get("kind", "analysis"),
                   "source_ids": ids, "text_path": rel, "data": args.get("data", {}),
                   "meaning_verified": False})
        db.execute("INSERT INTO notes VALUES (?,?,?)", (nid, rel, json.dumps(ids)))
    return {"note_id": nid, "path": str(root / rel), "unresolved_source_ids": missing,
            "meaning_verified": False}


def finish(args):
    root = root_for(args["run_id"])
    report = args["report"]
    if not isinstance(report, str) or not report.strip():
        raise ValueError("An empty report is not a research result")
    status = args.get("status", "partial")
    if status not in ("complete", "partial"):
        raise ValueError("status must be complete or partial; neither certifies scientific truth")
    with connect(root) as db:
        db.execute("BEGIN IMMEDIATE")
        sources = {r["id"]: dict(r) for r in db.execute("SELECT * FROM sources")}
        citations = set(re.findall(r"\[(S-[A-Za-z0-9_-]+)\]", report))
        unknown = sorted(citations - sources.keys())
        cited = sorted(citations & sources.keys())
        prose = re.sub(r"\[S-[A-Za-z0-9_-]+\]|https?://\S+", "", report)
        substantive = bool(re.search(r"\w{3}", prose))
        if not cited or unknown or not substantive:
            status = "partial"
        references = "\n\n## Sources / Источники\n\n" + "\n".join(
            f"- [{sid}] {sources[sid]['title']} — {sources[sid]['url']} ({sources[sid]['extent']}; {sources[sid]['path']})"
            for sid in cited)
        rendered = report + references + "\n"
        result = {"status": status, "source_records": len(sources),
                  "unique_sources": len({s['url'] for s in sources.values()}), "cited_sources": len(cited),
                  "unresolved_citations": unknown, "content_status": "present" if substantive else "references_only",
                  "structural_citation_check": "pass" if cited and not unknown else "incomplete",
                  "semantic_verification": "not_established_by_this_tool",
                  "platform_acceptance": "not_requested", "platform_submission": "unsubmitted",
                  "delivery_authorized": False,
                  "report_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
                  "report_path": str(root / "report.md")}
        # Serialize publication and keep every previous conclusion. Hash binds the two files
        # so readers detect a crash between their atomic replacements instead of reporting success.
        if (root / "report.md").exists():
            previous = root / ("report-" + uuid4().hex + ".md")
            write_text(previous, (root / "report.md").read_text(encoding="utf-8"))
        write_text(root / "report.md", rendered)
        write_json(root / "result.json", result)
    return result


def schema(name, description, properties, required):
    return {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}


STR = {"type": "string"}
TOOLS = [
    (schema("research_workspace", "Start/resume research, save its substantive roadmap, dispatch ready atomic work packets, complete steps with saved outputs, or inspect progress. No fixed source cap.",
            {"action": {"type": "string", "enum": ["start", "status", "plan", "dispatch", "complete_step", "record", "capabilities", "handoff"]}, "run_id": STR, "question": STR,
             "mode": STR, "host_context": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Host-issued IDs/receipt references for Foundation-managed work; never authorization or proof by themselves."}, "event": {"type": "object", "additionalProperties": True}, "plan": {"type": "object", "additionalProperties": True}, "wave": STR, "step_id": STR, "step_status": {"enum": ["done", "partial", "blocked"]}, "result_paths": {"type": "array", "items": STR}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["action"]), workspace),
    (schema("research_source", "Persist retrieved source text in full, with URL and stable citation ID. Use text_path for large files in the workspace; mark extent honestly. Does not fetch or certify the source.",
            {"run_id": STR, "url": STR, "title": STR, "text": STR, "text_path": STR,
             "extent": {"type": "string", "enum": ["full_text", "excerpt", "abstract", "metadata"]}, "stream": STR, "origin_ref": STR, "parse_receipt_ref": STR}, ["run_id", "url", "extent"]), source),
    (schema("research_note", "Save analysis, comparisons, hypotheses, contradictions, quotes with locations, or retrieval failures. Source IDs are links, not proof of meaning.",
            {"run_id": STR, "text": STR, "kind": {"type": "string", "enum": ["analysis", "source_assessment", "claim", "challenge", "method_application"]}, "data": {"type": "object", "additionalProperties": True}, "source_ids": {"type": "array", "items": STR}}, ["run_id", "text"]), note),
    (schema("research_finish", "Save a substantive cited report and append its sources. Unknown citations remain visible and mark the result partial. Never certifies semantic truth or sends externally.",
            {"run_id": STR, "report": STR, "status": {"type": "string", "enum": ["complete", "partial"]}}, ["run_id", "report", "status"]), finish),
]
