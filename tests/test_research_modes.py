import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from hermes_research_report.research_modes import MODES, profile, normalize_mode, instructions
from hermes_research_report.research_workspace import workspace

class ModeTests(unittest.TestCase):
    def test_five_distinct_depths_without_source_or_model_caps(self):
        self.assertEqual(MODES, ('search','research','deep','ultra','academic'))
        self.assertEqual(normalize_mode('deep research'), 'deep')
        self.assertEqual(normalize_mode('ultra_deep_research'), 'ultra')
        for mode in MODES:
            p = profile(mode)
            self.assertIsNone(p['fixed_source_cap'])
            self.assertIsNone(p['fixed_model_call_cap'])
            self.assertIn(p['purpose'], instructions(mode))
        self.assertNotIn('constructs',profile('research')['planning_fields'])
        self.assertIn('constructs',profile('deep')['planning_fields'])
        self.assertIn('knowledge_graph',profile('ultra')['planning_fields'])
        self.assertIn('academic_protocol',profile('academic')['planning_fields'])

    def test_mode_reaches_saved_plan_and_dispatched_worker(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'HERMES_HOME': d}):
            run = workspace({'action':'start','question':'An ordinary research question','mode':'research'})
            state = workspace({'action':'plan','run_id':run['run_id'],'plan':{'mode':'ultra','steps':[{'id':'A','question':'What differs?','method':'comparison','output':'comparison.md'}]}})
            self.assertEqual(state['depth_profile']['mode'], 'research')
            dispatched = workspace({'action':'dispatch','run_id':run['run_id']})
            self.assertEqual(dispatched['packets'][0]['context']['depth_profile']['mode'],'research')
            self.assertIn('preliminary analysis',dispatched['packets'][0]['goal'])
            resumed = workspace({'action':'status','run_id':run['run_id']})
            self.assertEqual(resumed['depth_profile']['mode'],'research')

    def test_context_local_hermes_home_has_priority_over_environment(self):
        import sys
        from types import SimpleNamespace
        from hermes_research_report.research_workspace import root_for
        with tempfile.TemporaryDirectory() as d:
            selected = Path(d) / 'selected-profile'
            with patch('hermes_research_report.research_workspace.integration_settings', return_value={'workspace_root': None}), patch.dict(os.environ, {'HERMES_HOME': str(Path(d)/'ambient-profile')}), patch.dict(sys.modules, {'hermes_constants': SimpleNamespace(get_hermes_home=lambda: selected)}):
                self.assertEqual(root_for('example'), selected/'research-runs'/'example')

if __name__=='__main__':unittest.main()
