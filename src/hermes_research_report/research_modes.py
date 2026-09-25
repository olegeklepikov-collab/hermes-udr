"""Mode-specific depth, independent of corpus size and provider choice."""
from __future__ import annotations
from copy import deepcopy
import json

PROFILES = {
    'search': {
        'purpose': 'Locate and verify a bounded fact, document or source set.',
        'decomposition': 'Resolve terms, entity, period and ambiguity; split only genuinely different lookup questions. No ceremonial hierarchy.',
        'planning_fields': ['question_frame'],
        'analysis': 'Read the relevant original passage; distinguish what it states from interpretation and uncertainty.',
        'challenge': 'Check identity, currency and an important discrepancy when present.',
        'stop': 'The requested lookup is answered or its access/ambiguity gap is explicit.',
    },
    'research': {
        'purpose': 'Answer a substantive question through organised multi-source collection and preliminary analysis.',
        'decomposition': 'Frame the question; identify relevant disciplines, concepts, source families and subquestions; choose methods and executable steps.',
        'planning_fields': ['question_frame', 'knowledge_map', 'method_selections', 'steps'],
        'analysis': 'Compare sources, definitions and observations; separate direct evidence, proxies, assumptions and practical implications.',
        'challenge': 'Cross-check central factual claims and examine a material alternative or contradiction.',
        'stop': 'Subquestions have useful supported answers or clearly bounded gaps; report the actual stop reason.',
    },
    'deep': {
        'purpose': 'Explain mechanisms, competing explanations and boundary conditions with depth appropriate to the question.',
        'decomposition': 'Organise streams and atomic dependency-linked work. Decompose consequential concepts into facets, attributes, dimensions and operationalisations. Examine adjacent disciplines and causal/system relations.',
        'planning_fields': ['question_frame', 'knowledge_map', 'method_selections', 'constructs', 'streams', 'steps'],
        'analysis': 'Read central full materials, methods and relevant appendices; compare designs, measurements, contexts and causal assumptions. Deep may require hundreds of sources.',
        'challenge': 'Seek contrary evidence; test rival explanations, source dependence, measurement validity and transferability.',
        'stop': 'The central explanatory uncertainties are resolved or specifically bounded; corpus size alone is not a stopping criterion.',
    },
    'ultra': {
        'purpose': 'Combine deep examination with wide interdisciplinary coverage and explicit treatment of competing frames.',
        'decomposition': 'Use streams, initiatives, adaptive waves, phases, stages and atomic steps with distinct meanings. Build a knowledge/relations map spanning core, adjacent and external expertise; examine applicable paradigmatic foundations, rival schools/models and operationalisations. Do not invent empty levels.',
        'planning_fields': ['question_frame', 'knowledge_map', 'method_selections', 'constructs', 'knowledge_graph', 'streams', 'initiatives', 'waves', 'steps'],
        'analysis': 'Explore interactions across streams, geography, languages, periods and evidence families; inspect originals deeply; synthesize tensions across explanatory and normative frames.',
        'challenge': 'Run targeted adversarial and sensitivity work, inspect blind spots and missing families, and revisit the question architecture when findings warrant it.',
        'stop': 'Coverage of priority question-by-family/context cells and diminishing informational gain support the declared scope, or explicit constraints leave a partial result. Never infer saturation from a source quota.',
    },
    'academic': {
        'purpose': 'Conduct a scientifically disciplined inquiry matched to its review/study type; not necessarily a clinical systematic review.',
        'decomposition': 'Define the scientific question, constructs, theory/model relations and appropriate epistemic assumptions; select protocol, study designs, terminology, eligibility and extraction structure before substantive synthesis.',
        'planning_fields': ['question_frame', 'knowledge_map', 'method_selections', 'constructs', 'academic_protocol', 'steps'],
        'analysis': 'Trace discovery and selection, pending full text, study/publication identities, methods, outcomes, quality/bias, comparability, uncertainty and transfer. Use qualitative or quantitative analysis as justified; pooling is not automatic.',
        'challenge': 'Check alternative interpretations, citation context, reproducibility of relevant computations and sensitivity to design/selection assumptions.',
        'stop': 'The declared scientific question and protocol are addressed with traceable limitations; do not relabel an opportunistic search as exhaustive.',
    },
}
ALIASES = {'deep_research': 'deep', 'deep research': 'deep', 'ultra_deep_research': 'ultra', 'ultra deep research': 'ultra'}
MODES = tuple(PROFILES)


def normalize_mode(value):
    if not isinstance(value, str):
        raise ValueError('Research mode must be a string')
    mode = ALIASES.get(value.strip().lower(), value.strip().lower())
    if mode not in PROFILES:
        raise ValueError('Choose search, research, deep, ultra or academic')
    return mode


def profile(value):
    mode = normalize_mode(value)
    return {'mode': mode, **deepcopy(PROFILES[mode]), 'fixed_source_cap': None,
            'fixed_model_call_cap': None, 'fixed_cash_budget': None,
            'qualification': 'Depth prescription, not a scientific-validity certificate.'}


def instructions(value):
    return ('Apply this research depth profile to planning, work packets, source reading and synthesis. '
            'A mode changes the intellectual work, not just the report label. '
            'Explain in the plan when a listed dimension is inapplicable; do not fill it with invented content.\n'
            + json.dumps(profile(value), ensure_ascii=False))
