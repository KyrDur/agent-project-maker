"""Sealing evidence: disabled Knowledge access, conservative attribution, retained scope."""
import asyncio
from copy import deepcopy
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from api import main
from experiments.runtime import ProcessRuntime
from test_experiment_service import setup
from test_experiment_comparison import pair, clone


@pytest.mark.parametrize("claim", [None, {"verified": True, "revision": "claimed-v1"},
                                  {"verified": True, "revision": "claimed-v2"}])
def test_backend_unknown_cannot_be_promoted_by_declarations(tmp_path, claim):
    service, ev, _ = setup(tmp_path, settings={"MODEL_BACKEND_REVISION": "user-label",
                                             "MODEL_BACKEND_VERIFIED": "true"})
    a, b, _, _ = pair(service, ev)
    if claim:
        # Even internal artifact metadata/readback declarations are not actual attestation.
        end = deepcopy(b.runtime_end_check)
        end["backend_identity"] = claim
        b = clone(service, b, warnings=[], metadata={"backend_identity": claim}, runtime_end_check=end)
    comp = service.compare(a.run_id, b.run_id)
    assert comp.comparable and comp.single_recorded_change
    assert not comp.attributable and comp.attribution_status == "INSUFFICIENT_EVIDENCE"
    assert "MODEL_BACKEND_REVISION_UNVERIFIED" in comp.attribution_warnings
    assert "SINGLE_RUN_RANDOMNESS_NOT_CAUSAL_PROOF" in comp.attribution_warnings
    assert all(p["effective_transition"] == "IMPROVED" for p in comp.case_comparisons)


def test_reduced_scope_derived_from_snapshots_not_filtered_run_warnings(tmp_path):
    service, ev, _ = setup(tmp_path)
    a, b, _, _ = pair(service, ev, limit=1)
    b = clone(service, b, warnings=[])
    comp = service.compare(a.run_id, b.run_id)
    assert comp.comparison_completeness == "PARTIAL" and comp.comparable
    assert "REDUCED_RUNTIME_KNOWLEDGE_DISABLED" in comp.attribution_warnings
    assert "query rewrite and rerank are disabled" in comp.runtime_scope
    assert "not full online RAG" in comp.runtime_scope
    assert service.store.get("comparisons", comp.comparison_id).model_dump() == comp.model_dump()


# Test-only bootstrap instrumentation. Production ProcessRuntime still creates a real
# child, sends its real stdin payload/frozen env, and consumes the real worker output.
# No testing hook/flag/provider is added to the production runtime or HTTP API.
CHILD_GUARDS = r'''
import asyncio, importlib.abc, json, os, sys
attempts = []
class NoKnowledgeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"api", "mcp.knowledge_base", "mcp.tool_manager", "memory"} or fullname.startswith("chromadb"):
            attempts.append(fullname)
            raise AssertionError("Disabled Knowledge dependency accessed")
sys.meta_path.insert(0, NoKnowledgeImports())
class BombProvider:
    def __getattribute__(self, name):
        attempts.append(name)
        raise AssertionError("Shared Knowledge/RAG provider accessed")
online_shared_knowledge = BombProvider()
from agents import agent_orchestrator as agents
original_init = agents.AgentOrchestrator.__init__
instances, roles = [], []
def guarded_init(self, *args, **kwargs):
    assert kwargs.get("rag_tool_manager") is None
    original_init(self, *args, **kwargs)
    instances.append(self)
agents.AgentOrchestrator.__init__ = guarded_init
original_handle = agents.BaseAgent.handle
async def guarded_handle(self, req):
    assert not self._shared_tools
    assert "search_knowledge_base" not in self.get_tools()
    roles.append(self.agent_type.value)
    return await original_handle(self, req)
agents.BaseAgent.handle = guarded_handle
from experiments.worker import execute
payload = json.load(sys.stdin)
assert set(payload) == {"run", "credential"}
output = asyncio.run(execute(payload))
assert not attempts, attempts
assert {"billing", "technical", "general"} <= set(roles), roles
for orchestrator in instances:
    assert not orchestrator._shared_tools
    for pool in orchestrator._pool.values():
        for agent in pool:
            assert "search_knowledge_base" not in agent.get_tools()
            try:
                agent.set_shared_tools({"forbidden": object()})
            except RuntimeError:
                pass
            else:
                raise AssertionError("Shared tools can be rebound")
    try:
        orchestrator.set_shared_tools({"forbidden": object()})
    except RuntimeError:
        pass
    else:
        raise AssertionError("Shared tools can be rebound")
output["runtime_end_check"]["test_boundary_evidence"] = {
    "child_pid": os.getpid(), "knowledge_access_attempts": attempts, "executed_roles": sorted(set(roles)),
    "payload_keys": sorted(payload), "shared_tool_rebinding": "denied"}
print(json.dumps(output, ensure_ascii=False, allow_nan=False))
'''


