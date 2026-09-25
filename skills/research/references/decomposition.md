# Decomposition as executed research work

Use this procedure for a substantive Deep, Ultra or Academic inquiry. Its purpose is to make the investigation discriminating and executable, not to produce a large outline. Reconnaissance is allowed while planning. A six-level heading tree without research operations is not a decomposition.

## 1. Frame the question before selecting instruments

Separate the user's question, intended use, decision if any, object, unit of analysis, population, geography/jurisdiction, period, and outcome. List competing definitions of consequential terms. Distinguish the target construct from its indicator: observed employee exit, intention to leave, employer-coded voluntary resignation and job-to-job transition are different outcomes. Identify assumptions, exclusions, access constraints and the cost of getting a central conclusion wrong. Unknowns become tasks, not invented defaults.

Write `question_frame` in the working plan. For each consequential construct record its definition, observable indicator, unit, acquisition method, proxy relationship, validity limitations, confounders and prohibited inference. Reuse `construct_operationalize` through the method tool when a structured construct assessment is useful; its output evaluates supplied information and does not discover validity evidence.

## 2. Build a knowledge and expertise nomenclature

Create `knowledge_map` entries with stable IDs and these fields:

- domain/subdomain and the question it can help answer;
- why core, adjacent or cross-disciplinary expertise is needed;
- mechanisms, competing schools and boundary conditions to investigate;
- relevant methods, standards/frameworks and evidence that establishes their applicability;
- source families and likely biases or access limitations;
- contribution expected from this perspective, and what it cannot establish.

Include practitioner and implementation knowledge where relevant, not just academic labels. Add external disciplines when they expose a missing mechanism or assumption, not merely to make the map look diverse. Industry frameworks need a version, jurisdiction/scope and a source; an unverified framework remains a candidate. The method catalogue below is a starting vocabulary, not an exhaustive ontology or a mandatory checklist.

## 3. Select and sequence methods, rather than list their names

For every selected method, save a `method_selections` entry: method_id/name, target question, reason for use, inputs, limitations, expected output and the step IDs where it is applied. Methods from different groups may be combined; do not apply every method in sequence. An evidence-informed causal diagram can precede targeted search; an uncertainty analysis follows model construction. Record why a major plausible alternative is not needed when that choice affects the conclusion.

| Question needing decomposition | Candidate methods | Concrete output and important limitation |
|---|---|---|
| Causes, failure paths, constraints | Root-cause analysis, 5 Whys, Ishikawa, Kepner–Tregoe, fault/event trees, bowtie, FMEA, risk breakdown, theory of constraints, Pareto | Competing causal paths, failure modes, bottlenecks and discriminating evidence. These methods generate hypotheses; repeated “why” is not causal identification, and FMEA scores are not calibrated probabilities. |
| Processes and interfaces | SIPOC, value-stream mapping, service blueprint, data-flow/swimlane diagrams, AS-IS/TO-BE, BPMN, IDEF0/IDEF3 | Activities, inputs, outputs, actors, hand-offs, waits, controls and failure points. A process drawing describes the proposed model; actual operations require observation. |
| Tasks, cognition, behaviour | Cognitive task analysis, hierarchical task analysis, COM-B, story mapping | Goals, subtasks, decisions, capabilities, opportunities and motivation hypotheses. Do not infer a person's motives from observed behaviour alone. |
| Systems and requirements | Use cases, Use Case 2.0, event storming, domain-driven design, functional flow, requirements/system breakdown, entity–relationship modelling, UML, dependency structure matrix, Problem Frames | Boundaries, interfaces, responsibilities, dependencies and tests of requirements. A software decomposition does not by itself explain a social or market system. |
| Concepts and competing problem frames | Concept/mind maps, problem trees, CATWOE, logical framework, logic model, soft-systems methodology, systems thinking, MECE, abstraction laddering, morphological analysis, functional decomposition, first principles, divide-and-conquer, causal layered analysis, goal structuring | Definitions, levels, stakeholder/worldview differences, construct relations and alternative models. Explain real overlaps; do not force mutually exclusive categories onto interacting causes. |
| Options and innovation | TRIZ/ARIZ/9 Windows, FAST, A3, value-focused thinking, impact mapping, opportunity-solution trees, Lotus Blossom, concept fans, feature/function-means trees | Options tied to needs and mechanisms, contradictions, constraints and tests. A generated option is not evidence of feasibility or benefit. |
| Goals, metrics and decision logic | Goal–Question–Metric, Minto structure, separation of concerns | Trace from desired outcome to questions, measurements and decision criteria. Presentation logic is not validation; distinguish a measure from its target construct. |
| End-to-end redesign | Business process reengineering, Six Sigma DMAIC, soft-systems methodology, TRIZ | An appropriate sequence of diagnosis, measurement, explanation, alternatives and testing. Use the relevant portions; do not install a transformation programme for a research question. |

