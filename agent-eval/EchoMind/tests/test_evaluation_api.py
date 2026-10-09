"""Real FastAPI serializer/review routes, injected evaluation provider, no services."""
from fastapi.testclient import TestClient
from api import main
from test_evaluation import evaluator


def test_api_groups_case_schema_and_review(monkeypatch):
    ev, _ = evaluator(score=.2)
    monkeypatch.setattr(main, '_evaluator', ev)
    client = TestClient(main.app)
    response = client.post('/eval/run', json={'intent_cases': [], 'dialog_cases': [
        {'case_id': 'api-task', 'turns': ['退款', '订单123', '到账时间'], 'must_do':['明确需要核验']} ]})
    assert response.status_code == 200
    report = response.json()
    assert report['dialog_case_metrics']['total'] == 1 and report['intent_metrics'] == {}
    assert len(report['results'][0]['turn_evidence']) == 3
    assert report['results'][0]['final_status'] == 'FAIL'
    for reason in ['', '   ']:
        bad = client.post('/eval/review', json={'timestamp':report['timestamp'],'case_id':'api-task',
            'human_final_status':'PASS','human_reason':reason})
        assert bad.status_code in (400, 422)
    review = client.post('/eval/review', json={'timestamp':report['timestamp'],'case_id':'api-task',
            'human_final_status':'PASS','human_reason':'核对回答证据后人工改判'})
    assert review.status_code == 200
    updated = review.json()
    assert updated['dialog_case_metrics']['passed'] == 1
    assert updated['results'][0]['original_status'] == 'FAIL'
    assert updated['results'][0]['human_final_status'] == 'PASS'
    assert updated['results'][0]['reviewed_at']
    assert updated['results'][0]['review_status'] == 'COMPLETED'
    assert updated['results'][0]['hard_rule_override'] is False


def test_api_legacy_question_and_invalid_judge(monkeypatch):
    ev, _ = evaluator(judge_error=RuntimeError('offline'))
    monkeypatch.setattr(main, '_evaluator', ev)
    client = TestClient(main.app)
    response = client.post('/eval/run', json={'intent_cases':[], 'dialog_cases':[{'question':'退款'}]})
    assert response.status_code == 200
    report = response.json()
    assert report['results'][0]['legacy'] and report['results'][0]['case']['legacy']
    assert report['results'][0]['execution_status'] == 'SUCCESS'
    assert report['results'][0]['judge_status'] == 'FAILED'
    assert report['results'][0]['final_status'] == 'INVALID'
    assert report['dialog_case_metrics']['valid'] == 0 and report['pass_rate'] is None
    assert report['avg_scores'] == {}


def test_api_pending_review_and_hard_rule_override_evidence(monkeypatch):
    ev, _ = evaluator()
    monkeypatch.setattr(main, '_evaluator', ev)
    client = TestClient(main.app)
    report = client.post('/eval/run', json={'intent_cases': [], 'dialog_cases': [
        {'case_id':'pending', 'input':'退款', 'judge_method':'human review'},
        {'case_id':'hard', 'input':'退款', 'executable_rules':[{'type':'required_tool', 'tool':'check_billing_fields'}]}
    ]}).json()
    metrics = report['dialog_case_metrics']
    assert metrics['pending_human_reviews'] == 1
    assert metrics['agent_errors'] == metrics['judge_errors'] == metrics['evaluation_errors'] == 0
    assert report['results'][0]['review_status'] == 'PENDING'
    assert set(report['evaluation_config']['quality_thresholds']) == {'relevance','accuracy','completeness','helpfulness'}
    response = client.post('/eval/review', json={'timestamp':report['timestamp'], 'case_id':'hard',
                         'human_final_status':'PASS', 'human_reason':'人工核对任务边界后覆盖规则'})
    assert response.status_code == 200
    updated = response.json()
    result = updated['results'][1]
    assert result['original_status'] == 'FAIL' and result['final_status'] == 'PASS'
    assert result['hard_rule_override'] and result['review_status'] == 'COMPLETED'
    assert result['original_reason'] == report['results'][1]['original_reason']
    assert result['hard_rule_violations'] == report['results'][1]['hard_rule_violations']
    assert result['human_reason'] == '人工核对任务边界后覆盖规则'
    assert updated['dialog_case_metrics']['hard_rule_violations'] == 1
    assert updated['dialog_case_metrics']['passed'] == 1


def test_api_average_is_display_only_and_cannot_compensate_accuracy(monkeypatch):
    ev, _ = evaluator(payload={'relevance':1, 'accuracy':.2, 'completeness':.9, 'helpfulness':.9})
    monkeypatch.setattr(main, '_evaluator', ev)
    response = TestClient(main.app).post('/eval/run', json={'intent_cases':[], 'dialog_cases':[{'question':'退款'}]})
    assert response.status_code == 200
    result = response.json()['results'][0]
    assert result['scores']['overall'] == .75 and result['final_status'] == 'FAIL'
