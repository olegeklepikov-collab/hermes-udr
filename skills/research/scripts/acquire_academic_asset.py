"""Fetch one declared public supplement through public-IP pinned HTTPS; no credential forwarding."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .acquire_publisher_raw import _fetch_one
    from .file_io import (
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
except ImportError:
    from acquire_publisher_raw import _fetch_one
    from file_io import (
        new_private_directory,
        write_exclusive_bytes,
        write_exclusive_json,
    )
from hermes_research_report.academic_publisher_raw import _validated_url
from hermes_research_report.canonical import with_receipt_hash
from hermes_research_report.runtime_snapshot import runtime_guarded


def acquire_asset(
    url: str, output: Path, *, allowed_hosts: list[str], maximum=50_000_000
) -> dict:
    host = urlsplit(url).hostname
    if not host or not isinstance(maximum, int) or not 1024 <= maximum <= 1_000_000_000:
        raise ValueError("academic_asset_options_invalid")
    allowed = set(allowed_hosts) | {host}
    new_private_directory(output)
    hops = []
    for index in range(4):
        host = urlsplit(url).hostname
        if host not in allowed:
            raise ValueError("academic_asset_redirect_host_not_allowed")
        _validated_url(url, host, max_query_chars=1800)
        status, headers, raw, ip, tls = _fetch_one(
            url, maximum, host, max_query_chars=1800
        )
        if not tls:
            raise ValueError("academic_asset_tls_missing")
        # Signed temporary query strings must not enter model prompts or reports.
        canonical = urlsplit(url)._replace(query="", fragment="").geturl()
        hops.append(
            {
                "url_without_query": canonical,
                "request_url_sha256": hashlib.sha256(url.encode()).hexdigest(),
                "status": status,
                "body_sha256": hashlib.sha256(raw).hexdigest(),
                "public_ip": ip,
                "tls": tls,
            }
        )
        write_exclusive_bytes(output / f"hop-{index}.bin", raw)
        write_exclusive_json(output / f"hop-{index}.json", hops[-1])
        if status in {301, 302, 303, 307, 308}:
            url = urljoin(url, headers.get("location", ""))
            continue
        receipt = with_receipt_hash(
            {
                "contract": "AcademicPublicAsset",
                "status": "acquired" if status == 200 else "http_error",
                "hops": hops,
                "content_type": headers.get("content-type"),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "content_file": "content.bin",
                "source_identity_verified": False,
            }
        )
        write_exclusive_bytes(output / "content.bin", raw)
        write_exclusive_json(output / "asset.json", receipt)
        return receipt
    raise ValueError("academic_asset_redirect_limit")


@runtime_guarded
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--max-bytes", type=int, default=50_000_000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-query-ack", action="store_true")
    args = parser.parse_args()
    if not args.public_query_ack:
        parser.error("public_query_ack_required")
    r = acquire_asset(
        args.url,
        args.output.resolve(),
        allowed_hosts=args.allow_host,
        maximum=args.max_bytes,
    )
    print(
        json.dumps(
            {
                "status": r["status"],
                "bytes": r["bytes"],
                "receipt_hash": r["receipt_hash"],
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
