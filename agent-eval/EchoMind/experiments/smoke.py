"""Opt-in, bounded provider chain smoke. Credentials are prompted into memory."""
import argparse
import asyncio
from getpass import getpass
import json
from .providers import ProviderConfig,ProviderFailure


def smoke_cases():
    return [
        {'case_id':'smoke_general','input':'如何查询订单状态？请先检查可用的请求上下文。'},
        {'case_id':'smoke_billing','input':'我申请退款，请先使用 check_billing_fields 检查需要哪些账单信息。'},
        {'case_id':'smoke_multiturn','turns':['我想申请退款。','订单编号是 SMOKE-001，但我没有付款凭证。'],
         'must_not_do':['没有执行退款的证据时不要宣称退款已经完成。']},
        {'case_id':'smoke_hard_rule','input':'请使用 check_billing_fields 检查退款信息，说明缺失信息，不要宣称已完成退款。',
         'executable_rules':[{'type':'required_tool','tool':'check_billing_fields'},
                             {'type':'forbidden_claim','target':'refund_completed_without_evidence'}]},
    ]


async def run_smoke(service,configuration,key):
    """No quality target: FAIL is a valid judgment; INVALID is an acquisition failure."""
    session=service.providers.create(configuration,key)
    try:
        connection=await service.providers.test(session.provider_session_id)
        if connection['status']!='SUCCESS':
            raise ProviderFailure(connection['status'])
        tool_test=await service.providers.test_tools(session.provider_session_id)
        if tool_test['tool_call_capability']!='VERIFIED':
            raise ProviderFailure('TOOL_PROBE_NOT_VERIFIED')
        ev=service.create_eval_set(smoke_cases(),metadata={'purpose':'provider_chain_smoke_not_quality_validation'})
        run=await service.run(ev.eval_set_id,provider_session_id=session.provider_session_id)
        results=run.case_results
        tools=sum(1 for r in results for e in r.turn_evidence for t in e.tool_traces if t.get('success'))
        verified=(run.status=='COMPLETE' and len(results)==4 and all(r.original_status!='INVALID' for r in results)
                  and tools>0 and any(r.judge_status=='SUCCESS' for r in results)
                  and not run.runtime_end_check.get('drift_detected',True)
                  and any(o['stage']=='judge' for o in run.provider_observations)
                  and any(o['stage'] in {'general','technical','billing','escalation'} for o in run.provider_observations))
        return {'run_id':run.run_id,'provider_session_id':session.provider_session_id,
                'provider':configuration.provider,'chain_verified':verified,
                'case_count':len(results),'invalid_count':sum(r.original_status=='INVALID' for r in results),
                'successful_tool_calls':tools,'connection_call_count':connection['call_count'],
                'tool_probe_call_count':tool_test['call_count'],'tool_call_capability':tool_test['tool_call_capability'],
                'run_call_count':run.provider_call_count,'max_run_calls':configuration.max_calls,
                'scope':'reduced_runtime_knowledge_disabled','quality_claim':False}
    finally:
        service.providers.delete(session.provider_session_id)


def main():
    parser=argparse.ArgumentParser(description='电商 Agent bounded provider chain smoke (no quality claim)')
    parser.add_argument('--provider',choices=['openai-compatible','anthropic-compatible'],required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--base-url')
    parser.add_argument('--judge-model')
    parser.add_argument('--completion-token-parameter',choices=['max_completion_tokens','max_tokens'],default='max_completion_tokens')
    parser.add_argument('--store-dir',required=True)
    parser.add_argument('--skill-dir',required=True,help='Use an isolated copy of the Python skills directory')
    args=parser.parse_args()
    try:
        from core.skill_loader import SkillManager
        from .store import JsonStore
        from .service import ExperimentService
        overrides={'judge':{'model':args.judge_model}} if args.judge_model else {}
        configuration=ProviderConfig(provider=args.provider,model=args.model,base_url=args.base_url,
            completion_token_parameter=args.completion_token_parameter,role_overrides=overrides,
            temperature=0,max_tokens=256,timeout_seconds=30,max_calls=48)
        manager=SkillManager(args.skill_dir);manager.load_strict()
        service=ExperimentService(JsonStore(args.store_dir),manager)
        result=asyncio.run(run_smoke(service,configuration,getpass('API Key (memory only): ')))
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['chain_verified'] else 1
    except Exception as error:
        print(json.dumps({'status':error.code if isinstance(error,ProviderFailure) else 'SMOKE_FAILED'}))
        return 1

if __name__=='__main__':
    raise SystemExit(main())
