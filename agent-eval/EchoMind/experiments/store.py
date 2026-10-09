"""One local JSON store. Atomic, durable writes and immutable sealed evidence."""
import json
import os
import re
import tempfile
from pathlib import Path
from contextlib import contextmanager
import fcntl
from .canonical import digest, encoded
from .models import EvalSet, Run, Decision, Change, ReviewRecord, Comparison
from .providers import ProviderSession
from .practice_models import ChatTurn, RepeatReport, ExperimentConclusion, InterviewAttempt
from .assist import AssistDraft
from .retrieval_models import (KnowledgeDataset, KnowledgeIndex, RetrievalEvalSet, RetrievalRun,
                               RetrievalChange, RetrievalComparison, RetrievalReview)

TYPES = {"provider_sessions": (ProviderSession, "provider_session_id"), "evalsets": (EvalSet, "eval_set_id"), "runs": (Run, "run_id"),
         "decisions": (Decision, "decision_id"), "changes": (Change, "change_id"),
         "reviews": (ReviewRecord, "review_id"), "comparisons": (Comparison, "comparison_id")}
TYPES.update({"knowledge_datasets": (KnowledgeDataset, "knowledge_dataset_id"),
              "ai_drafts": (AssistDraft, "draft_id"),
              "chat_turns": (ChatTurn, "turn_id"),
              "repeat_reports": (RepeatReport, "report_id"),
              "experiment_conclusions": (ExperimentConclusion, "conclusion_id"),
              "interview_attempts": (InterviewAttempt, "attempt_id"),
              "knowledge_indices": (KnowledgeIndex, "index_id"),
              "retrieval_evalsets": (RetrievalEvalSet, "retrieval_eval_set_id"),
              "retrieval_runs": (RetrievalRun, "run_id"),
              "retrieval_changes": (RetrievalChange, "change_id"),
              "retrieval_comparisons": (RetrievalComparison, "comparison_id"),
              "retrieval_reviews": (RetrievalReview, "review_id")})
VERSION_FIELDS = {'evalsets': 'eval_set_version', 'knowledge_datasets': 'version', 'retrieval_evalsets': 'version'}
TERMINAL = {"COMPLETE", "PARTIAL", "FAILED"}
SENSITIVE = re.compile(r"(^|_)(api_key|authorization|secret|password|credential|access_token|refresh_token)($|_)", re.I)

def safe_artifact(value, forbidden_values=()):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"([a-z])([A-Z])", r"\1_\2",key)
            if SENSITIVE.search(normalized) or normalized.lower() == "token":
                raise ValueError("Credential field prohibited in artifact")
            safe_artifact(item, forbidden_values)
    elif isinstance(value, (list, tuple)):
        for item in value:
            safe_artifact(item, forbidden_values)
    elif isinstance(value, str):
        if any(secret and secret in value for secret in forbidden_values):
            raise ValueError("Credential value prohibited in artifact")
        if re.search(r"(?i)bearer\s+[a-z0-9._-]{8,}|sk-ant-[a-z0-9_-]{8,}", value):
            raise ValueError("Credential value prohibited in artifact")

