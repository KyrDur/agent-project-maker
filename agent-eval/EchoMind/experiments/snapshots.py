"""Freeze explicit runtime contracts; audit source hashes are separate."""
import ast
import os
import json
from pathlib import Path
from urllib.parse import urlsplit
from importlib.metadata import version
from .canonical import digest, text_hash, evaluation_protocol, encoded
from .skills import skill_snapshot

ROOT = Path(__file__).resolve().parents[1]
ENV_KEYS = ["ANTHROPIC_MODEL","ANTHROPIC_BASE_URL","ECHOMIND_GENERAL_MODEL","ECHOMIND_TECHNICAL_MODEL",
            "ECHOMIND_BILLING_MODEL","ECHOMIND_ESCALATION_MODEL","ECHOMIND_COMPOSER_TEMPERATURE",
            "ECHOMIND_COMPOSER_MAX_TOKENS","ECHOMIND_MONITOR_FALLBACK_PENALTY"]
SOURCE_FILES = ["agents/agent_orchestrator.py","core/intent_recognizer.py","core/skill_loader.py",
                "evaluation/evaluator.py","evaluation/rules.py","evaluation/legacy.py","evaluation/models.py",
                "evaluation/metrics.py","evaluation/config.py"]
SOURCE_FILES += ["experiments/worker.py", "experiments/snapshots.py", "experiments/provider_transport.py",
                 "experiments/openai_chat.py", "experiments/providers.py"]

