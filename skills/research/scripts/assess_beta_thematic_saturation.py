"""Persist a calibrated thematic-saturation decision."""

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

from hermes_research_report.beta_saturation import assess_thematic_saturation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--progress", required=True, type=Path)
    parser.add_argument("--independence", required=True, type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("saturation_output_invalid")
        progress, _ = load_json(args.progress)
        independence, _ = load_json(args.independence)
        calibration = load_json(args.calibration)[0] if args.calibration else None
        result = assess_thematic_saturation(progress, independence, calibration)
        write_exclusive_json(args.output, result)
        print(
            json.dumps(
                {
                    "status": result["decision"],
                    "saturation_verified": result["saturation_verified"],
                    "blockers": result["blockers"],
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "error", "code": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
