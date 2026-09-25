"""Import classified data into a new inert root, or resolve a verified object."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from hermes_research_report.portable_bundle import import_bundle, resolve_object


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="operation", required=True)
    add = commands.add_parser("import")
    add.add_argument("--bundle", type=Path, required=True)
    add.add_argument("--output", type=Path, required=True)
    get = commands.add_parser("resolve")
    get.add_argument("--root", type=Path, required=True)
    get.add_argument("--id", required=True)
    get.add_argument("--revision", type=int, required=True)
    args = parser.parse_args()
    try:
        result = (
            import_bundle(args.bundle, args.output)
            if args.operation == "import"
            else resolve_object(args.root, args.id, args.revision)
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        code = (
            str(error)
            if isinstance(error, ValueError) and re.fullmatch(r"[a-z_]+", str(error))
            else "portable_bundle_invalid_or_unavailable"
        )
        print(json.dumps({"status": "blocked", "code": code}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
