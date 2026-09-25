# Release, migration and operations

[Home](../../README.md) · [Русский](../ru/release-and-operations.md)

The beta delivers an executable research core and a tested Foundation route. “Operational beta” means versioned installation, verifiable signatures and contents, failure handling and restartable finalization. It is not certification of scientific results or every integration. Exact hashes and signing state are in the [release manifest](../reference/release-manifest.json).

## Moving from r153/v22

Install into a separate profile and retain the old instance. Old databases, acceptance evidence and receipts are not automatically migrated into the new corpus. The Research surface shrinks from 147 registrations to 9; useful methods remain available on demand. Research mode is added, former source-count ceilings are removed, and Hermes supplies native delegation. Do not use legacy run_beta_* scripts as the new system's main entry point.

An instance owner authorizes cutover after comparing a representative question. Rollback restores the retained plugin directories and configuration. Preserve new workspaces separately; do not open new structures with old code assuming schema compatibility.

## Completion and failure

Foundation imports a draft before recording its existence and reference in memory/graph. A service failure does not discard the report. `complete` retries only finalization; after a restart, `ResearchSession.restore` validates canonical admission. Work ownership and lease must remain valid. Editing run.json is not a way around expired authorization.

Back up original files, workspaces, consistent SQLite snapshots and canonical state. ResearchHandoffV1 is a result handoff, not a full backup. Never rewrite hashes or receipts to hide discrepancies. The JSON/Dolt defect was corrected and verified prior state restored as a new revision without erasing history.

## Qualification boundary

Actual Hermes/Codex OAuth, Beads, Dolt CLI, AgentMemory and Graphiti were exercised on a dedicated macOS/Linux arm64 stand. Final-package, signature and recovery evidence is retained. The research example is synthetic: it establishes execution, not literature completeness. JATS XML parsing was tested in a network-disabled container; external entities were rejected.

This does not qualify every discipline, provider operation, PDF, production Telegram delivery, systemd installation or SQL authority configuration. Qualify the capabilities used by each deployment; do not require every methodological object for every question.
