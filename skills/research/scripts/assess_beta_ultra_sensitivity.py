"""Read back profiled source records and persist Ultra fragility without model calls."""

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
    from .screen_beta_academic import _records
except ImportError:
    from file_io import load_json, write_exclusive_json
    from screen_beta_academic import _records

from hermes_research_report.beta_modes import verify_beta_mode_plan
from hermes_research_report.beta_ultra_sensitivity import assess_beta_ultra_sensitivity
from hermes_research_report.errors import ContractError

_CODE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--challenge", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan_value, _ = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        execution, _ = load_json(args.execution)
        portfolio, _ = load_json(args.portfolio)
        challenge, _ = load_json(args.challenge)
        if any(type(value) is not dict for value in (execution, portfolio, challenge)):
            raise ValueError("ultra_sensitivity_inputs_invalid")
        if (
            not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or args.plan != args.output_root / f"{plan['run_id']}-planning/plan.json"
            or args.challenge
            != args.output_root / f"{plan['run_id']}-ultra-challenge/challenge.json"
        ):
            raise ValueError("ultra_sensitivity_paths_invalid")
        records = _records(plan, portfolio, args.output_root)
        result = assess_beta_ultra_sensitivity(
            plan=plan,
            execution=execution,
            portfolio=portfolio,
            challenge=challenge,
            records=records,
        )
        output = args.output_root / f"{plan['run_id']}.ultra-sensitivity.json"
        write_exclusive_json(output, result)
        print(
            json.dumps(
                {
                    "status": "single_source_fragility_recorded",
                    "run_id": plan["run_id"],
                    "single_citation_dependent_count": result[
                        "single_citation_dependent_count"
                    ],
                    "robustness_verified": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, OSError, ValueError) as error:
        code = error.code if isinstance(error, ContractError) else str(error)
        if not _CODE.fullmatch(code):
            code = "ultra_sensitivity_failed"
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
