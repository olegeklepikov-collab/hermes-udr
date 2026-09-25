"""Persist conservative Academic publication identities and no-pooling gate."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, write_exclusive_json
except ImportError:
    from file_io import load_json, write_exclusive_json

from hermes_research_report.beta_academic_study_graph import (
    build_beta_academic_study_graph,
)
from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.errors import ContractError

_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


def _optional(path: Path | None) -> object | None:
    if path is None:
        return None
    value, _ = load_json(path)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--screening", type=Path, required=True)
    parser.add_argument("--fulltext", type=Path)
    parser.add_argument("--structure", type=Path)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan_value, _ = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or args.plan != args.output_root / f"{plan['run_id']}-planning/plan.json"
        ):
            raise ValueError("study_graph_paths_invalid")
        execution, _ = load_json(args.execution)
        portfolio, _ = load_json(args.portfolio)
        screening, _ = load_json(args.screening)
        result = build_beta_academic_study_graph(
            plan=plan,
            execution=execution,
            portfolio=portfolio,
            screening=screening,
            fulltext=_optional(args.fulltext),
            structure=_optional(args.structure),
            analysis=_optional(args.analysis),
        )
        output = args.output_root / f"{plan['run_id']}.academic-study-graph.json"
        write_exclusive_json(output, result)
        print(
            json.dumps(
                {
                    "status": "study_identity_and_synthesis_boundary_recorded",
                    "run_id": plan["run_id"],
                    "identified_record_count": result["identified_record_count"],
                    "fulltext_read_count": result["fulltext_read_count"],
                    "quantitative_pooling_allowed": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, OSError, ValueError) as error:
        code = error.code if isinstance(error, ContractError) else str(error)
        if not _CODE.fullmatch(code):
            code = "academic_study_graph_failed"
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
