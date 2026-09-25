"""Exercise scale, concurrent preservation and honest citation semantics."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hermes_research_report.research_workspace import workspace, source, note, finish


class ResearchWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"HERMES_HOME": self.directory.name})
        self.environment.start()
        self.run = workspace({"action": "start", "question": "Cross-disciplinary causes and counter-evidence", "mode": "ultra"})
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.environment.stop)

    def test_hundreds_of_sources_parallel_full_text_and_resume(self):
        run_id = self.run['run_id']
        text = 'Methods and observations. ' * 2000 + 'ESSENTIAL FINDING AT END'
        def save(i):
            return source({'run_id': run_id, 'url': f'https://example.org/study/{i}?format=xml',
                           'text': text, 'extent': 'full_text', 'stream': f'stream-{i % 4}'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(save, range(240)))
            duplicates = list(pool.map(save, [0] * 8))
        self.assertEqual({x['source_id'] for x in duplicates}, {results[0]['source_id']})
        state = workspace({'action': 'status', 'run_id': run_id})
        self.assertEqual(state['unique_sources'], 240)
        self.assertEqual(state['stored_characters'], len(text) * 240)
        self.assertEqual(Path(results[-1]['path']).read_text(), text)
        self.assertEqual(state['next_offset'], 25)
        self.assertEqual(len(workspace({'action': 'status', 'run_id': run_id, 'offset': 200, 'limit': 100})['sources']), 40)

    def test_plan_revision_and_unverified_meaning_are_preserved(self):
        run_id = self.run['run_id']
        for number in (54, 108):
            workspace({'action': 'plan', 'run_id': run_id, 'plan': {'streams': [{'id': str(i), **({'question': 'Why?', 'method': 'Compare primary evidence'} if number == 54 else {'status': 'running'})} for i in range(number)]}})
        import json
        plan = json.loads((Path(self.run['root']) / 'plan.json').read_text())
        self.assertEqual(plan['revision'], 2)
        self.assertEqual(len(plan['streams']), 108)
        self.assertEqual(plan['streams'][0]['method'], 'Compare primary evidence')
        self.assertEqual(plan['streams'][0]['status'], 'running')
        material = source({'run_id': run_id, 'url': 'https://example.org/null', 'text': 'No causal effect established.', 'extent': 'full_text'})
        # A semantic substitution must never be labelled semantically verified by this bookkeeping tool.
        result = finish({'run_id': run_id, 'report': f"Causality is proven [{material['source_id']}].", 'status': 'complete'})
        self.assertEqual(result['semantic_verification'], 'not_established_by_this_tool')
        self.assertEqual(result['structural_citation_check'], 'pass')
        note({'run_id': run_id, 'text': 'This causal claim contradicts the source.', 'source_ids': [material['source_id']]})
        revised = finish({'run_id': run_id, 'report': 'Unresolved evidence [S-missing].', 'status': 'complete'})
        self.assertEqual(revised['status'], 'partial')
        self.assertEqual(revised['unresolved_citations'], ['S-missing'])
        self.assertEqual(len(list(Path(self.run['root']).glob('report-*.md'))), 1)

    def test_source_file_cannot_escape_workspace_and_large_file_preserved(self):
        root = Path(self.run['root'])
        p = root / 'retrieved.txt'
        p.write_text('a' * 1_100_000 + 'conclusion')
        row = source({'run_id': self.run['run_id'], 'url': 'https://example.org/paper', 'text_path': str(p), 'extent': 'full_text'})
        self.assertEqual(Path(row['path']).read_text(), p.read_text())
        clipped = source({'run_id': self.run['run_id'], 'url': 'https://example.org/clipped', 'text': 'Some material. This content has been truncated to stay below 50000 characters', 'extent': 'full_text'})
        self.assertEqual(clipped['extent'], 'excerpt')
        self.assertTrue(clipped['truncation_detected'])
        with self.assertRaises(ValueError):
            source({'run_id': self.run['run_id'], 'url': 'https://example.org/paper', 'text_path': '../outside.txt', 'extent': 'full_text'})

    def test_interrupted_source_retry_and_concurrent_reports(self):
        import hashlib
        import json
        run_id = self.run['run_id']
        root = Path(self.run['root'])
        url, text = 'https://example.org/orphan', 'The full original observation.'
        digest = hashlib.sha256(text.encode()).hexdigest()
        sid = 'S-' + hashlib.sha256((url + '\n' + digest).encode()).hexdigest()[:16]
        (root / 'materials' / (sid + '.txt')).write_text('partial')
        row = source({'run_id': run_id, 'url': url, 'text': text, 'extent': 'full_text'})
        self.assertEqual(Path(row['path']).read_text(), text)
        self.assertEqual(finish({'run_id': run_id, 'report': f'[{sid}]', 'status': 'complete'})['status'], 'partial')
        def save_report(i):
            return finish({'run_id': run_id, 'report': f'Analysis revision {i} [{sid}]', 'status': 'complete'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(save_report, range(8)))
        versions = list(root.glob('report-*.md')) + [root / 'report.md']
        self.assertEqual(len(versions), 9)
        self.assertEqual(sum('Analysis revision' in p.read_text() for p in versions), 8)
        result = json.loads((root / 'result.json').read_text())
        self.assertEqual(result['report_sha256'], hashlib.sha256((root / 'report.md').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