Pareto and MECE are attention/organisation heuristics, not source-exclusion rules. Add domain methods such as study-design appraisal, causal identification, sensitivity analysis, scenario comparison, case comparison, longitudinal analysis or a relevant domain standard when they answer a question the generic catalogue cannot.

## 4. Construct a roadmap whose leaves can actually execute

Use stable identifiers. Distinguish the levels by meaning:

- **Stream**: a coherent topic, perspective or evidence family, with an owner and a synthesis contribution.
- **Initiative**: an explanatory/comparative objective within or across streams.
- **Wave**: a dispatch/integration batch; its findings can change later work.
- **Phase**: discovery, materialisation, analysis, challenge or synthesis.
- **Stage**: a specific operation within a phase, such as terminology expansion, primary-source acquisition, construct comparison, or rival testing.
- **Step**: one executable question/action with specified inputs, method, evidence route, output and completion criterion.

Represent the actual executable leaves in `steps`. Each leaf has `id`, `question`, `method`, `inputs`, `source_routes`, `output`, `depends_on`, `stream`, `initiative`, `wave`, `phase`, `stage` and `status`. Use prose or lists where they carry the real research content. Avoid placeholder text such as “research the topic” or “analyse sources.” Child steps should resolve distinct uncertainties, not repeat the parent question.

A step is sufficiently atomic when a worker can execute it independently with the supplied context, its output can be inspected, and its unresolved issue can be assigned without reopening the entire investigation. Split a step when it mixes incompatible units, methods, populations, source routes, dependencies or outputs. Conversely, do not divide every search click into its own task. Cross-stream interactions and shared evidence receive a named owner to avoid duplicate work.

For a narrow Search, collapse unnecessary management levels. For Deep/Ultra, retain the explanatory links across the levels rather than a flat list of queries. There is no maximum number of leaves or source slots derived from the mode name.

## 5. Execute and revise

Save the plan with `research_workspace(action="plan")`, then obtain executable leaf work through `action="dispatch"`. It returns ready work packets and actual missing inputs/dependencies. Pass the returned goals and compact context to native `delegate_task`; use leaf agents only. After a packet completes, record its output with `action="complete_step"`. A completed label without an accessible output is not evidence of execution.

The controller integrates the wave: compare definitions and findings, reconcile shared-source dependencies, expose contradictions, and add or revise tasks that distinguish competing explanations. Preserve methods and dependencies during status updates. Do not silently reduce the question to what happened to be easy to retrieve. Capture search failures and unresolved assumptions as results that guide later work.

Before synthesis, check that the central questions have addressed evidence routes, useful outputs and challenge work. Do not equate every step being marked done with truth or completeness of the field. Unexecuted steps and unanswered questions belong in the report's explicit limitations.

## 6. Worked decomposition fragment

Question: “Which organisational changes reduce actual voluntary employee turnover?”

- Frame: actual employer-coded voluntary exit, not intention; keep population, observation window and jurisdiction explicit.
- Knowledge map: organisational psychology (constructs and mechanisms), labour economics (outside options and selection), operations (scheduling/workload), causal inference (identification), measurement (outcome coding), implementation/practitioner evidence (feasibility and side effects).
- Initiative: distinguish changes to job desirability from changes to external opportunities.
- Wave 1 / discovery / terminology: map actual-turnover and intention-to-quit definitions in primary methods; output an outcome/definition crosswalk.
- Wave 1 / discovery / family search: query primary intervention studies, official labour statistics and practitioner implementation evidence separately; output the queries, candidates, negative routes and limitations.
- Wave 2 / analysis / comparability: extract population, assignment/identification, intervention, comparator, outcome, window, attrition and effect uncertainty; output a comparison table with primary locators.
- Wave 2 / challenge / rival test: test whether a reported retention gain can be explained by selection, labour-market conditions or outcome recoding; output rivals and evidence that would distinguish them.
- Wave 3 / synthesis / decision framing: compare warranted options, assumptions, side effects and transfer limits; output a reasoned conclusion or a justified non-recommendation.

