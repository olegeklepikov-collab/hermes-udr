"""Acquire beta source candidates through an already configured Hermes web route."""

from __future__ import annotations

import argparse
import importlib
import json
import signal
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
except ImportError:
    from file_io import (
        fsync_directory,
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )

from hermes_research_report.beta_acquisition import (
    AcquisitionError,
    acquire_beta_sources,
)
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.canonical import sha256_json, with_receipt_hash
from hermes_research_report.errors import ContractError
from hermes_research_report.runtime_snapshot import runtime_guarded, verify_runtime


class AcquisitionDeadline(BaseException):
    """Escape provider error normalization when the whole run times out."""


@runtime_guarded
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--leaf-id")
    parser.add_argument(
        "--max-candidates-per-leaf", type=int, choices=(1, 2, 3), default=1
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-query-ack", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.public_query_ack:
            raise AcquisitionError("public_query_ack_required")
        plan_value, plan_file_sha = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        if plan["schema_version"] != 2:
            raise AcquisitionError("legacy_plan_execution_disabled")
        if any("concept_groups" not in leaf for leaf in plan["leaves"]):
            raise AcquisitionError("concept_groups_required")
        if plan["mode"] == "search":
            if args.leaf_id is not None or plan["source_families"] != ["web"]:
                raise AcquisitionError("mode_requires_profiled_source_adapters")
            expected_output = plan["run_id"]
        else:
            if args.leaf_id is None or not any(
                leaf["leaf_id"] == args.leaf_id
                and leaf["source_family"] in {"web", "official"}
                for leaf in plan["leaves"]
            ):
                raise AcquisitionError("mode_requires_profiled_source_adapters")
            family = next(
                leaf["source_family"]
                for leaf in plan["leaves"]
                if leaf["leaf_id"] == args.leaf_id
            )
            expected_output = f"{plan['run_id']}-{args.leaf_id}-{'official' if family == 'official' else 'keenable'}"
        if args.output.name != expected_output:
            raise AcquisitionError("output_run_id_mismatch")
        new_private_directory(args.output)
        write_exclusive_json(
            args.output / "attempt.json",
            {
                "schema_version": 1,
                "status": "started_unknown_until_reconciled",
                "run_id": plan["run_id"],
                "leaf_id": args.leaf_id,
                "plan_receipt_hash": plan["receipt_hash"],
                "plan_file_sha256": plan_file_sha,
                "retry_allowed": False,
            },
        )
        from hermes_cli.config import load_config
        from plugins.web.keyless_mcp import _ring_order, provider_tier

        effective_config_hash = sha256_json(load_config())
        web = load_config().get("web") or {}
        if (
            web.get("search_backend") != "keenable"
            or web.get("extract_backend") != "keenable"
            or web.get("keyless_rescue") is not False
            or provider_tier("keenable") != "free"
            or _ring_order("keenable") != ["keenable"]
        ):
            raise AcquisitionError("web_route_not_bounded_keyless")
        importlib.import_module("tools.web_tools")
        from tools.registry import registry

        try:
            from .loaded_runtime import effective_provider_inputs_hash
        except ImportError:
            from loaded_runtime import effective_provider_inputs_hash
        effective_inputs = effective_provider_inputs_hash()
        write_exclusive_json(
            args.output / "effective-source-runtime.json",
            with_receipt_hash(
                {
                    "contract": "LoadedHermesSourceRuntime",
                    "desired_runtime_hash": verify_runtime(),
                    "effective_config_hash": effective_config_hash,
                    "effective_provider_inputs_hash": effective_inputs,
                    "provider_route": "keenable_free_only",
                    "remote_provider_configuration_verified": False,
                    "raw_configuration_persisted": False,
                }
            ),
        )

        def source_guard():
            verify_runtime()
            if (
                sha256_json(load_config()) != effective_config_hash
                or effective_provider_inputs_hash() != effective_inputs
            ):
                raise AcquisitionError("runtime_loaded_configuration_changed")

        def search(query: str, limit: int) -> str:
            source_guard()
            result = registry.dispatch("web_search", {"query": query, "limit": limit})
            if type(result) is not str:
                raise AcquisitionError("search_host_response_invalid")
            return result

        def extract(urls: list[str]) -> str:
            source_guard()
            result = registry.dispatch(
                "web_extract", {"urls": urls, "char_limit": 50_000}
            )
            if type(result) is not str:
                raise AcquisitionError("extract_host_response_invalid")
            return result

        def deadline(_signum: int, _frame: object) -> None:
            raise AcquisitionDeadline()

        previous_handler = signal.signal(signal.SIGALRM, deadline)
        previous_timer = signal.setitimer(
            signal.ITIMER_REAL, float(plan["limits"]["wall_seconds"])
        )
        try:
            receipt, artifacts = acquire_beta_sources(
                plan,
                max_candidates_per_leaf=args.max_candidates_per_leaf,
                search=search,
                extract=extract,
                selected_leaf_id=args.leaf_id,
                route_proof={
                    "search_backend": "keenable",
                    "extract_backend": "keenable",
                    "keyless_ring": ["keenable"],
                    "keyless_rescue": False,
                    "provider_tier": "free",
                },
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
            signal.signal(signal.SIGALRM, previous_handler)
        for name, payload in artifacts.items():
            write_exclusive_bytes(args.output / name, payload)
        write_exclusive_json(args.output / "capture.json", receipt)
        fsync_directory(args.output)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "run_id": receipt["run_id"],
                    "successful_sources": receipt["successful_sources"],
                    "qualification_status": receipt["qualification_status"],
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        AcquisitionError,
        AcquisitionDeadline,
        ContractError,
        OSError,
        ValueError,
    ) as error:
        code = (
            error.code
            if isinstance(error, (AcquisitionError, ContractError))
            else "acquisition_deadline_exceeded"
            if isinstance(error, AcquisitionDeadline)
            else "acquisition_input_or_storage_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
