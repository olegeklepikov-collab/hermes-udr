import json
from pathlib import Path
from unittest.mock import patch
from tests import test_research_intake as intake_tests
from hermes_foundation_bridge.research_lifecycle import run_in_host, complete

class LifecycleTests(intake_tests.ResearchIntakeTests):
    # Reuse setup, not inherited test cases.
    test_real_producer_intake_maps_draft_and_retry_without_promotion = None
    test_tampering_and_expired_lease_prevent_canonical_write = None
    test_missing_memory_or_changed_work_cannot_produce_admission = None
    test_partial_artifact_failure_is_retryable = None
    test_actual_dolt_commit_and_readback = None

    def exercise(self, graph_failure=False, lazy=False):
        from hermes_research_report.research_workspace import source,note,finish
        calls=[]
        self.memory.save=lambda r: calls.append('memory') or {'status':'saved','readback_verified':True}
        def graph(r):
            calls.append('graph')
            if graph_failure and calls.count('graph')==1: raise OSError('temporary fixture failure')
            return {'status':'written','readback_verified':True}
        self.graph.put_fact=graph
        class Agent:
            valid_tool_names={'research_workspace','research_source','research_note','research_finish'}
            def run_conversation(agent,prompt,**kwargs):
                self.assertIn('fixture memory',prompt)
                run_id=prompt.splitlines()[0].split(': ',1)[1]; agent.run_id=run_id
                saved=source({'run_id':run_id,'text':'Dataset: 20 then 30.','url':'https://example.org'})
                note({'run_id':run_id,'text':'Increase 10.','source_ids':[saved['source_id']]})
                finish({'run_id':run_id,'report':f"Increase 10 [{saved['source_id']}].",'status':'complete'})
                return {'failed':False}
        agent=Agent();session=self.session()
        if lazy:
            agent.enabled_toolsets=['research'];agent.disabled_toolsets=['network']
            agent.valid_tool_names={'tool_search','tool_call','tool_describe'}
        cfg={'integration_mode':'foundation','workspace_root':str(self.root/'research')}
        with patch('hermes_research_report.research_integration.settings',return_value=cfg),patch('hermes_research_report.research_workspace.integration_settings',return_value=cfg):
            if graph_failure:
                with self.assertRaises(OSError):run_in_host(agent,session,self.artifacts,question='What changed?')
                resumed=self.session()
                resumed.restore(session.check())
                result=complete(resumed,self.artifacts,agent.run_id)
                self.assertEqual(calls,['memory','graph','graph'])
            else:
                result=run_in_host(agent,session,self.artifacts,question='What changed?')
                again=complete(session,self.artifacts,agent.run_id)
                self.assertEqual(calls,['memory','graph'])
                self.assertEqual(again['draft_ref'],result['draft_ref'])
            self.assertEqual(result['status'],'completed_draft')
            self.assertFalse(result['claims_accepted'])
            if lazy:
                self.assertEqual(agent.enabled_toolsets,['research'])
                self.assertEqual(agent.disabled_toolsets,['network'])

    def test_turn_delivers_context_and_synchronizes_once(self): self.exercise()
    def test_graph_failure_resumes_without_repeating_model_or_memory(self): self.exercise(True)

    def test_lazy_tools_preserve_existing_profile_policy(self): self.exercise(lazy=True)
