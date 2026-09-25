"""Host-only ResearchHandoffV1 intake. Reuses artifact and canonical writers.

The admission callable belongs to the host session, never to model tool arguments.
It must resolve live work/lease/profile and memory/graph state on each invocation.
There is deliberately no model-callable admission or canonical promotion tool here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
from typing import Callable

from .artifacts import ArtifactService
from .canonical import receipt, sha256_json
from .errors import fail


class ResearchIntake:
    def __init__(self, artifacts: ArtifactService, state, admit: Callable[[], dict]):
        self.artifacts, self.state, self.admit = artifacts, state, admit

    def _admission(self, binding):
        actual = self.admit()
        if not isinstance(actual, dict) or actual != binding:
            fail('research_context_mismatch', 'host_context', 'Контекст пакета не совпадает с проверенным контекстом сеанса.')
        required = ('host_run_id', 'project_id', 'profile_id', 'bead_id', 'work_contract_ref',
                    'lease_ref', 'agentmemory_receipt_ref', 'graphiti_receipt_ref')
        if any(not isinstance(actual.get(key), str) or not actual[key].strip() for key in required):
            fail('research_admission_missing', 'host_context', 'Отсутствует проверенная привязка запуска.')
        return actual

    def ingest(self, relative_package: str, manifest_sha256: str) -> dict:
        """Read a host-staged package under artifact quarantine, never an arbitrary path."""
        def read(relative, size):
            return self.artifacts._read_source(relative, size)[0]

        prefix = PurePosixPath(relative_package)
        if not relative_package or prefix.is_absolute() or '..' in prefix.parts:
            fail('research_path_invalid', 'package', 'Недопустимый путь пакета.')
        raw = read(str(prefix / 'manifest.json'), 4 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != manifest_sha256:
            fail('research_manifest_hash', 'manifest', 'Хеш манифеста не совпал.')
        manifest = json.loads(raw)
        if (manifest.get('contract') != 'ResearchHandoffV1' or manifest.get('schema_version') != 1
                or manifest.get('submission_status') != 'unsubmitted'
                or manifest.get('acceptance_status') != 'acceptance_not_requested'
                or manifest.get('production_qualified') is not False
                or not isinstance(manifest.get('handoff_id'), str) or not manifest['handoff_id'].startswith('H-')):
            fail('research_contract_invalid', 'manifest', 'Не поддерживается контракт пакета.')
        binding = self._admission(manifest.get('host_context'))
        rows = manifest.get('files')
        if not isinstance(rows, list) or not rows:
            fail('research_files_missing', 'manifest.files', 'Нет зарегистрированных файлов.')
        names = set()
        # Stage verified bytes on disk, not all source texts in memory. No research source-count cap.
        with tempfile.TemporaryDirectory(prefix='research-intake-', dir=self.artifacts.quarantine) as temporary:
            staging = Path(temporary)
            verified = []
            for index, row in enumerate(rows):
                if not isinstance(row, dict) or set(row) != {'path', 'sha256', 'bytes'}:
                    fail('research_file_invalid', 'manifest.files', 'Некорректная запись файла.')
                name = row['path']
                if not isinstance(name, str) or not name or name in names or '\\' in name:
                    fail('research_file_invalid', 'manifest.files', 'Повторный или некорректный путь.')
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or str(path) != name:
                    fail('research_path_invalid', 'manifest.files', 'Недопустимый путь файла.')
                names.add(name)
                size = row['bytes']
                if type(size) is not int or size < 0 or size > 64 * 1024 * 1024:
                    fail('research_file_size', 'manifest.files', 'Размер не поддерживается службой артефактов.')
                payload = read(str(prefix / path), max(size, 1))
                if len(payload) != size or hashlib.sha256(payload).hexdigest() != row['sha256']:
                    fail('research_file_hash', 'manifest.files', 'Файл изменён или повреждён.')
                target = staging / str(index)
                target.write_bytes(payload)
                verified.append((row, target))
            if not {'run.json', 'report.md', 'result.json', 'records/sources.json', 'records/notes.json'} <= names:
                fail('research_records_missing', 'manifest.files', 'Не хватает обязательных записей.')
            by_name = {row['path']: path for row, path in verified}
            run = json.loads(by_name['run.json'].read_bytes())
            result = json.loads(by_name['result.json'].read_bytes())
            if (run.get('run_id') != manifest.get('run_id') or run.get('host_context') != binding
                    or run.get('integration_mode') != 'foundation'
                    or result.get('status') not in ('complete', 'partial')
                    or manifest.get('result_status') != result.get('status')
                    or result.get('report_sha256') != hashlib.sha256(by_name['report.md'].read_bytes()).hexdigest()):
                fail('research_result_invalid', 'result', 'Не согласованы запуск, отчёт и контекст.')
            mappings = []
            local_ids = set()
            for record_file, collection, suffix in (('records/sources.json','materials','.txt'), ('records/notes.json','notes','.md')):
                records = json.loads(by_name[record_file].read_bytes())
                if not isinstance(records, list):
                    fail('research_records_invalid', record_file, 'Неверная форма записей.')
                for record in records:
                    if not isinstance(record, dict) or record.get('path') != f"{collection}/{record.get('id')}{suffix}" or record.get('path') not in by_name:
                        fail('research_record_path', record_file, 'Запись не связана с файлом.')
                    if record['id'] in local_ids:
                        fail('research_duplicate_id', record_file, 'Повторный идентификатор записи.')
                    local_ids.add(record['id'])
                    if collection == 'materials' and record.get('sha256') != hashlib.sha256(by_name[record['path']].read_bytes()).hexdigest():
                        fail('research_source_hash', record_file, 'Содержимое источника не совпадает с записью.')
                    mappings.append({'local_id':record['id'], 'path':record['path']})
            object_id = 'RHI-' + sha256_json({'project':binding['project_id'], 'handoff':manifest.get('handoff_id')})[:24]
            lookup = {'schema_version':1,'database':'kw_core','project_id':binding['project_id'],'object_id':object_id}
            current = self.state.get(lookup)
            if current['status'] == 'found':
                if current['object'].get('manifest_sha256') != manifest_sha256:
                    fail('research_handoff_conflict', 'handoff_id', 'Идентификатор передачи уже занят другим содержимым.')
                return receipt({'contract':'ResearchIntakeReceipt','status':'already_imported_draft',
                                'object_id':object_id,'canonical_readback':current,'claim_status_changed':False,'delivery_authorized':False})
            self._admission(binding)
            artifacts = []
            for row, path in verified:
                acquired = self.artifacts.ingest({'schema_version':1,
                    'acquisition_id':'RHA-'+sha256_json({'package':manifest_sha256,'path':row['path']})[:24],
                    'relative_path':str(path.relative_to(self.artifacts.quarantine)),
                    'media_type':'application/octet-stream','max_bytes':max(row['bytes'],1)})
                if acquired['status'] != 'accepted' or acquired['content_hash'] != row['sha256']:
                    fail('research_artifact_rejected','artifact','Артефакт не принят.')
                artifacts.append({'path':row['path'],'artifact_id':acquired['artifact_id'],'sha256':row['sha256']})
            ids = {row['path']:row['artifact_id'] for row in artifacts}
            for item in mappings: item['artifact_id'] = ids[item['path']]
            body = {'contract':'ResearchImportedDraftV1','handoff_id':manifest['handoff_id'],
                    'manifest_sha256':manifest_sha256,'host_context':binding,'run_id':manifest['run_id'],
                    'status':'imported_draft','artifacts':artifacts,'local_id_map':mappings,
                    'omitted_unregistered_retrieval_count':manifest.get('omitted_unregistered_retrieval_count',0),
                    'evidence_accepted':False,'claims_accepted':False,'delivery_authorized':False}
            self._admission(binding)
            written = self.state.put({**lookup,'expected_revision':0,'content_hash':sha256_json(body),
                      'schema_id':'ResearchImportedDraftV1','object':body,
                      'operation_id':object_id,'run_id':binding['host_run_id']})
            if written['status'] not in ('committed','no_op'):
                fail('research_canonical_write_failed','canonical','Запись черновика не подтверждена; принятые артефакты сохранены для повтора.')
            return receipt({'contract':'ResearchIntakeReceipt','status':'imported_draft','object_id':object_id,
                            'canonical_write':written,'local_id_map':mappings,
                            'claim_status_changed':False,'delivery_authorized':False})