@pytest.mark.parametrize("forged_tool", [False, True])
def test_real_worker_zero_knowledge_access_billing_technical_fallback_retest(tmp_path, monkeypatch, forged_tool):
    accesses, calls, spawns = [], [], []
    class BombProvider:
        def __getattribute__(self, name):
            if name == "__class__":  # pytest's setattr type inspection is not Knowledge access.
                return object.__getattribute__(self, name)
            accesses.append(name)
            raise AssertionError("Online shared Knowledge/RAG accessed")
    # Online service objects exist, but cannot be serialized or used by a formal Run.
    monkeypatch.setattr(main, "_tool_manager", BombProvider())
    monkeypatch.setattr(main, "_orchestrator", BombProvider())
    original_spawn = asyncio.create_subprocess_exec
    async def instrument_child(*args, **kwargs):
        assert args[1:] == ("-m", "experiments.worker")
        assert "PYTHONPATH" in kwargs["env"] and "HOME" not in kwargs["env"]
        spawns.append(args)
        return await original_spawn(args[0], "-c", CHILD_GUARDS, **kwargs)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", instrument_child)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(data)
            prompt = str(data.get("messages", ""))
            tools = {t["name"] for t in data.get("tools", [])}
            assert "search_knowledge_base" not in tools
            content, stop = None, "end_turn"
            if "客服意图分析专家" in prompt:
                text = json.dumps({"intent": "technical_crash" if "500" in prompt else "refund",
                                   "confidence": 1, "reasoning": "controlled transport"})
            elif "客服质量评估专家" in prompt:
                text = json.dumps(dict(relevance=.95, accuracy=.95, completeness=.95, helpfulness=.95))
            elif tools and "tool_result" not in prompt:
                tool = ("search_knowledge_base" if forged_tool and "check_billing_fields" in tools
                        else "check_billing_fields" if "check_billing_fields" in tools
                        else "lookup_error_code" if "lookup_error_code" in tools else "inspect_request_context")
                inputs = {"query": "must never retrieve"} if tool == "search_knowledge_base" else (
                    {"error_code": "500"} if tool == "lookup_error_code" else {})
                content = [{"type": "tool_use", "id": "call_fixture", "name": tool, "input": inputs}]
                stop = "tool_use"
                text = ""
            else:
                # Actual empty Billing response after tool call exercises General fallback.
                text = "" if "FALLBACK" in prompt and "check_billing_fields" in tools else "Please verify the provided information."
            response = {"id": "msg_fixture", "type": "message", "role": "assistant", "model": data["model"],
                        "content": content or [{"type": "text", "text": text}], "stop_reason": stop,
                        "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
            raw = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        service, _, _ = setup(tmp_path, runtime=ProcessRuntime(), settings={
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}", "ANTHROPIC_MODEL": "guarded-local"})
        ev = service.create_eval_set([{"case_id": "a", "input": "退款"},
                                      {"case_id": "b", "input": "页面报500错误"},
                                      {"case_id": "c", "input": "退款 FALLBACK"}])
        a, b, _, _ = pair(service, ev)
        assert len(spawns) == 2 and calls and not accesses
        for run in (a, b):
            assert run.status == "COMPLETE", run.warnings
            assert not run.runtime_end_check["drift_detected"]
            proof = run.runtime_end_check["test_boundary_evidence"]
            assert proof["child_pid"] != os.getpid()
            assert not proof["knowledge_access_attempts"]
            assert proof["executed_roles"] == ["billing", "general", "technical"]
            assert proof["payload_keys"] == ["credential", "run"]
            boundary = run.runtime_end_check["knowledge_boundary"]
            assert not boundary["shared_tools_bound"]
            assert not boundary["query_rewrite_enabled"] and not boundary["rerank_enabled"]
            assert all("search_knowledge_base" not in names for names in boundary["registered_role_tools"].values())
            assert [r.turn_evidence[0].agent_type for r in run.case_results] == ["billing", "technical", "general"]
            traces = [t for r in run.case_results for e in r.turn_evidence for t in e.tool_traces]
            assert any(t["tool_name"] == "lookup_error_code" and t["success"] for t in traces)
            assert any(t["tool_name"] == "inspect_request_context" and t["success"] for t in traces)
            retrieval = [t for t in traces if t["tool_name"] == "search_knowledge_base"]
            if forged_tool:
                # Rejected model requests remain visible evidence; no retrieval actually ran.
                assert retrieval and all(not t["success"] and "白名单" in t["error"] for t in retrieval)
                assert all("search_knowledge_base" not in e.tools_used for r in run.case_results for e in r.turn_evidence)
            else:
                assert not retrieval
                assert any(t["tool_name"] == "check_billing_fields" and t["success"] for t in traces)
        comp = service.compare(a.run_id, b.run_id)
        assert comp.comparable and comp.single_recorded_change and not comp.attributable
        assert "REDUCED_RUNTIME_KNOWLEDGE_DISABLED" in comp.attribution_warnings
    finally:
        server.shutdown()
        server.server_close()
