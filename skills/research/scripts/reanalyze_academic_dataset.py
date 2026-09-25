"""Recompute source-column changes from an XLSX supplement; preserve missing data and mapping limits."""

import argparse
import json
import re
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))
try:
    from .file_io import load_json, read_private_bytes, write_exclusive_json
    from .process_limits import run_bounded
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from process_limits import run_bounded
from hermes_research_report.academic_dataset import (
    column_headers,
    describe,
    infer_pairs,
    paired_change,
    read_xlsx,
)
from hermes_research_report.canonical import verify_receipt_hash, with_receipt_hash


def compare_reported(result: dict, spec: dict) -> dict:
    document, _ = load_json(Path(spec["document_path"]))
    if (
        not verify_receipt_hash(document)
        or document["document_id"] != result["parent_document_id"]
    ):
        raise ValueError("dataset_publication_unbound")
    page = next(p for p in document["pages"] if p["page"] == spec["page"])
    number = r"[+−-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
    pattern = re.compile(
        rf"^(?P<label>.*?)\s+(?P<a>{number})\((?P<aci>[^)]+)\)\s+(?P<b>{number})\((?P<bci>[^)]+)\)\s*$",
        re.MULTILINE,
    )
    published = {m["label"].strip(): m for m in pattern.finditer(page["text"])}
    comparisons = []

    def equal(value, displayed):
        digits = len(displayed.partition(".")[2])
        quantum = Decimal(1).scaleb(-digits)
        return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP) == Decimal(
            displayed.replace("−", "-")
        )

    for mapping in spec["mappings"]:
        source = published.get(mapping["label"])
        if source is None:
            comparisons.append(
                {"mapping": mapping, "status": "published_row_not_located"}
            )
            continue
        for index, group in enumerate(spec["group_order"]):
            record = next(
                (
                    r
                    for r in result["paired_changes"]
                    if r["mapping"]["baseline_name"] == mapping["baseline_name"]
                    and r["group"]["value"] == group
                ),
                None,
            )
            if record is None:
                comparisons.append(
                    {
                        "mapping": mapping,
                        "group": {"value": group, "label": str(group)},
                        "status": "data_mapping_missing",
                    }
                )
                continue
            prefix = "a" if index == 0 else "b"
            mean = source[prefix]
            ci = source[prefix + "ci"]
            observed = record["result"]
            mean_matches = observed["mean_change"] is not None and equal(
                observed["mean_change"], mean
            )
            reported_interval = None
            interval_matches = None
            if ci.upper() != "N/A":
                reported_interval = [v.strip() for v in ci.split(",")]
                if len(reported_interval) != 2:
                    raise ValueError("dataset_reported_ci_invalid")
                interval_matches = observed["t95_interval"] is not None and all(
                    equal(v, s)
                    for v, s in zip(
                        observed["t95_interval"], reported_interval, strict=True
                    )
                )
            comparisons.append(
                {
                    "mapping": mapping,
                    "group": record["group"],
                    "calculation_receipt_hash": observed["receipt_hash"],
                    "published_source": {
                        "page": spec["page"],
                        "start": source.start(),
                        "end": source.end(),
                        "quote": source.group(),
                        "text_sha256": page["text_sha256"],
                    },
                    "mean_reported": mean,
                    "mean_calculated": observed["mean_change"],
                    "mean_matches": mean_matches,
                    "interval_reported": reported_interval,
                    "interval_calculated": observed["t95_interval"],
                    "interval_matches": interval_matches,
                    "status": "matches_at_reported_precision"
                    if mean_matches and interval_matches is not False
                    else "discrepancy_requires_explanation",
                    "measurement_mapping_verified": False,
                }
            )
    return {
        "document_receipt_hash": document["receipt_hash"],
        "comparisons": comparisons,
        "rounding": "ROUND_HALF_UP at printed precision",
        "author_analysis_method_verified": False,
    }


def analyze_dataset(spec: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="udr-dataset-") as directory:
        request = Path(directory).resolve() / "request.json"
        write_exclusive_json(request, spec)
        execution = run_bounded(
            [
                sys.executable,
                str(Path(__file__).with_name("document_worker.py")),
                "dataset",
                str(request),
            ],
            wall_seconds=spec.get("parse_wall_seconds", 120),
            memory_bytes=spec.get("parse_memory_bytes", 1_500_000_000),
        )
    if execution["returncode"] != 0:
        raise ValueError("academic_dataset_worker_failed")
    result = json.loads(execution["stdout"])
    if not verify_receipt_hash(result):
        raise ValueError("academic_dataset_worker_receipt_invalid")
    return result


