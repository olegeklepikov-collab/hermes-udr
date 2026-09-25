import asyncio
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

from hermes_research_report.research_integration import HOST_REQUIRED, host_context, settings
from hermes_research_report.research_workspace import workspace, source, note, finish
from hermes_research_report.research_handoff import export_handoff
from hermes_research_report.research_fetch import fetch
from hermes_research_report.research_capabilities import web_provider

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {'integration_mode': 'foundation', 'workspace_root': self.tmp.name, 'web_provider_allowlist': {}}
        self.binding = {key: 'fixture-'+key for key in HOST_REQUIRED}
        self.scope = patch('hermes_research_report.research_workspace.integration_settings', return_value=self.cfg)
        self.scope.start(); self.addCleanup(self.scope.stop)

    def start(self):
        return workspace({'action':'start', 'question':'Integration fixture', 'host_context':self.binding})

    def test_binding_draft_handoff_is_not_canonical_acceptance(self):
        with self.assertRaises(ValueError):
            workspace({'action':'start','question':'No admission references'})
        run = self.start(); rid = run['run_id']
        saved = source({'run_id':rid, 'text':'Approved parser fixture text', 'url':'https://example.org',
                        'origin_ref':'ART-fixture','parse_receipt_ref':'PARSE-fixture'})
        note({'run_id':rid,'text':'A fixture observation','source_ids':[saved['source_id']]})
        finish({'run_id':rid,'report':f"Observation [{saved['source_id']}].",'status':'complete'})
        package = export_handoff({'run_id':rid})
        manifest = json.loads((Path(package['root'])/'manifest.json').read_text())
        self.assertEqual(manifest['host_context'], self.binding)
        self.assertEqual(manifest['submission_status'], 'unsubmitted')
        self.assertFalse(manifest['production_qualified'])
        self.assertTrue(any(p['path'].endswith('.provenance.json') for p in manifest['files']))
        with self.assertRaises(ValueError): host_context({'credential':'secret'}, required=True)

    def test_raw_fetch_never_invokes_local_parser_in_foundation(self):
        run=self.start()
        with patch('hermes_research_report.research_fetch.integration_settings', return_value=self.cfg), \
             patch('hermes_research_report.research_fetch._safe_url', side_effect=lambda x:x), \
             patch('hermes_research_report.research_fetch._fetch_one', return_value=(200,{'content-type':'application/pdf'},b'%PDF-fixture','93.184.216.34',True)), \
             patch('hermes_research_report.research_fetch._text') as parse:
            result=fetch({'run_id':run['run_id'],'url':'https://example.org/paper.pdf'})
        parse.assert_not_called()
        self.assertEqual(Path(result['original_path']).read_bytes(), b'%PDF-fixture')
        self.assertEqual(result['status'], 'raw_acquired_requires_host_intake')

    def test_provider_requires_explicit_operation_permission(self):
        rid=self.start()['run_id']
        provider=SimpleNamespace(name='future-service', supports_extract=lambda:True,
          is_available=lambda:True,is_keyless_available=lambda:False,extract=AsyncMock(return_value={'text':'fixture'}))
        runtime=SimpleNamespace(discover_plugins=lambda:None,load_config=lambda:{},web_providers=lambda:[provider],web_provider=lambda n:provider)
        args={'run_id':rid,'action':'extract','provider':provider.name,'urls':['https://example.org']}
        with patch('hermes_research_report.research_capabilities._runtime',return_value=runtime), \
             patch('hermes_research_report.research_capabilities._web_policy',return_value={'web_extract'}), \
             patch('hermes_research_report.research_capabilities.integration_settings',return_value=self.cfg), \
             patch('hermes_research_report.research_capabilities._extract_urls',new=AsyncMock(return_value=(args['urls'],[]))):
            with self.assertRaisesRegex(ValueError,'provider_operation_not_enabled'): asyncio.run(web_provider(args))
            provider.extract.assert_not_called()
            self.cfg['web_provider_allowlist']={provider.name:['extract']}
            self.assertEqual(asyncio.run(web_provider(args))['status'],'provider_response_recorded')
            provider.extract.assert_called_once()

    def test_cli_refuses_second_controller(self):
        path=Path(__file__).resolve().parents[1]/'skills/research/scripts/run_research.py'
        spec=importlib.util.spec_from_file_location('integration_runner',path)
        runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
        with patch('hermes_research_report.research_integration.settings',return_value=self.cfg), patch('sys.stderr',new=io.StringIO()):
            self.assertEqual(runner.main(['--question','fixture']),2)
        rid=self.start()['run_id']
        with self.assertRaisesRegex(ValueError,'foundation_managed_run'): runner._existing_run(rid,None,None)

    def test_actual_config_selects_root_and_rejects_invalid_policy(self):
        with patch('hermes_cli.config.load_config_readonly', return_value={'research':self.cfg}):
            self.assertEqual(settings()['workspace_root'], self.tmp.name)
        with patch('hermes_cli.config.load_config_readonly', return_value={'research':{'web_provider_allowlist':{'service':['invented']}}}):
            with self.assertRaises(ValueError): settings()
