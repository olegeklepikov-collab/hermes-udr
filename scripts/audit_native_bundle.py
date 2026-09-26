"""Fail-closed audit of the files that may leave the development workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_MODULES = (
    "__init__",
    "research_workspace",
    "research_integration",
    "research_handoff",
    "research_modes",
    "research_capabilities",
    "research_methods",
    "research_roadmap",
    "research_journal",
    "research_fetch",
    "academic",
    "academic_integrity",
    "academic_arxiv",
    "beta_academic_study_graph",
    "beta_coverage",
    "beta_atomic_answer",
    "beta_source_lineage",
    "beta_control_stop",
    "beta_coverage_planner",
    "beta_coverage_holes",
    "beta_coverage_repair",
    "beta_coverage_query",
    "beta_coverage_loop",
    "beta_coverage_screen",
    "beta_source_reuse",
    "beta_coverage_discovery",
    "beta_instrument_portfolio",
    "beta_evidence_independence",
    "beta_saturation",
    "beta_research_gates",
    "academic_oa_text",
    "academic_openalex",
    "acquisition_integrity",
    "academic_datacite",
    "beta_dataset_query",
    "beta_domain_decomposition",
    "beta_domain_instruments",
    "beta_domain_source",
    "beta_atomic_split",
    "beta_coverage_mapping",
    "academic_publisher_raw",
    "advanced_academic",
    "academic_review_bindings",
    "artifacts",
    "beta_acquisition",
    "beta_fact_map",
    "beta_model",
    "beta_modes",
    "beta_origin_graph",
    "beta_planner",
    "beta_semantic",
    "beta_source_portfolio",
    "beta_ultra_sensitivity",
    "attribution",
    "briefing",
    "budget",
    "business",
    "business_controls",
    "canonical",
    "runtime_snapshot",
    "turn_trace",
    "circuit",
    "claims",
    "claim_verification",
    "collaboration",
    "comparison",
    "context_lifecycle",
    "corpus",
    "coverage_details",
    "coverage_status",
    "decisions",
    "decomposition",
    "deep_qualification",
    "deployment",
    "document_graph",
    "dolt",
    "engagement",
    "epistemics",
    "errors",
    "evidence",
    "foundation",
    "governance",
    "greenfield",
    "installation",
    "instruments",
    "intake",
    "knowledge",
    "lifecycle",
    "narrative",
    "numeric_reproduction",
    "academic_numeric_evidence",
    "academic_numeric_inventory",
    "academic_comparability",
    "academic_appraisal",
    "academic_dataset",
    "orchestration",
    "policy",
    "portability",
    "portable_bundle",
    "provenance",
    "provider_catalog",
    "provider_contracts",
    "provider_execution",
    "provider_live",
    "qualification",
    "report",
    "review_release",
    "routing",
    "r3_evidence",
    "runtime_contracts",
    "run_contract",
    "schemas",
    "scholarly",
    "search_ledger",
    "search_execution",
    "search_workflow",
    "security_controls",
    "source_families",
    "sources",
    "state",
    "state_semantics",
    "udr",
    "work_execution",
)
_ALLOWED = {
    "LICENSE",
    "README.md",
    "__init__.py",
    "plugin.py",
    "plugin.yaml",
    "src/__init__.py",
    "src/hermes_research_report/py.typed",
    "skills/research/SKILL.md",
    "skills/research/scripts/corpus_from_receipts.py",
    "skills/research/scripts/import_portable_bundle.py",
    "skills/research/scripts/acquire_orthogonal_metadata.py",
    "skills/research/scripts/acquire_beta_sources.py",
    "skills/research/scripts/acquire_arxiv_metadata.py",
    "skills/research/scripts/acquire_arxiv_fulltext.py",
    "skills/research/scripts/analyze_beta_fulltext.py",
    "skills/research/scripts/reconcile_beta_fulltext.py",
    "skills/research/scripts/verify_beta_pdf_structure.py",
    "skills/research/scripts/acquire_openalex_metadata.py",
    "skills/research/scripts/acquire_datacite_metadata.py",
    "skills/research/scripts/plan_beta_dataset_batch.py",
    "skills/research/scripts/plan_beta_domain.py",
    "skills/research/scripts/reconcile_beta_domain.py",
    "skills/research/scripts/regrade_beta_domain.py",
    "skills/research/scripts/calibrate_beta_domain_instruments.py",
    "skills/research/scripts/fill_beta_coverage_holes.py",
    "skills/research/scripts/reconcile_beta_coverage_holes.py",
    "skills/research/scripts/review_beta_coverage_holes.py",
    "skills/research/scripts/plan_beta_domain_web.py",
    "skills/research/scripts/replan_beta_domain_web.py",
    "skills/research/scripts/observe_beta_domain_web.py",
    "skills/research/scripts/plan_beta_domain_pair.py",
    "skills/research/scripts/reconcile_beta_domain_pair.py",
    "skills/research/scripts/screen_beta_domain_abstract.py",
    "skills/research/scripts/split_beta_coverage_atoms.py",
    "skills/research/scripts/reconcile_beta_fulltext_chunks.py",
    "skills/research/scripts/reassemble_beta_search.py",
    "skills/research/scripts/reassemble_beta_ultra_coverage.py",
    "skills/research/scripts/map_beta_coverage_plan.py",
    "skills/research/scripts/observe_beta_plan_coverage.py",
    "skills/research/scripts/reconcile_beta_coverage_mapping.py",
    "skills/research/scripts/advance_beta_coverage.py",
    "skills/research/scripts/reconcile_beta_dataset_batch.py",
    "skills/research/scripts/observe_beta_dataset_batch.py",
    "skills/research/scripts/acquire_openalex_oa_text.py",
    "skills/research/scripts/acquire_publisher_raw.py",
    "skills/research/scripts/screen_openalex_oa_text.py",
    "skills/research/scripts/assess_beta_source_portfolio.py",
    "skills/research/scripts/assess_beta_coverage.py",
    "skills/research/scripts/plan_beta_coverage.py",
    "skills/research/scripts/reconcile_beta_coverage.py",
    "skills/research/scripts/reconcile_beta_coverage_review.py",
    "skills/research/scripts/reconcile_beta_coverage_revision.py",
    "skills/research/scripts/review_beta_coverage.py",
    "skills/research/scripts/revise_beta_coverage.py",
    "skills/research/scripts/route_beta_coverage.py",
    "skills/research/scripts/reconcile_beta_coverage_route.py",
    "skills/research/scripts/review_revised_beta_coverage.py",
    "skills/research/scripts/plan_beta_coverage_source.py",
    "skills/research/scripts/reconcile_beta_coverage_source.py",
    "skills/research/scripts/observe_beta_coverage_batch.py",
    "skills/research/scripts/adapt_beta_coverage_query.py",
    "skills/research/scripts/plan_beta_coverage_cross_domain.py",
    "skills/research/scripts/reconcile_beta_coverage_cross_domain.py",
    "skills/research/scripts/observe_beta_coverage_cross_domain.py",
    "skills/research/scripts/screen_beta_coverage_candidate.py",
    "skills/research/scripts/reconcile_beta_coverage_screen.py",
    "skills/research/scripts/suggest_beta_source_reuse.py",
    "skills/research/scripts/detect_beta_coverage_gap.py",
    "skills/research/scripts/reconcile_beta_coverage_gap.py",
    "skills/research/scripts/assess_beta_instrument_portfolio.py",
    "skills/research/scripts/assess_beta_evidence_independence.py",
    "skills/research/scripts/assess_beta_thematic_saturation.py",
    "skills/research/scripts/assess_beta_research_gates.py",
    "skills/research/scripts/assemble_beta_search.py",
    "skills/research/scripts/draft_beta_model.py",
    "skills/research/scripts/model_call.py",
    "skills/research/scripts/loaded_runtime.py",
    "skills/research/scripts/runtime_model_worker.py",
    "skills/research/scripts/reconcile_beta_model.py",
    "skills/research/scripts/verify_beta_semantic.py",
    "skills/research/scripts/verify_openalex_oa_semantic.py",
    "skills/research/scripts/assemble_beta_deep_partial.py",
    "skills/research/scripts/assess_beta_origin_graph.py",
    "skills/research/scripts/run_beta_deep.py",
    "skills/research/scripts/run_beta_deep_question.py",
    "skills/research/scripts/run_beta_abstract_fallback.py",
    "skills/research/scripts/compare_beta_deep_works.py",
    "skills/research/scripts/run_beta_research.py",
    "skills/research/scripts/run_research.py",
    "skills/research/references/decomposition.md",
    "skills/research/references/foundation-integration.md",
    "skills/research/references/modes-and-tools.md",
    "skills/research/references/evidence-methods.md",
    "skills/research/references/knowledge-foundations.md",
    "skills/research/references/search-narrative-loops.md",
    "skills/research/scripts/complete_beta_content.py",
    "skills/research/scripts/run_beta_stage_two.py",
    "skills/research/scripts/audit_beta_academic_numbers.py",
    "skills/research/scripts/appraise_beta_papers.py",
    "skills/research/scripts/vision_model_worker.py",
    "skills/research/scripts/process_limits.py",
    "skills/research/scripts/document_worker.py",
    "skills/research/scripts/reanalyze_academic_dataset.py",
    "skills/research/scripts/acquire_academic_asset.py",
    "skills/research/scripts/read_beta_public_content.py",
    "skills/research/scripts/reassemble_beta_academic.py",
    "skills/research/scripts/screen_beta_academic.py",
    "skills/research/scripts/challenge_beta_ultra.py",
    "skills/research/scripts/assess_beta_ultra_sensitivity.py",
    "skills/research/scripts/assess_beta_academic_study_graph.py",
    "skills/research/scripts/plan_beta_mode.py",
    "skills/research/scripts/plan_beta_from_question.py",
    "skills/research/scripts/reconcile_beta_plan.py",
    "skills/research/scripts/reconcile_beta_semantic.py",
    "skills/research/scripts/execute_beta_sources.py",
    "skills/research/scripts/run_beta_search.py",
    "skills/research/scripts/file_io.py",
    "skills/research/scripts/report_from_files.py",
    "skills/research/scripts/render_telegram_dm_baseline.py",
    "skills/research/templates/telegram-dm-standalone.config.yaml",
    "bundle-manifest.json",
} | {f"src/hermes_research_report/{name}.py" for name in _MODULES}
_FORBIDDEN_BYTES = re.compile(
    rb"/Users/|/Volumes/|/var/folders/|/tmp/|file://|\.codex/|\.hermes/"
    rb"|active-ditto|\.CloudStorage|olegklepikov|PavelHermes"
    rb"|gho_[A-Za-z0-9]{12,}|sk-[A-Za-z0-9]{12,}"
    rb"|[0-9]{8,10}:[A-Za-z0-9_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
_DEV_TEXT = re.compile(
    rb"(?i)IMPLEMENTATION_STATUS|BUILD_RECEIPT|development_unsigned|not_decided"
    rb"|\bTODO\b|\bFIXME\b|\bHACK\b"
)


class NativeAuditError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def audit_native_bundle(path: Path) -> dict[str, object]:
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size < 5_000_000
    ):
        raise NativeAuditError("archive_invalid")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != _ALLOWED:
                raise NativeAuditError("native_member_set_invalid")
            if any(
                info.is_dir()
                or info.file_size > 1_000_000
                or (info.external_attr >> 16) & 0o170000 == 0o120000
                for info in infos
            ):
                raise NativeAuditError("unsafe_member")
            payloads = {name: archive.read(name) for name in names}
    except (OSError, zipfile.BadZipFile):
        raise NativeAuditError("archive_invalid") from None
    if any(_FORBIDDEN_BYTES.search(raw) for raw in payloads.values()):
        raise NativeAuditError("local_identity_or_secret_marker")
    if any(
        _DEV_TEXT.search(raw) for name, raw in payloads.items() if name != "LICENSE"
    ):
        raise NativeAuditError("development_text_in_public_surface")
    if payloads["README.md"] != (ROOT / "RELEASE_README.md").read_bytes():
        raise NativeAuditError("release_readme_mismatch")
    if payloads["LICENSE"] != (ROOT / "LICENSE").read_bytes():
        raise NativeAuditError("license_mismatch")
    try:
        manifest = json.loads(payloads["bundle-manifest.json"])
    except json.JSONDecodeError:
        raise NativeAuditError("manifest_invalid") from None
    if (
        not isinstance(manifest, dict)
        or manifest.get("bundle_type") != "hermes-plugin"
        or manifest.get("name") != "ultra-deep-research"
        or manifest.get("entry_point") != "plugin.py"
        or manifest.get("license") != "Apache-2.0"
        or manifest.get("release_status") != "unsigned_native_candidate"
        or not isinstance(manifest.get("files"), list)
    ):
        raise NativeAuditError("manifest_invalid")
    rows = manifest["files"]
    if len(rows) != len(_ALLOWED) - 1 or {
        row.get("path") for row in rows if isinstance(row, dict)
    } != _ALLOWED - {"bundle-manifest.json"}:
        raise NativeAuditError("manifest_member_set_invalid")
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("sha256") != _sha(payloads[row["path"]])
            or row.get("bytes") != len(payloads[row["path"]])
        ):
            raise NativeAuditError("manifest_digest_invalid")
    tool_count = len(
        re.findall(rb"(?m)^  - research_[a-z0-9_]+\r?$", payloads["plugin.yaml"])
    )
    if tool_count != 9:
        raise NativeAuditError("native_tool_manifest_invalid")
    return {
        "status": "clean_native_candidate",
        "archive_sha256": _sha(path.read_bytes()),
        "member_count": len(names),
        "registered_tool_manifest_count": tool_count,
        "license": "Apache-2.0",
        "development_artifacts_present": False,
        "local_identity_or_secret_markers_present": False,
        "signed": False,
        "published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        result = audit_native_bundle(args.archive)
    except NativeAuditError as error:
        print(json.dumps({"status": "blocked", "code": error.code}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
