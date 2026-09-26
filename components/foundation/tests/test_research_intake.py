import hashlib
from contextlib import closing
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from hermes_foundation_bridge.artifacts import ArtifactService
from hermes_foundation_bridge.canonical import sha256_json
from hermes_foundation_bridge.dolt_state import DoltStateAdapter
from hermes_foundation_bridge.runtime import RuntimeCoordinator
from hermes_foundation_bridge.research_intake import ResearchIntake
from hermes_foundation_bridge.research_session import ResearchSession

class State:
    def __init__(self): self.objects={}
    def get(self,r):
        item=self.objects.get((r['database'],r['object_id']))
        return {'status':'found' if item else 'not_found','object':copy.deepcopy(item['object']) if item else None,
                'object_ref':{'revision':1,'schema_id':item['schema_id']} if item else None}
    def put(self,r):
        self.objects[r['database'],r['object_id']]=copy.deepcopy(r)
        return {'status':'committed','readback_verified':True}

class ResearchIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.artifacts=ArtifactService(self.root);self.artifacts.prepare(dry_run=False)
        self.runtime=RuntimeCoordinator(self.root);self.runtime.migration_receipt(apply=True)
        self.runtime.acquire_lease({'schema_version':1,'work_id':'TASK-1','holder_id':'worker','expected_revision':1,'ttl_seconds':600})
        self.work={'status':'active','project_id':'PROJECT-1','profile_id':'research','holder_id':'worker',
          'host_run_id':'RUN-1','bead_id':'TASK-1','lease_revision':1,
          'memory_scope':{'tenant_id':'TENANT-1','project_id':'PROJECT-1','profile_id':'research','work_kind':'research'}}
        self.state=State();self.seed()
        self.beads=SimpleNamespace(get=lambda _: {'issue':{'id':'TASK-1','status':'in_progress','assignee':'worker'}})
        self.memory=SimpleNamespace(context=lambda r:{'status':'assembled','scope':r['scope'],'context':'fixture memory','context_hash':'a'*64})
        self.graph=SimpleNamespace(search=lambda r:{'status':'queried','project_id':r['project_id'],'results':[]})

    def seed(self):
        self.state.put({'schema_version':1,'database':'kw_core','project_id':'PROJECT-1','object_id':'WORK-1',
          'object':self.work,'schema_id':'ResearchWorkContractV1','expected_revision':0,'content_hash':sha256_json(self.work),
          'operation_id':'OP-1','run_id':'RUN-1'})

    def session(self):
        return ResearchSession(self.state,self.runtime,self.beads,self.memory,self.graph,
          project_id='PROJECT-1',profile_id='research',host_run_id='RUN-1',work_contract_ref='WORK-1',holder_id='worker')

    def package(self,binding):
        # Exercise the actual producer rather than a parallel hand-written manifest.
        from hermes_research_report.research_workspace import workspace,source,note,finish
        from hermes_research_report.research_handoff import export_handoff
        cfg={'integration_mode':'foundation','workspace_root':str(self.root/'research')}
        with patch('hermes_research_report.research_workspace.integration_settings',return_value=cfg):
            run=workspace({'action':'start','question':'Test research','host_context':binding})
            saved=source({'run_id':run['run_id'],'url':'https://example.org','text':'Fixture source'})
            note({'run_id':run['run_id'],'text':'Fixture finding','source_ids':[saved['source_id']]})
            finish({'run_id':run['run_id'],'report':f"Finding [{saved['source_id']}].",'status':'complete'})
            packet=export_handoff({'run_id':run['run_id']})
        shutil.copytree(packet['root'],self.artifacts.quarantine/'packet')
        return packet['manifest_sha256']

    def test_real_producer_intake_maps_draft_and_retry_without_promotion(self):
        session=self.session();binding=session.prepare('fixture')['host_context'];digest=self.package(binding)
        service=ResearchIntake(self.artifacts,self.state,session.check)
        first=service.ingest('packet',digest);second=service.ingest('packet',digest)
        self.assertEqual(first['status'],'imported_draft');self.assertEqual(second['status'],'already_imported_draft')
        self.assertEqual(len(first['local_id_map']),2);self.assertFalse(first['delivery_authorized'])
        self.assertFalse(first['claim_status_changed'])

    def test_tampering_and_expired_lease_prevent_canonical_write(self):
        session=self.session();digest=self.package(session.prepare('fixture')['host_context'])
        service=ResearchIntake(self.artifacts,self.state,session.check)
        report=self.artifacts.quarantine/'packet/report.md';report.chmod(0o600);report.write_text('tampered')
        with self.assertRaises(ValueError):service.ingest('packet',digest)
        self.assertFalse(list(self.artifacts.originals.iterdir()))
        with closing(self.runtime._connect()) as c, c:c.execute("UPDATE leases SET expires_at='2000-01-01T00:00:00+00:00'")
        with self.assertRaises(ValueError):session.check()
        self.assertFalse(any(k[1].startswith('RHI-') for k in self.state.objects))

    def test_missing_memory_or_changed_work_cannot_produce_admission(self):
        self.memory.context=lambda r: {'status':'unavailable'}
        with self.assertRaises(ValueError):self.session().prepare('fixture')
        self.work['profile_id']='operator'
        with self.assertRaises(ValueError):self.session().prepare('fixture')

    def test_partial_artifact_failure_is_retryable(self):
        session=self.session();digest=self.package(session.prepare('fixture')['host_context'])
        service=ResearchIntake(self.artifacts,self.state,session.check)
        original=self.artifacts.ingest;count=0
        def interrupted(r):
            nonlocal count
            count+=1
            if count==2: raise OSError('fixture interruption')
            return original(r)
        with patch.object(self.artifacts,'ingest',side_effect=interrupted):
            with self.assertRaises(OSError):service.ingest('packet',digest)
        self.assertFalse(any(k[1].startswith('RHI-') for k in self.state.objects))
        self.assertEqual(service.ingest('packet',digest)['status'],'imported_draft')

    @unittest.skipUnless(shutil.which('dolt'),'requires local Dolt')
    def test_actual_dolt_commit_and_readback(self):
        self.state=DoltStateAdapter(self.root);self.state.migrate(apply=True);self.seed()
        session=self.session();digest=self.package(session.prepare('fixture')['host_context'])
        result=ResearchIntake(self.artifacts,self.state,session.check).ingest('packet',digest)
        self.assertEqual(result['canonical_write']['status'],'committed')
        read=self.state.get({'schema_version':1,'database':'kw_core','project_id':'PROJECT-1','object_id':result['object_id']})
        self.assertEqual(read['object']['status'],'imported_draft')
        self.assertFalse(read['object']['evidence_accepted'])
