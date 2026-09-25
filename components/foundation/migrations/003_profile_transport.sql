PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    schema_version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS handoffs (
    package_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    from_profile TEXT NOT NULL,
    to_profile TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_positions (
    package_id TEXT PRIMARY KEY,
    reviewer_profile TEXT NOT NULL,
    position_hash TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operator_effects (
    effect_ref TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resumptions (
    package_id TEXT PRIMARY KEY,
    new_worker_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telegram_bindings (
    binding_ref TEXT PRIMARY KEY,
    chat_hash TEXT NOT NULL,
    user_hash TEXT NOT NULL,
    project_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    bead_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_receipts (
    media_ref TEXT PRIMARY KEY,
    binding_ref TEXT NOT NULL,
    media_kind TEXT NOT NULL,
    artifact_hash TEXT NOT NULL,
    transcript_hash TEXT,
    transformation_ref TEXT,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    idempotency_key TEXT PRIMARY KEY,
    artifact_hash TEXT NOT NULL,
    model_run_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('prepared', 'delivered', 'ambiguous_delivery', 'rejected', 'delivered_duplicate')),
    attempts INTEGER NOT NULL,
    payload_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

