"""Run one native Hermes research session over the persistent research workspace."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

from hermes_research_report.research_workspace import root_for, workspace, write_json

from hermes_research_report.research_modes import MODES, normalize_mode, instructions as mode_instructions

_MODES = MODES
_REQUIRED_TOOLS = {
    "research_workspace", "research_method", "research_source", "research_note", "research_finish",

}


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _positive_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def _available_tools(names=None) -> None:
    if names is None:
        import model_tools
        names = model_tools.get_all_tool_names()
    missing = _REQUIRED_TOOLS - set(names)
    if missing:
        raise ValueError("research_tools_unavailable")


def _create_agent(skill: str, *, model_class: str | None,
                  max_iterations: int | None, max_seconds: float | None):
    # Import after setting HERMES_RESEARCH_MODEL_CLASS: other research scripts
    # import PROVIDER/MODEL at process startup from this same resolver.
    from hermes_cli.config import load_config
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from hermes_constants import parse_reasoning_effort
    from run_agent import AIAgent
    try:
        from .model_call import _model_selection
    except ImportError:
        from model_call import _model_selection

    config = load_config()
    selection = _model_selection(config, model_class)
    runtime = resolve_runtime_provider(
        requested=selection["provider"], target_model=selection["model"]
    )
    reasoning = parse_reasoning_effort(selection["reasoning"])
    if reasoning is None:
        raise ValueError("research_reasoning_invalid")
    from hermes_research_report.research_capabilities import inventory
    run_id = os.environ.get("HERMES_RESEARCH_RUN_ID")
    capabilities = inventory({"run_id": run_id, "platform": "cli"})
    _available_tools(capabilities["parent_definition_names"])
    toolsets = capabilities["parent_enabled_toolsets"]
    capability_note = ("\nConnected capabilities were discovered from this Hermes profile, including enabled plugin/MCP tools. "
                       "Use native tool discovery/describe to inspect all service-specific operations and parameter modes. "
                       "Do not reduce a connector to generic web_search/web_extract or assume an unexposed vendor API is available. "
                       "Full schemas and leaf-access inventory: " + capabilities["full_snapshot_path"])
    skill += capability_note
    options: dict[str, Any] = {
        "api_key": runtime.get("api_key"),
        "base_url": runtime.get("base_url"),
        "provider": runtime.get("provider"),
        "requested_provider": runtime.get("requested_provider"),
        "api_mode": runtime.get("api_mode"),
        "model": selection["model"],
        "credential_pool": runtime.get("credential_pool"),
        "fallback_model": None,
        "reasoning_config": reasoning,
        "enabled_toolsets": toolsets,
        "disabled_toolsets": capabilities["parent_disabled_toolsets"],
        "quiet_mode": True,
        "platform": "cli",
        "ephemeral_system_prompt": skill,
        "skip_background_review": True,
    }
    if max_iterations is not None:
        options["max_iterations"] = max_iterations
    if max_seconds is not None:
        options["run_budget_seconds"] = max_seconds
    agent = AIAgent(**options)
    agent._research_model_selection = selection
    agent._research_capabilities = capabilities
    actual = sorted(getattr(agent, "valid_tool_names", ()))
    write_json(root_for(run_id) / "agent-capabilities.json", {
        "inventory_path": capabilities["full_snapshot_path"],
        "actual_agent_tools_observed": True, "visible_tool_names": actual,
        "lazy_dispatch_available": "tool_call" in actual,
        "service_effectiveness_tested": False,
    })
    return agent


def _existing_run(run_id: str, question: str | None, mode: str | None) -> tuple[str, str, dict]:
    state = workspace({"action": "status", "run_id": run_id})
    record = json.loads((root_for(run_id) / "run.json").read_text(encoding="utf-8"))
    if record.get("integration_mode") == "foundation":
        raise ValueError("foundation_managed_run_requires_existing_host_session")
    stored_question, stored_mode = record.get("question"), record.get("mode")
    if (
        type(stored_question) is not str or not stored_question.strip()
        or stored_mode not in _MODES
        or (question is not None and question.strip() != stored_question)
        or (mode is not None and mode != stored_mode)
    ):
        raise ValueError("research_resume_mismatch")
    return stored_question, stored_mode, state


def _result(run_id: str) -> tuple[int, dict[str, Any]]:
    state = workspace({"action": "status", "run_id": run_id})
    root = root_for(run_id)
    report = root / "report.md"
    receipt = root / "result.json"
    if not report.is_file() or not receipt.is_file():
        raise ValueError("research_result_missing")
    report_bytes = report.read_bytes()
    if not report_bytes.strip():
        raise ValueError("research_result_missing")
    recorded = json.loads(receipt.read_text(encoding="utf-8"))
    expected_hash = recorded.get("report_sha256")
    if (
        state["source_records"] < 1
        or recorded.get("status") not in ("complete", "partial")
        or recorded.get("report_path") != str(report)
        or recorded.get("source_records") != state["source_records"]
        or (expected_hash is not None and expected_hash != hashlib.sha256(report_bytes).hexdigest())
        or (recorded.get("status") == "complete" and (
            type(recorded.get("cited_sources")) is not int
            or recorded["cited_sources"] < 1
        ))
    ):
        raise ValueError("research_result_invalid")
    status = recorded["status"]
    return (0 if status == "complete" else 3), {
        "status": status,
        "run_id": run_id,
        "root": str(root),
        "report_path": str(report),
        "result_path": str(receipt),
        "source_records": state["source_records"],
        "unique_sources": state["unique_sources"],
        "cited_sources": recorded.get("cited_sources"),
        "semantic_verification": recorded.get("semantic_verification"),
    }


def _execution_summary(
    turn: dict[str, Any], *, partial: bool, selection: dict[str, Any] | None = None
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    delegated_tasks = 0
    messages = turn.get("messages")
    for message in messages if type(messages) is list else []:
        if type(message) is not dict or message.get("role") != "assistant":
            continue
        calls = message.get("tool_calls")
        for call in calls if type(calls) is list else []:
            if type(call) is not dict or type(call.get("function")) is not dict:
                continue
            function = call["function"]
            name = function.get("name")
            if type(name) is not str or not name:
                continue
            counts[name] += 1
            if name != "delegate_task":
                continue
            arguments = function.get("arguments")
            try:
                args = json.loads(arguments) if type(arguments) is str else arguments
            except (ValueError, TypeError):
                args = None
            if type(args) is dict:
                if type(args.get("tasks")) is list:
                    delegated_tasks += len(args["tasks"])
                elif type(args.get("goal")) is str:
                    delegated_tasks += 1
    api_calls = turn.get("api_calls")
    route = selection if type(selection) is dict else {}
    return {
        "api_calls": api_calls if type(api_calls) is int and api_calls >= 0 else None,
        "tool_call_counts": dict(sorted(counts.items())),
        "delegate_task_batch_task_count": delegated_tasks,
        "completed": turn.get("completed") is True and not partial,
        "partial": partial,
        **{key: route.get(key) for key in (
            "provider", "model", "reasoning", "requested_model_class",
            "model_class_selection_source", "model_route_source", "model_class_mapping_hash",
        )},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question")
    parser.add_argument("--mode", type=normalize_mode, choices=_MODES)
    parser.add_argument("--resume-run")
    parser.add_argument("--model-class")
    parser.add_argument("--max-iterations", type=_positive_int)
    parser.add_argument("--max-seconds", type=_positive_seconds)
    args = parser.parse_args(argv)
    from hermes_research_report.research_integration import settings as integration_settings
    if integration_settings()["integration_mode"] == "foundation":
        print(json.dumps({"status": "error", "code": "foundation_managed_run_requires_existing_host_session"}), file=sys.stderr)
        return 2

    if not args.resume_run and not (args.question or "").strip():
        parser.error("--question is required for a new run")
    if args.model_class is not None:
        os.environ["HERMES_RESEARCH_MODEL_CLASS"] = args.model_class
    model_class = os.environ.get("HERMES_RESEARCH_MODEL_CLASS")
    previous_run_id = os.environ.get("HERMES_RESEARCH_RUN_ID")
    run_id: str | None = None
    agent = None
    try:
        if args.resume_run:
            question, mode, state = _existing_run(args.resume_run, args.question, args.mode)
        else:
            question, mode = args.question.strip(), args.mode or "deep"
            state = workspace({"action": "start", "question": question, "mode": mode})
        run_id = state["run_id"]
        os.environ["HERMES_RESEARCH_RUN_ID"] = run_id
        result_file = root_for(run_id) / "result.json"
        prior_result = (
            (result_file.stat().st_ino, result_file.stat().st_mtime_ns)
            if result_file.is_file() else None
        )
        skill = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
        if not skill.strip():
            raise ValueError("research_skill_empty")
        skill += "\n\n" + mode_instructions(mode)
        from gateway.session_context import declare_stateless_channel

        declare_stateless_channel()  # delegate_task must join inline in this CLI process.
        agent = _create_agent(
            skill, model_class=model_class, max_iterations=args.max_iterations,
            max_seconds=args.max_seconds,
        )
        prompt = (
            f"Research run: {run_id}\nMode: {mode}\nQuestion: {question}\n"
            "The runner has already started this workspace. Call research_workspace "
            "with action=status and this run_id; do not start another workspace. "
            "On resume, read existing plan.json, report.md and notes first; address "
            "unresolved acquisition and analysis gaps instead of repeating discovery. "
            "Use the full Research skill supplied in the system context. Work through "
            "native research_workspace/research_source/research_note/research_finish "
            "tools; use available file, parsing and computation tools (terminal when enabled), and preserve full acquired text in the workspace. Delegate independent leaf work only, "
            "without recursive delegation. "
            "Make the methodology explicit: select relevant guides, record the question frame, knowledge map and justified methods; bind applicable foundations and constructs. Execute roadmap packets through workspace dispatch and complete_step, and record actual search/loop decisions. Save retrieved material and cite source IDs in a substantive report. "
            "Use research_finish with complete or partial according to the evidence. "
            "Do not publish or send the report externally."
        )
        turn = agent.run_conversation(prompt)
        code, summary = _result(run_id)
        if prior_result is not None and (
            result_file.stat().st_ino, result_file.stat().st_mtime_ns
        ) == prior_result:
            raise ValueError("research_result_not_updated")
        if type(turn) is not dict:
            raise ValueError("research_agent_result_invalid")
        incomplete_turn = (
            turn.get("completed") is not True
            or turn.get("partial") is True
            or turn.get("failed") is True
            or bool(turn.get("error"))
        )
        partial = code == 3 or incomplete_turn
        if partial:
            code = 3
            summary["status"] = "partial"
            summary["agent_turn_incomplete"] = incomplete_turn
        write_json(
            root_for(run_id) / "execution.json",
            _execution_summary(
                turn, partial=partial,
                selection=getattr(agent, "_research_model_selection", None),
            ),
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return code
    except Exception:  # noqa: BLE001 — credential-bearing runtime errors must not enter CLI output.
        print(json.dumps({"status": "error", "code": "research_run_failed", "run_id": run_id}), file=sys.stderr)
        return 2
    finally:
        if previous_run_id is None:
            os.environ.pop("HERMES_RESEARCH_RUN_ID", None)
        else:
            os.environ["HERMES_RESEARCH_RUN_ID"] = previous_run_id
        if agent is not None:
            agent.close()


if __name__ == "__main__":
    raise SystemExit(main())
