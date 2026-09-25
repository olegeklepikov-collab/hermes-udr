"""Read public official-document candidates and actual CSV/JSON dataset bytes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))
try:
    from .acquire_publisher_raw import _fetch_one
    from .file_io import (
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
except ImportError:
    from acquire_publisher_raw import _fetch_one
    from file_io import (
        load_json,
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
from hermes_research_report.beta_acquisition import _safe_url
from hermes_research_report.canonical import with_receipt_hash


class VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []
        self.main_parts = []
        self.main_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"main", "article"}:
            self.main_depth += 1
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"main", "article"}:
            self.main_depth = max(0, self.main_depth - 1)
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, value):
        if not self.hidden and value.strip():
            self.parts.append(value.strip())
            if self.main_depth:
                self.main_parts.append(value.strip())


def decode_public_content(raw: bytes, format: str) -> tuple[str, dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    profile = {
        "format": format,
        "decode_replacements": text.count("\ufffd"),
        "measurements_verified": False,
        "license_verified": False,
    }
    if format == "html":
        parser = VisibleHTML()
        parser.feed(text)
        parser.close()
        text = "\n".join(parser.main_parts or parser.parts)
        profile["html_scope"] = (
            "main_or_article" if parser.main_parts else "visible_text_fallback"
        )
        profile["visuals_verified"] = False
    elif format == "csv":
        if text.lstrip().lower().startswith(("<!doctype html", "<html")):
            raise ValueError("public_csv_is_html")
        reader = csv.reader(io.StringIO(text))
        header = next(reader, [])
        rows = 0
        mismatches = 0
        for row in reader:
            if not row:
                continue
            rows += 1
            mismatches += len(row) != len(header)
        profile.update(
            columns=header,
            data_row_count=rows,
            unequal_width_rows=mismatches,
            header_assumed_first_row=True,
            numerical_meaning_verified=False,
        )
    elif format == "arff":
        attributes = re.findall(r"(?im)^\s*@attribute\s+(.+)$", text)
        sections = re.split(r"(?im)^\s*@data\s*$", text, maxsplit=1)
        if not attributes or len(sections) != 2:
            raise ValueError("public_arff_schema_missing")
        rows = list(
            csv.reader(
                line
                for line in sections[1].splitlines()
                if line.strip() and not line.lstrip().startswith("%")
            )
        )
        profile.update(
            attributes=attributes,
            data_row_count=len(rows),
            unequal_width_rows=sum(len(row) != len(attributes) for row in rows),
            numerical_meaning_verified=False,
        )
    elif format == "json":
        value = json.loads(text)
        profile.update(
            root_type=type(value).__name__,
            top_level_count=len(value) if isinstance(value, (dict, list)) else None,
        )
    elif format != "text":
        raise ValueError("public_content_format_unsupported")
    if not text.strip():
        raise ValueError("public_content_empty")
    return text, profile


def acquire_public_content(
    spec: dict, output: Path, *, maximum_bytes: int = 2_000_000, fetch=_fetch_one
) -> dict:
    if spec.get("kind") not in {"official", "dataset"} or spec.get("format") not in {
        "html",
        "csv",
        "json",
        "text",
        "arff",
    }:
        raise ValueError("public_content_spec_invalid")
    if type(maximum_bytes) is not int or not 1024 <= maximum_bytes <= 50_000_000:
        raise ValueError("public_content_size_limit_invalid")
    original = _safe_url(spec["url"])
    host = urlsplit(original).hostname
    new_private_directory(output)
    write_exclusive_json(
        output / "attempt.json",
        {
            "url": original,
            "maximum_bytes": maximum_bytes,
            "status": "started",
            "retry_allowed": False,
        },
    )
    url = original
    hops = []
    raw = b""
    text = ""
    profile = {}
    reason = None
    try:
        for _ in range(4):
            status, headers, raw, ip, tls = fetch(url, maximum_bytes, host)
            if not tls or len(raw) > maximum_bytes:
                raise ValueError("public_content_transport_invalid")
            hops.append(
                {
                    "url": url,
                    "status": status,
                    "public_ip": ip,
                    "body_sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
            write_exclusive_bytes(output / f"hop-{len(hops)}.raw", raw)
            if status in {301, 302, 303, 307, 308}:
                target = _safe_url(urljoin(url, headers.get("location", "")))
                if urlsplit(target).hostname not in {
                    host,
                    "www." + str(host),
                    str(host).removeprefix("www."),
                }:
                    raise ValueError("public_content_cross_host_redirect")
                if target in {row["url"] for row in hops}:
                    raise ValueError("public_content_redirect_cycle")
                url = target
                continue
            if status != 200:
                raise ValueError(f"public_content_http_{status}")
            text, profile = decode_public_content(raw, spec["format"])
            break
        else:
            raise ValueError("public_content_redirect_limit")
    except (OSError, ValueError, csv.Error) as error:
        reason = str(error)[:200]
    source_id = "SRC-" + hashlib.sha256(original.encode()).hexdigest()[:16].upper()
    if text:
        write_exclusive_bytes(output / f"{source_id}.txt", text.encode())
    receipt = with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaPublicContentRead",
            "source_id": source_id,
            "title": spec.get("title", original),
            "url": url,
            "requested_url": original,
            "declared_family": spec["kind"],
            "mapped_atom_ids": spec.get("atom_ids", []),
            "format": spec["format"],
            "status": "content_read" if text else "content_unavailable",
            "reason": reason,
            "hops": hops,
            "raw_bytes": len(raw),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "text_file": f"{source_id}.txt" if text else None,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest() if text else None,
            "text_chars": len(text),
            "profile": profile,
            "read_scope": "dataset_content"
            if spec["kind"] == "dataset"
            else "extracted_text",
            "official_authority_verified": False,
            "independent_origin_verified": False,
            "license_verified": False,
            "source_calls": len(hops),
            "release_authorized": False,
        }
    )
    write_exclusive_json(output / "content.json", receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    parser.add_argument("--public-query-ack", action="store_true")
    args = parser.parse_args(argv)
    if not args.public_query_ack:
        parser.error("public_query_ack_required")
    manifest, _ = load_json(args.manifest)
    new_private_directory(args.output)
    rows = []
    for index, source in enumerate(manifest["sources"], 1):
        rows.append(
            acquire_public_content(
                source,
                args.output / f"source-{index:03d}",
                maximum_bytes=args.max_bytes,
            )
        )
    receipt = with_receipt_hash(
        {
            "contract": "BetaPublicContentBatch",
            "sources": rows,
            "release_authorized": False,
        }
    )
    write_exclusive_json(args.output / "batch.json", receipt)
    print(
        json.dumps(
            {
                "read": sum(row["status"] == "content_read" for row in rows),
                "total": len(rows),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
