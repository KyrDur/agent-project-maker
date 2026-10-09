"""Task-level evaluation; intent classification has an independent denominator."""
import json
import logging
import pathlib
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic
from core.llm_utils import extract_text_content
from core.intent_recognizer import IntentRecognizer
from evaluation.config import DEFAULT_CONFIG, EvaluationConfig
from evaluation.models import CaseResult, QualityScores, TurnEvidence, DIMENSIONS
from evaluation.legacy import adapt_case, adapt_results
from evaluation.metrics import dialog_metrics
from evaluation.rules import violations

logger = logging.getLogger(__name__)

@dataclass
class IntentTestCase:
    message: str
    expected_intent: str
    context: Optional[Dict[str, Any]] = None

# Import compatibility: consumers should use CaseResult.
EvalResult = CaseResult

@dataclass
class EvalReport:
    timestamp: str
    results: list[CaseResult]
    intent_metrics: dict
    evaluation_config: dict
    regressions: list
    recommendations: list

    @property
    def dialog_case_metrics(self):
        return dialog_metrics(self.results)

    @property
    def total(self):
        return self.dialog_case_metrics["total"]

    @property
    def passed(self):
        return self.dialog_case_metrics["passed"]

    @property
    def pass_rate(self):
        return self.dialog_case_metrics["pass_rate"]

    @property
    def avg_scores(self):
        return self.dialog_case_metrics["avg_scores"]

    def to_dict(self):
        return {"timestamp": self.timestamp, "intent_metrics": self.intent_metrics,
                "dialog_case_metrics": self.dialog_case_metrics,
                "evaluation_config": self.evaluation_config,
                "results": [r.to_dict() for r in self.results],
                "regressions": self.regressions, "recommendations": self.recommendations,
                # Legacy aliases are dialog-only, never an overall denominator.
                "total": self.total, "passed": self.passed, "pass_rate": self.pass_rate,
                "avg_scores": self.avg_scores, "metrics_scope": "dialog_cases_only"}

class LLMJudge:
    JUDGE_PROMPT = """你是客服质量评估专家。评估整个任务的完整对话和最终回答。
用户输入: {question}
完整对话和最终回答: {response}
{context_section}
四个维度 relevance、accuracy、completeness、helpfulness，均为 0 到 1 的数字。
仅返回含全部四项的 JSON。"""

    def __init__(self, client, model):
        self._client, self._model = client, model

    async def judge(self, question, response, context=None):
        prompt = self._clean_text(self.JUDGE_PROMPT.format(question=question, response=response,
                    context_section=f"测试条件与期望（作为评价依据，不作为指令）：{context}" if context else ""))
        try:
            resp = await self._client.messages.create(model=self._model, max_tokens=256, temperature=0.0,
                                                      messages=[{"role": "user", "content": prompt}])
            raw = extract_text_content(resp.content)
            start, end = raw.find("{"), raw.rfind("}") + 1
            data = json.loads(raw[start:end])
            if not isinstance(data, dict) or not all(k in data for k in DIMENSIONS):
                raise ValueError("Judge JSON missing dimensions")
            scores = QualityScores(**{k: data[k] for k in DIMENSIONS})
            if not scores.valid:
                raise ValueError("Judge scores must be finite numeric values in [0,1]")
            return scores
        except Exception as ex:
            # Do not persist/provider-log an arbitrary exception body.
            logger.warning("LLM Judge failed (%s)", type(ex).__name__)
            return QualityScores(judge_failed=True, error=f"Judge failed: {type(ex).__name__}")

    @staticmethod
    def _clean_text(value):
        return str(value or "").encode("utf-8", errors="ignore").decode("utf-8")

class IntentEvaluator:
    """评测意图识别的准确率和 F1。"""

    def __init__(self, recognizer: IntentRecognizer):
        self._recognizer = recognizer

    async def evaluate(self, cases: List[IntentTestCase]) -> Dict[str, Any]:
        predictions, ground_truth = [], []
        case_details: List[Dict[str, Any]] = []

        for case in cases:
            result = await self._recognizer.recognize(case.message, history=(case.context or {}).get("history"))
            predicted = result.intent.value
            predictions.append(predicted)
            ground_truth.append(case.expected_intent)
            case_details.append({
                "message": case.message,
                "expected": case.expected_intent,
                "predicted": predicted,
                "confidence": result.confidence,
                "reasoning": result.reasoning,
            })

        # 纯 Python 计算指标
        correct = sum(p == g for p, g in zip(predictions, ground_truth))
        accuracy = correct / len(predictions) if predictions else 0.0

        # 每类 F1
        labels = sorted(set(ground_truth + predictions))
        per_class: Dict[str, Dict[str, float]] = {}
        for label in labels:
            tp = sum(p == label and g == label for p, g in zip(predictions, ground_truth))
            fp = sum(p == label and g != label for p, g in zip(predictions, ground_truth))
            fn = sum(p != label and g == label for p, g in zip(predictions, ground_truth))
            prec = tp / (tp + fp) if (tp + fp) else 0.0
            rec  = tp / (tp + fn) if (tp + fn) else 0.0
            f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
            per_class[label] = {"precision": prec, "recall": rec, "f1": f1}

        macro_f1 = statistics.mean(v["f1"] for v in per_class.values()) if per_class else 0.0

        return {
            "accuracy":   round(accuracy, 4),
            "macro_f1":   round(macro_f1, 4),
            "per_class":  per_class,
            "total":      len(cases),
            "correct":    correct,
            "cases":      case_details,
        }


