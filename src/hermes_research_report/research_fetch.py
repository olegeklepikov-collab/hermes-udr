"""Bounded direct public fetch into the research workspace, with exact raw bytes."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from .beta_acquisition import _safe_url
from .research_workspace import root_for, source, write_json, write_text
from .research_integration import settings as integration_settings

_SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "research" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
from acquire_orthogonal_metadata import _JATS_DOCTYPE  # noqa: E402
from acquire_publisher_raw import _fetch_one  # noqa: E402
from read_beta_public_content import decode_public_content  # noqa: E402

MAX_BYTES = 50_000_000
_REDIRECTS = {301, 302, 303, 307, 308}


def _text(raw: bytes, content_type: str, original: Path) -> tuple[str, str]:
    lower = raw[:512].lower()
    media = content_type.split(";", 1)[0].strip().lower()
    if raw.startswith(b"%PDF-") or media == "application/pdf":
        if shutil.which("pdftotext"):
            result = subprocess.run(
                ["pdftotext", "-layout", str(original), "-"],
                capture_output=True, check=False, timeout=90,
            )
            if result.returncode or len(result.stdout) > MAX_BYTES:
                raise ValueError("pdf_text_unavailable_or_over_limit")
            text, method = result.stdout.decode("utf-8"), "pdftotext_layout"
        else:
            import pdfplumber

            pages = []
            has_text = False
            with pdfplumber.open(original) as document:
                count = len(document.pages)
                for number, page in enumerate(document.pages, 1):
                    content = page.extract_text(layout=True) or ""
                    has_text = has_text or bool(content.strip())
                    pages.append(f"[PDF page {number}/{count}]\n{content}")
            if not has_text:
                raise ValueError("pdf_text_unavailable_or_over_limit")
            text, method = "\n\n".join(pages), "pdfplumber_all_pages"
            if len(text.encode("utf-8")) > MAX_BYTES:
                raise ValueError("pdf_text_unavailable_or_over_limit")
    elif media in {"application/xml", "text/xml", "application/jats+xml"} or lower.lstrip().startswith((b"<?xml", b"<!doctype article", b"<article")):
        upper = raw.upper()
        if b"<!ENTITY" in upper:
            raise ValueError("xml_entity_forbidden")
        if b"<!DOCTYPE" in upper:
            found = list(_JATS_DOCTYPE.finditer(raw))
            if len(found) != 1 or upper.count(b"<!DOCTYPE") != 1:
                raise ValueError("xml_doctype_unsupported")
            raw = raw[: found[0].start()] + raw[found[0].end() :]
        root = ET.fromstring(raw)
        text, method = " ".join(" ".join(root.itertext()).split()), "xml_itertext"
    elif media == "text/html" or lower.lstrip().startswith((b"<!doctype html", b"<html")):
        text, profile = decode_public_content(raw, "html")
        method = "html_visible_text" + ("_decode_replacements" if profile["decode_replacements"] else "")
    else:
        text, method = raw.decode("utf-8-sig", errors="replace"), "utf8_text"
    if not text.strip() or "content has been truncated to stay below" in text.casefold():
        raise ValueError("empty_or_provider_truncated_text")
    return text, method


def fetch(args: dict) -> dict:
    """Fetch public HTTPS bytes without credentials and register extracted full text."""
    if type(args) is not dict or type(args.get("run_id")) is not str:
        raise ValueError("fetch_request_invalid")
    maximum = args.get("max_bytes", MAX_BYTES)
    if type(maximum) is not int or not 1024 <= maximum <= MAX_BYTES:
        raise ValueError("max_bytes_invalid")
    root = root_for(args["run_id"])
    if not (root / "run.json").is_file():
        raise ValueError("unknown_research_run")
    url = _safe_url(args.get("url"))
    hops = []
    raw = b""
    headers: dict[str, str] = {}
    for redirect_count in range(6):  # initial read plus at most five redirects
        host = urlsplit(url).hostname
        status, headers, raw, public_ip, tls = _fetch_one(
            url, maximum, host, max_query_chars=500,
        )
        if not tls or len(raw) > maximum:
            raise ValueError("public_fetch_transport_invalid")
        hops.append({"url": url, "status": status, "public_ip": public_ip,
                     "sha256": hashlib.sha256(raw).hexdigest()})
        if status in _REDIRECTS:
            if redirect_count == 5:
                raise ValueError("public_fetch_redirect_limit")
            target = headers.get("location")
            if not target:
                raise ValueError("public_fetch_redirect_missing")
            url = _safe_url(urljoin(url, target))
            if url in {row["url"] for row in hops}:
                raise ValueError("public_fetch_redirect_cycle")
            continue
        if status != 200:
            raise ValueError(f"public_fetch_http_{status}")
        break
    folder = root / "retrievals" / uuid4().hex
    folder.mkdir(parents=True, mode=0o700)
    original = folder / "original.bin"
    with original.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    original.chmod(0o600)
    metadata = {"requested_url": args["url"], "final_url": url,
                "http_status": 200, "hops": hops, "original_path": str(original),
                "original_sha256": hashlib.sha256(raw).hexdigest(),
                "original_bytes": len(raw), "raw_complete": True,
                "content_type": headers.get("content-type", ""),
                "meaning_verified": False}
    if integration_settings()["integration_mode"] == "foundation":
        metadata.update(status="raw_acquired_requires_host_intake", classification="untrusted_raw",
                        platform_acceptance="not_requested", source_id=None)
        write_json(folder / "metadata.json", metadata)
        return {"status": metadata["status"], "original_path": str(original),
                "original_sha256": metadata["original_sha256"], "metadata_file": str(folder / "metadata.json"),
                "next_action": "Host artifact intake and approved parser execution; register the resulting text with provenance refs.",
                "host_parser_invoked": False, "meaning_verified": False}
    try:
        text, method = _text(raw, metadata["content_type"], original)
        text_path = folder / "text.txt"
        write_text(text_path, text)
        saved = source({"run_id": args["run_id"], "url": url,
                        "title": args.get("title", url), "stream": args.get("stream", ""),
                        "text_path": str(text_path), "extent": "full_text"})
        if saved["extent"] != "full_text":
            raise ValueError("extracted_text_not_full")
        metadata.update(status="full_text_registered", extraction=method,
                        visuals_verified=False,
                        text_sha256=saved["sha256"], text_characters=saved["characters"],
                        source_id=saved["source_id"])
        write_json(folder / "metadata.json", metadata)
        return {**saved, "status": "full_text_registered",
                "original_sha256": metadata["original_sha256"],
                "original_bytes": len(raw), "metadata_file": str(folder / "metadata.json")}
    except (OSError, ValueError, UnicodeError, ET.ParseError, subprocess.TimeoutExpired) as error:
        metadata.update(status="text_extraction_failed", error=type(error).__name__)
        write_json(folder / "metadata.json", metadata)
        raise
