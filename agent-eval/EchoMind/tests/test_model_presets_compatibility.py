"""Explicit compatible inference setting, verified via local HTTP, not a commercial model."""
import asyncio
import pytest
from pydantic import ValidationError
from experiments.providers import ProviderConfig
from experiments.runtime import ProcessRuntime
from test_experiment_service import setup
from test_openai_chat import chat_provider


@pytest.mark.parametrize('mode', [None, 'disabled'])
def test_explicit_thinking_mode_reaches_all_http_calls_and_frozen_snapshots(tmp_path, mode):
    service, _, _ = setup(tmp_path, runtime=ProcessRuntime())
    with chat_provider() as (url, observed):
        session = service.providers.create(ProviderConfig(base_url=url, provider='openai-compatible', model='deepseek-flash',
                        completion_token_parameter='max_tokens', thinking_mode=mode), 'local-test-credential')
        assert asyncio.run(service.providers.test(session.provider_session_id))['status'] == 'SUCCESS'
        probe = asyncio.run(service.providers.test_tools(session.provider_session_id))
        assert probe['tool_call_capability'] == 'VERIFIED'
        ev = service.create_eval_set([{'case_id': 'refund', 'turns': ['退款']}])
        run = asyncio.run(service.run(ev.eval_set_id, provider_session_id=session.provider_session_id))
        assert run.case_results[0].execution_status == 'SUCCESS'
        assert run.provider_configuration_snapshot['thinking_mode'] == mode
        if mode is None:
            assert 'thinking_mode' not in run.inference_config_snapshot
            assert all('thinking' not in call['body'] for call in observed['calls'])
        else:
            assert run.inference_config_snapshot['thinking_mode'] == mode
            assert all(call['body']['thinking'] == {'type': 'disabled'} for call in observed['calls'])
        assert all('max_tokens' in call['body'] and 'max_completion_tokens' not in call['body'] for call in observed['calls'])


def test_thinking_override_cannot_silently_apply_to_anthropic_or_enable_unsupported_mode():
    with pytest.raises(ValidationError):
        ProviderConfig(provider='anthropic-compatible', model='claude', thinking_mode='disabled')
    with pytest.raises(ValidationError):
        ProviderConfig(provider='openai-compatible', model='deepseek-flash', thinking_mode='enabled')