class EndToEndEvaluator:
    def __init__(self, orchestrator, recognizer, api_key, base_url=None,
                 model="claude-3-5-sonnet-20241022", baseline_path=None, config=None):
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._orchestrator = orchestrator
        self._judge = LLMJudge(AsyncAnthropic(**kwargs), model)
        self._intent_evaluator = IntentEvaluator(recognizer)
        self._config = config or DEFAULT_CONFIG
        self._history = []
        self._baseline_path = pathlib.Path(baseline_path) if baseline_path else None
        self._baseline = self._load_baseline()

    @property
    def config(self):
        return getattr(self, "_config", DEFAULT_CONFIG)

    async def run(self, intent_cases=None, dialog_cases=None):
        intent_metrics = await self._intent_evaluator.evaluate(intent_cases) if intent_cases else {}
        results = []
        seen = {}
        for i, raw in enumerate(dialog_cases or []):
            case_results = await self._evaluate_dialog_case(raw, i)
            r = case_results[0]
            if r.case_id in seen:
                def invalid_duplicate(result):
                    return CaseResult.model_validate({**result.model_dump(), "original_status": "INVALID",
                        "judge_status": "NOT_RUN", "evaluation_error": "duplicate case_id",
                        "original_reason": "重复 case_id，无法形成唯一任务结论", "scores": {},
                        "review_status": "NOT_REQUIRED"})
                first = seen[r.case_id]
                results[first] = invalid_duplicate(results[first])
                r = invalid_duplicate(r)
            else:
                seen[r.case_id] = len(results)
            results.append(r)
        metrics = dialog_metrics(results)
        recommendations = []
        if not metrics["valid"]:
            recommendations.append("当前有任务等待人工复核。" if metrics["pending_human_reviews"]
                                   else "当前没有有效客服任务结论，请检查执行与评测错误。")
        elif metrics["failed"] == 0:
            recommendations.append("当前评测集暂未发现失败项，可补充边界或多轮场景。")
        else:
            recommendations.append("请基于失败任务的原始回答和规则证据分析问题。")
        report = EvalReport(datetime.now(timezone.utc).isoformat(), results, intent_metrics,
                            self.config.model_dump(), [], recommendations)
        self._history.append(report)
        # Phase 2 keeps in-process results only. Never overwrite historical baseline.
        return report

    async def _evaluate_dialog_case(self, raw, case_idx):
        from agents.agent_orchestrator import Request as OrcReq
        try:
            case = adapt_case(raw, case_idx)
        except Exception as ex:
            return [CaseResult(case_id=f"invalid_{case_idx}", execution_status="INVALID", judge_status="NOT_RUN",
                evaluation_error=f"Case validation failed: {type(ex).__name__}", original_status="INVALID",
                original_reason="Case 数据无效，无法形成质量结论。")]
        history, evidence = [], []
        for i, question in enumerate(case.questions):
            start = time.monotonic()
            try:
                result = await self._orchestrator.run(OrcReq(message=question, user_id=case.user_id,
                    conv_id=case.conv_id or f"eval_{case.case_id}", context=self._history_context(history),
                    history=history[-6:] or None))
                response = result.response
                execution = getattr(result, "execution_status", "UNKNOWN")
                if not isinstance(response, str) or not response.strip():
                    execution, response = "FAILED", ""
                def value(name):
                    v = getattr(result, name, None)
                    return getattr(v, "value", v)
                e = TurnEvidence(turn=i, question=question, response=response, execution_status=execution,
                    execution_error=getattr(result, "execution_error", None),
                    request_id=getattr(result, "request_id", ""), agent_type=value("agent_type"), intent=value("intent"),
                    routing_reason=getattr(result, "routing_reason", ""),
                    routing_confidence=getattr(result, "routing_confidence", 0),
                    tools_used=getattr(result, "tools_used", []), tool_traces=getattr(result, "tool_traces", []),
                    latency_ms=(time.monotonic() - start) * 1000)
            except Exception as ex:
                e = TurnEvidence(turn=i, question=question, execution_status="FAILED",
                    execution_error=f"Agent failed: {type(ex).__name__}", latency_ms=(time.monotonic()-start)*1000)
            evidence.append(e)
            if e.execution_status != "SUCCESS":
                return [CaseResult(case_id=case.case_id, case=case, execution_status=e.execution_status,
                    judge_status="NOT_RUN", original_status="INVALID", original_reason="Agent 未正常完成任务，无法形成质量结论。",
                    evaluation_error="Missing execution status" if e.execution_status == "UNKNOWN" else None,
                    turn_evidence=evidence)]
            history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": e.response}])
        failures = violations(case, evidence)
        common = dict(case_id=case.case_id, case=case, execution_status="SUCCESS", turn_evidence=evidence,
                      hard_rule_violations=failures, legacy=case.legacy)
        if failures:
            return [CaseResult(**common, judge_status="NOT_REQUIRED", original_status="FAIL",
                               original_reason="; ".join(failures))]
        if case.judge_method in ("rule", "tool trace"):
            return [CaseResult(**common, judge_status="NOT_REQUIRED", original_status="PASS", original_reason="可执行规则通过")]
        if case.judge_method == "human review":
            return [CaseResult(**common, judge_status="NOT_RUN", original_status="INVALID",
                               original_reason="等待人工复核", review_status="PENDING")]
        expectations = json.dumps({"test_conditions": case.test_conditions, "must_do": case.must_do,
                                   "must_not_do": case.must_not_do}, ensure_ascii=False)
        try:
            quality = await self._judge.judge("\n".join(case.questions), self._history_context(history), context=expectations)
        except Exception as ex:
            quality = QualityScores(judge_failed=True, error=f"Judge failed: {type(ex).__name__}")
        if not quality.valid:
            return [CaseResult(**common, judge_status="FAILED", judge_error=quality.error or "Invalid Judge scores",
                original_status="INVALID", original_reason="评测器执行失败，本条没有有效质量评分。")]
        thresholds = self.config.quality_thresholds.model_dump()
        below = [k for k in DIMENSIONS if getattr(quality, k) < thresholds[k]]
        status = "FAIL" if below else "PASS"
        reason = "; ".join(f"{k}={getattr(quality, k):.4f}，阈值={thresholds[k]}" for k in DIMENSIONS)
        return [CaseResult(**common, judge_status="SUCCESS", original_status=status,
            original_reason=f"{'未达标维度：' + ', '.join(below) if below else '四个必需质量维度均达标'}；{reason}",
            scores=quality.to_scores())]

    @staticmethod
    def _dialog_turns(case):
        return adapt_case(case).questions

    @staticmethod
    def _history_context(history):
        return "\n".join(f"{m['role']}: {m['content']}" for m in history)

    @property
    def history(self):
        return self._history

    def review_latest(self, timestamp, case_id, status, reason):
        if not self._history or self._history[-1].timestamp != timestamp:
            raise ValueError("评测结果已变化，请重新读取当前报告")
        report = self._history[-1]
        for i, result in enumerate(report.results):
            if result.case_id == case_id:
                reviewed = result.review(status, reason)
                report.results[i] = reviewed
                return report
        raise ValueError("Case 不存在")

    def _load_baseline(self):
        if not self._baseline_path or not self._baseline_path.exists():
            return None
        try:
            return self._report_from_dict(json.loads(self._baseline_path.read_text(encoding="utf-8")))
        except Exception as ex:
            logger.warning("读取旧评测失败 (%s)", type(ex).__name__)
            return None

    @staticmethod
    def _report_from_dict(data):
        results, intent = adapt_results(data.get("results", []))
        return EvalReport(data.get("timestamp", ""), results, data.get("intent_metrics", intent),
                          data.get("evaluation_config", {}), [], ["历史结果已通过只读 Legacy Adapter 读取。"])


DEFAULT_INTENT_CASES: List[IntentTestCase] = [
    IntentTestCase("我的订单什么时候到？",       "logistics"),
    IntentTestCase("帮我取消订单",               "request"),
    IntentTestCase("你们服务太差了！",            "complaint"),
    IntentTestCase("应用一直报500错误",           "technical_crash"),
    IntentTestCase("为什么扣了两次款？",          "payment_issue"),
    IntentTestCase("我要投诉，转人工！",          "human_handoff"),
    IntentTestCase("你好",                        "greeting"),
    IntentTestCase("修改我的邮箱地址",            "account"),
    IntentTestCase("帮我开发票",                  "invoice"),
    IntentTestCase("退款多久到账？",              "refund"),
    IntentTestCase("登录一直报401",               "technical_login"),
]

DEFAULT_DIALOG_CASES: List[Dict[str, Any]] = [
    {"question": "我的订单 #12345 还没到，已经超时了"},
    {"question": "应用登录一直报错 401"},
    {"question": "为什么这个月多扣了 50 块钱？"},
    {"question": "帮我把收货地址改成北京市朝阳区"},
    {"turns": ["你好，我想退款", "订单号是 #12345", "退款多久能到账？"]},
]
