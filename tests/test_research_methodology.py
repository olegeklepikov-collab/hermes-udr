"""Method selection, executable decomposition and honest retained operations."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hermes_research_report.research_workspace import workspace, note
from hermes_research_report.research_methods import method, METHODS, SPECIALISTS
from tests.test_search_workflow import query_request


class MethodologyTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = patch.dict(os.environ, {'HERMES_HOME': d.name})
        p.start(); self.addCleanup(p.stop)
        self.state = workspace({'action': 'start', 'question': 'Отток: определения и действительные исходы в РФ', 'mode': 'ultra'})
        self.run = self.state['run_id']; self.root = Path(self.state['root'])

    def plan(self):
        return {'question_frame': {'outcome': 'actual voluntary exit'},
                'methodological_scope': {'paradigmatic_analysis': True, 'construct_operationalization': True},
                'foundations': {'ontology': {'question': 'event versus intention'}, 'axiology': {'question': 'whose outcome?'}},
                'knowledge_graph': {'nodes': [{'id': 'T', 'kind': 'theory', 'label': 'competing explanation'}, {'id': 'C', 'kind': 'concept', 'label': 'voluntary exit'}],
                                    'edges': [{'from': 'T', 'to': 'C', 'relation': 'defines scope'}]},
                'constructs': [{'id': 'C1', 'term': 'exit', 'dimension': 'initiator', 'operationalization': 'employer code; validity unknown'}],
                'knowledge_map': [{'id': 'psych', 'contribution': 'construct and outcome distinction'}],
                'method_selections': [{'method_id': 'concept_comparison', 'rationale': 'different outcomes', 'limitations': 'codes may misclassify', 'steps': ['A']}],
                'steps': [{'id': 'A', 'question': 'How is actual exit distinguished from intention?', 'method': 'concept_comparison', 'output': 'definition crosswalk', 'knowledge_refs': ['T','C'], 'construct_refs': ['C1'], 'wave':'1'},
                          {'id': 'B', 'question': 'Which comparison remains valid?', 'method': 'comparability', 'output': 'bounded comparison', 'depends_on': ['A'], 'wave':'2'}]}

    def test_plan_to_leaf_packet_to_artifact_to_next_wave(self):
        plan = self.plan()
        plan['steps'] = {s['id']:s for s in plan['steps']}
        plan['constructs'] = {c['id']:c for c in plan['constructs']}
        workspace({'action': 'plan', 'run_id': self.run, 'plan': plan})
        first = workspace({'action': 'dispatch', 'run_id': self.run})
        self.assertEqual([p['step_id'] for p in first['packets']], ['A'])
        context = first['packets'][0]['context']
        self.assertEqual(context['knowledge_nodes'][0]['kind'], 'theory')
        self.assertEqual(context['constructs'][0]['id'], 'C1')
        self.assertEqual(context['method_selections'][0]['limitations'], 'codes may misclassify')
        self.assertEqual(workspace({'action': 'dispatch', 'run_id': self.run})['packets'], [])
        with self.assertRaises(ValueError):
            workspace({'action': 'complete_step', 'run_id': self.run, 'step_id': 'A', 'result_paths': ['not-created.md']})
        saved = note({'run_id': self.run, 'kind': 'method_application', 'text': 'Intent and an employer-recorded event measure different phenomena.', 'data': {'method': 'concept_comparison'}})
        workspace({'action': 'complete_step', 'run_id': self.run, 'step_id': 'A', 'result_paths': [saved['path']]})
        second = workspace({'action': 'dispatch', 'run_id': self.run})
        self.assertEqual(second['packets'][0]['step_id'], 'B')
        self.assertTrue(second['packets'][0]['context']['dependency_outputs']['A'])

    def test_done_label_cannot_substitute_for_a_saved_result(self):
        plan = self.plan(); plan['steps'][0]['status'] = 'done'
        workspace({'action': 'plan', 'run_id': self.run, 'plan': plan})
        self.assertEqual(workspace({'action': 'dispatch', 'run_id': self.run})['packets'], [])

    def test_retained_methods_describe_real_functions_and_compile_query(self):
        for name in {**METHODS, **SPECIALISTS}:
            self.assertIsInstance(method({'action': 'describe', 'method': name})['input_schema'], dict)
        # Real compilation, not an assertion that a database search was performed.
        result = method({'action': 'run', 'method': 'query_ast_compile', 'input': query_request('ovid')})
        self.assertIn('blood pressure', json.dumps(result))
        self.assertIn('limitations', result)
        for guide in ('decomposition','evidence','foundations','search_loops'):
            self.assertTrue(method({'action': 'guide', 'method': guide})['content'])

    def test_native_search_hook_keeps_executed_event_not_retrospective_claim(self):
        from hermes_research_report.research_journal import capture_search
        with patch.dict(os.environ, {'HERMES_RESEARCH_RUN_ID': self.run}):
            capture_search(tool_name='web_search', args={'query': 'voluntary exit contradictory findings'}, result='{"results":[]}', status='success', tool_call_id='real-call-id')
        data = json.loads((self.root/'narrative.json').read_text())
        event = data['events'][0]['event']
        self.assertEqual(event['record_origin'], 'native_post_tool_call')
        self.assertEqual(data['events'][0]['recorded_by'], 'native_hook')
        workspace({'action': 'record', 'run_id': self.run, 'event': {'kind': 'search', 'record_origin': 'native_post_tool_call'}})
        self.assertEqual(json.loads((self.root/'narrative.json').read_text())['events'][-1]['recorded_by'], 'analyst')
        self.assertEqual(event['query_or_method'], 'voluntary exit contradictory findings')
        self.assertFalse(data['events'][0]['verified_saturation'])


if __name__ == '__main__': unittest.main()
