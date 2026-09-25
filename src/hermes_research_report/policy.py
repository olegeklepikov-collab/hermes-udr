"""GIP-001–028 greenfield inheritance policy."""

from __future__ import annotations

from .canonical import sha256_json

POLICY_VERSION = "1.1"

GREENFIELD_POLICY: tuple[tuple[str, str, str], ...] = (
    ("GIP-001", "host_and_service_identity", "create_new"),
    ("GIP-002", "root_map", "create_new"),
    ("GIP-003", "hermes_runtime", "install_pinned_clean"),
    ("GIP-004", "hermes_local_patches", "reimplement_or_package_explicitly"),
    ("GIP-005", "foundation_repository", "create_new_repository"),
    ("GIP-006", "config_yaml", "generate_new"),
    ("GIP-007", "hermes_profiles", "create_blank"),
    ("GIP-008", "plugins_and_bridge", "install_pinned_clean"),
    ("GIP-009", "python_venvs_and_node_modules", "rebuild_from_lock"),
    (
        "GIP-010",
        "secrets_and_auth",
        "provision_new_or_user_authorized_secret_import_contract",
    ),
    ("GIP-011", "telegram_bot", "create_new_operator_gated"),
    ("GIP-012", "hermes_session_state", "start_empty"),
    ("GIP-013", "beads_work_graph", "start_empty"),
    ("GIP-014", "dolt_subject_databases", "migrate_from_empty"),
    ("GIP-015", "runtime_sqlite", "create_empty_from_migrations"),
    ("GIP-016", "artifact_store", "create_empty_roots"),
    ("GIP-017", "agentmemory_data", "start_empty"),
    ("GIP-018", "graphiti_falkordb_data", "start_empty"),
    ("GIP-019", "zvec_collections", "rebuild_from_approved_new_sources"),
    ("GIP-020", "model_routing", "redeclare_and_requalify"),
    (
        "GIP-021",
        "skills_and_external_snapshots",
        "refetch_or_copy_verified_release_artifact",
    ),
    ("GIP-022", "cron_and_service_units", "generate_new"),
    ("GIP-023", "browser_profiles", "start_empty"),
    ("GIP-024", "logs_and_receipts", "do_not_import_as_runtime"),
    ("GIP-025", "integration_registry", "create_new_from_declared_components"),
    ("GIP-026", "backups", "create_new_backup_chain"),
    ("GIP-027", "domain_knowledge_and_artifacts", "explicit_post_activation_import"),
    ("GIP-028", "current_instance_observations", "convert_to_fixtures_only"),
)

POLICY_BY_ASSET = {
    asset: {"asset_id": asset_id, "policy": policy}
    for asset_id, asset, policy in GREENFIELD_POLICY
}
POLICY_HASH = sha256_json(
    {
        "version": POLICY_VERSION,
        "assets": [
            {"asset_id": i, "asset_class": a, "policy": p}
            for i, a, p in GREENFIELD_POLICY
        ],
    }
)

ALLOWED_BOOTSTRAP_TRANSFER_MODES = frozenset(
    {"normative_document", "exact_release", "synthetic_fixture"}
)
PROHIBITED_OPERATIONAL_MODES = frozenset(
    {"copy", "clone", "restore", "inherit", "mount", "reuse_live"}
)

REQUIRED_ROOT_KINDS = frozenset(
    {
        "instance_root",
        "hermes_home",
        "config_root",
        "state_root",
        "runtime_root",
        "artifact_root",
        "backup_root",
    }
)
REQUIRED_STORE_TYPES = frozenset(
    {
        "beads",
        "dolt",
        "runtime_sqlite",
        "artifacts",
        "agentmemory",
        "graphiti",
        "zvec",
        "integration_registry",
    }
)
REQUIRED_PROFILE_IDS = frozenset(
    {
        "default",
        "engineering",
        "quantitative",
        "review",
        "operator",
        "research",
        "academic",
        "parser",
    }
)
REQUIRED_IDENTITY_FLAGS = frozenset(
    {
        "service_identity",
        "instance",
        "profiles",
        "service_units",
        "ports",
        "secrets",
        "telegram",
    }
)
REQUIRED_CHARACTERISTIC_CLASSES = frozenset(
    {"cli", "mcp", "plugin", "profile", "service", "cron", "browser"}
)
REQUIRED_FOUNDATION_GATES = tuple(f"G{i}" for i in range(9))
