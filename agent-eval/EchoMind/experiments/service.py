"""Orchestrate persisted experiments without changing Phase 2 decisions."""
from copy import deepcopy
import os
from evaluation.config import EvaluationConfig
from evaluation.models import CaseResult
from evaluation.metrics import dialog_metrics
from .canonical import create_eval_set, verify_eval_set, evaluation_protocol, digest
from .models import EvalSet, Run, Decision, Change, ReviewRecord, now
from .store import TERMINAL
from .snapshots import capture, control_snapshot, runtime_identity
from .skills import SkillController, skill_diff, one_body
from .runtime import ProcessRuntime
from .providers import ProviderSessions, ProviderConfig, ProviderFailure

class ExperimentService:
    def __init__(self,store,skill_manager,credential=None,runtime=None,settings=None):
        self.store = store
        self.skills = SkillController(skill_manager)
        self.credential = credential or ""  # Legacy internal harness only; never server env fallback.
        self.store.forbidden_values = tuple(set(self.store.forbidden_values + ((self.credential,) if self.credential else ())))
        self.providers = ProviderSessions(store)
        self.runtime = runtime or ProcessRuntime()
        self.settings = dict(settings or {})
        # Interrupted execution cannot be silently resumed as a successful observation.
        with self.store.transaction():
            for run in self.store.list("runs"):
                if run.status not in TERMINAL:
                    try:
                        lease = self.store.acquire_run_lease(run.run_id)
                    except BlockingIOError:
                        continue  # Another process is still acquiring this Run's evidence.
                    try:
                        self.store.put("runs",Run.model_validate({**run.model_dump(),"status":"FAILED","finished_at":now(),
                            "runtime_end_check":{"drift_detected":True,"reliable_isolation":False,"reasons":["PROCESS_INTERRUPTED"]},
                            "warnings":[*run.warnings,"PROCESS_INTERRUPTED"]}))
                    finally:
                        lease.close()
            for change in self.store.list("changes"):
                if change.implemented_status == "APPLYING" or change.rollback_status == "ROLLING_BACK":
                    data = change.model_dump()
                    if change.implemented_status == "APPLYING":
                        data["implemented_status"] = "FAILED"
                    if change.rollback_status == "ROLLING_BACK":
                        data["rollback_status"] = "FAILED"
                    data["error"] = "PROCESS_INTERRUPTED_UNVERIFIED_ACTIVATION"
                    data["application_evidence"] = {**change.application_evidence,
                        "restart_current_readback_hash":self.skills.current()["hash"]}
                    self.store.put("changes",Change.model_validate(data))

    def create_eval_set(self,dialog_cases,intent_cases=None,**kwargs):
        ev = create_eval_set(dialog_cases,intent_cases,**kwargs)
        with self.store.transaction():
            return self.store.put("evalsets",ev)

    def create_decision(self,run_id,selected_case_ids,**fields):
        run = self.store.get("runs",run_id)
        if run.status not in TERMINAL:
            raise ValueError("Decision requires sealed Run")
        ids = {c.case_id for c in run.case_results} | {c["case_id"] for c in run.intent_sample_results}
        if not selected_case_ids or not set(selected_case_ids) <= ids:
            raise ValueError("Unknown or empty selected_case_ids")
        if fields.get("status","DRAFT") != "DRAFT":
            raise ValueError("Create a suggestion first, then explicitly confirm")
        decision = Decision(related_run_id=run_id,selected_case_ids=selected_case_ids,**fields)
        with self.store.transaction():
            return self.store.put("decisions",decision)

    def confirm_decision(self,decision_id,**confirmation):
        with self.store.transaction():
            previous = self.store.get("decisions",decision_id)
            allowed = {"user_confirmed_root_cause","root_cause_reason","alternatives","selected_strategy",
                       "selection_reason","expected_benefit","possible_side_effects","confirmed_by"}
            if set(confirmation)-allowed:
                raise ValueError("Unsupported Decision confirmation fields")
            decision = Decision.model_validate({**previous.model_dump(),**confirmation,"status":"CONFIRMED","confirmed_at":now()})
            return self.store.put("decisions",decision)

    def propose_change(self,decision_id,skill_id,rule_body,before_hash,change_type="SKILL_RULE",
                       change_scope="ONE_SKILL_RULE_BODY"):
        with self.store.transaction():
            decision = self.store.get("decisions",decision_id)
            if decision.status != "CONFIRMED":
                raise ValueError("Only CONFIRMED Decisions can propose an applied intervention")
            baseline = self.store.get("runs",decision.related_run_id)
            before = baseline.skill_version
            unsupported = change_type != "SKILL_RULE" or change_scope != "ONE_SKILL_RULE_BODY"
            if before_hash != before["hash"]:
                raise ValueError("before_hash does not match Baseline")
            after,diff = (deepcopy(before),[]) if unsupported else self.skills.propose(before,skill_id,rule_body)
            change = Change(decision_id=decision_id,baseline_run_id=baseline.run_id,
                change_type=change_type,affected_component=skill_id,change_scope=change_scope,
                before_snapshot=before,before_hash=before_hash,after_snapshot=after,after_hash=after["hash"],
                declared_diff=diff,implemented_status="UNSUPPORTED" if unsupported else "PROPOSED")
            return self.store.put("changes",change)

    def apply_change(self,change_id):
        with self.store.transaction(), self.skills.manager.activation_lock:
            change = self.store.get("changes",change_id)
            if change.implemented_status != "PROPOSED":
                raise ValueError("Change is not PROPOSED")
            decision = self.store.get("decisions",change.decision_id)
            baseline = self.store.get("runs",change.baseline_run_id)
            if decision.status != "CONFIRMED" or decision.related_run_id != baseline.run_id:
                raise ValueError("Confirmed Decision/Baseline mismatch")
            current = self.skills.verify_disk()
            if current["hash"] != change.before_hash or baseline.skill_version != change.before_snapshot:
                raise ValueError("before_hash mismatch")
            self._check_non_skill_controls(baseline)
            if change.after_hash == change.before_hash:
                return self.store.put("changes",Change.model_validate({**change.model_dump(),"implemented_status":"NOOP",
                    "observed_diff":[],"application_evidence":{"noop_readback":current["hash"]}}))
            parsed,declared = self.skills.propose(change.before_snapshot,change.affected_component,
                next(s["rule_body"] for s in change.after_snapshot["skills"] if s["skill_id"] == change.affected_component))
            if (change.change_type != "SKILL_RULE" or change.change_scope != "ONE_SKILL_RULE_BODY"
                    or not one_body(declared) or declared != change.declared_diff or parsed != change.after_snapshot):
                raise ValueError("UNSUPPORTED or declared_diff mismatch")
            applying = self.store.put("changes",Change.model_validate({**change.model_dump(),"implemented_status":"APPLYING"}))
            try:
                actual = self.skills.activate(change.before_snapshot,change.after_snapshot,change.affected_component)
                observed = skill_diff(change.before_snapshot,actual)
                if observed != change.declared_diff:
                    raise ValueError("observed_diff mismatch")
                result = Change.model_validate({**applying.model_dump(),"implemented_status":"APPLIED","applied_at":now(),
                    "observed_diff":observed,"verified_effective_version":actual["hash"],
                    "application_evidence":{"strict_parse":True,"atomic_write":True,"reload":True,
                        "readback_hash":actual["hash"],"disk_matches_loaded":True}})
                return self.store.put("changes",result)
            except Exception as error:
                # If final artifact writing fails after activation, compensate before marking failure.
                if self.skills.current()["hash"] == change.after_hash:
                    try:
                        self.skills.activate(change.after_snapshot,change.before_snapshot,change.affected_component)
                    except Exception:
                        pass
                failed = Change.model_validate({**applying.model_dump(),"implemented_status":"FAILED",
                    "error":type(error).__name__,"application_evidence":{"current_readback_hash":self.skills.current()["hash"]}})
                self.store.put("changes",failed)
                raise ValueError("Skill Apply failed; check saved failure/readback evidence") from None

    def rollback(self,change_id):
        with self.store.transaction(), self.skills.manager.activation_lock:
            change = self.store.get("changes",change_id)
            if change.implemented_status != "APPLIED" or change.rollback_status != "NOT_REQUESTED":
                raise ValueError("Only active APPLIED Change can roll back")
            if self.skills.verify_disk()["hash"] != change.after_hash:
                raise ValueError("After version is no longer active; refusing destructive rollback")
            rolling = self.store.put("changes",Change.model_validate({**change.model_dump(),"rollback_status":"ROLLING_BACK"}))
            try:
                actual = self.skills.activate(change.after_snapshot,change.before_snapshot,change.affected_component)
                result = Change.model_validate({**rolling.model_dump(),"rollback_status":"ROLLED_BACK","rollback_at":now(),
                    "application_evidence":{**rolling.application_evidence,"rollback_reload":True,
                        "rollback_readback_hash":actual["hash"]}})
                return self.store.put("changes",result)
            except Exception as error:
                self.store.put("changes",Change.model_validate({**rolling.model_dump(),"rollback_status":"FAILED",
                    "application_evidence":{**rolling.application_evidence,"rollback_current_hash":self.skills.current()["hash"]},
                    "error":type(error).__name__}))
                raise ValueError("Rollback failed; actual version not verified") from None

    def _snapshot(self,eval_set,provider_config=None):
        config = EvaluationConfig.model_validate(eval_set.pass_criteria_snapshot["evaluation_config"])
        protocol = evaluation_protocol(config)
        if protocol != eval_set.pass_criteria_snapshot["evaluation_protocol"]:
            raise ValueError("EvalSet protocol incompatible with current Phase 2 semantics")
        self.skills.verify_disk()
        return capture(self.skills.manager,config,self.settings,provider_config)

    def _check_non_skill_controls(self,run):
        ev = verify_eval_set(EvalSet.model_validate(run.eval_set_snapshot))
        provider_config = ProviderConfig.model_validate(run.provider_configuration_snapshot) if run.provider_session_id else None
        current = self._snapshot(ev,provider_config)
        for key in control_snapshot(current):
            if key != "skill_version" and getattr(run,key) != current[key]:
                raise ValueError("Non-Skill controls changed: "+key)

    async def run(self,eval_set_id,run_type="BASELINE",parent_run_id=None,decision_id=None,change_ids=None,eval_set_version=None,provider_session_id=None):
        with self.store.transaction(), self.skills.manager.activation_lock:
            if run_type == "RETEST" and parent_run_id and eval_set_version is None:
                eval_set_version = self.store.get("runs",parent_run_id).eval_set_snapshot["eval_set_version"]
            ev = verify_eval_set(self.store.get("evalsets",eval_set_id,eval_set_version))
            session = self.providers.get(provider_session_id) if provider_session_id else None
            snapshot = self._snapshot(ev,session.configuration if session else None)
            if session and session.status not in {"READY","CREDENTIAL_UNAVAILABLE","DELETED"}:
                raise ProviderFailure("CONNECTION_NOT_VERIFIED")
            requires_tools = bool(ev.case_snapshot)  # Every Dialog Agent registers role tools; Intent-only does not.
            if (session and session.status=='READY' and session.text_connection_status!='READY'):
                raise ProviderFailure('CONNECTION_NOT_VERIFIED')
            if (session and session.status=='READY' and requires_tools
                    and session.tool_call_capability=='UNSUPPORTED'):
                raise ProviderFailure('TOOL_CALL_UNSUPPORTED')
            changes = list(change_ids or [])
            if run_type == "RETEST":
                if not parent_run_id or not decision_id or not changes:
                    raise ValueError("Optimization Retest requires confirmed Decision and APPLIED Change")
                baseline = self.store.get("runs",parent_run_id)
                decision = self.store.get("decisions",decision_id)
                if (baseline.status not in TERMINAL or baseline.eval_set_hash != ev.eval_set_hash
                        or baseline.eval_set_id != ev.eval_set_id or decision.status != "CONFIRMED"
                        or decision.related_run_id != baseline.run_id):
                    raise ValueError("Optimization Retest requires same EvalSet and confirmed parent Decision")
                current = baseline.skill_version
                for cid in changes:
                    change = self.store.get("changes",cid)
                    if (change.implemented_status != "APPLIED" or change.rollback_status != "NOT_REQUESTED"
                            or change.before_hash != current["hash"] or change.observed_diff != change.declared_diff):
                        raise ValueError("Change chain is not currently APPLIED")
                    current = change.after_snapshot
                if current != snapshot["skill_version"]:
                    raise ValueError("Applied after version is not current")
            elif run_type == "BASELINE":
                if parent_run_id or decision_id or changes:
                    raise ValueError("Ordinary Baseline must not masquerade as optimization Retest")
            else:
                raise ValueError("Unsupported Run type")
            worker_environment = snapshot.pop("worker_environment")
            warnings = snapshot.pop("warnings")
            readiness = {}
            if session:
                readiness={'text_connection_status':session.text_connection_status,
                           'tool_call_capability':session.tool_call_capability,'requires_tools':requires_tools}
                if requires_tools and session.tool_call_capability in {'UNKNOWN','FAILED'}:
                    warnings.append('TOOL_CALL_CAPABILITY_'+session.tool_call_capability)
            run = Run(provider_session_id=provider_session_id,run_type=run_type,parent_run_id=parent_run_id,decision_id=decision_id,applied_change_ids=changes,
                provider_readiness_snapshot=readiness,
                eval_set_id=ev.eval_set_id,eval_set_hash=ev.eval_set_hash,eval_set_snapshot=ev.snapshot,
                evaluation_protocol_hash=digest(snapshot["evaluation_protocol_snapshot"]),
                runtime_start_snapshot=deepcopy(snapshot),warnings=warnings,
                execution_order=[c.case_id for c in sorted(ev.intent_case_snapshot,key=lambda c:c.case_id)]
                    + [c.case_id for c in sorted(ev.case_snapshot,key=lambda c:c.case_id)],**snapshot)
            lease = self.store.acquire_run_lease(run.run_id)
            try:
                self.store.put("runs",run)
                run = self.store.put("runs",Run.model_validate({**run.model_dump(),"status":"RUNNING","started_at":now()}))
            except BaseException:
                lease.close()
                raise
        try:
            run_credential = self.providers.credential(provider_session_id) if provider_session_id else self.credential
            if provider_session_id and session.configuration.judge_provider_session_id:
                run_credential={'main':run_credential,'judge':self.providers.judge_credential(provider_session_id)}
            if not run_credential:
                raise ProviderFailure("CREDENTIAL_UNAVAILABLE")
            output = await self.runtime.execute(run,run_credential,worker_environment)
            results = [CaseResult.model_validate(r) for r in output["case_results"]]
            # IDs and original machine results must come from this exact immutable EvalSet.
            expected = {c.case_id:c for c in ev.case_snapshot}
            if len({r.case_id for r in results}) != len(results) or any(r.case_id not in expected or r.case != expected[r.case_id]
                    or r.human_final_status is not None for r in results):
                raise ValueError("Runtime evidence does not match bound EvalSet")
            samples = output.get("intent_sample_results",[])
            intent_ids = {c.case_id for c in ev.intent_case_snapshot}
            if len({s["case_id"] for s in samples}) != len(samples) or any(s["case_id"] not in intent_ids for s in samples):
                raise ValueError("Runtime intent identity mismatch")
            end = output["runtime_end_check"]
            if end.get("actual_snapshot") != run.runtime_start_snapshot:
                end = {**end,"drift_detected":True,"reasons":sorted(set(end.get("reasons",[])+["RUNTIME_CONFIG_DRIFT"]))}
            count = len(results)+len(samples)
            status = "COMPLETE" if count == len(run.execution_order) else "PARTIAL"
            observations = output.get("provider_observations",[])
            model_warnings = []
            if any(o.get("requested_model") != o.get("response_model_identifier") for o in observations):
                model_warnings.append("RESPONSE_MODEL_IDENTIFIER_DIFFERS_FROM_REQUEST")
            if run.parent_run_id:
                parent = self.store.get("runs",run.parent_run_id)
                observed_models = lambda items: {(o["stage"],o["response_model_identifier"]) for o in items}
                if observed_models(parent.provider_observations) != observed_models(observations):
                    model_warnings.append("RESPONSE_MODEL_IDENTIFIER_CHANGED")
            final = Run.model_validate({**run.model_dump(),"case_results":results,
                "provider_observations":observations,"provider_call_count":output.get("provider_call_count",0),
                "warnings":[*run.warnings,*model_warnings],"intent_metrics":output.get("intent_metrics",{}),
                "intent_sample_results":samples,"runtime_end_check":end,"status":status,"finished_at":now()})
            # Reject provider secrets in evidence; do not log the unsafe body.
            from .store import safe_artifact
            safe_artifact(final.model_dump(),self.store.forbidden_values+(run_credential,))
        except BaseException as error:
            # Cancellation and provider failure seal a failed acquisition, not a fabricated score.
            failure = error.code if isinstance(error,ProviderFailure) else "RUNTIME_FAILED"
            final = Run.model_validate({**run.model_dump(),"status":"FAILED","finished_at":now(),
                "runtime_end_check":{"reliable_isolation":False,"drift_detected":True,"reasons":[failure]},
                "warnings":[*run.warnings,failure]})
        try:
            with self.store.transaction():
                return self.store.put("runs",final)
        finally:
            lease.close()

    def review(self,run_id,case_id,status,reason,reviewer):
        with self.store.transaction():
            run = self.store.get("runs",run_id)
            if run.status not in TERMINAL:
                raise ValueError("Review requires sealed Run")
            records = [r for r in self.store.list("reviews") if r.run_id == run_id]
            revision = max([r.revision for r in records],default=0)+1
            results = self.effective_results(run,max([r.revision for r in records],default=0))
            original = next((r for r in results if r.case_id == case_id),None)
            if original is None:
                raise ValueError("Unknown Case")
            reviewed = original.review(status,reason)  # Phase 2 remains the sole review validator.
            record = ReviewRecord(run_id=run_id,case_id=case_id,revision=revision,human_final_status=status,
                human_reason=reviewed.human_reason,reviewed_at=reviewed.reviewed_at,reviewer=reviewer,
                hard_rule_override=reviewed.hard_rule_override,original_status=original.original_status,
                original_reason=original.original_reason)
            return self.store.put("reviews",record)

    def effective_results(self,run,revision=None):
        records = sorted([r for r in self.store.list("reviews") if r.run_id == run.run_id],key=lambda r:r.revision)
        if revision is not None:
            records = [r for r in records if r.revision <= revision]
        results = {r.case_id:r for r in run.case_results}
        for review in records:
            base = results[review.case_id]
            results[review.case_id] = CaseResult.model_validate({**base.model_dump(),
                "human_final_status":review.human_final_status,"human_reason":review.human_reason,
                "reviewed_at":review.reviewed_at,"hard_rule_override":review.hard_rule_override,
                "review_status":"COMPLETED"})
        return list(results.values())

    def result_view(self,run_id):
        run = self.store.get("runs",run_id)
        results = self.effective_results(run)
        return {"run":run.model_dump(mode="json"),"effective_results":[r.to_dict() for r in results],
                "intent_metrics":run.intent_metrics,"dialog_case_metrics":dialog_metrics(results)}

    def compare(self,baseline_id,retest_id):
        from .comparison import compare
        with self.store.transaction():
            return self.store.put("comparisons",compare(self,baseline_id,retest_id))
