"""Safe provider boundary: sanitize before existing Agent/Judge can log exceptions."""
import json
import logging
import math
import httpx
from types import SimpleNamespace
from anthropic import AsyncAnthropic, APIStatusError, APITimeoutError, APIConnectionError
from .providers import ProviderFailure, explicitly_unsupported_tools


def classify(error):
    if isinstance(error,(APITimeoutError,httpx.TimeoutException)):
        return 'TIMEOUT'
    if isinstance(error,(APIConnectionError,httpx.RequestError)):
        return 'NETWORK_ERROR'
    if isinstance(error,APIStatusError):
        if error.status_code in {400,422} and explicitly_unsupported_tools(error.body):
            return 'TOOL_CALL_UNSUPPORTED'
        return {401:'AUTH_FAILED',403:'AUTH_FAILED',404:'MODEL_NOT_FOUND',429:'RATE_LIMITED'}.get(error.status_code,'PROVIDER_ERROR')
    return 'INVALID_RESPONSE' if isinstance(error,(ValueError,TypeError,AttributeError,KeyError)) else 'PROVIDER_ERROR'

class ObservedProvider:
    def __init__(self,config,key,judge_key=None):
        self.config, self._key = config, key
        self.call_count = 0
        self.observations, self.errors = [], []
        self._judge=None
        if config.judge_provider_configuration:
            if not judge_key: raise ProviderFailure('CREDENTIAL_UNAVAILABLE')
            from .providers import ProviderConfig
            self._judge=ObservedProvider(ProviderConfig.model_validate(config.judge_provider_configuration),judge_key)
        self._secrets=tuple(k for k in (key,judge_key) if k)
        # SDK/httpx debug logs include request bodies/headers. This boundary runs in
        # a dedicated worker (or connection test) and suppresses those loggers before
        # any secret-bearing client request. Our own errors contain only static codes.
        for name in ('anthropic','anthropic._base_client','httpx','httpcore'):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        if config.provider == 'openai-compatible':
            from .openai_chat import ChatCompletionClient
            self._sdk = ChatCompletionClient(config,key)
        else:
            self._sdk = AsyncAnthropic(api_key=key,base_url=config.base_url,timeout=config.timeout_seconds,
                                       max_retries=0,_strict_response_validation=True,
                                       http_client=httpx.AsyncClient(timeout=config.timeout_seconds,
                                                                     trust_env=False,follow_redirects=False))

    def client(self,role,connection_test=False,tool_probe=False):
        resolved = self.config.resolved()[role]
        async def create(**kwargs):
            model = resolved['model']
            if self.call_count >= self.config.max_calls:
                self.errors.append({'stage':role,'status':'CALL_BUDGET_EXCEEDED'})
                raise ProviderFailure('CALL_BUDGET_EXCEEDED')
            if role=='judge' and getattr(self,'_judge',None):
                self.call_count+=1
                before=len(self._judge.observations);error_before=len(self._judge.errors)
                try:
                    response=await self._judge.client('judge',connection_test,tool_probe).messages.create(**kwargs)
                    if any(k in json.dumps(response.model_dump(mode='json'),ensure_ascii=False) for k in getattr(self,'_secrets',(self._key,))):
                        raise ProviderFailure('INVALID_RESPONSE')
                    return response
                except ProviderFailure as error:
                    if not self._judge.errors[error_before:]:self.errors.append({'stage':'judge','status':error.code})
                    raise
                finally:
                    self.observations.extend({**v,'provider_session_id':self.config.judge_provider_session_id} for v in self._judge.observations[before:])
                    self.errors.extend(self._judge.errors[error_before:])
            try:
                # Explicit user snapshot always wins over literals in legacy callers.
                kwargs.update(model=model,temperature=resolved['temperature'],
                              max_tokens=min(resolved['max_tokens'],8 if connection_test else 64)
                              if connection_test or tool_probe else resolved['max_tokens'])
                self.call_count += 1
                response = await self._sdk.messages.create(**kwargs)
                payload = response.model_dump(mode='json')
                if any(k in json.dumps(payload,ensure_ascii=False,allow_nan=False) for k in getattr(self,'_secrets',(self._key,))):
                    raise ProviderFailure('INVALID_RESPONSE')
                if (not isinstance(response.model,str) or not response.model.strip()
                        or not isinstance(response.id,str) or not response.id.strip()):
                    raise ProviderFailure('INVALID_RESPONSE')
                blocks = response.content
                if not blocks or len(blocks)>32:
                    raise ProviderFailure('INVALID_RESPONSE')
                text_present = False
                tool_ids = set()
                for block in blocks:
                    if block.type == 'text':
                        text_present |= bool(block.text.strip())
                    elif block.type == 'tool_use':
                        allowed = {tool['name']:tool for tool in kwargs.get('tools',[])}
                        if (not isinstance(block.id,str) or not block.id or block.id in tool_ids or block.name not in allowed
                                or not isinstance(block.input,dict)):
                            raise ProviderFailure('INVALID_RESPONSE')
                        tool_ids.add(block.id)
                        from agents.agent_orchestrator import BaseAgent
                        spec = SimpleNamespace(input_schema=allowed[block.name]['input_schema'])
                        BaseAgent._validate_tool_input(spec,block.input)
                    else:
                        raise ProviderFailure('INVALID_RESPONSE')
                if not text_present and not any(b.type == 'tool_use' for b in blocks):
                    raise ProviderFailure('INVALID_RESPONSE')
                if role == 'intent' and not connection_test:
                    # Acquisition validation only; voting/quality semantics stay in
                    # the original recognizer/evaluator. A failed parse must not be
                    # concealed by its local fallback in a formal provider Run.
                    raw='\n'.join(b.text for b in blocks if b.type == 'text')
                    data=json.loads(raw[raw.find('{'):raw.rfind('}')+1])
                    from core.intent_recognizer import IntentCategory
                    confidence=data.get('confidence')
                    if (data.get('intent') not in {i.value for i in IntentCategory}
                            or isinstance(confidence,bool) or not isinstance(confidence,(int,float))
                            or not math.isfinite(confidence) or not 0<=confidence<=1):
                        raise ProviderFailure('INVALID_RESPONSE')
                self.observations.append({'stage':role,'requested_model':model,'response_model_identifier':response.model,
                                          'response_identifier':response.id})
                return response
            except ProviderFailure as error:
                code = error.code
            except Exception as error:
                code = classify(error)
            self.errors.append({'stage':role,'status':code})
            raise ProviderFailure(code) from None
        return SimpleNamespace(messages=SimpleNamespace(create=create))

    async def close(self):
        await self._sdk.close()
        if getattr(self,'_judge',None): await self._judge.close()
