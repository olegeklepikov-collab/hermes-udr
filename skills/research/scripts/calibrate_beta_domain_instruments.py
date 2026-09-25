"""Reconcile mandatory source families against a saved domain decomposition."""

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

from hermes_research_report.beta_domain_instruments import (
    calibrate_domain_instruments,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--decomposition", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--revision", type=int, choices=(1, 2), default=1)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        decomposition, _ = load_json(args.decomposition)
        if (
            type(frame) is not dict
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{frame['run_id']}-coverage-planning/frame.json"
        ):
            raise ValueError("domain_instrument_paths_invalid")
        calibrated, receipt = calibrate_domain_instruments(frame, decomposition)
        suffix = "domain-instruments" if args.revision == 1 else "domain-instruments-v2"
        output = args.output_root / f"{frame['run_id']}-{suffix}"
        new_private_directory(output)
        write_exclusive_json(output / "frame.json", calibrated)
        write_exclusive_json(output / "calibration.json", receipt)
        print(
            json.dumps(
                {
                    "status": "provisional_instrument_calibration",
                    "run_id": frame["run_id"],
                    "atom_count": receipt["atom_count"],
                    "removed_family_requirement_count": receipt[
                        "removed_family_requirement_count"
                    ],
                    "rank_gaps": receipt["required_importance_rank_gaps"],
                    "empty_branches": receipt["empty_branch_ids"],
                    "academic_route_unresolved_atom_count": receipt[
                        "academic_route_unresolved_atom_count"
                    ],
                    "web_monoculture_risk_atom_count": receipt[
                        "web_monoculture_risk_atom_count"
                    ],
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
