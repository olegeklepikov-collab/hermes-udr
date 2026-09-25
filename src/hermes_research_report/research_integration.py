"""Instance-owned integration settings and non-authoritative host references."""
from __future__ import annotations
from pathlib import Path

HOST_REQUIRED = ('host_run_id', 'project_id', 'profile_id', 'bead_id', 'work_contract_ref',
               'lease_ref', 'agentmemory_receipt_ref', 'graphiti_receipt_ref')
HOST_FIELDS = HOST_REQUIRED + ('tenant_id', 'session_id', 'operation_id', 'context_policy_ref', 'effective_runtime_ref', 'telegram_chat_id_hash')


def settings():
    try:
        from hermes_cli.config import load_config_readonly
    except ImportError:
        config = {}
    else:
        config = load_config_readonly()
    value = config.get('research', {}) if isinstance(config, dict) else {}
    if not isinstance(value, dict):
        raise ValueError('research configuration must be an object')
    mode = value.get('integration_mode', 'standalone')
    if mode not in ('standalone', 'foundation'):
        raise ValueError('research.integration_mode must be standalone or foundation')
    root = value.get('workspace_root')
    if root is not None and (not isinstance(root, str) or not Path(root).is_absolute()):
        raise ValueError('research.workspace_root must be an absolute instance-owned path')
    policy = value.get('web_provider_allowlist')
    if policy is not None and (not isinstance(policy, dict) or any(
        not isinstance(k, str) or not isinstance(v, list) or any(op not in ('search', 'extract') for op in v)
        for k, v in policy.items()
    )):
        raise ValueError('research.web_provider_allowlist must map provider IDs to search/extract operations')
    return {'integration_mode': mode, 'workspace_root': root, 'web_provider_allowlist': policy}


def host_context(value, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, dict) or set(value) - set(HOST_FIELDS):
        raise ValueError('host_context accepts stable host object references only')
    if required and any(not value.get(key) for key in HOST_REQUIRED):
        raise ValueError('Foundation run requires work, lease, memory and graph context references')
    if any(not isinstance(v, str) or not v.strip() or len(v) > 1024 or any(ord(c) < 32 for c in v)
           for v in value.values()):
        raise ValueError('Host references must be nonempty opaque identifiers, not credentials or payloads')
    return dict(value)
