"""Export a local, unsubmitted Research draft for a separate Foundation importer."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from datetime import datetime, timezone
from uuid import uuid4

from .research_workspace import connect, root_for, write_json


def _regular_bytes(root: Path, relative: str) -> bytes:
    """Read only a regular file within this run; reject linked path components."""
    if type(relative) is not str:
        raise ValueError("handoff_path_invalid")
    name = Path(relative)
    if name.is_absolute() or not name.parts or any(part in (".", "..") for part in name.parts):
        raise ValueError("handoff_path_invalid")
    path = root / name
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("handoff_link_not_allowed")
        current = current.parent
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("handoff_file_not_regular")
    return path.read_bytes()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n").encode()


def export_handoff(args: dict) -> dict:
    """Snapshot local records and selected files; never claim host intake or acceptance."""
    if type(args) is not dict or type(args.get("run_id")) is not str:
        raise ValueError("handoff_run_id_required")
    run_id = args["run_id"]
    root = root_for(run_id)
    handoffs = root / "handoffs"
    if handoffs.is_symlink() or (handoffs.exists() and not handoffs.is_dir()):
        raise ValueError("handoff_parent_invalid")
    handoff_id = "H-" + uuid4().hex
    final = handoffs / handoff_id
    temporary = handoffs / (handoff_id + ".tmp")
    handoffs.mkdir(mode=0o700, exist_ok=True)
    files: list[dict] = []
    added: dict[str, str] = {}
    temporary_created = False
    published = False

    def add(relative: str, content: bytes) -> None:
        digest = hashlib.sha256(content).hexdigest()
        if relative in added:
            if added[relative] != digest:
                raise ValueError("handoff_duplicate_content_mismatch")
            return
        target = temporary / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        files.append({"path": relative, "sha256": digest,
                      "bytes": len(content)})
        added[relative] = digest

    try:
        with connect(root) as db:
            db.execute("BEGIN IMMEDIATE")
            run_bytes = _regular_bytes(root, "run.json")
            report_bytes = _regular_bytes(root, "report.md")
            result_bytes = _regular_bytes(root, "result.json")
            run = json.loads(run_bytes)
            result = json.loads(result_bytes)
            if type(run) is not dict or run.get("run_id") != run_id or type(result) is not dict:
                raise ValueError("handoff_run_or_result_invalid")
            if result.get("status") not in ("complete", "partial") or not report_bytes.strip():
                raise ValueError("handoff_saved_report_required")
            if result.get("report_sha256") != hashlib.sha256(report_bytes).hexdigest():
                raise ValueError("handoff_report_hash_mismatch")

            sources = [dict(row) for row in db.execute("SELECT * FROM sources ORDER BY id")]
            notes = [dict(row) for row in db.execute("SELECT * FROM notes ORDER BY id")]
            plans = ([{"revision": row[0], "document": json.loads(row[1])}
                      for row in db.execute("SELECT revision, document FROM plans ORDER BY revision")]
                     if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='plans'").fetchone() else [])
            journal = ([{"seq": row[0], "document": json.loads(row[1])}
                        for row in db.execute("SELECT seq, document FROM journal ORDER BY seq")]
                       if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal'").fetchone() else [])
            step_paths = []
            if plans:
                latest = plans[-1]["document"]
                if type(latest) is not dict or type(latest.get("steps", [])) is not list:
                    raise ValueError("handoff_plan_invalid")
                if any(type(step) is not dict or step.get("status") in ("dispatched", "running")
                       for step in latest.get("steps", [])):
                    raise ValueError("handoff_active_worker")
                for step in latest.get("steps", []):
                    outputs = step.get("result_paths", [])
                    if type(outputs) is not list or any(type(path) is not str for path in outputs):
                        raise ValueError("handoff_step_outputs_invalid")
                    step_paths.extend(outputs)

            temporary.mkdir(mode=0o700)
            temporary_created = True
            for name, content in (("run.json", run_bytes), ("report.md", report_bytes),
                                  ("result.json", result_bytes)):
                add(name, content)
            if (root / "execution.json").exists():
                add("execution.json", _regular_bytes(root, "execution.json"))
            for name, value in (("records/sources.json", sources), ("records/notes.json", notes),
                                ("records/plans.json", plans), ("records/journal.json", journal)):
                add(name, _json_bytes(value))

            source_hashes = {}
            for row in sources:
                sid = row["id"]
                if type(sid) is not str or not re.fullmatch(r"S-[0-9a-f]{16}", sid):
                    raise ValueError("handoff_source_id_invalid")
                relative = f"materials/{sid}.txt"
                if row["path"] != relative:
                    raise ValueError("handoff_source_path_invalid")
                content = _regular_bytes(root, relative)
                if hashlib.sha256(content).hexdigest() != row["sha256"]:
                    raise ValueError("handoff_source_hash_mismatch")
                add(relative, content)
                source_hashes[sid] = row["sha256"]
                provenance_name = f"materials/{sid}.provenance.json"
                if (root / provenance_name).exists():
                    provenance_bytes = _regular_bytes(root, provenance_name)
                    provenance = json.loads(provenance_bytes)
                    if type(provenance) is not dict or provenance.get("source_id", sid) != sid:
                        raise ValueError("handoff_source_provenance_invalid")
                    if ("content_sha256" in provenance
                            and provenance["content_sha256"] != row["sha256"]):
                        raise ValueError("handoff_source_provenance_hash_mismatch")
                    add(provenance_name, provenance_bytes)

            for row in notes:
                nid = row["id"]
                if type(nid) is not str or not re.fullmatch(r"N-[0-9a-f]{16}", nid):
                    raise ValueError("handoff_note_id_invalid")
                relative = f"notes/{nid}.md"
                if row["path"] != relative:
                    raise ValueError("handoff_note_path_invalid")
                add(relative, _regular_bytes(root, relative))
                metadata_name = f"notes/{nid}.json"
                if (root / metadata_name).exists():
                    metadata_bytes = _regular_bytes(root, metadata_name)
                    metadata = json.loads(metadata_bytes)
                    if type(metadata) is not dict or metadata.get("note_id") != nid or metadata.get("text_path") != relative:
                        raise ValueError("handoff_note_metadata_invalid")
                    add(metadata_name, metadata_bytes)

            for relative in step_paths:
                name = Path(relative)
                if name.parts and name.parts[0] in {
                    "handoffs", "retrievals", "provider-calls", "capabilities", "cache",
                    ".cache", "auth", "config", "credentials", "secrets", "tokens",
                } or name.name in {
                    "corpus.sqlite", "corpus.sqlite-wal", "corpus.sqlite-shm",
                    "config.yaml", "config.yml", "config.json", "auth.json",
                    "credentials.json", "secrets.json", ".env",
                }:
                    raise ValueError("handoff_step_output_excluded")
                add(relative, _regular_bytes(root, relative))

            retrievals = root / "retrievals"
            included_retrievals = 0
            omitted_retrievals = 0
            if retrievals.exists():
                if retrievals.is_symlink() or not retrievals.is_dir():
                    raise ValueError("handoff_retrieval_dir_invalid")
                for folder in sorted(retrievals.iterdir()):
                    if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", folder.name):
                        raise ValueError("handoff_retrieval_dir_invalid")
                    metadata_name = f"retrievals/{folder.name}/metadata.json"
                    if not (root / metadata_name).exists():
                        omitted_retrievals += 1
                        continue  # In-flight retrievals never enter a handoff.
                    metadata_bytes = _regular_bytes(root, metadata_name)
                    metadata = json.loads(metadata_bytes)
                    if type(metadata) is not dict or metadata.get("status") != "full_text_registered":
                        omitted_retrievals += 1
                        continue
                    original_name = f"retrievals/{folder.name}/original.bin"
                    if (metadata.get("source_id") not in source_hashes
                            or metadata.get("original_path") != str(root / original_name)):
                        raise ValueError("handoff_retrieval_reference_invalid")
                    if (metadata.get("text_sha256") is not None
                            and metadata["text_sha256"] != source_hashes[metadata["source_id"]]):
                        raise ValueError("handoff_retrieval_text_hash_mismatch")
                    original_bytes = _regular_bytes(root, original_name)
                    if metadata.get("original_sha256") != hashlib.sha256(original_bytes).hexdigest():
                        raise ValueError("handoff_original_hash_mismatch")
                    add(original_name, original_bytes)
                    add(metadata_name, metadata_bytes)
                    included_retrievals += 1

            manifest = {
                "schema_version": 1, "contract": "ResearchHandoffV1",
                "handoff_id": handoff_id, "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "scope": "local_research_draft", "status": "result_draft",
                "result_status": result["status"],
                "submission_status": "unsubmitted", "acceptance_status": "acceptance_not_requested",
                "production_qualified": False, "production": False,
                "host_intake_required": True, "host_rehash_required": True,
                "integrity_scope": "local_hashes_not_signature_or_tamper_proof",
                "local_ids_and_host_context": "references_only",
                "host_context": run.get("host_context") if type(run.get("host_context")) is dict else None,
                "source_records": len(sources), "note_records": len(notes),
                "included_completed_retrievals": included_retrievals,
                "omitted_unregistered_retrieval_count": omitted_retrievals,
                "files": sorted(files, key=lambda item: item["path"]),
            }
            write_json(temporary / "manifest.json", manifest)
            manifest_bytes = _regular_bytes(temporary, "manifest.json")
            for item in manifest["files"]:
                data = _regular_bytes(temporary, item["path"])
                if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise ValueError("handoff_package_hash_mismatch")
            manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
            package_paths = list(temporary.rglob("*"))
            for path in package_paths:
                if path.is_file():
                    path.chmod(0o400)
            for path in package_paths:
                if path.is_dir():
                    path.chmod(0o500)
            if final.exists():
                raise ValueError("handoff_id_collision")
            temporary.rename(final)
            published = True
            final.chmod(0o500)
            if os.name == "posix":
                directory_fd = os.open(handoffs, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        return {"handoff_id": handoff_id, "run_id": run_id, "root": str(final),
                "manifest_path": str(final / "manifest.json"), "manifest_sha256": manifest_sha256,
                "file_count": len(files), "host_intake_required": True,
                "submission_status": "unsubmitted", "acceptance_status": "acceptance_not_requested",
                "production_qualified": False}
    except BaseException:
        for candidate in ((temporary,) if temporary_created else ()) + ((final,) if published else ()):
            if candidate.exists():
                for path in candidate.rglob("*"):
                    if path.is_dir():
                        path.chmod(0o700)
                candidate.chmod(0o700)
                shutil.rmtree(candidate)
        raise
