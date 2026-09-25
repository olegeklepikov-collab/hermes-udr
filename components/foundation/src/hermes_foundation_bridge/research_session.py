"""Host-owned admission for research; no model-supplied receipt is trusted."""
from __future__ import annotations

from .canonical import sha256_json
from .errors import fail


class ResearchSession:
    """Created by the existing host session with its canonical work reference.

    prepare returns actual context to that host, which must deliver it to Hermes.
    check is the admission callable for ResearchIntake. This is a host API, not
    an additional controller, tool permission grant or generic model tool.
    """
    def __init__(self, state, runtime, beads, memory, graph, *, project_id, profile_id,
                 host_run_id, work_contract_ref, holder_id):
        self.state, self.runtime, self.beads = state, runtime, beads
        self.memory, self.graph = memory, graph
        self.project_id, self.profile_id = project_id, profile_id
        self.host_run_id, self.work_contract_ref, self.holder_id = host_run_id, work_contract_ref, holder_id
        self.binding = None
        self.contract_hash = None

    def _work(self):
        response = self.state.get({'schema_version':1,'database':'kw_core',
            'project_id':self.project_id,'object_id':self.work_contract_ref})
        work = response.get('object')
        if (response.get('status') != 'found' or response.get('object_ref', {}).get('schema_id') != 'ResearchWorkContractV1'
                or not isinstance(work, dict) or work.get('status') != 'active'
                or work.get('project_id') != self.project_id or work.get('profile_id') != self.profile_id
                or work.get('holder_id') != self.holder_id or work.get('host_run_id') != self.host_run_id):
            fail('research_work_not_authorized','work_contract','Не найден действующий контракт данного сеанса.')
        scope = work.get('memory_scope')
        if (not isinstance(scope, dict) or scope.get('project_id') != self.project_id
                or scope.get('profile_id') != self.profile_id):
            fail('research_scope_mismatch','memory_scope','Область памяти не совпадает с задачей.')
        issue = self.beads.get({'schema_version':1,'issue_id':work['bead_id']}).get('issue', {})
        if issue.get('id') != work['bead_id'] or issue.get('status') != 'in_progress' or issue.get('assignee') != self.holder_id:
            fail('research_work_not_claimed','bead_id','Задача не принадлежит исполнителю.')
        lease = self.runtime.check_lease(work['bead_id'], self.holder_id, work['lease_revision'])
        if not lease['lease_active']:
            fail('research_lease_inactive','lease','Аренда недействительна.')
        return work

    def prepare(self, query: str) -> dict:
        work = self._work()
        memory = self.memory.context({'schema_version':1,'scope':work['memory_scope'],'query':query,'limit':5})
        graph = self.graph.search({'schema_version':1,'project_id':self.project_id,'query':query,'limit':10})
        if (memory.get('status') != 'assembled' or memory.get('scope') != work['memory_scope']
                or graph.get('status') != 'queried' or graph.get('project_id') != self.project_id):
            fail('research_context_unavailable','context','Обязательный контекст не получен.')
        if sha256_json(self._work()) != sha256_json(work):
            fail('research_work_changed','work_contract','Контракт изменился во время получения контекста.')
        self.contract_hash = sha256_json(work)
        binding = {'host_run_id':self.host_run_id,'project_id':self.project_id,'profile_id':self.profile_id,
            'bead_id':work['bead_id'],'work_contract_ref':self.work_contract_ref,
            'lease_ref':f"{work['bead_id']}:{work['lease_revision']}",
            'agentmemory_receipt_ref':sha256_json(memory),'graphiti_receipt_ref':sha256_json(graph)}
        body = {'contract':'ResearchAdmissionV1','host_context':binding,'work_contract_sha256':self.contract_hash,
                'query_sha256':sha256_json({'query':query}),
                'memory_context_sha256':memory.get('context_hash'),
                'graph_result_sha256':sha256_json(graph.get('results',[])),
                'context_delivered_to_model':False}
        object_id='RAD-'+sha256_json(binding)[:24]
        lookup={'schema_version':1,'database':'kw_context','project_id':self.project_id,'object_id':object_id}
        existing=self.state.get(lookup)
        expected=existing['object_ref']['revision'] if existing['status']=='found' else 0
        written=self.state.put({**lookup,'expected_revision':expected,'content_hash':sha256_json(body),
            'schema_id':'ResearchAdmissionV1','object':body,'operation_id':object_id,'run_id':self.host_run_id})
        if written['status'] not in ('committed','no_op'):
            fail('research_admission_not_saved','context','Не сохранено происхождение контекста.')
        self.binding=binding
        return {'host_context':dict(binding),'memory_context':memory['context'],
                'graph_results':graph.get('results',[]),'admission_ref':object_id,
                'canonical_write':written,'context_delivered_to_model':False}

    def restore(self, binding: dict) -> None:
        """Resume finalization from a canonical admission, without rerunning research."""
        work = self._work()
        expected = {'project_id':self.project_id,'profile_id':self.profile_id,
                    'host_run_id':self.host_run_id,'work_contract_ref':self.work_contract_ref,
                    'bead_id':work['bead_id'],'lease_ref':f"{work['bead_id']}:{work['lease_revision']}"}
        if not isinstance(binding, dict) or any(binding.get(k) != v for k,v in expected.items()):
            fail('research_context_mismatch','admission','Сохранённый контекст принадлежит другой работе.')
        saved = self.state.get({'schema_version':1,'database':'kw_context','project_id':self.project_id,
                               'object_id':'RAD-'+sha256_json(binding)[:24]})
        body = saved.get('object')
        if (saved.get('status') != 'found' or saved.get('object_ref',{}).get('schema_id') != 'ResearchAdmissionV1'
                or not isinstance(body,dict) or body.get('host_context') != binding
                or body.get('work_contract_sha256') != sha256_json(work)):
            fail('research_admission_missing','admission','Не найден действующий канонический допуск.')
        self.binding = dict(binding)
        self.contract_hash = sha256_json(work)

    def check(self) -> dict:
        if self.binding is None:
            fail('research_session_not_prepared','context','Контекст сеанса не подготовлен.')
        if sha256_json(self._work()) != self.contract_hash:
            fail('research_work_changed','work_contract','Контракт изменился; требуется новый допуск.')
        return dict(self.binding)
