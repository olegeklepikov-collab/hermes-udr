# Hermes UDR

**Wide and deep research inside Hermes — from a decomposed question to a retained source corpus and a cited analytical report.**

[Русский](README.ru.md) · [Current release](https://github.com/olegeklepikov-collab/hermes-udr/releases/tag/v0.44.0-beta.1) · [Installation](docs/en/installation.md) · [Architecture](docs/en/architecture.md) · [Research workflows](docs/en/workflows.md)

## Current system

| Component | Version | Responsibility |
|---|---|---|
| Ultra Deep Research | **0.44.0b1** | Research planning, acquisition, source storage, preliminary analysis and reporting |
| Foundation Bridge | **0.13.0b1** | Host admission, artifact intake, canonical state, memory/graph lifecycle and recoverable finalization |

This **signed operational beta** is the first release in the Hermes UDR repository and succeeds the previous Ultra Deep Research r153/v22 line. It replaces the old contract-heavy execution route with nine core research tools and native Hermes execution. Historical tags remain in the [predecessor repository](https://github.com/olegeklepikov-collab/ultra-deep-research). Integration is tested; universal scientific quality and production activation are not claimed.

## What it does

- Offers **Search, Research, Deep, Ultra and Academic** depth profiles. Broad questions can use large source corpora; profiles do not impose the former 16/32-source ceilings.
- Builds a question-specific knowledge map: disciplinary and cross-disciplinary perspectives, paradigmatic assumptions, concepts, dimensions, operational definitions, methods and relevant standards. Depth follows the question and mode; every inquiry does not require every methodological layer.
- Turns decomposition into an executable roadmap with dependencies, atomic work packets, retained outputs and explicit gaps. Native Hermes delegation supplies leaf workers; the plugin does not create a recursive agent controller.
- Retains full provider responses and acquired material on disk, alongside source-linked notes, competing explanations, search decisions and the final report. Search results, abstracts, full texts and accepted evidence remain distinct.
- Discovers enabled Hermes tools, plugins, MCP connections and registered web providers. Service-specific operations remain available through their connected tools rather than being reduced to a single generic search interface.
- Requests an operator-defined **model class** in standalone execution. A Foundation-managed run uses the model and permissions of its existing Hermes agent. No particular model vendor or model ID is mandatory.
- Hands an immutable-by-convention draft snapshot to Foundation, which rechecks hashes, records artifacts and canonical mappings, and synchronizes the draft reference to AgentMemory and Graphiti. Finalization can resume without repeating the research.

Exa, Firecrawl, Tavily, Parallel, Keenable, Nimble, Scite, Consensus, Undermind, Scholar Gateway, OpenAlex, PubMed and future services are potential integrations through Hermes. **This is an open connection mechanism, not a claim that every vendor, API operation or subscription has been tested.** Tools and modes must actually be exposed by the installed connector and allowed by the selected profile.

## Start here

1. [Install the exact pair or standalone Research](docs/en/installation.md).
2. [Configure replaceable model classes](docs/en/model-classes.md).
3. [Choose a research depth and execute the roadmap](docs/en/workflows.md).
4. [Integrate Foundation with an existing host session](docs/reference/foundation.md).
5. [Review validation, migration, recovery and release boundaries](docs/en/release-and-operations.md).

[Tool reference](docs/reference/tools.md) · [Release manifest](docs/reference/release-manifest.json) · [Contributing and tests](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## Repository layout

```text
plugin.py, plugin.yaml       Research plugin entry and manifest
src/hermes_research_report/  Research implementation and optional methods
skills/research/            Skill, native runner and methodological guides
components/foundation/       Paired Foundation plugin and host integration APIs
docs/en/, docs/ru/           English and Russian documentation
docs/reference/             Tool map, host contract and exact release metadata
tests/, scripts/            Focused checks and Research packaging tools
```

Keep the complete plugin layouts, including skills/scripts. An isolated Python module or a generic wheel is not a substitute for the plugin bundle.

## Evidence and limits

The integration was exercised with actual Hermes/Codex OAuth, Beads, Dolt CLI, AgentMemory and Graphiti on a dedicated macOS/Linux arm64 stand. The final Foundation package passed 34 focused tests and native Plugin Doctor. A Linux-discovered Dolt JSON corruption was repaired and finalization resumed from verified state without another model call. Synthetic inputs validate the route, **not research completeness or all depth profiles**.

Checksums verify bytes; an unsigned checksum is not publisher authentication. A local `complete` report or canonical `imported_draft` does not establish claim truth, publication permission or delivery authorization. No credentials, personal research corpora, databases or operational snapshots are distributed.

Apache-2.0. Dependencies retain their own licenses.
