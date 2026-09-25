"""Read back exact source files and persist an unreleased work-origin map."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from .acquire_openalex_oa_text import _preflight as _metadata_preflight
    from .execute_beta_sources import _publisher_readback
    from .file_io import load_json, read_private_bytes, write_exclusive_json
    from .screen_openalex_oa_text import _preflight as _article_preflight
except ImportError:
    from acquire_openalex_oa_text import _preflight as _metadata_preflight
    from execute_beta_sources import _publisher_readback
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from screen_openalex_oa_text import _preflight as _article_preflight

from hermes_research_report.beta_origin_graph import build_beta_origin_graph
from hermes_research_report.beta_source_portfolio import _expected_files, _file_rows
from hermes_research_report.errors import ContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--metadata-capture", type=Path, required=True)
    parser.add_argument("--article-capture", type=Path, required=True)
    parser.add_argument("--publisher-capture", type=Path, required=True)
    parser.add_argument("--web-capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan, metadata, article, _source_id, _text, _excerpt, _prompt, _cost = (
            _article_preflight(args.plan, args.metadata_capture, args.article_capture)
        )
        raw_plan, raw_metadata, _short = _metadata_preflight(
            args.plan, args.metadata_capture, article["work_id"]
        )
        if (
            raw_plan["receipt_hash"] != plan["receipt_hash"]
            or raw_metadata["receipt_hash"] != metadata["receipt_hash"]
        ):
            raise ValueError("origin_metadata_raw_not_bound")
        publisher = _publisher_readback(args.publisher_capture, plan, metadata, article)
        execution_value, _ = load_json(args.execution)
        portfolio_value, _ = load_json(args.portfolio)
        web_value = None
        if args.web_capture is not None:
            web_value, _ = load_json(args.web_capture)
            if type(web_value) is not dict or args.web_capture.name != "capture.json":
                raise ValueError("origin_web_receipt_invalid")
            rows = _file_rows(_expected_files(web_value), "web.expected_files")
            for row in rows:
                payload = read_private_bytes(args.web_capture.parent / str(row["path"]))
                if (
                    len(payload) != row["bytes"]
                    or hashlib.sha256(payload).hexdigest() != row["sha256"]
                ):
                    raise ValueError("origin_web_artifact_tampered")
        if args.output.name != f"{plan['run_id']}.origin-graph.json":
            raise ValueError("origin_output_name_invalid")
        graph = build_beta_origin_graph(
            plan=plan,
            execution=execution_value,
            portfolio=portfolio_value,
            metadata=metadata,
            article=article,
            publisher=publisher,
            web_capture=web_value,
        )
        write_exclusive_json(args.output, graph)
        print(
            json.dumps(
                {
                    "status": graph["status"],
                    "run_id": graph["run_id"],
                    "attested_publisher_work_count": graph[
                        "attested_publisher_work_count"
                    ],
                    "independent_primary_work_count_verified": 0,
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
            else str(error)
            if isinstance(error, ValueError)
            and str(error).replace("_", "").isalnum()
            and len(str(error)) < 80
            else "origin_graph_failed"
        )
        print(json.dumps({"status": "error", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
