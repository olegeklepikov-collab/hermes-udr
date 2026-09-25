"""Materialize one corpus receipt from bounded acquisition JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from file_io import load_json, write_exclusive_json

from hermes_research_report.corpus import materialize_corpus
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request, request_hash = load_json(args.request)
        receipt = materialize_corpus(request)
        output_hash = write_exclusive_json(
            args.output,
            {
                "schema_version": 1,
                "input_sha256": request_hash,
                "receipt": receipt,
            },
        )
    except (ContractError, ValueError, OSError) as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": getattr(error, "code", "file_input_error"),
                        "path": getattr(error, "path", None),
                        "message": str(error),
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "artifact": str(args.output.resolve()),
                "artifact_sha256": output_hash,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