def provider_endpoint(value):
    url = urlsplit(value or "https://api.anthropic.com")
    if url.scheme not in {"https","http"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Provider endpoint must not contain credentials, query or fragment")
    try:
        url.port
    except ValueError:
        raise ValueError("Invalid provider endpoint port") from None
    return value or "https://api.anthropic.com"

def prompt_snapshot():
    # Template content, not the full source identity.
    agent = (ROOT/"agents/agent_orchestrator.py").read_text()
    intent = (ROOT/"core/intent_recognizer.py").read_text()
    templates = {}
    for name,source in (("agent",agent),("intent",intent)):
        tree = ast.parse(source)
        templates[name] = [node.value for node in ast.walk(tree)
                           if isinstance(node,ast.Constant) and isinstance(node.value,str)
                           and len(node.value)>30]
    return {"snapshot":templates, "hash":digest(templates)}

def capture(manager,config,settings=None,provider_config=None):
    from agents.agent_orchestrator import GeneralAgent, TechnicalAgent, BillingAgent, EscalationAgent, AgentOrchestrator
    from core.intent_recognizer import _TEMPLATES
    from dataclasses import asdict
    settings = dict(settings or {})
    env = {key:settings.get(key,os.getenv(key,"")) for key in ENV_KEYS}
    if provider_config is not None:
        env = {key:"" for key in ENV_KEYS}
        env.update(ANTHROPIC_MODEL=provider_config.model,ANTHROPIC_BASE_URL=provider_config.base_url,
                   ECHOMIND_MONITOR_FALLBACK_PENALTY=".5")
        for role,values in provider_config.resolved().items():
            if role in {"general","technical","billing","escalation"}:
                env["ECHOMIND_"+role.upper()+"_MODEL"] = values["model"]
    model = env["ANTHROPIC_MODEL"] or "claude-3-5-sonnet-20241022"
    endpoint = provider_endpoint(env["ANTHROPIC_BASE_URL"])
    agents = {}
    for cls in (GeneralAgent,TechnicalAgent,BillingAgent,EscalationAgent):
        role = cls.agent_type.value
        profile = asdict(cls.profile)
        profile["model"] = env["ECHOMIND_"+role.upper()+"_MODEL"] or profile.get("model") or model
        agents[role] = profile
    inference = {"provider":{"type":"anthropic-compatible","endpoint":endpoint},
        "agents":{role:{"model":p["model"],"temperature":p["temperature"],"max_tokens":p["max_tokens"]}
                  for role,p in agents.items()},
        "judge":{"model":model,"temperature":0.0,"max_tokens":256},
        "intent":{"model":model,"temperature":.1,"max_tokens":256},
        "composer":{"model":model,"temperature":float(env["ECHOMIND_COMPOSER_TEMPERATURE"] or ".1"),
                    "max_tokens":int(env["ECHOMIND_COMPOSER_MAX_TOKENS"] or "1000")},
        "query_rewrite":{"enabled":False,"model":None,"temperature":.3,"max_tokens":256},
        "rerank":{"enabled":False,"model":None,"temperature":0.0,"max_tokens":256},
        "embedding":{"type":"local_char_ngram_md5","dimensions":256,"remote_enabled":False},
        "other_inference":{"seed":"provider_default/unknown","top_p":"provider_default/unknown",
                           "stop":"provider_default/unknown","timeout_seconds":600,"max_retries":2},
        "sdk_version":version("anthropic")}
    if provider_config is not None:
        resolved = provider_config.resolved()
        for role,profile in agents.items():
            profile.update(resolved[role])
        inference["agents"] = {role:resolved[role] for role in agents}
        for role in ("composer","intent","judge"):
            inference[role] = resolved[role]
        inference["provider"]["type"] = provider_config.provider
        inference["transport"] = "openai_chat_completions_v1" if provider_config.provider == "openai-compatible" else "anthropic_messages"
        inference["sdk_version"] = {"httpx":version("httpx"),"anthropic":version("anthropic")}
        inference["completion_token_parameter"] = provider_config.completion_token_parameter
        if provider_config.thinking_mode is not None:
            inference["thinking_mode"] = provider_config.thinking_mode
        inference["other_inference"].update(timeout_seconds=provider_config.timeout_seconds,max_retries=0,
                                             max_calls=provider_config.max_calls)
        inference["model_inheritance"] = {role:"explicit_override" if role in provider_config.role_overrides
                                           else "user_default" for role in resolved}
        inference["parameter_inheritance"] = {
            role:{field:"explicit_override" if role in provider_config.role_overrides
                  and getattr(provider_config.role_overrides[role],field) is not None else "user_default"
                  for field in ("model","temperature","max_tokens")} for role in resolved}
    # Canonical JSON rejects NaN / Infinity before execution.
    digest(inference)
    templates = {key.value:list(value) for key,value in _TEMPLATES.items()}
    routing = {"intent_mapping":{k.value:v.value for k,v in AgentOrchestrator._INTENT_ROUTING.items()},
               "protocol":"phase2-1", "monitor_fallback_penalty":float(env["ECHOMIND_MONITOR_FALLBACK_PENALTY"] or ".5"),
               "monitor":"disabled","initial_agent_stats":"zero","templates":templates}
    policy = {"isolation":"private_subprocess","reliable_isolation":True,
              "monitor":"not_started","skill_reload":"prohibited","learn":"prohibited",
              "environment":"frozen_allowlist","execution_order":"intent_then_dialog_sorted_id",
              "state_reset_policy":"fresh_run_and_per_dialog_case",
              "cache_policy":{"intent":"disabled","tool":"disabled","knowledge":"disabled"},
              "memory":"not_used_by_phase2_evaluator","knowledge_mode":"disabled", "knowledge_tool_registration":"absent",
              "implementation_guard":digest({f:text_hash((ROOT/f).read_text()) for f in SOURCE_FILES})}
    # First backend does not pretend to isolate an online mutable Chroma collection.
    # RAG is explicitly disabled and identical in both runs; no external KB change support.
    knowledge = {"mode":"disabled","generation":None,"hash":digest({"mode":"disabled"}),
                 "reason":"Formal v1 runtime has no shared mutable Knowledge binding"}
    snapshot = {"agent_config_snapshot":agents,"inference_config_snapshot":inference,
            "skill_version":skill_snapshot(manager),"prompt_version":prompt_snapshot(),
            "knowledge_version":knowledge,"routing_config_version":routing,
            "runtime_policy_snapshot":policy,
            "evaluation_protocol_snapshot":evaluation_protocol(config),
            "evaluation_config_snapshot":config.model_dump(),
            "worker_environment":{k:str(v) for k,v in env.items()},
            "warnings":["SINGLE_RUN_RANDOMNESS","MODEL_BACKEND_REVISION_UNVERIFIED","KNOWLEDGE_DISABLED_IN_FORMAL_RUNTIME"]}
    if provider_config is not None:
        snapshot["provider_configuration_snapshot"] = provider_config.model_dump()
    return json.loads(encoded(snapshot))

def control_snapshot(snapshot):
    return {k:v for k,v in snapshot.items() if k not in {"worker_environment","warnings"}}

def runtime_identity(snapshot):
    return digest(control_snapshot(snapshot))
