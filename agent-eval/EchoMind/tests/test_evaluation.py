"""Phase 2 contracts: scripted providers verify semantics, not model quality."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.config import EvaluationConfig
from evaluation.evaluator import EndToEndEvaluator, IntentEvaluator, IntentTestCase, LLMJudge
from evaluation.legacy import adapt_case
from evaluation.models import CaseResult, EvaluationCase, QualityScores, DIMENSIONS
from evaluation.metrics import dialog_metrics
from agents.agent_orchestrator import AgentType
from core.intent_recognizer import IntentCategory


def run(coro):
    return asyncio.run(coro)


class Provider:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.calls = payload, error, []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(content=[{'type': 'text', 'text': json.dumps(self.payload)}])


def quality(score):
    return dict(relevance=score, accuracy=score, completeness=score, helpfulness=score)


class Orch:
    def __init__(self, status='SUCCESS', error=None, answer='请提供订单号核验退款申请。', traces=None):
        self.calls, self.status, self.error, self.answer, self.traces = [], status, error, answer, traces or []

    async def run(self, req):
        self.calls.append(req)
        if self.error:
            raise self.error
        return SimpleNamespace(response=self.answer, execution_status=self.status,
            agent_type=AgentType.BILLING, intent=IntentCategory.REFUND, request_id='request',
            routing_reason='refund to billing', routing_confidence=.9,
            tools_used=[t['tool_name'] for t in self.traces], tool_traces=self.traces)


def evaluator(score=.8, payload=None, judge_error=None, orch=None, config=None):
    ev = EndToEndEvaluator.__new__(EndToEndEvaluator)
    ev._history, ev._baseline, ev._baseline_path = [], None, None
    ev._orchestrator = orch or Orch()
    provider = Provider(quality(score) if payload is None else payload, judge_error)
    ev._judge = LLMJudge(provider, 'scripted-judge')
    ev._config = config or EvaluationConfig()
    class Recognizer:
        async def recognize(self, message, history=None):
            return SimpleNamespace(intent=IntentCategory.REFUND, confidence=1, reasoning='fixture')
    ev._intent_evaluator = IntentEvaluator(Recognizer())
    return ev, provider


def case(**kwargs):
    return dict(case_id='refund', input='退款', **kwargs)


def test_judge_failure_is_invalid_and_excluded():
    ev, _ = evaluator(judge_error=RuntimeError('private-provider-body'))
    report = run(ev.run(dialog_cases=[case()]))
    r = report.results[0]
    assert (r.execution_status, r.judge_status, r.final_status) == ('SUCCESS', 'FAILED', 'INVALID')
    assert r.exclude_from_quality_metrics and r.scores == {}
    assert report.avg_scores == {} and report.pass_rate is None
    assert report.dialog_case_metrics['valid'] == 0
    assert report.dialog_case_metrics['judge_errors'] == 1
    assert 'private-provider-body' not in json.dumps(report.to_dict())


@pytest.mark.parametrize('bad', [{}, {'relevance': .9}, quality(float('nan')), quality(float('inf')),
                                 quality(-.1), quality(1.1), quality(True), quality('0.9')])
def test_bad_judge_payload_never_becomes_quality(bad):
    ev, _ = evaluator(payload=bad)
    r = run(ev.run(dialog_cases=[case()])).results[0]
    assert r.final_status == 'INVALID' and not r.scores and r.judge_status == 'FAILED'


def test_three_turn_task_is_one_case_and_one_judgement():
    ev, provider = evaluator()
    report = run(ev.run(dialog_cases=[{'case_id': 'multi', 'turns': ['退款', '订单123', '多久到账']}]))
    assert report.total == 1 and report.dialog_case_metrics['valid'] == 1
    assert len(report.results[0].turn_evidence) == 3 and len(provider.calls) == 1
    assert '订单123' in provider.calls[0]['messages'][0]['content']
    assert len(ev._orchestrator.calls[-1].history) == 4


def test_intent_and_dialog_have_independent_denominators():
    ev, _ = evaluator()
    report = run(ev.run(intent_cases=[IntentTestCase('退款', 'refund'), IntentTestCase('退款', 'greeting')],
                        dialog_cases=[case()]))
    assert report.intent_metrics['total'] == 2 and report.intent_metrics['correct'] == 1
    assert report.total == 1 and report.passed == 1 and report.pass_rate == 1
    assert 'intent_accuracy' not in report.avg_scores
    assert report.to_dict()['metrics_scope'] == 'dialog_cases_only'


@pytest.mark.parametrize('orch', [Orch(status='FAILED'), Orch(status='UNKNOWN'), Orch(answer=''),
                                 Orch(error=RuntimeError('offline'))])
def test_invalid_execution_never_calls_judge_even_with_high_score(orch):
    ev, provider = evaluator(score=1, orch=orch)
    report = run(ev.run(dialog_cases=[case()]))
    assert report.results[0].final_status == 'INVALID' and not provider.calls
    assert report.results[0].judge_status == 'NOT_RUN' and report.dialog_case_metrics['valid'] == 0


def test_invalid_execution_cannot_accept_stale_high_score():
    with pytest.raises(ValueError):
        CaseResult(case_id='old', execution_status='FAILED', judge_status='SUCCESS',
                   original_status='PASS', original_reason='old judgement', scores={**quality(1), 'overall': 1})


def test_hard_rule_overrides_high_quality_without_calling_judge():
    ev, provider = evaluator(score=.95)
    report = run(ev.run(dialog_cases=[case(executable_rules=[{'type':'required_tool', 'tool':'check_billing_fields'}])]))
    r = report.results[0]
    assert r.final_status == 'FAIL' and r.judge_status == 'NOT_REQUIRED' and not provider.calls
    assert report.dialog_case_metrics['hard_rule_violations'] == 1
    assert report.dialog_case_metrics['valid'] == 1


@pytest.mark.parametrize('score,status', [(0.75, 'PASS'), (.749999, 'FAIL'), (0, 'FAIL'), (1, 'PASS')])
def test_quality_threshold_boundary(score, status):
    ev, _ = evaluator(score=score)
    report = run(ev.run(dialog_cases=[case()]))
    assert report.results[0].final_status == status
    assert report.evaluation_config['quality_thresholds'] == EvaluationConfig().quality_thresholds.model_dump()


def test_configured_threshold_used_once():
    ev, _ = evaluator(score=.8, config=EvaluationConfig(quality_thresholds={'accuracy': .9}))
    report = run(ev.run(dialog_cases=[case()]))
    assert report.results[0].final_status == 'FAIL'
    assert report.evaluation_config['quality_thresholds']['accuracy'] == .9
    assert report.evaluation_config['quality_thresholds']['relevance'] == .75
    assert report.results[0].scores['overall'] == .8
    assert 'accuracy' in report.results[0].original_reason


@pytest.mark.parametrize('dimension', DIMENSIONS)
@pytest.mark.parametrize('low,high', [(.2, 1), (.74, .76)])
def test_one_low_dimension_cannot_be_compensated_by_average(dimension, low, high):
    payload = quality(high)
    payload[dimension] = low
    ev, _ = evaluator(payload=payload)
    report = run(ev.run(dialog_cases=[case()]))
    result = report.results[0]
    assert result.scores['overall'] >= .75
    assert result.final_status == 'FAIL' and result.judge_status == 'SUCCESS'
    assert report.dialog_case_metrics['valid'] == 1 and report.passed == 0
    assert dimension in result.original_reason


def test_requested_compensating_example_fails_at_average_boundary():
    ev, _ = evaluator(payload=dict(relevance=1, accuracy=.2, completeness=.9, helpfulness=.9))
    result = run(ev.run(dialog_cases=[case()])).results[0]
    assert result.scores['overall'] == .75 and result.final_status == 'FAIL'


def test_each_configured_dimension_passes_at_its_own_boundary():
    thresholds = dict(relevance=.7, accuracy=.9, completeness=.6, helpfulness=.8)
    ev, _ = evaluator(payload=thresholds, config=EvaluationConfig(quality_thresholds=thresholds))
    report = run(ev.run(dialog_cases=[case()]))
    assert report.results[0].final_status == 'PASS'
    assert report.evaluation_config == {'quality_thresholds': thresholds}


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -.1, 1.1])
def test_dimension_threshold_config_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        EvaluationConfig(quality_thresholds={'accuracy': bad})


def test_natural_language_expectation_is_judge_context_not_a_hard_rule():
    ev, provider = evaluator(score=.95, orch=Orch(answer='退款已经完成'))
    report = run(ev.run(dialog_cases=[case(must_not_do=['声称退款已经完成'])]))
    assert report.results[0].final_status == 'PASS' and not report.results[0].hard_rule_violations
    assert '声称退款已经完成' in provider.calls[0]['messages'][0]['content']


@pytest.mark.parametrize('answer,status', [('退款已经完成。','FAIL'), ('不能声称退款已经完成。','PASS'),
                                         ('退款已成功。','FAIL')])
def test_explicit_forbidden_claim_rule(answer, status):
    ev, _ = evaluator(orch=Orch(answer=answer))
    r = run(ev.run(dialog_cases=[case(executable_rules=[{'type':'forbidden_claim',
                          'target':'refund_completed_without_evidence'}])])).results[0]
    assert r.final_status == status


def test_required_tool_requires_successful_trace_not_just_tools_used():
    for success, expected in [(False, 'FAIL'), (True, 'PASS')]:
        ev, _ = evaluator(orch=Orch(traces=[{'tool_name':'check_billing_fields','success':success}]))
        r = run(ev.run(dialog_cases=[case(executable_rules=[{'type':'required_tool','tool':'check_billing_fields'}])])).results[0]
        assert r.final_status == expected


@pytest.mark.parametrize('reason', ['', '   ', None])
def test_review_requires_reason(reason):
    ev, _ = evaluator(score=.2)
    report = run(ev.run(dialog_cases=[case()]))
    with pytest.raises(ValueError):
        ev.review_latest(report.timestamp, 'refund', 'PASS', reason)
    assert report.results[0].human_final_status is None


def test_review_changes_statistics_but_preserves_machine_judgement():
    ev, _ = evaluator(score=.2)
    report = run(ev.run(dialog_cases=[case()]))
    original = report.results[0]
    ev.review_latest(report.timestamp, 'refund', 'PASS', '人工核对业务边界正确')
    reviewed = report.results[0]
    assert original.original_status == reviewed.original_status == 'FAIL'
    assert original.original_reason == reviewed.original_reason
    assert reviewed.human_final_status == reviewed.final_status == 'PASS' and reviewed.reviewed_at
    assert reviewed.review_status == 'COMPLETED' and not reviewed.hard_rule_override
    assert report.passed == 1 and report.pass_rate == 1
    ev.review_latest(report.timestamp, 'refund', 'INVALID', '证据不足')
    assert report.dialog_case_metrics['valid'] == 0 and report.avg_scores == {}
    with pytest.raises(ValueError):
        ev.review_latest('stale', 'refund', 'PASS', 'reason')


def test_review_does_not_make_judge_error_valid():
    ev, _ = evaluator(judge_error=RuntimeError('offline'))
    report = run(ev.run(dialog_cases=[case()]))
    with pytest.raises(ValueError):
        ev.review_latest(report.timestamp, 'refund', 'PASS', 'arbitrary')


def test_human_only_review_can_form_valid_result_without_scores():
    ev, provider = evaluator()
    report = run(ev.run(dialog_cases=[case(judge_method='human review')]))
    assert report.results[0].final_status == 'INVALID' and not provider.calls
    assert report.results[0].review_status == 'PENDING' and report.results[0].exclude_from_quality_metrics
    assert report.dialog_case_metrics['pending_human_reviews'] == 1
    assert all(report.dialog_case_metrics[k] == 0 for k in ('agent_errors', 'judge_errors', 'evaluation_errors'))
    assert report.recommendations == ['当前有任务等待人工复核。']
    decoded = EndToEndEvaluator._report_from_dict(report.to_dict())
    assert decoded.results[0].review_status == 'PENDING'
    ev.review_latest(report.timestamp, 'refund', 'PASS', '人工核对完整回答')
    assert report.dialog_case_metrics['valid'] == 1 and report.avg_scores == {}
    assert report.results[0].review_status == 'COMPLETED'
    assert report.dialog_case_metrics['pending_human_reviews'] == 0


def test_pending_review_is_separate_from_real_errors_in_mixed_report():
    ev, _ = evaluator()
    pending = run(ev.run(dialog_cases=[case(judge_method='human review')])).results[0]
    ev, _ = evaluator(orch=Orch(status='FAILED'))
    agent = run(ev.run(dialog_cases=[case(judge_method='human review')])).results[0]
    ev, _ = evaluator(judge_error=RuntimeError('offline'))
    judge = run(ev.run(dialog_cases=[case()])).results[0]
    ev, _ = evaluator()
    invalid = run(ev.run(dialog_cases=[{}])).results[0]
    metrics = dialog_metrics([pending, agent, judge, invalid])
    assert metrics['pending_human_reviews'] == 1 and metrics['invalid'] == 4
    assert metrics['agent_errors'] == metrics['judge_errors'] == metrics['evaluation_errors'] == 1
    assert all(r.review_status == 'NOT_REQUIRED' for r in (agent, judge, invalid))


def test_duplicate_human_cases_are_evaluation_errors_not_pending():
    ev, _ = evaluator()
    report = run(ev.run(dialog_cases=[case(judge_method='human review'), case(judge_method='human review')]))
    assert report.dialog_case_metrics['pending_human_reviews'] == 0
    assert report.dialog_case_metrics['evaluation_errors'] == 2


def test_hard_rule_review_override_is_explicit_and_preserves_evidence():
    ev, _ = evaluator()
    report = run(ev.run(dialog_cases=[case(executable_rules=[{'type':'required_tool', 'tool':'check_billing_fields'}])]))
    original = report.results[0]
    assert original.original_status == 'FAIL' and not original.hard_rule_override
    ev.review_latest(report.timestamp, 'refund', 'PASS', '复核确认此场景无需调用该工具，人工覆盖机器规则')
    result = report.results[0]
    assert result.original_status == 'FAIL' and result.human_final_status == result.final_status == 'PASS'
    assert result.hard_rule_override and result.review_status == 'COMPLETED'
    assert result.hard_rule_violations == original.hard_rule_violations
    assert result.original_reason == original.original_reason
    assert result.case == original.case and result.turn_evidence == original.turn_evidence
    assert result.human_reason and result.reviewed_at
    assert report.passed == 1 and report.dialog_case_metrics['hard_rule_violations'] == 1
    assert report.avg_scores == {}  # an override does not fabricate Judge scores
    decoded = EndToEndEvaluator._report_from_dict(report.to_dict())
    assert decoded.results[0].hard_rule_override and decoded.results[0].original_status == 'FAIL'
    assert decoded.results[0].human_reason == result.human_reason
    with pytest.raises(ValueError):
        CaseResult.model_validate({**result.model_dump(), 'hard_rule_override': False})
    ev.review_latest(report.timestamp, 'refund', 'INVALID', '后续复核证据不足')
    assert report.results[0].hard_rule_override and report.results[0].hard_rule_violations
    assert report.dialog_case_metrics['valid'] == 0


def test_agent_error_still_cannot_be_reviewed_into_pass():
    ev, _ = evaluator(orch=Orch(status='FAILED'))
    report = run(ev.run(dialog_cases=[case()]))
    with pytest.raises(ValueError):
        ev.review_latest(report.timestamp, 'refund', 'PASS', 'reason does not repair execution')
    assert report.results[0].review_status == 'NOT_REQUIRED'


@pytest.mark.parametrize('method', ['human review', 'LLM judge'])
def test_prior_phase2_review_fields_adapt_without_rewriting_source(method):
    ev, _ = evaluator()
    report = run(ev.run(dialog_cases=[case(judge_method=method,
        executable_rules=[] if method == 'human review' else [{'type':'required_tool', 'tool':'check_billing_fields'}])]))
    if method == 'LLM judge':
        ev.review_latest(report.timestamp, 'refund', 'PASS', '旧版人工覆盖规则理由')
    raw = report.to_dict()
    raw['results'][0].pop('review_status')
    raw['results'][0].pop('hard_rule_override')
    before = copy.deepcopy(raw)
    decoded = EndToEndEvaluator._report_from_dict(raw)
    assert raw == before
    result = decoded.results[0]
    assert result.review_status == ('PENDING' if method == 'human review' else 'COMPLETED')
    assert result.hard_rule_override == (method == 'LLM judge')
    assert result.original_status == raw['results'][0]['original_status']
    assert result.original_reason == raw['results'][0]['original_reason']


def test_legacy_failed_placeholder_is_read_only_and_excluded():
    path = Path(__file__).parents[1] / 'data/eval/baseline.json'
    before = path.read_bytes()
    raw = json.loads(before)
    original = copy.deepcopy(raw)
    report = EndToEndEvaluator._report_from_dict(raw)
    assert raw == original and path.read_bytes() == before
    assert report.avg_scores == {} and report.dialog_case_metrics['valid'] == 0
    assert report.intent_metrics['total'] == 11
    assert report.total == 5  # seven historic turns belong to five dialog Cases
    assert all('Legacy Invalid Judge Result' in r.legacy_notice for r in report.results)
    assert all(r.final_status == 'INVALID' and r.legacy_original_results for r in report.results)


@pytest.mark.parametrize('legacy', [{'question':'退款'}, {'turns':['退款', '订单123']}])
def test_legacy_adapter_preserves_input_without_invented_expectations(legacy):
    original = copy.deepcopy(legacy)
    normalized = adapt_case(legacy)
    assert normalized.legacy and normalized.must_do == normalized.must_not_do == []
    assert normalized.test_conditions is None and legacy == original
    ev, _ = evaluator()
    report = run(ev.run(dialog_cases=[legacy]))
    assert report.total == 1 and report.results[0].final_status == 'PASS'


@pytest.mark.parametrize('bad', [{}, {'case_id':'bad','turns':[]}, {'case_id':'bad','input':' '},
    {'case_id':'bad','input':'退款','executable_rules':[{'type':'made_up'}]},
    {'case_id':'bad','input':'退款','judge_method':'rule'}])
def test_bad_case_is_counted_as_invalid_not_silently_skipped(bad):
    ev, provider = evaluator()
    report = run(ev.run(dialog_cases=[bad]))
    assert report.total == 1 and report.results[0].final_status == 'INVALID' and not provider.calls
    assert report.dialog_case_metrics['evaluation_errors'] == 1


def test_serialized_report_roundtrip_and_review_preserved():
    ev, _ = evaluator(score=.2)
    report = run(ev.run(dialog_cases=[case()]))
    ev.review_latest(report.timestamp, 'refund', 'PASS', 'reason')
    decoded = EndToEndEvaluator._report_from_dict(report.to_dict())
    assert decoded.results[0].original_status == 'FAIL' and decoded.results[0].final_status == 'PASS'
    assert decoded.passed == 1


def test_baseline_file_is_not_overwritten_by_evaluation(tmp_path):
    ev, _ = evaluator()
    ev._baseline_path = tmp_path / 'baseline.json'
    ev._baseline_path.write_text('historical data')
    run(ev.run(dialog_cases=[case()]))
    assert ev._baseline_path.read_text() == 'historical data'


def test_missing_quality_result_cannot_be_valid_success():
    with pytest.raises(ValueError):
        CaseResult(case_id='missing', execution_status='SUCCESS', judge_status='SUCCESS',
                   original_status='PASS', original_reason='missing scores')


def test_hard_violation_in_early_turn_fails_whole_task():
    class EarlyClaim(Orch):
        async def run(self, req):
            self.answer = '退款已完成。' if not self.calls else '请进一步核验。'
            return await super().run(req)
    ev, provider = evaluator(orch=EarlyClaim())
    report = run(ev.run(dialog_cases=[{'case_id':'multi','turns':['退款','确认'],
        'executable_rules':[{'type':'forbidden_claim','target':'refund_completed_without_evidence'}]}]))
    assert report.total == 1 and report.results[0].final_status == 'FAIL' and not provider.calls


def test_model_rejects_forged_review_without_reason():
    with pytest.raises(ValueError):
        CaseResult(case_id='fake', execution_status='SUCCESS', judge_status='NOT_REQUIRED',
                   original_status='FAIL', original_reason='machine', human_final_status='PASS')


def test_mixed_valid_and_judge_error_denominator_and_average():
    ev, _ = evaluator()
    class MixedJudge:
        async def judge(self, question, response, context=None):
            return QualityScores(judge_failed=True) if question == 'invalid' else QualityScores(.8,.8,.8,.8)
    ev._judge = MixedJudge()
    report = run(ev.run(dialog_cases=[{'case_id':'a','input':'valid'}, {'case_id':'b','input':'invalid'}]))
    assert report.total == 2 and report.dialog_case_metrics['valid'] == 1
    assert report.passed == 1 and report.pass_rate == 1 and report.avg_scores['overall'] == .8
    assert report.dialog_case_metrics['quality_scored_cases'] == 1


def test_expected_intent_rule_and_rule_only_evaluation():
    ev, provider = evaluator()
    good = run(ev.run(dialog_cases=[case(judge_method='rule', executable_rules=[{'type':'expected_intent','target':'refund'}])]))
    bad = run(ev.run(dialog_cases=[case(judge_method='rule', executable_rules=[{'type':'expected_intent','target':'greeting'}])]))
    assert good.results[0].final_status == 'PASS' and bad.results[0].final_status == 'FAIL'
    assert not provider.calls


def test_agent_error_and_judge_error_are_separate_counts():
    ev, _ = evaluator(orch=Orch(status='FAILED'))
    report = run(ev.run(dialog_cases=[case()]))
    assert report.dialog_case_metrics['agent_errors'] == 1 and report.dialog_case_metrics['judge_errors'] == 0


def test_all_pass_recommendation_does_not_fabricate_failure():
    ev, _ = evaluator()
    report = run(ev.run(dialog_cases=[case()]))
    assert report.recommendations == ['当前评测集暂未发现失败项，可补充边界或多轮场景。']


def test_duplicate_case_ids_are_all_invalid_and_roundtrip_safely():
    ev, _ = evaluator()
    report = run(ev.run(dialog_cases=[case(), case(), case()]))
    assert report.total == 3 and report.dialog_case_metrics['valid'] == 0
    assert all(r.final_status == 'INVALID' and r.evaluation_error == 'duplicate case_id' for r in report.results)
    reread = EndToEndEvaluator._report_from_dict(report.to_dict())
    assert reread.total == 3 and reread.dialog_case_metrics['valid'] == 0
    with pytest.raises(ValueError):
        ev.review_latest(report.timestamp, 'refund', 'PASS', 'duplicate data cannot pass')
