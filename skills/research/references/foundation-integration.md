# Foundation integration

Use this reference only when the instance sets `research.integration_mode: foundation`.

The existing Hermes host session owns admission, leases, profile policy, AgentMemory/Graphiti lifecycle and canonical state. Do not start the standalone research CLI from it. Use the research tools and native leaf delegation within that session.

Before `research_workspace.start`, obtain host references: host_run_id, project_id, profile_id, bead_id, work_contract_ref, lease_ref, agentmemory_receipt_ref, graphiti_receipt_ref. Pass them as host_context. References are linkage only, never proof of authorization. Never put credentials or context payloads in them.

The operator sets an absolute `research.workspace_root` per profile and maps it into any required containers. The optional `research.web_provider_allowlist` maps open-ended provider IDs to lists of search/extract operations. In foundation mode an absent policy allows none through the generic provider selector. Other native/MCP tools remain subject to host policy. Registration, permission and verified effectiveness are distinct.

In foundation mode research_fetch stores raw bytes without parsing. Ask the host artifact intake and approved parser to process them, then register the resulting text with research_source origin_ref and parse_receipt_ref. Docker terminal configuration alone does not sandbox Python plugin code.

Finish a local draft, then call research_workspace action=handoff. ResearchHandoffV1 snapshots registered material and completed step outputs; omitted_unregistered_retrieval_count reports raw acquisitions outside the snapshot. The host must independently rehash files, validate paths and live host bindings, import artifacts and return canonical IDs and an intake receipt. This importer is a host integration requirement, not implemented by the research plugin. A local complete status is not acceptance, release or delivery authorization. Hashes are not signatures. Evidence provenance does not establish semantic support.

Standalone mode remains the default. Foundation qualification requires the exact Hermes build and an actual end-to-end host test; local contract tests do not establish production readiness.
