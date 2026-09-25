"""Turn a substantive working roadmap into native Hermes leaf work packets."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path


def normalize_plan(plan):
    """Accept equivalent keyed collections and row lists without changing their meaning."""
    plan = dict(plan)
    for field in ("steps", "constructs", "knowledge_map", "method_selections", "streams", "initiatives", "waves"):
        value = plan.get(field)
        if isinstance(value, dict):
            plan[field] = [{"id": str(key), **row} for key, row in value.items() if isinstance(row, dict)]
            if len(plan[field]) != len(value):
                raise ValueError(f"{field} entries must be objects")
    for selection in plan.get("method_selections", []):
        if isinstance(selection, dict) and "step_ids" not in selection:
            links = selection.get("steps", selection.get("applied_to", []))
            if isinstance(links, list) and all(isinstance(x, str) for x in links):
                selection["step_ids"] = links
    graph = plan.get("knowledge_graph")
    if isinstance(graph, dict) and isinstance(graph.get("nodes"), dict):
        plan["knowledge_graph"] = {**graph, "nodes": [{"id": str(key), **row} for key,row in graph["nodes"].items() if isinstance(row, dict)]}
    return plan


def _has_outputs(step, root):
    paths = step.get("result_paths", [])
    if not isinstance(paths, list) or not paths:
        return False
    for name in paths:
        if not isinstance(name, str):
            return False
        p = (root / name).resolve()
        if not p.is_relative_to(root.resolve()) or not p.is_file() or not p.stat().st_size:
            return False
    return True


def inspect(plan, root=None):
    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        return [], ["steps must be a list of executable leaves"]
    counts = Counter(s.get("id") for s in steps if isinstance(s, dict) and isinstance(s.get("id"), str))
    by_id = {s["id"]: s for s in steps if isinstance(s, dict) and isinstance(s.get("id"), str) and counts[s["id"]] == 1}
    ready, issues = [], []
    required = list(plan.get("depth_profile", {}).get("planning_fields", ["question_frame", "knowledge_map", "method_selections"]))
    scope = plan.get("methodological_scope", {})
    if isinstance(scope, dict) and scope.get("paradigmatic_analysis") is True:
        required.extend(["foundations", "knowledge_graph"])
    if isinstance(scope, dict) and scope.get("construct_operationalization") is True:
        required.append("constructs")
    for key in required:
        if not plan.get(key):
            issues.append(f"Missing substantive planning component: {key}")
    if any(n > 1 for n in counts.values()):
        issues.append("Duplicate step IDs cannot be dispatched unambiguously")
    for step in steps:
        if not isinstance(step, dict) or step.get("id") not in by_id:
            issues.append("A step has no unique stable ID")
            continue
        if step.get("status", "pending") not in ("pending", "ready"):
            continue
        missing = [key for key in ("question", "method", "output") if not step.get(key)]
        deps = step.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(x, str) for x in deps):
            issues.append(f"{step['id']}: depends_on must list step IDs")
            continue
        if missing:
            issues.append(f"{step['id']}: supply " + ", ".join(missing))
            continue
        unknown = [d for d in deps if d not in by_id]
        if unknown:
            issues.append(f"{step['id']}: unknown dependencies " + ", ".join(unknown))
            continue
        if all(by_id[d].get("status") == "done" and (root is None or _has_outputs(by_id[d], root)) for d in deps):
            ready.append(step)
    return ready, issues


def dispatch(plan, root: Path, *, limit=3, wave=None):
    """Reserve a batch, not a cap on the number of tasks or sources in the run."""
    if type(limit) is not int or limit < 1:
        raise ValueError("Dispatch limit must be a positive batch size")
    ready, issues = inspect(plan, root)
    ready = [s for s in ready if wave is None or s.get("wave") == wave]
    packets = []
    for step in ready[:limit]:
        context = {k: step[k] for k in ("id", "question", "method", "inputs", "source_routes", "output",
                   "depends_on", "stream", "initiative", "wave", "phase", "stage", "completion_criterion") if k in step}
        selections = [m for m in plan.get("method_selections", []) if isinstance(m, dict) and
                      (step["id"] in (m.get("step_ids") or []) or m.get("method_id") == step.get("method"))]
        context["method_selections"] = selections
        axes = step.get("foundation_axes") or list(plan.get("foundations", {}))
        context["foundations"] = {k: v for k, v in plan.get("foundations", {}).items() if k in axes}
        refs = step.get("knowledge_refs") or [x for x in step.get("inputs", []) if isinstance(x, str)]
        graph = plan.get("knowledge_graph", {})
        context["knowledge_nodes"] = [n for n in graph.get("nodes", []) if isinstance(n, dict) and n.get("id") in refs]
        context["knowledge_relations"] = [e for e in graph.get("edges", []) if isinstance(e, dict) and e.get("from") in refs and e.get("to") in refs]
        construct_refs = step.get("construct_refs") or [x for x in step.get("inputs", []) if isinstance(x, str)]
        context["constructs"] = [c for c in plan.get("constructs", []) if isinstance(c, dict) and c.get("id") in construct_refs]
        guides = Path(__file__).resolve().parents[2] / "skills/research/references"
        context["method_guides"] = [str(guides / name) for name in ("decomposition.md", "evidence-methods.md", "knowledge-foundations.md", "search-narrative-loops.md")]
        context["plan_path"] = str(root / "plan.json")
        context["question_frame"] = plan.get("question_frame", {})
        context["knowledge_map"] = [entry for entry in plan.get("knowledge_map", []) if isinstance(entry, dict) and entry.get("id") in refs]
        context["workspace"] = str(root)
        context["run_id"] = root.name
        context["depth_profile"] = plan.get("depth_profile", {})
        context["dependency_outputs"] = {s["id"]: s.get("result_paths", []) for s in plan.get("steps", [])
                                         if isinstance(s, dict) and s.get("id") in step.get("depends_on", [])}
        # Only targeted context enters the child; full corpus and prior analyses stay on disk.
        goal = ("Execute this research work packet as a leaf agent; do not delegate. "
                "Read only the relevant method/profile sections in method_guides and resolve relevant construct/knowledge references from plan_path. Do not discard a definition just because it is absent from this compact packet. "
                "Search/read/analyse as the method requires; preserve original sources and source IDs. "
                "Save the requested substantive output in the workspace; report its path, findings and limitations. Record actual searches and loop decisions via research_workspace action=record. Separate source observations, interpretation, normative premises and proposed decisions. "
                "A saved negative search or access failure is a valid result, not evidence of absence. "
                "Do not change the parent roadmap or call research_finish for the whole run.\n" +
                json.dumps(context, ensure_ascii=False))
        packets.append({"step_id": step["id"], "goal": goal, "context": context})
        step["status"] = "dispatched"
    return {"packets": packets, "ready_remaining": max(0, len(ready) - len(packets)), "planning_issues": issues,
            "waiting": [{"step_id": s.get("id"), "status": s.get("status", "pending"), "depends_on": s.get("depends_on", [])} for s in plan.get("steps", []) if isinstance(s, dict) and s.get("status") != "done"] if not packets else [],
            "progress": Counter(s.get("status", "pending") for s in plan.get("steps", []) if isinstance(s, dict))}


def complete_step(plan, root: Path, step_id, paths, *, status="done"):
    if status not in ("done", "partial", "blocked"):
        raise ValueError("Step status must be done, partial or blocked")
    matches = [s for s in plan.get("steps", []) if isinstance(s, dict) and s.get("id") == step_id]
    if len(matches) != 1:
        raise ValueError("Unknown or ambiguous step_id")
    if not isinstance(paths, list) or not paths:
        raise ValueError("Save a substantive output or a documented failure before completing a step")
    outputs = []
    for name in paths:
        p = Path(name)
        if not p.is_absolute():
            p = root / p
        p = p.resolve()
        if not p.is_relative_to(root.resolve()) or not p.is_file() or not p.stat().st_size:
            raise ValueError("Step outputs must be nonempty files inside this workspace")
        outputs.append(p.relative_to(root.resolve()).as_posix())
    matches[0].update(status=status, result_paths=outputs)
    return {"step_id": step_id, "status": status, "result_paths": outputs,
            "checked": "artifact existence, not scientific validity"}
