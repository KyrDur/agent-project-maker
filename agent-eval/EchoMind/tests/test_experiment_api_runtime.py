import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from fastapi.testclient import TestClient
from api import main
from experiments.api import configure
from experiments.runtime import ProcessRuntime
from test_experiment_service import setup, baseline

def test_actual_process_http_provider_skill_loop_and_intent_separation(tmp_path):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(data)
            prompt=str(data.get("messages",""))
            if "客服意图分析专家" in prompt:
                text=json.dumps({"intent":"refund","confidence":1,"reasoning":"local transport"})
            elif "客服质量评估专家" in prompt:
                score=.95 if "payment" in prompt else .2
                text=json.dumps(dict(relevance=score,accuracy=score,completeness=score,helpfulness=score))
            else:
                text="payment checked" if "payment" in data.get("system","") else "needs evidence"
            response={"id":"msg_fixture","type":"message","role":"assistant","model":data["model"],
                "content":[{"type":"text","text":text}],"stop_reason":"end_turn","stop_sequence":None,
                "usage":{"input_tokens":1,"output_tokens":1}}
            raw=json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        service,_,manager=setup(tmp_path,runtime=ProcessRuntime(),
            settings={"ANTHROPIC_BASE_URL":f"http://127.0.0.1:{server.server_port}","ANTHROPIC_MODEL":"local-fixture"})
        ev=service.create_eval_set([{"case_id":"dialog","turns":["退款","退款 order","退款 time"]}],
            [{"case_id":"intent","message":"退款","expected_intent":"refund"}])
        a=asyncio.run(service.run(ev.eval_set_id))
        assert a.status=="COMPLETE" and not a.runtime_end_check["drift_detected"]
        assert a.case_results[0].original_status=="FAIL"
        assert len(a.case_results)==1 and len(a.case_results[0].turn_evidence)==3
        assert a.intent_metrics["total"]==1 and a.intent_sample_results[0]["case_id"]=="intent"
        draft=service.create_decision(a.run_id,["dialog"],root_cause_suggestion="Guidance")
        dec=service.confirm_decision(draft.decision_id,user_confirmed_root_cause="Rule too short",
            root_cause_reason="Evidence checked",selected_strategy="Check payment",selection_reason="Small change",
            expected_benefit="Completeness",possible_side_effects="Longer",confirmed_by="user")
        change=service.propose_change(dec.decision_id,"refund.md","Verify payment before claims.",a.skill_version["hash"])
        change=service.apply_change(change.change_id)
        b=asyncio.run(service.run(ev.eval_set_id,"RETEST",a.run_id,dec.decision_id,[change.change_id]))
        assert b.status=="COMPLETE" and b.case_results[0].original_status=="PASS"
        comp=service.compare(a.run_id,b.run_id)
        assert comp.comparable and not comp.attributable and comp.single_recorded_change
        assert comp.attribution_status=="INSUFFICIENT_EVIDENCE"
        assert comp.case_comparisons[0]["effective_transition"]=="IMPROVED"
        assert comp.group_metrics["intent_metrics"]["sample_pairs"][0]["transition"]=="STILL_CORRECT"
        assert comp.expected_case_count==2 and len(comp.case_comparisons)==1
        assert service.result_view(b.run_id)["dialog_case_metrics"]["total"]==1
        service.rollback(change.change_id)
        assert "payment" not in manager.prompt_for("退款","billing")
        # Actual separate SDK requests, with pinned per-stage inference values.
        assert any(c["temperature"]==0 and c["max_tokens"]==256 for c in calls)
        assert any(c["temperature"]==0 and c["max_tokens"]==1100 for c in calls)
        assert any(c["temperature"]==.1 and c["max_tokens"]==256 for c in calls)
    finally:
        server.shutdown()
        server.server_close()

def test_experiment_api_real_lifecycle_and_readback(tmp_path,monkeypatch):
    service,_,_=setup(tmp_path)
    # This existing API test uses FixtureRuntime, not a network connection fixture.
    from experiments.providers import ProviderConfig
    from secrets import token_hex
    session=service.providers.create(ProviderConfig(model="fixture"),token_hex(24))
    service.store.put("provider_sessions",session.model_copy(update={"status":"READY","text_connection_status":"READY"}))
    configure(lambda:service)
    client=TestClient(main.app)
    try:
        ev=client.post("/experiments/evalsets",json={"dialog_cases":[{"question":"退款"}]}).json()
        a=client.post("/experiments/runs",json={"eval_set_id":ev["eval_set_id"],"provider_session_id":session.provider_session_id}).json()
        assert a["status"]=="COMPLETE"
        cid=a["case_results"][0]["case_id"]
        decision=client.post("/experiments/decisions",json={"related_run_id":a["run_id"],
            "selected_case_ids":[cid],"root_cause_suggestion":"possible"}).json()
        assert decision["status"]=="DRAFT"
        bad=client.post("/experiments/changes",json={"decision_id":decision["decision_id"],
            "skill_id":"refund.md","rule_body":"new","before_hash":a["skill_version"]["hash"]})
        assert bad.status_code==409
        confirmed=client.post(f'/experiments/decisions/{decision["decision_id"]}/confirm',json={
            "user_confirmed_root_cause":"Insufficient rule","root_cause_reason":"Read response",
            "selected_strategy":"Add payment check","selection_reason":"Minimal",
            "expected_benefit":"Accuracy","possible_side_effects":"Longer","confirmed_by":"user"})
        assert confirmed.status_code==200
        change=client.post("/experiments/changes",json={"decision_id":decision["decision_id"],
            "skill_id":"refund.md","rule_body":"Verify payment.","before_hash":a["skill_version"]["hash"]}).json()
        assert client.post(f'/experiments/changes/{change["change_id"]}/apply').json()["implemented_status"]=="APPLIED"
        service.runtime.score=.95
        b=client.post("/experiments/runs",json={"eval_set_id":ev["eval_set_id"],"provider_session_id":session.provider_session_id,"run_type":"RETEST",
            "parent_run_id":a["run_id"],"decision_id":decision["decision_id"],"change_ids":[change["change_id"]]}).json()
        review=client.post(f'/experiments/runs/{a["run_id"]}/reviews',json={"case_id":cid,
            "human_final_status":"PASS","human_reason":"Manual evidence checked","reviewer":"user"})
        assert review.status_code==200
        comp=client.post("/experiments/comparisons",json={"baseline_run_id":a["run_id"],"retest_run_id":b["run_id"]}).json()
        assert comp["comparable"] and comp["case_comparisons"][0]["machine_transition"]=="IMPROVED"
        assert comp["case_comparisons"][0]["effective_transition"]=="STILL_PASS"
        assert "REDUCED_RUNTIME_KNOWLEDGE_DISABLED" in comp["attribution_warnings"]
        assert "not full online RAG" in comp["runtime_scope"]
        assert "MODEL_BACKEND_REVISION_UNVERIFIED" in comp["attribution_warnings"]
        assert comp["single_recorded_change"] and not comp["attributable"]
        assert comp["attribution_status"]=="INSUFFICIENT_EVIDENCE"
        assert client.get(f'/experiments/comparisons/{comp["comparison_id"]}').json()==comp
        assert client.post(f'/experiments/changes/{change["change_id"]}/rollback').json()["rollback_status"]=="ROLLED_BACK"
        assert client.post("/experiments/runs",json={"eval_set_id":ev["eval_set_id"],"api_key":"no"}).status_code==422
        assert client.get("/experiments/runs/missing").status_code==404
    finally:
        configure(main._experiments)
