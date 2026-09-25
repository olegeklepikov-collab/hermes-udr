"""Read bounded XLSX values and recompute paired descriptive statistics without Excel execution."""

from __future__ import annotations

import hashlib
import io
import math
import posixpath
import re
import statistics
import zipfile
from decimal import Decimal, localcontext
from functools import lru_cache
from xml.etree import ElementTree as ET

from .canonical import with_receipt_hash

_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def read_xlsx(raw: bytes, *, max_uncompressed=50_000_000, max_cells=1_000_000) -> dict:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 1000
            or len({e.filename for e in entries}) != len(entries)
            or sum(e.file_size for e in entries) > max_uncompressed
        ):
            raise ValueError("academic_xlsx_archive_limit")

        def xml(name):
            data = archive.read(name)
            if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise ValueError("academic_xlsx_dtd_rejected")
            return ET.fromstring(data)

        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(si.itertext())
                for si in xml("xl/sharedStrings.xml").findall("s:si", _NS)
            ]
        relationships = {
            r.attrib["Id"]: r.attrib for r in xml("xl/_rels/workbook.xml.rels")
        }
        sheets = []
        count = 0
        for sheet in xml("xl/workbook.xml").findall("s:sheets/s:sheet", _NS):
            rid = sheet.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            relationship = relationships[rid]
            if relationship.get("TargetMode") == "External":
                raise ValueError("academic_xlsx_external_sheet_rejected")
            target = relationship["Target"]
            target = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath("xl/" + target)
            )
            if not target.startswith("xl/") or ".." in target.split("/"):
                raise ValueError("academic_xlsx_sheet_path_invalid")
            cells = {}
            for cell in xml(target).findall("s:sheetData/s:row/s:c", _NS):
                count += 1
                if count > max_cells:
                    raise ValueError("academic_xlsx_cell_limit")
                ref = cell.attrib["r"]
                if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", ref) or ref in cells:
                    raise ValueError("academic_xlsx_cell_identity_invalid")
                kind = cell.attrib.get("t", "n")
                value_node = cell.find("s:v", _NS)
                value = value_node.text if value_node is not None else None
                formula = cell.find("s:f", _NS)
                if kind == "s" and value is not None:
                    value = strings[int(value)]
                elif kind == "inlineStr":
                    inline = cell.find("s:is", _NS)
                    if inline is None:
                        raise ValueError("academic_xlsx_inline_string_missing")
                    value = "".join(inline.itertext())
                elif kind == "b" and value is not None:
                    value = value == "1"
                elif kind == "n" and value is not None:
                    number = Decimal(value)
                    value = (
                        float(number)
                        if number.is_finite() and abs(number.adjusted()) < 100
                        else value
                    )
                cells[ref] = {
                    "value": value,
                    "type": kind,
                    "formula": formula.text if formula is not None else None,
                    "numeric_lexeme": value_node.text
                    if value_node is not None and kind == "n"
                    else None,
                }
            sheets.append(
                {"name": sheet.attrib["name"], "cells": cells, "source_part": target}
            )
    return with_receipt_hash(
        {
            "contract": "AcademicWorkbookValues",
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "sheets": sheets,
            "cell_count": count,
            "formulas_executed": False,
            "macros_executed": False,
        }
    )


@lru_cache(maxsize=256)
def student_t_critical(df: int, confidence=0.95) -> float:
    if type(df) is not int or not 1 <= df <= 100000 or not 0.5 < confidence <= 0.99:
        raise ValueError("academic_t_parameters_invalid")
    factor = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(
        df * math.pi
    )

    def density(x):
        return factor * (1 + x * x / df) ** (-(df + 1) / 2)

    def integral(a, b, fa, fb, fm, whole, eps, depth):
        mid = (a + b) / 2
        left_mid = (a + mid) / 2
        right_mid = (mid + b) / 2
        fl, fr = density(left_mid), density(right_mid)
        left = (mid - a) * (fa + 4 * fl + fm) / 6
        right = (b - mid) * (fm + 4 * fr + fb) / 6
        if abs(left + right - whole) <= 15 * eps:
            return left + right + (left + right - whole) / 15
        if depth <= 0:
            raise ValueError("academic_t_integration_not_converged")
        return integral(a, mid, fa, fm, fl, left, eps / 2, depth - 1) + integral(
            mid, b, fm, fb, fr, right, eps / 2, depth - 1
        )

    def cdf(x):
        fa, fb, fm = density(0), density(x), density(x / 2)
        return 0.5 + integral(0, x, fa, fb, fm, x * (fa + 4 * fm + fb) / 6, 1e-12, 24)

    target = (1 + confidence) / 2
    lo, hi = 0.0, 1.0
    while cdf(hi) < target:
        hi *= 2
        if hi > 1024:
            raise ValueError("academic_t_quantile_not_bracketed")
    for _ in range(60):
        mid = (lo + hi) / 2
        if cdf(mid) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    return (lo + hi) / 2


