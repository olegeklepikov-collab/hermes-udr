from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from types import ModuleType
from pathlib import Path
from unittest.mock import patch

from hermes_research_report.research_workspace import finish, source, workspace
from skills.research.scripts import run_research


def native_session_context_stub():
    """Only the Hermes context boundary is absent from portable unit tests."""
    gateway = ModuleType("gateway")
    gateway.__path__ = []
    context = ModuleType("gateway.session_context")
    context.declare_stateless_channel = lambda: None
    return patch.dict(sys.modules, {
        "gateway": gateway,
        "gateway.session_context": context,
    })


class FakeAgent:
    def __init__(self, *, finish_status: str | None, failed: bool = False):
        self.finish_status = finish_status
        self.failed = failed
        self.closed = False

    def run_conversation(self, prompt: str) -> dict:
        run_id = prompt.split("Research run: ", 1)[1].splitlines()[0]
        if self.finish_status is not None:
            row = source({
                "run_id": run_id, "url": "https://example.org/research",
                "title": "Controlled source", "text": "A retained source passage.",
                "extent": "excerpt",
            })
            finish({
                "run_id": run_id,
                "report": f"Controlled finding [{row['source_id']}].",
                "status": self.finish_status,
            })
        return {"completed": not self.failed, "failed": self.failed}

    def close(self) -> None:
        self.closed = True


class RunResearchTests(unittest.TestCase):
    def _case(self, status: str | None, *extra: str):
        with tempfile.TemporaryDirectory() as directory:
            agent = FakeAgent(finish_status=status)
            passed = []

            def create(skill, **kwargs):
                self.assertIn("Research", skill)
                passed.append(kwargs)
                return agent

            out, err = io.StringIO(), io.StringIO()
            with (
                patch.dict(os.environ, {"HERMES_HOME": directory, "HERMES_YOLO_MODE": "0"}),
                patch.object(run_research, "_available_tools"),
                patch.object(run_research, "_create_agent", side_effect=create),
                native_session_context_stub(),
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                code = run_research.main([
                    "--question", "What does F1 require?", "--mode", "deep",
                    "--model-class", "balanced", "--max-iterations", "17",
                    "--max-seconds", "120", *extra,
                ])
            self.assertTrue(agent.closed)
            self.assertEqual(passed[0]["model_class"], "balanced")
            self.assertEqual(passed[0]["max_iterations"], 17)
            self.assertEqual(passed[0]["max_seconds"], 120.0)
            return code, out.getvalue(), err.getvalue()

    def test_complete_native_turn_requires_saved_report_and_source(self):
        code, output, error = self._case("complete")
        self.assertEqual(code, 0, error)
        result = json.loads(output)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["source_records"], 1)
        self.assertEqual(result["cited_sources"], 1)
        self.assertEqual(result["semantic_verification"], "not_established_by_this_tool")

    def test_partial_report_has_distinct_exit_code(self):
        code, output, error = self._case("partial")
        self.assertEqual(code, 3, error)
        self.assertEqual(json.loads(output)["status"], "partial")

    def test_missing_result_fails_without_claiming_completion(self):
        code, output, error = self._case(None)
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertEqual(json.loads(error)["status"], "error")

    def test_resume_uses_existing_workspace_without_new_start(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"HERMES_HOME": directory, "HERMES_YOLO_MODE": "0"}):
                state = workspace({"action": "start", "question": "Resume question?", "mode": "ultra"})
                agent = FakeAgent(finish_status="partial")
                out = io.StringIO()
                with (
                    patch.object(run_research, "_available_tools"),
                    patch.object(run_research, "_create_agent", return_value=agent),
                    native_session_context_stub(),
                    contextlib.redirect_stdout(out),
                ):
                    code = run_research.main(["--resume-run", state["run_id"]])
                self.assertEqual(code, 3)
                self.assertEqual(json.loads(out.getvalue())["run_id"], state["run_id"])
                self.assertTrue(agent.closed)

    def test_incomplete_hermes_turn_is_partial_and_execution_has_aggregates_only(self):
        class IncompleteAgent(FakeAgent):
            def run_conversation(self, prompt: str) -> dict:
                super().run_conversation(prompt)
                return {
                    "completed": False, "partial": True, "failed": False,
                    "api_calls": 3,
                    "messages": [{"role": "assistant", "tool_calls": [
                        {"function": {"name": "delegate_task", "arguments": json.dumps({
                            "tasks": [{"goal": "PRIVATE-ONE"}, {"goal": "PRIVATE-TWO"}]
                        })}},
                        {"function": {"name": "research_source", "arguments": "PRIVATE-CONTENT"}},
                    ]}],
                }

        with tempfile.TemporaryDirectory() as directory:
            agent = IncompleteAgent(finish_status="complete")
            agent._research_model_selection = {
                "provider": "fixture-provider", "model": "fixture-model", "reasoning": "low",
                "requested_model_class": "balanced", "model_class_selection_source": "environment",
                "model_route_source": "research_model_class", "model_class_mapping_hash": "a" * 64,
            }
            out = io.StringIO()
            with (
                patch.dict(os.environ, {"HERMES_HOME": directory, "HERMES_YOLO_MODE": "1"}),
                patch.object(run_research, "_available_tools"),
                patch.object(run_research, "_create_agent", return_value=agent),
                native_session_context_stub(),
                contextlib.redirect_stdout(out),
            ):
                code = run_research.main(["--question", "Controlled question?"])
            self.assertEqual(code, 3)
            summary = json.loads(out.getvalue())
            self.assertEqual(summary["status"], "partial")
            self.assertTrue(summary["agent_turn_incomplete"])
            execution_text = (Path(summary["root"]) / "execution.json").read_text(encoding="utf-8")
            execution = json.loads(execution_text)
            self.assertEqual(execution["api_calls"], 3)
            self.assertEqual(execution["tool_call_counts"], {"delegate_task": 1, "research_source": 1})
            self.assertEqual(execution["delegate_task_batch_task_count"], 2)
            self.assertFalse(execution["completed"])
            self.assertTrue(execution["partial"])
            self.assertEqual(execution["requested_model_class"], "balanced")
            self.assertEqual(execution["model_class_mapping_hash"], "a" * 64)
            self.assertNotIn("PRIVATE-", execution_text)
            self.assertTrue(agent.closed)


if __name__ == "__main__":
    unittest.main()
