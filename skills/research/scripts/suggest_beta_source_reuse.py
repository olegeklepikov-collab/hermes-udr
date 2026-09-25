"""Route retained text toward other atoms without claiming semantic relevance."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .file_io import load_json, read_private_bytes, write_exclusive_json
except ImportError:
    from file_io import load_json, read_private_bytes, write_exclusive_json

from hermes_research_report.beta_source_reuse import suggest_source_reuse
from hermes_research_report.canonical import verify_receipt_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame, _ = load_json(args.frame)
        capture, _ = load_json(args.capture)
        screen, _ = load_json(args.screen)
        run, _ = load_json(args.screen.parent / "screen-run.json")
        if any(
            type(value) is not dict or not verify_receipt_hash(value)
            for value in (frame, capture, screen, run)
        ):
            raise ValueError("source_reuse_receipts_invalid")
        frame = cast(dict[str, Any], frame)
        capture = cast(dict[str, Any], capture)
        screen = cast(dict[str, Any], screen)
        run = cast(dict[str, Any], run)
        run_id = frame["run_id"]
        batch_run_id = f"{run_id}-B03"
        source_id = screen["source_id"]
        root = args.frame.parent.parent
        if (
            args.frame != root / f"{run_id}-coverage-route-repair/frame.json"
            or args.capture != root / f"{batch_run_id}-LEAF-003-keenable/capture.json"
            or args.screen
            != root / f"{batch_run_id}-S02-{source_id}-screen/screen.json"
            or run.get("screen_receipt_hash") != screen["receipt_hash"]
            or screen.get("capture_receipt_hash") != capture["receipt_hash"]
        ):
            raise ValueError("source_reuse_paths_invalid")
        name = f"{source_id}.txt"
        artifacts = capture.get("artifact_hashes")
        matches = (
            [
                item
                for item in artifacts
                if type(item) is dict and item.get("path") == name
            ]
            if type(artifacts) is list
            else []
        )
        if len(matches) != 1:
            raise ValueError("source_reuse_file_not_bound")
        raw = read_private_bytes(args.capture.parent / name, maximum=50_000)
        if len(raw) != matches[0].get("bytes") or hashlib.sha256(
            raw
        ).hexdigest() != matches[0].get("sha256"):
            raise ValueError("source_reuse_file_not_bound")
        result = suggest_source_reuse(
            frame=frame,
            source_id=source_id,
            title=screen["title"],
            text=raw.decode("utf-8"),
            screened_atom_id=screen["atom_id"],
            screen=screen,
        )
        write_exclusive_json(args.screen.parent / "source-reuse-v2.json", result)
        print(
            json.dumps(
                {
                    "status": "suggested",
                    "source_id": source_id,
                    "suggestion_count": len(result["suggestions"]),
                    "semantic_relevance_verified": False,
                    "release_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, UnicodeError, KeyError, TypeError) as error:
        print(json.dumps({"status": "error", "code": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
