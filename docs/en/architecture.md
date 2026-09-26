# Architecture and evidence boundaries

[Home](../../README.md) · [Русский](../ru/architecture.md) · [Workflows](workflows.md)

Research 0.44.0b2 and Foundation 0.14.0b1 form the signed native beta. The [release manifest](../reference/release-manifest.json) identifies the exact components; [validation](../reference/validation.json) defines the tested scope. Software verification does not certify research conclusions or activate a production instance.

## One controller, two components

Hermes owns the existing session, model calls, enabled tools, native leaf delegation and user transport. Research registers nine focused tools: workspace, source, note, finish, original fetch, method guidance, connected web-provider access, period comparison and report construction. It keeps the working corpus and substantive plan in one run-local workspace. The local `corpus.sqlite` is a draft notebook, never the Foundation authority or a second controller.

Foundation owns tracked work, lease and writer checks, canonical objects, artifact originals, scoped memory and graph operations. Its 64 public tools and five hooks remain distinct from the **host-only** `ResearchSession`, `run_in_host`, `complete` and `ResearchIntake` APIs. A model cannot submit a package for canonical admission by calling a Foundation tool. Beads, Dolt, runtime SQLite and the artifact store retain separate authority boundaries; no distributed transaction or scientific acceptance is implied.

| Boundary | What it holds | What it does not establish |
|---|---|---|
| Research workspace | Question, plan revisions, `S-*` source records, `N-*` notes, original retrievals, step outputs and report | Canonical work ownership or truth of a cited claim |
| `ResearchHandoffV1` | Immutable, SHA-256-listed snapshot of registered results and their local identifiers | Submission, acceptance or delivery; unregistered raw retrievals are counted as omitted |
| Foundation artifact and Dolt stores | Verified imported bytes, draft mapping to canonical artifact IDs, versioned commit | Acceptance of evidence or claims |
| AgentMemory and Graphiti | Scoped context and a synchronized reference to an imported draft | Independent primary evidence |

## Planning and evidence

The plan records a question frame, a map of relevant knowledge and source families, method selections and executable atomic steps. Deep and Ultra can add constructs, relations, streams, initiatives and waves where useful. Each step names its question, method, output and dependencies. `research_workspace` dispatches ready packets with only relevant context; Hermes performs any actual leaf delegation. A leaf saves a nonempty output or documented failure before the parent marks that step complete. There is no universal source quota: depth and stopping conditions depend on the question and mode.

Collection records source identity, search and access outcomes, original bytes where available, reading extent and provenance. Analysis separates observation, interpretation, hypothesis and proposed action; compares independent source families and rival explanations; and records contradictions, negative searches and access gaps. A URL, quotation match, hash or model judgment alone does not establish semantic support. Reports retain limitations and unknown citations.

## Managed intake

`research.integration_mode=standalone` is the default. With `foundation`, the existing Hermes host creates a `ResearchSession` against an active `ResearchWorkContractV1`, a claimed Beads task and a live lease. `prepare` obtains scoped AgentMemory and Graphiti context and records a canonical admission. The resulting identifiers and receipt references are **references, not authority proof**; `check` re-reads host state. `run_in_host` sends the context through the existing Hermes agent and starts the Research run. The standalone command-line controller must not be used as a second managed controller.

Research's `handoff` action snapshots registered source, note, plan, journal, step and report files. Foundation `complete` stages that package, verifies paths, bytes, hashes, run binding and active admission, then imports it as `ResearchImportedDraftV1`. It subsequently synchronizes a draft reference to AgentMemory and Graphiti. `ResearchSession.restore` allows finalization from a saved canonical admission without repeating the model call. Retried completion reuses the first package and checks canonical state. Neither `research_finish` nor `complete` approves claims, authorizes delivery or certifies the research.

In Foundation mode, `research_fetch` saves the public original as `original.bin` and marks it `raw_acquired_requires_host_intake`; it does not parse untrusted content locally. An authorized host intake and parser profile must produce text and provenance references before `research_source` can register it. Python plugin code runs in the Hermes process. Configured tool access and native provider availability likewise do not grant Graphiti writes or outbound delivery; host policy remains decisive.
