"""Persist an evidence-root independence assessment."""

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

from hermes_research_report.beta_evidence_independence import (
    assess_evidence_independence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", required=True, type=Path)
    parser.add_argument("--progress", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("independence_output_invalid")
        frame, _ = load_json(args.frame)
        progress, _ = load_json(args.progress)
        evidence, _ = load_json(args.evidence)
        result = assess_evidence_independence(frame, progress, evidence)
        write_exclusive_json(args.output, result)
        print(
            json.dumps(
                {
                    "status": "verified_partial"
                    if not result["all_atoms_meet_independence"]
                    else "verified",
                    "atoms_meeting_independence": result["atoms_meeting_independence"],
                    "atom_count": result["atom_count"],
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
