"""Fixed parser dispatch inside a monitored child process; no model or arbitrary command dispatch."""

import json
import sys
from pathlib import Path


def main():
    from file_io import load_json

    operation = sys.argv[1]
    request, _ = load_json(Path(sys.argv[2]))
    if operation == "academic_pdf":
        from appraise_beta_papers import _prepare_document

        result = _prepare_document(
            request["spec"],
            Path(request["output"]),
            pdftotext=request["pdftotext"],
            max_pages=request["max_pages"],
        )
        print(json.dumps({"receipt_hash": result["receipt_hash"]}))
    elif operation == "dataset":
        from reanalyze_academic_dataset import _analyze_dataset

        print(
            json.dumps(_analyze_dataset(request), ensure_ascii=False, allow_nan=False)
        )
    else:
        raise ValueError("document_worker_operation_invalid")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - redact parser-specific source details at the process boundary
        # No source content, temporary URLs or secret values in error output.
        print('{"error":"document_worker_failed"}', file=sys.stderr)
        raise SystemExit(2)
