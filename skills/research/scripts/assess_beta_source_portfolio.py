"""Recheck saved source bytes and compose one unreleased mode portfolio."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, read_private_bytes, write_exclusive_json
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json

from hermes_research_report.academic_datacite import (
    MAX_RAW_BYTES as MAX_DATACITE_RAW_BYTES,
)
from hermes_research_report.beta_source_portfolio import (
    _expected_files,
    _file_rows,
    assess_beta_source_portfolio,
)
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--acquisition", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan, _ = load_json(args.plan)
        observations = []
        for path in args.acquisition:
            receipt, _ = load_json(path)
            if type(receipt) is not dict or path.name != "capture.json":
                raise ValueError("acquisition_receipt_invalid")
            rows = _file_rows(
                _expected_files(receipt),
                "receipt.expected_files",
                maximum=MAX_DATACITE_RAW_BYTES
                if receipt.get("contract") == "BetaDataCiteDatasetMetadataAcquisition"
                else 250_000,
            )
            actual = []
            for row in rows:
                payload = read_private_bytes(
                    path.parent / str(row["path"]),
                    maximum=MAX_DATACITE_RAW_BYTES
                    if receipt.get("contract")
                    == "BetaDataCiteDatasetMetadataAcquisition"
                    else 250_000,
                )
                actual.append(
                    {
                        "path": row["path"],
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "bytes": len(payload),
                    }
                )
            observations.append({"receipt": receipt, "artifact_readback": actual})
        result = assess_beta_source_portfolio(
            {"schema_version": 1, "plan": plan, "observations": observations}
        )
        write_exclusive_json(args.output, result)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "run_id": result["run_id"],
                    "candidate_leaf_ids": result["candidate_leaf_ids"],
                    "missing_or_failed_leaf_ids": result["missing_or_failed_leaf_ids"],
                    "independent_primary_source_count": 0,
                    "mode_qualified": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, OSError, ValueError) as error:
        code = (
            error.code
            if isinstance(error, ContractError)
            else "portfolio_input_or_storage_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