class JsonStore:
    def __init__(self, root, forbidden_values=()):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.forbidden_values = tuple(forbidden_values)

    @contextmanager
    def transaction(self):
        # Interprocess lock also serializes review revision allocation / apply lifecycle.
        with (self.root / ".lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def acquire_run_lease(self,identifier,group="runs"):
        self.path(group,identifier)  # Validate before using identity in a lock filename.
        directory = self.root / (".run-leases" if group == "runs" else ".retrieval-run-leases")
        directory.mkdir(exist_ok=True)
        stream = (directory / identifier).open("a+")
        try:
            fcntl.flock(stream,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            stream.close()
            raise
        return stream

    def path(self, group, identifier, version=None):
        if group not in TYPES or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier):
            raise ValueError("Invalid artifact identity")
        if group in VERSION_FIELDS:
            if "--v" in identifier:
                identifier, suffix = identifier.rsplit("--v",1)
                if not suffix.isdigit():
                    raise ValueError("Invalid EvalSet revision")
                version = int(suffix)
            if version is None:
                versions = [int(p.stem.rsplit("--v",1)[1]) for p in (self.root/group).glob(identifier+"--v*.json")]
                version = max(versions,default=1)
            if not isinstance(version,int) or version < 1:
                raise ValueError("Invalid EvalSet revision")
            identifier = identifier+"--v"+str(version)
        return self.root / group / (identifier + ".json")

    def get(self, group, identifier, version=None):
        envelope = json.loads(self.path(group, identifier,version).read_text(encoding="utf-8"))
        payload = envelope["artifact"]
        if envelope["sha256"] != digest(payload):
            raise ValueError("Artifact integrity mismatch")
        adapted = dict(payload)
        if group == 'provider_sessions':
            # Read compatibility only: do not expose obsolete key-derived identifiers
            # or silently rewrite a historical artifact on GET.
            adapted.pop('masked_fingerprint',None)
            if 'text_connection_status' not in adapted and adapted.get('status')=='READY':
                adapted['text_connection_status']='READY'
        obj = TYPES[group][0].model_validate(adapted)
        if isinstance(obj, Run) and obj.status in TERMINAL:
            data = dict(payload)  # Preserve hash identity of older schemas with absent new defaults.
            expected = data.pop("artifact_hash")
            if expected != digest(data):
                raise ValueError("Sealed Run hash mismatch")
        return obj

    def list(self, group):
        directory = self.root / group
        return [self.get(group, p.stem) for p in sorted(directory.glob("*.json"))]

    def put(self, group, obj):
        model, id_field = TYPES[group]
        obj = model.model_validate(obj.model_dump())
        data = obj.model_dump(mode="json")
        safe_artifact(data, self.forbidden_values)
        revision = getattr(obj, VERSION_FIELDS[group]) if group in VERSION_FIELDS else None
        path = self.path(group, getattr(obj, id_field),revision)
        if path.exists():
            previous = self.get(group, getattr(obj, id_field),revision)
            if group in {'ai_drafts','knowledge_datasets','knowledge_indices','retrieval_evalsets',
                         'retrieval_comparisons','retrieval_reviews','chat_turns','repeat_reports','experiment_conclusions','interview_attempts'}:
                raise ValueError('Immutable retrieval artifact already sealed')
            if group == 'retrieval_runs':
                if previous.status in TERMINAL:
                    raise ValueError('Immutable retrieval Run already sealed')
                mutable = {'status','finished_at','case_results','answer_results','metrics','answer_metrics',
                           'provider_observations','provider_call_count','warnings','runtime_end_check'}
                if obj.status not in TERMINAL or any(previous.model_dump()[k] != data[k] for k in data if k not in mutable):
                    raise ValueError('Retrieval Run controls are frozen')
            if group == 'retrieval_changes':
                if previous.implemented_status != 'PROPOSED' or obj.implemented_status != 'APPLIED':
                    raise ValueError('Applied retrieval Change is immutable')
                mutable = {'implemented_status','applied_at','observed_diff','application_evidence'}
                if any(previous.model_dump()[k]!=data[k] for k in data if k not in mutable):
                    raise ValueError('Confirmed retrieval Change is immutable')
            if group in {"evalsets", "reviews", "comparisons"} or (group == "runs" and previous.status in TERMINAL):
                raise ValueError("Immutable artifact already sealed")
            if group == "provider_sessions":
                if previous.configuration != obj.configuration:
                    raise ValueError("Provider configuration is immutable; create a new Session")
                if previous.status == "DELETED":
                    raise ValueError("Deleted ProviderSession cannot be revived")
            if group == "decisions" and previous.status == "CONFIRMED":
                raise ValueError("Confirmed Decision is immutable")
            if group == "runs":
                if previous.status == "RUNNING" and obj.status not in TERMINAL:
                    raise ValueError("Invalid Run transition")
                frozen = ("provider_session_id", "provider_configuration_snapshot", "provider_readiness_snapshot", "run_id", "run_type", "parent_run_id", "decision_id", "applied_change_ids",
                          "eval_set_snapshot", "eval_set_hash", "evaluation_config_snapshot",
                          "evaluation_protocol_snapshot", "evaluation_protocol_hash", "agent_config_snapshot",
                          "inference_config_snapshot", "skill_version", "prompt_version", "knowledge_version",
                          "routing_config_version", "runtime_policy_snapshot", "runtime_start_snapshot", "execution_order")
                if any(getattr(previous, k) != getattr(obj, k) for k in frozen):
                    raise ValueError("Run configuration is frozen")
            if group == "changes" and previous.implemented_status in {"APPLIED", "NOOP", "FAILED", "UNSUPPORTED"}:
                # Only rollback evidence can be appended after apply finishes.
                mutable = {"rollback_status", "rollback_at", "application_evidence", "error"}
                if any(previous.model_dump()[k] != data[k] for k in data if k not in mutable):
                    raise ValueError("Sealed Change apply evidence is immutable")
                for k, v in previous.application_evidence.items():
                    if obj.application_evidence.get(k) != v:
                        raise ValueError("Cannot erase prior application evidence")
        if group == "runs" and obj.status in TERMINAL:
            data["artifact_hash"] = digest({k: v for k, v in data.items() if k != "artifact_hash"})
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {"sha256": digest(data), "artifact": data}
        fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded(envelope))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return self.get(group, getattr(obj, id_field),revision)
