PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;

CREATE TABLE IF NOT EXISTS schema_meta (
    schema_version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    bead_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    model_ref TEXT NOT NULL,
    tool_ref TEXT,
    context_refs_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    commit_refs_json TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    cost_microunits INTEGER NOT NULL,
    outcome_status TEXT NOT NULL,
    priority TEXT NOT NULL,
    evidence_eligible INTEGER NOT NULL,
    redacted_field_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_spool (
    trace_id TEXT PRIMARY KEY,
    envelope_json TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Separate from the coordinator writer lock; included in the existing collector backup.
CREATE TABLE IF NOT EXISTS hook_queue (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    envelope_hash TEXT NOT NULL UNIQUE,
    envelope_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'quarantined'))
);
