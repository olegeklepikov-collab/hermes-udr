"""Write one bounded beta-mode plan from a strict local JSON request."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, write_exclusive_json
except ImportError:
    from file_io import load_json, write_exclusive_json

from hermes_research_report.beta_modes import build_beta_mode_plan
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request, _ = load_json(args.request)
        if type(request) is not dict or request.get("schema_version") != 2:
            raise ValueError("legacy_plan_creation_disabled")
        leaves = request.get("leaves")
        if type(leaves) is not list or any(
            type(leaf) is not dict or "concept_groups" not in leaf for leaf in leaves
        ):
            raise ValueError("concept_groups_required")
        if any(
            leaf.get("source_family")
            not in {"web", "scholarly_index", "preprint_archive"}
            for leaf in leaves
        ):
            raise ValueError("source_family_unavailable")
        plan = build_beta_mode_plan(request)
        write_exclusive_json(args.output, plan)
        print(
            json.dumps(
                {
                    "status": plan["status"],
                    "mode": plan["mode"],
                    "run_id": plan["run_id"],
                    "missing_obligations": plan["missing_obligations"],
                    "qualification_status": plan["qualification_status"],
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0 if plan["status"] == "ready_to_execute" else 3
    except (ContractError, OSError, ValueError) as error:
        code = (
            error.code
            if isinstance(error, ContractError)
            else str(error)
            if isinstance(error, ValueError)
            and str(error).replace("_", "").isalnum()
            and len(str(error)) < 80
            else "plan_input_or_storage_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
