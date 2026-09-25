# Hermes UDR research workflows

[Home](../../README.md) · [Русский](../ru/workflows.md) · [Architecture](architecture.md) · [Tool catalog](../reference/tools.md)

Hermes UDR 0.44 has five depth profiles. They prescribe different intellectual work; none certifies the finished result. The same question can legitimately yield a partial report when access, time, method or evidence is insufficient.

| Mode | Work expected | Stopping question |
|---|---|---|
| **Search** | Resolve names and ambiguity; locate and read the relevant original passage; check a material discrepancy. | Is the bounded lookup answered, or is the access/identity gap stated? |
| **Research** | Map disciplines, concepts and source families; collect across them; compare observations, proxies and assumptions; test a material alternative. | Are the substantive subquestions supported or their gaps explicit? |
| **Deep** | Examine constructs and their measures, mechanisms, competing explanations, methods, appendices and boundary conditions. A large corpus may be needed. | Are central explanatory uncertainties resolved or bounded? |
| **Ultra** | Add wide interdisciplinary coverage, interacting streams and adaptive waves; compare rival paradigms and challenge blind spots. | Do priority question-by-family/context cells and informational gain support the stated scope? |
| **Academic** | Choose the scientific question and study/review design; document protocol, eligibility, discovery, selection, full-text status, methods, bias and uncertainty. | Does the traceable protocol support the stated conclusion without claiming an opportunistic search was exhaustive? |

## One run, substantive work

1. **Start and frame.** `research_workspace(action="start")` creates a private run-local workspace with the question and chosen mode. In managed Foundation mode, only the existing host starts it through `run_in_host`, supplying a host-issued context after live work, lease, memory and graph checks.
2. **Plan.** Save a question frame, knowledge map, source-family map, method selections and atomic steps with stable IDs, inputs, outputs and dependencies. Use constructs, relations, streams, initiatives, phases or waves only where they clarify the work. This is a revisionable roadmap, not a fixed gate chain or a source-count limit.
3. **Find and read.** Use Hermes tools that are actually enabled in the session. `research_web_provider` exposes only the registered provider's search/extract interface; dedicated plugin or MCP operations have their own schemas. Inventory is not proof that a service worked. Record positive and negative searches, source identity, original-reading extent and access failures. `research_fetch` stores original public bytes; in Foundation mode it waits for approved host parsing before a text source can be registered.
4. **Delegate atomic leaves when useful.** `research_workspace(action="dispatch")` returns dependency-ready packets with relevant methods, knowledge references and expected outputs. Hermes performs the actual native leaf delegation under its enabled/disabled tool policy. Each leaf writes a substantive result or documented failure into the same run workspace. `complete_step` checks saved output presence, not scientific validity; the parent synthesizes the returned work.
5. **Analyse and report.** `research_source` records text with an honest extent and stable `S-*` citation ID; `research_note` links analysis to source IDs. Distinguish direct observation, proxy, inference, hypothesis and proposed decision. Compare independent sources, rival explanations, selection effects and relevant uncertainty. `research_finish` saves a cited report, marks unknown citations visibly and never sends it externally.

Method guides under `skills/research/references/` describe decomposition, knowledge foundations, qualified collection and search/reading loops. They guide judgment; they are not approvals to skip source reading, invent measurements or turn a regulatory requirement into evidence of effectiveness. A saved failure or negative search narrows a claim; it is not proof that a phenomenon is absent.

## Managed handoff and recovery

`research_workspace(action="handoff")` produces an immutable `ResearchHandoffV1` snapshot with hashes for registered records, step results and the report. The package is an **unsubmitted draft**. Foundation's host-only `complete(session, artifacts, run_id)` verifies it against the live admission and imports a `ResearchImportedDraftV1` object and artifacts, then stores a draft reference in AgentMemory and Graphiti. `ResearchSession.restore(binding)` plus `complete` can resume this finalization without repeating the model call. The host must separately decide evidence acceptance, release and delivery.

A report marked `complete` means the local run has a saved report and structural citation check; it does not prove semantic support, source independence or academic validity. This working copy precedes signing; the [release manifest](../reference/release-manifest.json) defines the published status. The available integration tests do not qualify all corporate or academic uses.
