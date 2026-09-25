"""Report which frame requirements have a real executable source adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .execute_beta_sources import _FAMILY_SCRIPTS
    from .file_io import load_json, write_exclusive_json
except ImportError:
    from execute_beta_sources import _FAMILY_SCRIPTS
    from file_io import load_json, write_exclusive_json

from hermes_research_report.beta_instrument_portfolio import (
    assess_instrument_portfolio,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        if not args.output.is_absolute() or args.output.is_symlink():
            raise ValueError("instrument_portfolio_output_invalid")
        result = assess_instrument_portfolio(
            frame, executable_families=frozenset(_FAMILY_SCRIPTS)
        )
        write_exclusive_json(args.output, result)
        print(
            json.dumps(
                {
                    "status": "partial_instrument_portfolio",
                    "atom_count": result["atom_count"],
                    "atoms_with_all_required_routes": result[
                        "atoms_with_all_required_routes"
                    ],
                    "unavailable_family_atom_counts": result[
                        "unavailable_family_atom_counts"
                    ],
                    "research_can_continue": result[
                        "research_can_continue_on_executable_routes"
                    ],
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
