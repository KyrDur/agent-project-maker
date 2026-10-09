"""Unexposed isolated experiment instance; deliberately no Memory or Monitor."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from copy import deepcopy
from types import MethodType
from dataclasses import asdict, replace
from core.skill_loader import SkillManager
from experiments.models import Run
from experiments.canonical import digest
from experiments.snapshots import capture, control_snapshot, runtime_identity, ROOT
from evaluation.config import EvaluationConfig
from evaluation.evaluator import EndToEndEvaluator, IntentTestCase

def denied(*args,**kwargs):
    raise RuntimeError("Experiment runtime mutation prohibited")

async def execute(payload):
    from agents.agent_orchestrator import AgentOrchestrator, AgentStats
    from core.intent_recognizer import IntentRecognizer, IntentCategory
    import core.intent_recognizer as intent_module
    from evaluation.models import EvaluationCase
    run = Run.model_validate(payload["run"])
    config = EvaluationConfig.model_validate(run.evaluation_config_snapshot)
    key = payload["credential"]
    judge_key=key.get('judge') if isinstance(key,dict) else None
    if isinstance(key,dict): key=key['main']
    provider_config = None
    provider = None
    if run.provider_session_id:
        from experiments.providers import ProviderConfig
        from experiments.provider_transport import ObservedProvider
        provider_config = ProviderConfig.model_validate(run.provider_configuration_snapshot)
        provider = ObservedProvider(provider_config,key,judge_key)
    with tempfile.TemporaryDirectory(prefix="echomind-run-") as folder:
        for relative,raw in run.skill_version["files"].items():
            path = Path(folder)/relative
            path.resolve().relative_to(Path(folder).resolve())
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(raw,encoding="utf-8")
        manager = SkillManager(folder,run.skill_version["max_prompt_chars"])
        manager.load_strict()
        manager.reload = denied
        manager.load = denied
        manager.load_strict = denied
        intent_module._TEMPLATES = {IntentCategory(k):list(v) for k,v in run.routing_config_version["templates"].items()}
        base = run.inference_config_snapshot["inference"] if "inference" in run.inference_config_snapshot else run.inference_config_snapshot
        endpoint = base["provider"]["endpoint"]
        model = base["judge"]["model"]
        orchestrator = AgentOrchestrator(api_key=key,base_url=endpoint,model=model,skill_manager=manager)
        # Online constructor registers an unbound search tool even when its manager is
        # None. Formal experiments must remove it, rather than merely fail retrieval.
        orchestrator.set_shared_tools({})
        orchestrator.set_shared_tools = denied
        for agents in orchestrator._pool.values():
            for agent in agents:
                agent.set_shared_tools = denied
        def knowledge_boundary():
            tools = {role.value:sorted(agent.get_tools()) for role,agents in orchestrator._pool.items()
                     for agent in agents}
            if orchestrator._shared_tools or any(agent._shared_tools for agents in orchestrator._pool.values()
                                                  for agent in agents):
                raise RuntimeError("Shared tools prohibited in formal experiment")
            if any("search_knowledge_base" in names for names in tools.values()):
                raise RuntimeError("Knowledge tool prohibited in formal experiment")
            return tools
        knowledge_boundary()
        recognizer = IntentRecognizer(api_key=key,base_url=endpoint,model=base["intent"]["model"])
        clients = [recognizer,orchestrator._intent_recognizer]
        for item in clients:
            item.learn = denied
            async def embed(self,text):
                return self._local_embedding(text)
            item._embed_text = MethodType(embed,item)
            original_recognize = item.recognize
            async def recognize(message,history=None,_item=item,_recognize=original_recognize):
                _item._cache.clear()
                error_start = len(provider.errors) if provider else 0
                result = await _recognize(message,history=history)
                if provider and _item is recognizer and len(provider.errors)>error_start:
                    from experiments.providers import ProviderFailure
                    raise ProviderFailure(provider.errors[error_start]['status'])
                return result
            item.recognize = recognize
        orchestrator.update_routing_penalties = denied
        orchestrator.set_skill_manager = denied
        start = capture(manager,config,provider_config=provider_config)
        expected = {key:getattr(run,key) for key in control_snapshot(start)}
        drift = []
        def actual_snapshot():
            actual = capture(manager,config,provider_config=provider_config)
            for role,agents in orchestrator._pool.items():
                agent = agents[0]
                profile = asdict(agent.profile)
                profile["model"] = agent._model
                actual["agent_config_snapshot"][role.value] = profile
                actual["inference_config_snapshot"]["agents"][role.value] = {
                    "model":agent._model,"temperature":agent.profile.temperature,"max_tokens":agent.profile.max_tokens}
                if any(item.stats.monitor_penalty for item in agents):
                    drift.append("MONITOR_PENALTY_DRIFT")
            actual["inference_config_snapshot"]["intent"]["model"] = recognizer.model
            if orchestrator._intent_recognizer.model != recognizer.model:
                drift.append("ROUTER_RECOGNIZER_MODEL_DRIFT")
            actual["inference_config_snapshot"]["composer"]["model"] = orchestrator._composer._model
            actual["inference_config_snapshot"]["judge"]["model"] = evaluator._judge._model
            # Normalize dataclass tuples to their persisted JSON representation.
            from experiments.canonical import encoded
            return json.loads(encoded(actual))
        def check():
            knowledge_boundary()
            actual = actual_snapshot()
            if control_snapshot(actual) != expected:
                drift.append("RUNTIME_CONFIG_DRIFT")
        last_case = None
        original_run = orchestrator.run
        async def guarded(req):
            nonlocal last_case
            if req.conv_id != last_case:
                last_case = req.conv_id
                for agents in orchestrator._pool.values():
                    for agent in agents:
                        agent.stats = AgentStats()
            check()
            error_start = len(provider.errors) if provider else 0
            response = await original_run(req)
            if provider and len(provider.errors) > error_start:
                # Successful fallback cannot conceal a failed provider acquisition.
                # Pass execution evidence to the unchanged Phase 2 invalidation path.
                response.execution_status = "FAILED"
                response.execution_error = provider.errors[error_start]["status"]
            check()
            return response
        orchestrator.run = guarded
        evaluator = EndToEndEvaluator(orchestrator,recognizer,key,endpoint,model,config=config)
        if provider:
            resolved = provider_config.resolved()
            for role,agents in orchestrator._pool.items():
                for agent in agents:
                    agent._model = resolved[role.value]["model"]
                    agent.profile = replace(agent.profile,**resolved[role.value])
                    agent._client = provider.client(role.value)
            for item in clients:
                item.model = resolved["intent"]["model"]
                item.client = provider.client("intent")
            orchestrator._composer._model = resolved["composer"]["model"]
            orchestrator._composer._client = provider.client("composer")
            evaluator._judge._model = resolved["judge"]["model"]
            evaluator._judge._client = provider.client("judge")
        check()
        dialog = sorted([EvaluationCase.model_validate(c) for c in run.eval_set_snapshot["case_snapshot"]],key=lambda c:c.case_id)
        intents = sorted(run.eval_set_snapshot["intent_case_snapshot"],key=lambda c:c["case_id"])
        report = await evaluator.run(intent_cases=[IntentTestCase(c["message"],c["expected_intent"],c["context"]) for c in intents],
                                     dialog_cases=dialog)
        check()
        samples = [{**c,"case_id":formal["case_id"]} for formal,c in zip(intents,report.intent_metrics.get("cases",[]))]
        if provider:
            await provider.close()
        return {"provider_observations":provider.observations if provider else [],
                "provider_call_count":provider.call_count if provider else 0,
                "case_results":[r.model_dump(mode="json") for r in report.results],
                "intent_metrics":report.intent_metrics,"intent_sample_results":samples,
                "runtime_end_check":{"drift_detected":bool(drift),
                    "reasons":sorted(set(drift)), "actual_snapshot":control_snapshot(actual_snapshot()),
                    "reliable_isolation":True,
                    "provider_errors":provider.errors if provider else [],
                    "knowledge_boundary":{"mode":"disabled", "shared_tools_bound":False,
                                          "registered_role_tools":knowledge_boundary(),
                                          "query_rewrite_enabled":False,"rerank_enabled":False}}}

if __name__ == "__main__":
    try:
        result = asyncio.run(execute(json.load(sys.stdin)))
    except Exception as error:
        from experiments.providers import ProviderFailure
        result = {"error":error.code if isinstance(error,ProviderFailure) else type(error).__name__}
    sys.stdout.write(json.dumps(result,ensure_ascii=False,allow_nan=False))
