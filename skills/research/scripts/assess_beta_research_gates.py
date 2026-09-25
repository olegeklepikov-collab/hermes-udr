"""Persist a research-result G0–G8 vector."""

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

from hermes_research_report.beta_research_gates import assess_research_gate_vector


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--gates", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("research_gate_output_invalid")
        gates, _ = load_json(args.gates)
        result = assess_research_gate_vector(args.run_id, gates)
        write_exclusive_json(args.output, result)
        print(
            json.dumps(
                {
                    "status": "qualified"
                    if result["research_qualification_complete"]
                    else "partial",
                    "pass_count": result["pass_count"],
                    "partial_count": result["partial_count"],
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