These are examples of work structure, not pre-filled findings.

## Provenance and adaptation

Adapted from the user's Dropbox `/Диагностические системы/Диагностические руководства/Руководства Fin MD/промпт_декомпозиция.docx` and `/База для агентов/Исследования/udr-atomic-methodology/`. The first supplies a method-selection/decomposition vocabulary; the second connects questions, sources, observations, claims, alternatives and decisions. These are internal methodological guides, not empirical qualification certificates. The draft's per-document human approval and recursive/meta-orchestration are not adopted: current user instructions require economical autonomous execution without recursive agent trees.

## Open extensions and orthogonal decomposition axes

The catalogue is open. Select complementary axes before selecting branded methods; a new domain technique is admissible when its provenance, question, prerequisites, procedure, expected output and limitations are explicit. A method absent from the Python helper catalogue can still be executed by the agent with the appropriate connected tools; do not misrepresent an instruction as an implemented numerical routine.

| Axis | Questions and operations | Typical output / limit |
|---|---|---|
| Spatial and scale | Local/site/organisation/network/region/global; compare aggregation and cross-level interactions | Scale map; avoid ecological and atomistic inference errors. |
| Temporal and historical | Events, sequences, lags, cohorts, lifecycle, path dependence, regime changes | Timeline and temporal causal alternatives; contemporaneous movement alone does not establish cause. |
| Actors and institutions | Stakeholders, authority, incentives, resources, power, rules, coordination | Actor–relationship map; reported interests are not necessarily observed motives. |
| Relational and network | Dependencies, flows, feedback, concentration, diffusion, contagion | Network/interaction model; identify missing ties and boundary effects. |
| Causal and counterfactual | Mechanisms, confounding, mediation, selection, competing explanations, interventions | Causal alternatives and discriminators; distinguish model assumptions from identification evidence. |
| Measurement and data generation | Sampling, coding, denominators, measurement invariance, missingness, lineage | Construct-to-data map and comparability conditions; more precise numbers need not be more valid. |
| Variation and distribution | Subgroups, heterogeneity, tails, exceptional cases, inequalities, contexts | Distributional comparison; do not let averages erase contrary subgroup findings. |
| Decisions and economics | Alternatives, opportunity costs, reversibility, dependencies, sensitivity, thresholds | Conditional option comparison; separate observed inputs, assumptions and forecasts. |
| Design and implementation | Requirements, interfaces, feasibility, adoption, operating conditions, unintended effects | Implementation hypotheses and tests; feasibility is not demonstrated effectiveness. |
| Normative and institutional validity | Rights, obligations, values, legitimacy, jurisdiction, affected parties | Explicit normative premises and conflicts; desirability is distinct from empirical performance. |
| Interpretive and linguistic | Definitions, categories, narratives, translations, positions, contextual meanings | Competing interpretations with textual support; translation equivalence is not automatic. |
| Epistemic and methodological | Evidence production, disciplinary traditions, rival paradigms, inference rules | An explicit account of which kinds of answer each approach can support. |
| Uncertainty and robustness | Unknowns, structural/model uncertainty, scenarios, sensitivity, adversarial cases | Conditions under which a conclusion changes; no invented numerical confidence. |
| Synthesis and transfer | Convergence/divergence across settings, mechanism transport, boundary conditions | A bounded integrated explanation, with irreducible disagreements retained. |

Use these axes across science, business, engineering, policy, history, humanities and mixed inquiries. The relevant domain may require other axes. Record additions in the knowledge map and link them to actual tasks rather than extending an obligatory checklist.

## Depth is selected by research mode

The runtime supplies the authoritative `depth_profile` for `search`, `research`, `deep`, `ultra` or `academic`; workers inherit it in their work packets. Search resolves a bounded lookup; Research provides structured multi-source preliminary analysis; Deep examines mechanisms and constructs; Ultra combines depth with wide cross-disciplinary coverage and competing frames; Academic follows the chosen scientific question/protocol. Academic is not simply “more nodes than Ultra.” None of these profiles sets a fixed source quota. The unit of decomposition is an independently investigable uncertainty, not a heading count.
