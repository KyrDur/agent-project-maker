"""Small, validated evaluation objects. One task has one machine decision."""
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["PASS", "FAIL", "INVALID"]
ExecutionStatus = Literal["SUCCESS", "FAILED", "INVALID", "UNKNOWN"]
JudgeStatus = Literal["SUCCESS", "FAILED", "NOT_RUN", "NOT_REQUIRED"]
ReviewStatus = Literal["NOT_REQUIRED", "PENDING", "COMPLETED"]
DIMENSIONS = ("relevance", "accuracy", "completeness", "helpfulness")


class ExecutableRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["required_tool", "expected_intent", "forbidden_claim"]
    tool: Optional[str] = None
    target: Optional[str] = None

    @model_validator(mode="after")
    def valid_rule(self):
        if self.type == "required_tool":
            if not self.tool or not self.tool.strip() or self.target is not None:
                raise ValueError("required_tool needs tool only")
        elif self.type == "expected_intent":
            if not self.target or not self.target.strip() or self.tool is not None:
                raise ValueError("expected_intent needs target only")
        elif self.target != "refund_completed_without_evidence" or self.tool is not None:
            raise ValueError("unsupported forbidden_claim target")
        return self


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str = Field(min_length=1)
    title: str = ""
    scenario: Optional[str] = None
    input: Optional[str] = None
    turns: list[str] = Field(default_factory=list)
    test_conditions: Optional[str] = None
    must_do: list[str] = Field(default_factory=list)
    must_not_do: list[str] = Field(default_factory=list)
    executable_rules: list[ExecutableRule] = Field(default_factory=list)
    judge_method: Literal["rule", "tool trace", "LLM judge", "human review"] = "LLM judge"
    source: Literal["platform_preset", "user_modified", "user_created", "ai_generated"] = "platform_preset"
    legacy: bool = False
    user_id: str = "eval_user"
    conv_id: Optional[str] = None

    @model_validator(mode="after")
    def valid_input(self):
        if self.turns and self.input is not None:
            raise ValueError("use input or turns, not both")
        questions = self.turns or ([self.input] if self.input is not None else [])
        if not questions or any(not q.strip() for q in questions):
            raise ValueError("non-empty input/turns required")
        if self.judge_method in ("rule", "tool trace") and not self.executable_rules:
            raise ValueError("rule evaluation requires executable_rules")
        return self

    @property
    def questions(self):
        return self.turns or [self.input]


@dataclass(frozen=True)
class QualityScores:
    relevance: Optional[float] = None
    accuracy: Optional[float] = None
    completeness: Optional[float] = None
    helpfulness: Optional[float] = None
    judge_failed: bool = False
    error: Optional[str] = None

    @property
    def valid(self):
        return not self.judge_failed and all(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and 0 <= v <= 1
            for v in (getattr(self, key) for key in DIMENSIONS)
        )

    @property
    def overall(self):
        return statistics.mean(getattr(self, k) for k in DIMENSIONS) if self.valid else None

    def to_scores(self):
        return {**{k: getattr(self, k) for k in DIMENSIONS}, "overall": self.overall} if self.valid else {}


class TurnEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    turn: int
    question: str
    response: str = ""
    execution_status: ExecutionStatus
    execution_error: Optional[str] = None
    request_id: str = ""
    agent_type: Optional[str] = None
    intent: Optional[str] = None
    routing_reason: str = ""
    routing_confidence: float = 0
    tools_used: list[str] = Field(default_factory=list)
    tool_traces: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float = 0


class CaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    case_id: str
    case: Optional[EvaluationCase] = None
    execution_status: ExecutionStatus
    judge_status: JudgeStatus
    evaluation_error: Optional[str] = None
    judge_error: Optional[str] = None
    original_status: Status
    original_reason: str
    scores: dict[str, float] = Field(default_factory=dict)
    turn_evidence: list[TurnEvidence] = Field(default_factory=list)
    hard_rule_violations: list[str] = Field(default_factory=list)
    human_final_status: Optional[Status] = None
    human_reason: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_status: ReviewStatus = "NOT_REQUIRED"
    hard_rule_override: bool = False
    legacy: bool = False
    legacy_notice: Optional[str] = None
    legacy_original_results: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def adapt_existing_review(cls, data):
        # Older Phase 2 reports retain their original decisions and evidence.
        if isinstance(data, dict) and "review_status" not in data:
            data = dict(data)
            case = data.get("case")
            method = case.get("judge_method") if isinstance(case, dict) else getattr(case, "judge_method", None)
            pending = (method == "human review" and data.get("execution_status") == "SUCCESS"
                       and data.get("judge_status") == "NOT_RUN" and data.get("original_status") == "INVALID"
                       and not data.get("evaluation_error"))
            data["review_status"] = ("COMPLETED" if data.get("human_final_status") is not None
                                     else "PENDING" if pending else "NOT_REQUIRED")
            data.setdefault("hard_rule_override", bool(data.get("hard_rule_violations")
                                                       and data.get("human_final_status") == "PASS"))
        return data

    @model_validator(mode="after")
    def enforce_invalid(self):
        if self.execution_status != "SUCCESS" or self.judge_status == "FAILED" or self.evaluation_error:
            if self.original_status != "INVALID" or self.scores or self.human_final_status in ("PASS", "FAIL"):
                raise ValueError("无效执行或 Judge 不能带有效质量分或 PASS/FAIL")
        if self.judge_status == "SUCCESS":
            quality = QualityScores(**{k: self.scores.get(k) for k in DIMENSIONS})
            if not quality.valid or self.scores.get("overall") != quality.overall:
                raise ValueError("质量评分缺失、非有限或越界")
        if self.human_final_status is not None and (not self.human_reason or not self.human_reason.strip() or not self.reviewed_at):
            raise ValueError("人工判定需要 reason 和 reviewed_at")
        if (self.review_status == "COMPLETED") != (self.human_final_status is not None):
            raise ValueError("COMPLETED 必须对应已记录的人工判定")
        pending = (self.case is not None and self.case.judge_method == "human review"
                   and self.execution_status == "SUCCESS" and self.judge_status == "NOT_RUN"
                   and self.original_status == "INVALID" and self.evaluation_error is None
                   and self.human_final_status is None)
        if (self.review_status == "PENDING") != pending:
            raise ValueError("PENDING 仅用于有效执行后等待人工复核的任务")
        if self.hard_rule_violations and self.human_final_status == "PASS" and not self.hard_rule_override:
            raise ValueError("人工覆盖 Hard Rule FAIL 必须记录 hard_rule_override")
        if self.hard_rule_violations and self.original_status not in ("FAIL", "INVALID"):
            raise ValueError("机器规则违规不能保存为机器 PASS")
        if self.hard_rule_override and (not self.hard_rule_violations or self.human_final_status is None):
            raise ValueError("hard_rule_override 必须保留规则违规与人工复核证据")
        return self

    @property
    def final_status(self):
        return self.human_final_status or self.original_status

    @property
    def exclude_from_quality_metrics(self):
        return (self.execution_status != "SUCCESS" or self.judge_status == "FAILED"
                or self.evaluation_error is not None or self.final_status == "INVALID")

    @property
    def passed(self):
        return self.final_status == "PASS"

    @property
    def test_id(self):
        return self.case_id

    @property
    def metadata(self):
        last = self.turn_evidence[-1].model_dump() if self.turn_evidence else {}
        return {**last, "judge_failed": self.judge_status == "FAILED", "judge_error": self.judge_error,
                "legacy_notice": self.legacy_notice}

    def review(self, status: Status, reason: str):
        if status not in ("PASS", "FAIL", "INVALID") or not reason or not reason.strip():
            raise ValueError("人工判定必须提供合法状态和非空 reason")
        # A reviewer cannot turn an unexecuted/unjudged task into a quality conclusion.
        if status != "INVALID" and (self.execution_status != "SUCCESS"
                or self.judge_status == "FAILED" or self.evaluation_error is not None):
            raise ValueError("执行或评测无效的结果不能人工改为有效质量结论")
        return self.model_validate({**self.model_dump(), "human_final_status": status, "human_reason": reason.strip(),
                                   "review_status": "COMPLETED",
                                   "hard_rule_override": self.hard_rule_override or bool(self.hard_rule_violations and status == "PASS"),
                                   "reviewed_at": datetime.now(timezone.utc).isoformat()})

    def to_dict(self):
        return {**self.model_dump(), "final_status": self.final_status,
                "exclude_from_quality_metrics": self.exclude_from_quality_metrics,
                "test_id": self.test_id, "passed": self.passed,
                "detail": self.human_reason or self.original_reason, "metadata": self.metadata}
