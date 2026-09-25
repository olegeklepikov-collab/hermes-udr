"""Record mapped query attempts without promoting candidates to evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, new_private_directory, write_exclusive_json
except ImportError:
    from file_io import load_json, new_private_directory, write_exclusive_json

from hermes_research_report.beta_coverage_mapping import observe_mapped_queries
from hermes_research_report.beta_modes import verify_beta_mode_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        plan_value, _ = load_json(args.plan)
        plan = verify_beta_mode_plan(plan_value)
        mapping, _ = load_json(args.mapping)
        portfolio, _ = load_json(args.portfolio)
        if (
            type(frame) is not dict
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{frame['run_id']}-coverage-planning/frame.json"
            or args.plan != args.output_root / f"{plan['run_id']}-planning/plan.json"
            or args.mapping
            != args.output_root / f"{plan['run_id']}-coverage-map-plan/mapping.json"
            or args.portfolio
            != args.output_root / f"{plan['run_id']}-execution/portfolio.json"
        ):
            raise ValueError("coverage_mapped_observation_paths_invalid")
        rows, progress, receipt = observe_mapped_queries(
            frame=frame, plan=plan, mapping=mapping, portfolio=portfolio
        )
        output = args.output_root / f"{plan['run_id']}-coverage-observed"
        new_private_directory(output)
        write_exclusive_json(output / "observations.json", rows)
        write_exclusive_json(output / "progress.json", progress)
        write_exclusive_json(output / "observation.json", receipt)
        print(
            json.dumps(
                {
                    "status": "mapped_queries_observed",
                    "run_id": plan["run_id"],
                    "queried_atom_count": len(receipt["queried_atom_ids"]),
                    "unqueried_atom_count": len(receipt["unqueried_atom_ids"]),
                    "verified_source_count": 0,
                    "saturation_verified": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, UnicodeError, KeyError, TypeError) as error:
        print(json.dumps({"status": "error", "code": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
