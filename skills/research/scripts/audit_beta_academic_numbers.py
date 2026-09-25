"""Audit retained table percentages without treating a PDF extraction as validated data."""

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

from hermes_research_report.academic_numeric_evidence import (
    audit_binary_percentage_table,
)
from hermes_research_report.academic_numeric_inventory import inspect_numeric_text
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash


def audit_structure(
    structure_path: Path, pdf_path: Path, *, positive: str, other: str
) -> dict:
    structure, _ = load_json(structure_path)
    if (
        not verify_receipt_hash(structure)
        or structure.get("contract") != "BetaAcademicPdfStructure"
    ):
        raise ValueError("academic_structure_invalid")
    pdf = read_private_bytes(pdf_path, maximum=100_000_000)
    if hashlib.sha256(pdf).hexdigest() != structure["pdf_sha256"]:
        raise ValueError("academic_pdf_changed")
    results = []
    skipped = []
    retained = []
    numeric_pages = []
    for page in structure["pages"]:
        text_name = page.get("text_file", f"page-{page['page']:04d}.txt")
        if type(text_name) is not str or Path(text_name).name != text_name:
            raise ValueError("academic_text_path_invalid")
        text_bytes = read_private_bytes(
            structure_path.parent / text_name, maximum=20_000_000
        )
        if hashlib.sha256(text_bytes).hexdigest() != page["text_sha256"]:
            raise ValueError("academic_text_changed")
        inventory = inspect_numeric_text(text_bytes.decode())
        numeric_pages.append(
            {
                "page": page["page"],
                "text_file": text_name,
                "text_sha256": page["text_sha256"],
                "inventory": inventory,
            }
        )
        name = page["table_file"]
        if type(name) is not str or Path(name).name != name:
            raise ValueError("academic_table_path_invalid")
        data = read_private_bytes(structure_path.parent / name, maximum=20_000_000)
        if hashlib.sha256(data).hexdigest() != page["table_sha256"]:
            raise ValueError("academic_table_changed")
        tables = json.loads(data)
        for table in tables:
            locator = {
                "page": page["page"],
                "table_index": table["table_index"],
                "bbox": table["bbox"],
                "table_file": name,
                "table_file_sha256": page["table_sha256"],
            }
            grid = table["grid"]
            if (
                len(grid) < 2
                or not grid
                or any(len(row) != len(grid[0]) for row in grid)
            ):
                skipped.append({**locator, "reason": "no_rectangular_body"})
                continue
            retained.append({**locator, "grid": grid})
    consumed = set()
    for index, table in enumerate(retained):
        if index in consumed:
            continue
        grid = table["grid"]
        locator = {k: v for k, v in table.items() if k != "grid"}
        header = grid[0][1:]
        # A continuation lacks the ordinary column header. Preserve the proposed
        # join and every original cell; never silently repair text contamination.
        has_header = all(
            isinstance(c, str) and c not in {positive, other} for c in header
        )
        if not has_header:
            skipped.append(
                {**locator, "reason": "unbound_continuation_or_missing_header"}
            )
            continue
        segments = [locator]
        if index + 1 < len(retained):
            following = retained[index + 1]
            next_grid = following["grid"]
            if (
                following["page"] == table["page"] + 1
                and following["table_index"] == 1
                and len(next_grid[0]) == len(grid[0])
                and sum(c in {positive, other} for c in next_grid[0][1:])
                >= len(header) - 1
            ):
                grid = [*grid, *next_grid]
                consumed.add(index + 1)
                segments.append({k: v for k, v in following.items() if k != "grid"})
        body = [cell for row in grid[1:] for cell in row[1:]]
        if not body or not any(cell == positive for cell in body):
            skipped.append({**locator, "reason": "not_declared_binary_alphabet"})
            continue
        if sum(cell not in {positive, other} for cell in body) > max(
            1, len(body) // 20
        ):
            skipped.append({**locator, "reason": "not_declared_binary_alphabet"})
            continue
        result = audit_binary_percentage_table(grid, positive=positive, other=other)
        results.append(
            {
                **locator,
                "segments": segments,
                "continuation_association": "proposed_from_adjacency"
                if len(segments) > 1
                else "not_needed",
                "complete_table_verified": False,
                **result,
            }
        )
    return with_receipt_hash(
        {
            "contract": "AcademicRetainedTableArithmetic",
            "structure_receipt_hash": structure["receipt_hash"],
            "pdf_sha256": structure["pdf_sha256"],
            "tables": results,
            "numeric_pages": numeric_pages,
            "numeric_inventory_counts": {
                key: sum(len(p["inventory"][key]) for p in numeric_pages)
                for key in (
                    "count_percent_records",
                    "confidence_intervals",
                    "mean_sd_records",
                    "location_dispersion_pairs",
                )
            },
            "unassessed_tables": skipped,
            "check_count": sum(len(t["checks"]) for t in results),
            "match_count": sum(
                c["arithmetic_match"] for t in results for c in t["checks"]
            ),
            "interpretation": "conditional_binary_count_over_all_cells",
            "source_classifications_validated": False,
            "all_essential_results_checked": False,
            "release_authorized": False,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--structure", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--positive", required=True)
    parser.add_argument("--other", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_structure(
        args.structure.resolve(),
        args.pdf.resolve(),
        positive=args.positive,
        other=args.other,
    )
    write_exclusive_json(args.output.resolve(), result)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "checks": result["check_count"],
                "matches": result["match_count"],
                "receipt_hash": result["receipt_hash"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
