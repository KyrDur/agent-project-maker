"""Interactive grounded Agent shares the evaluation retrieval and answer pipeline."""
import asyncio
import re
import time
from .models import uid
from .practice_models import ChatTurn, RepeatReport, ExperimentConclusion
from .retrieval_models import RetrievalConfig, RetrievalCase
from .retrieval_runtime import retrieve_context, grounded_answer, pipeline_snapshot
from .provider_transport import ObservedProvider
from .providers import ProviderFailure

class PracticeService:
    def __init__(self, retrieval):
        self.rag = retrieval
        self.store = retrieval.store

    def conversation(self, identifier):
        self.store.path('chat_turns', identifier)
        turns=sorted((t for t in self.store.list('chat_turns') if t.conversation_id==identifier),key=lambda t:t.sequence)
        if not turns: raise FileNotFoundError()
        return turns

    async def chat(self, provider_session_id, index_id, message, retrieval_config=None, conversation_id=None):
        if not message.strip(): raise ValueError('Empty message')
        session=self.rag.providers.get(provider_session_id)
        key=self.rag.providers.credential(provider_session_id)
        if session.text_connection_status!='READY': raise ProviderFailure('CONNECTION_NOT_VERIFIED')
        index=self.store.get('knowledge_indices',index_id)
        await asyncio.to_thread(self.rag.knowledge.verify,index)
        config=RetrievalConfig.model_validate(retrieval_config or {})
        turns=self.conversation(conversation_id) if conversation_id else []
        identity=conversation_id or uid()
        try: lease=self.store.acquire_run_lease(identity,'chat_turns')
        except BlockingIOError: raise ProviderFailure('CONVERSATION_BUSY') from None
        provider=None
        try:
            if turns:
                turns=self.conversation(identity)
                first=turns[0]
                if (first.index_id!=index_id or first.retrieval_config!=config
                    or first.provider_session_id!=provider_session_id
                    or first.provider_configuration_snapshot!=session.configuration.model_dump()
                    or first.pipeline!=pipeline_snapshot(session.configuration)):
                    raise ProviderFailure('CHAT_CONFIGURATION_CHANGED')
            if len(turns)>=30: raise ProviderFailure('CONVERSATION_LIMIT_REACHED')
            context=[]
            for turn in [t for t in turns if t.status=='SUCCESS'][-5:]:
                context.extend([{'role':'user','content':turn.message},{'role':'assistant','content':turn.answer}])
            provider=ObservedProvider(session.configuration,key,self.rag.providers.judge_credential(provider_session_id))
            started=time.monotonic()
            row=await retrieve_context(self.rag.knowledge,index,provider,message,config,pipeline_snapshot(session.configuration),context)
            answer=''; error=row['error']; status='FAILED'; citations=[]
            if row['status']=='SUCCESS':
                try:
                    answer=await grounded_answer(provider,message,row['results'],context)
                    if len(answer)>10000: raise ProviderFailure('INVALID_RESPONSE')
                    # Only a retrieved ID explicitly cited by the answer counts as
                    # a citation. The remaining candidates stay in retrieval evidence.
                    for item in row['results']:
                        doc=item['document_id']
                        if re.search(r'(?<![A-Za-z0-9_-])'+re.escape(doc)+r'(?![A-Za-z0-9_-])',answer):
                            citations.append(item)
                    await asyncio.to_thread(self.rag.knowledge.verify,index)
                    status='SUCCESS'
                except ProviderFailure as e: error=e.code; answer=''
                except Exception: error='RETRIEVAL_EXECUTION_FAILED'; answer=''
            artifact=ChatTurn(conversation_id=identity,sequence=len(turns)+1,index_id=index_id,
                knowledge_version=index.knowledge_version,provider_session_id=provider_session_id,
                provider_configuration_snapshot=session.configuration.model_dump(),retrieval_config=config,
                pipeline=pipeline_snapshot(session.configuration),message=message.strip(),context=context,
                answer=answer,status=status,error=error,retrieval=row,citations=citations,
                provider_observations=provider.observations,provider_call_count=provider.call_count,
                latency_ms=(time.monotonic()-started)*1000)
            with self.store.transaction(): return self.store.put('chat_turns',artifact)
        finally:
            if provider: await provider.close()
            lease.close()

    def to_case(self, turn_id, expected_answer, relevant_document_ids, must_do, must_not_do, partition, confirmed):
        turn=self.store.get('chat_turns',turn_id)
        if turn.status!='SUCCESS' or not confirmed or not (expected_answer.strip() or must_do):
            raise ValueError('User must confirm success criteria')
        index=self.store.get('knowledge_indices',turn.index_id)
        missing=bool(set(relevant_document_ids)-{c['document_id'] for c in index.chunks})
        case=RetrievalCase(case_id='chat_'+turn.turn_id,query=turn.message,
            context=turn.context,source_chat_turn_id=turn.turn_id,source='user_created',
            expected_answer=expected_answer.strip() or None,relevant_document_ids=relevant_document_ids,
            must_do=must_do,must_not_do=must_not_do,partition=partition,allow_missing_knowledge=missing)
        from .store import safe_artifact
        safe_artifact(case.model_dump(),self.store.forbidden_values)
        return case

    def conclude(self, comparison_id, decision, reason, user_confirmed):
        self.store.get('retrieval_comparisons',comparison_id)
        if not reason.strip() or not user_confirmed: raise ValueError('Explicit judgment required')
        artifact=ExperimentConclusion(comparison_id=comparison_id,decision=decision,
            reason=reason.strip(),user_confirmed=True)
        with self.store.transaction(): return self.store.put('experiment_conclusions',artifact)

    async def repeat(self, source_run_id, provider_session_id, repetitions):
        source=self.store.get('retrieval_runs',source_run_id)
        if source.status!='COMPLETE': raise ValueError('Only complete experiments can repeat')
        session=self.rag.providers.get(provider_session_id)
        if session.configuration.model_dump()!=source.provider_configuration_snapshot:
            raise ValueError('Repeated experiment configuration changed')
        snapshot=source.controls['eval_set_snapshot']; runs=[]
        # Each attempt is independent, uses the exact frozen test and configuration,
        # and preserves all failure records. This is a stability check, not a win claim.
        for _ in range(repetitions):
            run=await self.rag.run(provider_session_id,snapshot['retrieval_eval_set_id'],
                version=snapshot['version'],retrieval_config=source.retrieval_config.model_dump(),
                verify_answers=source.verify_answers)
            if run.controls!=source.controls: raise ValueError('Frozen repetition controls changed')
            runs.append(run)
        summary={}
        for metric in ['hit_at_1','hit_at_3','mrr','recall_at_k','precision_at_k','ndcg_at_k']:
            values=[r.metrics[metric] for r in runs if r.status=='COMPLETE' and r.metrics.get(metric) is not None]
            summary[metric]={'values':values,'minimum':min(values) if values else None,
                'maximum':max(values) if values else None,'mean':sum(values)/len(values) if values else None}
        summary['attempts']=[{'run_id':r.run_id,'status':r.status,'answer_metrics':r.answer_metrics,
            'latency_ms':sum(c['latency_ms'] for c in r.case_results)} for r in runs]
        report=RepeatReport(source_run_id=source_run_id,run_ids=[r.run_id for r in runs],repetitions=repetitions,
            summary=summary,provider_call_count=sum(r.provider_call_count for r in runs),
            warnings=['STABILITY_CHECK_NOT_CAUSAL_PROOF','SAME_CASES_NOT_NEW_HOLDOUT','MODEL_BACKEND_REVISION_UNKNOWN'])
        with self.store.transaction(): return self.store.put('repeat_reports',report)
