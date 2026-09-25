"""Persist a provisional atomic coverage and novelty assessment."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, read_private_bytes, write_exclusive_json
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json

from hermes_research_report.beta_coverage import assess_beta_coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--observations", type=Path, action="append", required=True)
    parser.add_argument("--discovery-signals", type=Path, action="append")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-exhausted", action="store_true")
    args = parser.parse_args(argv)
    try:
        if (
            not args.output.is_absolute()
            or args.output.exists()
            or args.output.is_symlink()
            or args.output.parent.is_symlink()
            or not args.output.parent.is_dir()
            or stat.S_IMODE(args.output.parent.stat().st_mode) & 0o077
        ):
            raise ValueError("coverage_output_not_private")
        signal_paths = args.discovery_signals or []
        for path in [args.frame, *args.observations, *signal_paths]:
            read_private_bytes(path, maximum=4_000_000)
        frame, _ = load_json(args.frame)
        observations = []
        for path in args.observations:
            page, _ = load_json(path)
            if type(page) is not list:
                raise ValueError("coverage_observation_page_invalid")
            observations.extend(page)
        signals = []
        for path in signal_paths:
            page, _ = load_json(path)
            if type(page) is not list:
                raise ValueError("coverage_signal_page_invalid")
            signals.extend(page)
        result = assess_beta_coverage(
            frame,
            observations,
            discovery_signals=signals,
            budget_exhausted=args.budget_exhausted,
        )
        write_exclusive_json(args.output, result)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "error", "reason": str(error)}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": str(args.output),
                "evidence_floor_fraction": result["evidence_floor_fraction"],
                "frame_expansion_required": result["frame_expansion_required"],
                "observed_novelty_plateau": result["observed_novelty_plateau"],
                "saturation_verified": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
