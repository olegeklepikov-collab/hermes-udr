"""Nine focused tools; Hermes owns execution, retrieval and native delegation."""
from __future__ import annotations
import json
try:
    from .src.hermes_research_report.research_workspace import TOOLS, schema
    from .src.hermes_research_report.research_fetch import fetch
    from .src.hermes_research_report.research_methods import method, METHOD_SCHEMA
    from .src.hermes_research_report.research_journal import capture_search
    from .src.hermes_research_report.research_capabilities import provider_tool, PROVIDER_SCHEMA
    from .src.hermes_research_report.comparison import COMPARISON_TOOL_SCHEMA, compare_periods
    from .src.hermes_research_report.report import REPORT_TOOL_SCHEMA, ReportInputError, build_report
except ImportError:
    from src.hermes_research_report.research_workspace import TOOLS, schema
    from src.hermes_research_report.research_fetch import fetch
    from src.hermes_research_report.research_methods import method, METHOD_SCHEMA
    from src.hermes_research_report.research_journal import capture_search
    from src.hermes_research_report.research_capabilities import provider_tool, PROVIDER_SCHEMA
    from src.hermes_research_report.comparison import COMPARISON_TOOL_SCHEMA, compare_periods
    from src.hermes_research_report.report import REPORT_TOOL_SCHEMA, ReportInputError, build_report

def handle_comparison(args: object, **_kwargs: object) -> str:
    try:
        if type(args) is not dict or set(args) != {
            "observations",
            "before",
            "after",
        }:
            raise ValueError(
                "Нужны observations, before и after без дополнительных полей."
            )
        result = compare_periods(args["observations"], args["before"], args["after"])
    except ValueError as error:
        result = {
            "status": "error",
            "error": {"code": "invalid_comparison", "message": str(error)},
        }
    return json.dumps(result, ensure_ascii=False, allow_nan=False)


def handle_report(args: object, **_kwargs: object) -> str:
    try:
        result = build_report(args)
    except ReportInputError as error:
        result = {
            "status": "error",
            "error": {
                "code": error.code,
                "path": error.path,
                "message": str(error),
            },
        }
    return json.dumps(result, ensure_ascii=False, allow_nan=False)



def _handler(function):
    def handle(args, **kwargs):
        try:
            result = function(args)
        except (ValueError, KeyError, TypeError, OSError) as error:
            result = {"status": "error", "error": str(error)}
        return json.dumps(result, ensure_ascii=False, allow_nan=False)
    return handle


def register(ctx):
    ctx.register_tool(name="research_web_provider", toolset="research", schema=PROVIDER_SCHEMA, handler=provider_tool, is_async=True, check_fn=lambda: True)
    if hasattr(ctx, "register_hook"):
        ctx.register_hook("post_tool_call", capture_search)
    fetch_schema = schema("research_fetch", "Retrieve original public HTTPS bytes and save the complete extracted text (PDF, HTML, XML, JSON, text). Returns paths for section-by-section reading, without a 50k-character clipping window. Never certifies semantic support.",
                          {"run_id": {"type": "string"}, "url": {"type": "string"}, "title": {"type": "string"}, "stream": {"type": "string"}, "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 50000000}}, ["run_id", "url"])
    for definition, function in [*TOOLS, (fetch_schema, fetch), (METHOD_SCHEMA, method)]:
        ctx.register_tool(name=definition["name"], toolset="research", schema=definition,
                          handler=_handler(function), check_fn=lambda: True)
    for name, definition, handler in (
        ("research_compare_periods", COMPARISON_TOOL_SCHEMA, handle_comparison),
        ("research_build_report", REPORT_TOOL_SCHEMA, handle_report),
    ):
        ctx.register_tool(name=name, toolset="research", schema=definition, handler=handler, check_fn=lambda: True)