def _analyze_dataset(spec: dict) -> dict:
    raw = read_private_bytes(
        Path(spec["path"]), maximum=spec.get("max_bytes", 50_000_000)
    )
    workbook = read_xlsx(
        raw,
        max_uncompressed=spec.get("max_uncompressed", 50_000_000),
        max_cells=spec.get("max_cells", 1_000_000),
    )
    sheet = next(s for s in workbook["sheets"] if s["name"] == spec["sheet"])
    headers = column_headers(sheet)
    group_col = spec.get("group_column")
    if group_col is not None and group_col not in headers:
        raise ValueError("academic_dataset_group_column_missing")
    labels = {}
    codebook = spec.get("group_codebook")
    if codebook:
        dictionary = next(
            s for s in workbook["sheets"] if s["name"] == codebook["sheet"]
        )
        for ref, cell in dictionary["cells"].items():
            col = codebook["value_column"]
            if (
                ref.startswith(col)
                and ref[len(col) :].isdigit()
                and int(ref[len(col) :]) >= codebook.get("first_row", 2)
            ):
                target = codebook["label_column"] + ref[len(col) :]
                label = dictionary["cells"].get(target, {}).get("value")
                if label is not None:
                    labels[cell["value"]] = {
                        "label": str(label),
                        "cells": [ref, target],
                        "sheet": dictionary["name"],
                    }
    groups = [{"label": "all", "value": None}]
    if group_col:
        values = sorted(
            {
                c["value"]
                for ref, c in sheet["cells"].items()
                if ref.startswith(group_col)
                and ref[len(group_col) :].isdigit()
                and ref != group_col + "1"
                and c["value"] is not None
            },
            key=str,
        )
        if len(values) > spec.get("max_groups", 128):
            raise ValueError("academic_dataset_group_limit_adjustable")
        groups.extend(
            {
                "label": labels.get(v, {}).get("label", str(v)),
                "value": v,
                "label_provenance": labels.get(v),
            }
            for v in values
        )
    pairs = infer_pairs(sheet)
    for pair in spec.get("additional_pairs", []):
        if pair["baseline"] not in headers or pair["followup"] not in headers:
            raise ValueError("academic_dataset_mapping_unknown_column")
        pairs.append(
            {
                **pair,
                "baseline_name": headers[pair["baseline"]],
                "followup_name": headers[pair["followup"]],
                "mapping_basis": "explicit_analysis_mapping",
                "measurement_equivalence_verified": False,
            }
        )
    results = []
    for pair in pairs:
        for group in groups:
            result = paired_change(
                sheet,
                pair["baseline"],
                pair["followup"],
                group_column=group_col if group["value"] is not None else None,
                group_value=group["value"],
                id_column=spec.get("id_column"),
            )
            results.append({"mapping": pair, "group": group, "result": result})
    summaries = []
    for column in spec.get("summary_columns", []):
        for group in groups:
            values = []
            refs = []
            for ref, c in sheet["cells"].items():
                if (
                    not ref.startswith(column)
                    or not ref[len(column) :].isdigit()
                    or ref == column + "1"
                ):
                    continue
                row = ref[len(column) :]
                if (
                    group["value"] is not None
                    and sheet["cells"].get(group_col + row, {}).get("value")
                    != group["value"]
                ):
                    continue
                if (
                    c["type"] == "n"
                    and c["formula"] is None
                    and type(c["value"]) in (int, float)
                ):
                    values.append(c["value"])
                    refs.append(ref)
            summaries.append(
                {
                    "column": column,
                    "name": headers[column],
                    "group": group,
                    "source_cells": refs,
                    "descriptive": describe(values),
                }
            )
    body = {
        "contract": "AcademicDatasetReanalysis",
        "source_workbook_sha256": workbook["source_sha256"],
        "workbook_receipt_hash": workbook["receipt_hash"],
        "sheet": sheet["name"],
        "headers": headers,
        "paired_changes": results,
        "descriptive_summaries": summaries,
        "formula_cells_not_executed": sum(
            c["formula"] is not None
            for s in workbook["sheets"]
            for c in s["cells"].values()
        ),
        "source_url": spec.get("source_url"),
        "parent_document_id": spec.get("parent_document_id"),
        "unit_and_pairing_semantics_verified": False,
        "method": "complete-pair descriptive changes and Student t95 intervals; no causal inference",
        "release_authorized": False,
    }
    if spec.get("publication_comparison"):
        body["publication_comparison"] = compare_reported(
            body, spec["publication_comparison"]
        )
    return with_receipt_hash(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec, _ = load_json(args.spec)
    result = analyze_dataset(spec)
    write_exclusive_json(args.output.resolve(), result)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "paired_analyses": len(result["paired_changes"]),
                "receipt_hash": result["receipt_hash"],
            }
        )
    )


if __name__ == "__main__":
    main()
