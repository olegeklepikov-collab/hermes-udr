"""Build one report artifact from bounded corpus and draft JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from file_io import load_json, write_exclusive_json

from hermes_research_report.report import ReportInputError, build_report

_CORPUS_FIELDS = {"question", "sources", "profile", "query_log", "limitations"}
_DRAFT_FIELDS = {
    "claims",
    "analysis",
    "comparisons",
    "open_questions",
    "stop_reason",
    "limitations",
    "response_format",
}


def assemble(corpus: object, draft: object) -> tuple[dict, dict]:
    if type(corpus) is not dict or set(corpus) - _CORPUS_FIELDS:
        raise ValueError("Неверная схема corpus.")
    if type(draft) is not dict or set(draft) - _DRAFT_FIELDS:
        raise ValueError("Неверная схема draft.")
    request = deepcopy(corpus)
    request.update(deepcopy(draft))
    request["limitations"] = [
        *deepcopy(corpus.get("limitations", [])),
        *deepcopy(draft.get("limitations", [])),
    ]
    return request, build_report(request)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        corpus, corpus_hash = load_json(args.corpus)
        draft, draft_hash = load_json(args.draft)
        request, report = assemble(corpus, draft)
        artifact = {
            "schema_version": 1,
            "inputs": {
                "corpus_sha256": corpus_hash,
                "draft_sha256": draft_hash,
            },
            "request": request,
            "report": report,
        }
        output_hash = write_exclusive_json(args.output, artifact)
    except (ReportInputError, ValueError, OSError) as error:
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
                "status": report["status"],
                "artifact": str(args.output.resolve()),
                "artifact_sha256": output_hash,
                "inputs": artifact["inputs"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