def column_headers(sheet: dict) -> dict[str, str]:
    return {
        ref[:-1]: str(cell["value"])
        for ref, cell in sheet["cells"].items()
        if re.fullmatch(r"[A-Z]+1", ref) and cell["value"] is not None
    }


def infer_pairs(sheet: dict) -> list[dict]:
    headers = column_headers(sheet)

    def normalized(name):
        return re.sub(
            r"[^a-z0-9]", "", re.sub(r"(?i)(12w|_baseline$|_bl$)", "", name).lower()
        )

    pairs = []
    for follow, name in headers.items():
        if "12w" not in name.lower():
            continue
        candidates = [
            (col, label)
            for col, label in headers.items()
            if "12w" not in label.lower() and normalized(label) == normalized(name)
        ]
        if len(candidates) == 1:
            col, label = candidates[0]
            pairs.append(
                {
                    "baseline": col,
                    "followup": follow,
                    "baseline_name": label,
                    "followup_name": name,
                    "mapping_basis": "matching_variable_names_with_12W_BL_baseline_markers",
                    "measurement_equivalence_verified": False,
                }
            )
    return pairs


def paired_change(
    sheet: dict,
    baseline: str,
    followup: str,
    *,
    group_column=None,
    group_value=None,
    id_column=None,
) -> dict:
    cells = sheet["cells"]
    row_numbers = set()
    for ref in cells:
        match = re.fullmatch(r"[A-Z]+([1-9][0-9]*)", ref)
        if match is None:
            raise ValueError("academic_dataset_cell_reference_invalid")
        if int(match.group(1)) > 1:
            row_numbers.add(int(match.group(1)))
    rows = sorted(row_numbers)
    differences: list[Decimal] = []
    inputs = []
    excluded = []
    selected = 0
    ids = set()
    for row in rows:
        if group_column is not None:
            observed = cells.get(f"{group_column}{row}", {}).get("value")
            if observed != group_value or isinstance(observed, bool) != isinstance(
                group_value, bool
            ):
                continue
        selected += 1
        if id_column:
            identity = cells.get(f"{id_column}{row}", {}).get("value")
            if identity is None or identity in ids:
                raise ValueError("academic_dataset_subject_id_invalid")
            ids.add(identity)
        refs = [f"{baseline}{row}", f"{followup}{row}"]
        pair = [cells.get(ref) for ref in refs]
        if any(c is None or c["value"] is None for c in pair):
            excluded.append({"row": row, "cells": refs, "reason": "missing_pair"})
            continue
        if any(
            c["formula"] is not None or c["type"] != "n" or c["numeric_lexeme"] is None
            for c in pair
        ):
            excluded.append(
                {
                    "row": row,
                    "cells": refs,
                    "reason": "non_numeric_or_unrecomputed_formula",
                }
            )
            continue
        values = [Decimal(c["numeric_lexeme"]) for c in pair]
        if any(not v.is_finite() for v in values):
            excluded.append({"row": row, "cells": refs, "reason": "nonfinite_value"})
            continue
        differences.append(values[1] - values[0])
        inputs.append(
            {
                "row": row,
                "cells": refs,
                "baseline": str(values[0]),
                "followup": str(values[1]),
            }
        )
    n = len(differences)
    mean = sd = se = None
    interval = None
    with localcontext() as ctx:
        ctx.prec = 40
        if n:
            mean = sum(differences, Decimal(0)) / n
        if n > 1:
            assert mean is not None
            variance = sum(((v - mean) ** 2 for v in differences), Decimal(0)) / (n - 1)
            sd = variance.sqrt()
            se = sd / Decimal(n).sqrt()
            t = Decimal(str(student_t_critical(n - 1)))
            interval = [str(mean - t * se), str(mean + t * se)]
    return with_receipt_hash(
        {
            "contract": "AcademicPairedChange",
            "sheet": sheet["name"],
            "baseline_column": baseline,
            "followup_column": followup,
            "group_column": group_column,
            "group_value": group_value,
            "selected_rows": selected,
            "complete_pairs": n,
            "excluded": excluded,
            "input_cells": inputs,
            "mean_change": str(mean) if mean is not None else None,
            "sample_sd": str(sd) if sd is not None else None,
            "standard_error": str(se) if se is not None else None,
            "t95_interval": interval,
            "zero_sample_variance": sd == 0 if sd is not None else None,
            "method": "paired_complete_cases_followup_minus_baseline_sample_sd_student_t95_df_n_minus_one",
            "method_assumptions_verified": False,
            "causal_effect_verified": False,
        }
    )


def describe(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None, "quartiles_exclusive": None}
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "quartiles_exclusive": statistics.quantiles(values, n=4, method="exclusive")
        if len(values) >= 4
        else None,
    }
