"""Apply exact critic splits and explicit analyst rewrites as a new frame."""

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

from hermes_research_report.beta_atomic_split import split_coverage_atoms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--extra", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        review, _ = load_json(args.review)
        extra, _ = load_json(args.extra)
        if (
            type(frame) is not dict
            or not args.output_root.is_absolute()
            or args.output_root.is_symlink()
            or not args.output_root.is_dir()
            or args.frame
            != args.output_root / f"{frame['run_id']}-hole-fill/frame.json"
            or args.review
            != args.output_root / f"{frame['run_id']}-hole-review/review.json"
        ):
            raise ValueError("atomic_split_paths_invalid")
        revised, receipt = split_coverage_atoms(frame, review, extra=extra)
        output = args.output_root / f"{frame['run_id']}-atomic-split"
        new_private_directory(output)
        write_exclusive_json(output / "frame.json", revised)
        write_exclusive_json(output / "split.json", receipt)
        print(
            json.dumps(
                {
                    "status": "provisional_atomic_split",
                    "run_id": frame["run_id"],
                    "atom_count": len(revised["atoms"]),
                    "remaining_critic_omission_count": len(
                        receipt["remaining_critic_omissions"]
                    ),
                    "source_observations_transfer_allowed": False,
                    "semantic_atomicity_verified": False,
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
