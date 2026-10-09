"""Explicit user configurations and memory-only credentials; no environment fallback."""
from copy import deepcopy
import time
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator, model_serializer
from .models import Artifact, now
from .snapshots import provider_endpoint

ConnectionStatus = Literal['SUCCESS','AUTH_FAILED','MODEL_NOT_FOUND','RATE_LIMITED','TIMEOUT',
                           'NETWORK_ERROR','INVALID_RESPONSE','PROVIDER_ERROR']
FAILURE_CODES = {'AUTH_FAILED','MODEL_NOT_FOUND','RATE_LIMITED','TIMEOUT','NETWORK_ERROR',
                 'INVALID_RESPONSE','PROVIDER_ERROR','CALL_BUDGET_EXCEEDED','CREDENTIAL_UNAVAILABLE',
                 'TOOL_CALL_UNSUPPORTED'}
ROLES = ('general','technical','billing','escalation','composer','intent','judge')

class ModelConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0, ge=0, le=1)
    max_tokens: int = Field(default=256, ge=1, le=4096, strict=True)

    @model_validator(mode='after')
    def no_whitespace_model(self):
        if self.model != self.model.strip() or any(ord(c)<32 for c in self.model):
            raise ValueError('Invalid model identifier')
        return self

class RoleConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)
    model: str | None = Field(default=None,min_length=1,max_length=200)
    temperature: float | None = Field(default=None,ge=0,le=1)
    max_tokens: int | None = Field(default=None,ge=1,le=4096,strict=True)

    @model_validator(mode='after')
    def validate_model(self):
        if self.model is not None and (self.model != self.model.strip() or any(ord(c)<32 for c in self.model)):
            raise ValueError('Invalid model identifier')
        return self

class ProviderConfig(ModelConfig):
    provider: Literal['anthropic-compatible','openai-compatible'] = 'anthropic-compatible'
    base_url: str | None = None
    completion_token_parameter: Literal['max_completion_tokens','max_tokens'] = 'max_completion_tokens'
    # Explicit non-thinking mode for compatible services such as DeepSeek.
    # None preserves the provider's default and the existing request contract.
    thinking_mode: Literal['disabled'] | None = None
    # Overrides are explicit and each inherits the user default, never server env.
    role_overrides: dict[str, RoleConfig] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30, ge=.1, le=120)
    max_calls: int = Field(default=100, ge=1, le=500, strict=True)
    judge_provider_session_id: str | None = Field(default=None,pattern=r'^[A-Za-z0-9_-]{1,128}$')
    judge_provider_configuration: dict | None = None

    @model_serializer(mode='wrap')
    def legacy_serialization(self, handler):
        data=handler(self)
        if self.judge_provider_session_id is None:
            data.pop('judge_provider_session_id',None)
            data.pop('judge_provider_configuration',None)
        return data

    @model_validator(mode='after')
    def endpoint_and_roles(self):
        if bool(self.judge_provider_session_id) != bool(self.judge_provider_configuration):
            raise ValueError('Independent Judge binding is incomplete')
        if self.judge_provider_configuration:
            if self.judge_provider_configuration.get('judge_provider_session_id'):
                raise ValueError('Nested Judge binding is prohibited')
            judge=ProviderConfig.model_validate(self.judge_provider_configuration)
            object.__setattr__(self,'judge_provider_configuration',judge.model_dump())
        if self.thinking_mode is not None and self.provider != 'openai-compatible':
            raise ValueError('Thinking mode override requires Chat Completions')
        endpoint = self.base_url or ('https://api.openai.com/v1' if self.provider=='openai-compatible' else 'https://api.anthropic.com')
        if len(endpoint)>2048 or endpoint != endpoint.strip() or any(ord(c)<32 for c in endpoint):
            raise ValueError('Invalid provider endpoint')
        provider_endpoint(endpoint)
        object.__setattr__(self,'base_url',endpoint)
        if set(self.role_overrides)-set(ROLES):
            raise ValueError('Unsupported role override')
        return self

    def resolved(self):
        default = self.model_dump(include={'model','temperature','max_tokens'})
        result={role:deepcopy({**default,**self.role_overrides[role].model_dump(exclude_none=True)} if role in self.role_overrides else default)
                for role in ROLES}
        if self.judge_provider_configuration:
            result['judge']=ProviderConfig.model_validate(self.judge_provider_configuration).resolved()['judge']
        return result

class ProviderSession(Artifact):
    provider_session_id: str = Field(default_factory=lambda:str(uuid4()))
    configuration: ProviderConfig
    status: Literal['UNTESTED','READY','CONNECTION_FAILED','CREDENTIAL_UNAVAILABLE','DELETED'] = 'UNTESTED'
    # READY on the legacy status is text-only, never a claim about Agent tools.
    text_connection_status: Literal['UNTESTED','READY','FAILED'] = 'UNTESTED'
    tool_call_capability: Literal['UNKNOWN','VERIFIED','UNSUPPORTED','FAILED'] = 'UNKNOWN'
    last_tested_at: str | None = None
    last_connection_test: dict = Field(default_factory=dict)
    last_tool_test: dict = Field(default_factory=dict)

class ProviderSessionInput(ProviderConfig):
    api_key: SecretStr

class ProviderFailure(RuntimeError):
    def __init__(self,code):
        self.code = code
        super().__init__(code)  # Never embed HTTP response, URL, key, or SDK exception text.

def explicitly_unsupported_tools(body):
    """Only structured capability errors count; prose/transport failures do not."""
    error=body.get('error',{}) if isinstance(body,dict) else {}
    if not isinstance(error,dict):return False
    code=error.get('code') or error.get('type')
    return (code in {'tool_calling_not_supported','tools_not_supported','unsupported_tools',
                     'function_calling_not_supported'}
            or code=='unsupported_parameter' and error.get('param') in {'tools','tool_choice'})

class ProviderSessions:
    def __init__(self,store):
        self.store = store
        self._keys = {}
        self.endpoint_validator = None

    def create(self,configuration,key):
        from .store import safe_artifact
        config = ProviderConfig.model_validate(configuration)
        if self.endpoint_validator:
            self.endpoint_validator(config)
        if config.judge_provider_session_id:
            judge=self.get(config.judge_provider_session_id)
            self.credential(judge.provider_session_id)
            if judge.text_connection_status!='READY' or judge.configuration.model_dump()!=config.judge_provider_configuration:
                raise ValueError('Judge must match a verified session')
        if not isinstance(key,str) or len(key)<8 or key != key.strip() or any(ord(c)<32 for c in key):
            raise ValueError('Invalid credential')
        safe_artifact(config.model_dump(),(key,))
        session = ProviderSession(configuration=config)
        with self.store.transaction():
            self.store.forbidden_values += (key,)
            self.store.put('provider_sessions',session)
            self._keys[session.provider_session_id] = key
        return session

    def public(self,session):
        # Presence is computed from this process vault. No key suffix or derived
        # credential identifier is persisted, returned, or used for lookup.
        result={**session.model_dump(),'credential_status':
                'PRESENT' if session.provider_session_id in self._keys and session.status!='DELETED' else 'UNAVAILABLE'}
        if session.configuration.judge_provider_session_id:
            target=session.configuration.judge_provider_session_id
            result['judge_connection']={'session_id':target,'available':target in self._keys and self.get(target).status!='DELETED'}
        return result

    def get(self,identifier):
        session = self.store.get('provider_sessions',identifier)
        if session.status != 'DELETED' and identifier not in self._keys:
            return session.model_copy(update={'status':'CREDENTIAL_UNAVAILABLE'})
        return session

    def credential(self,identifier):
        session = self.get(identifier)
        if session.status == 'CREDENTIAL_UNAVAILABLE' or session.status == 'DELETED':
            raise ProviderFailure('CREDENTIAL_UNAVAILABLE')
        return self._keys[identifier]

    def judge_credential(self,identifier):
        session=self.get(identifier)
        target=session.configuration.judge_provider_session_id
        return self.credential(target) if target else None

    def bind_judge(self,identifier,judge_identifier=None):
        base=self.get(identifier)
        key=self.credential(identifier)
        configuration=base.configuration.model_dump()
        configuration.pop('judge_provider_session_id',None)
        configuration.pop('judge_provider_configuration',None)
        if judge_identifier:
            judge=self.get(judge_identifier)
            if judge.configuration.judge_provider_session_id or judge.text_connection_status!='READY':
                raise ValueError('Judge session must be separately verified')
            configuration.update(judge_provider_session_id=judge_identifier,
                                 judge_provider_configuration=judge.configuration.model_dump())
        return self.create(configuration,key)

    def delete(self,identifier):
        with self.store.transaction():
            session = self.store.get('provider_sessions',identifier)
            result = session.model_copy(update={'status':'DELETED'})
            self.store.put('provider_sessions',result)
            key = self._keys.pop(identifier,None)
            if key and key not in self._keys.values():
                self.store.forbidden_values = tuple(k for k in self.store.forbidden_values if k != key)
        return result

    async def test(self,identifier):
        session = self.get(identifier)
        tested = now()
        start = time.monotonic()
        try:
            key = self.credential(identifier)
        except ProviderFailure:
            return {'status':'CREDENTIAL_UNAVAILABLE','provider':session.configuration.provider,
                    'tested_at':tested,'latency_ms':0,'observations':[], 'call_count':0,
                    'text_connection_status':session.text_connection_status,
                    'tool_call_capability':session.tool_call_capability,'scope':'TEXT_CONNECTION_ONLY'}
        from .provider_transport import ObservedProvider
        provider = ObservedProvider(session.configuration,key,*([self.judge_credential(identifier)] if session.configuration.judge_provider_session_id else []))
        status = 'SUCCESS'
        try:
            # Test each distinct effective model, including a distinct Judge. One call
            # per distinct model; minimal output budget, no tool invocation or retries.
            tested_models = set()
            for role,config in session.configuration.resolved().items():
                identity=(role=='judge' and bool(session.configuration.judge_provider_session_id),config['model'])
                if identity in tested_models:
                    continue
                tested_models.add(identity)
                await provider.client(role,connection_test=True).messages.create(messages=[{'role':'user','content':'Reply OK.'}])
        except ProviderFailure as error:
            status = error.code
        finally:
            await provider.close()
        result = {'status':status,'provider':session.configuration.provider,'tested_at':tested,
                  'latency_ms':round((time.monotonic()-start)*1000,1),
                  'observations':provider.observations,'call_count':provider.call_count,
                  'text_connection_status':'READY' if status=='SUCCESS' else 'FAILED',
                  'tool_call_capability':session.tool_call_capability,
                  'scope':'TEXT_CONNECTION_ONLY'}
        with self.store.transaction():
            # An in-flight connection test must not resurrect a deleted credential.
            latest = self.store.get('provider_sessions',identifier)
            if latest.status != 'DELETED' and identifier in self._keys:
                self.store.put('provider_sessions',latest.model_copy(update={
                    'status':'READY' if status == 'SUCCESS' else 'CONNECTION_FAILED',
                    'text_connection_status':'READY' if status=='SUCCESS' else 'FAILED',
                    'last_tested_at':tested,'last_connection_test':result}))
        return result

    async def test_tools(self,identifier):
        """One forced echo call per distinct Agent model; no business tool executes."""
        session=self.get(identifier)
        key=self.credential(identifier)
        if session.text_connection_status!='READY':
            raise ProviderFailure('TEXT_CONNECTION_NOT_READY')
        from .provider_transport import ObservedProvider
        provider=ObservedProvider(session.configuration,key,*([self.judge_credential(identifier)] if session.configuration.judge_provider_session_id else []))
        tested=now();start=time.monotonic();checks=[]
        try:
            seen=set()
            for role,config in session.configuration.resolved().items():
                if role not in {'general','technical','billing','escalation'} or config['model'] in seen:
                    continue
                seen.add(config['model'])
                value='echo-'+uuid4().hex[:12]
                try:
                    response=await provider.client(role,tool_probe=True).messages.create(
                        messages=[{'role':'user','content':f'Call echo once with value {value}. This is a protocol probe.'}],
                        tools=[{'name':'echo','description':'Return the supplied value; protocol probe only.',
                                'input_schema':{'type':'object','properties':{'value':{'type':'string'}},
                                                'required':['value'],'additionalProperties':False}}],
                        tool_choice={'type':'tool','name':'echo'})
                    calls=[b for b in response.content if b.type=='tool_use']
                    if len(calls)!=1 or calls[0].name!='echo' or calls[0].input!={'value':value}:
                        raise ProviderFailure('INVALID_RESPONSE')
                    checks.append({'model':config['model'],'capability':'VERIFIED','status':'SUCCESS'})
                except ProviderFailure as error:
                    checks.append({'model':config['model'],
                        'capability':'UNSUPPORTED' if error.code=='TOOL_CALL_UNSUPPORTED' else 'FAILED',
                        'status':'INVALID_TOOL_RESPONSE' if error.code=='INVALID_RESPONSE' else error.code})
                    if error.code=='CALL_BUDGET_EXCEEDED':break
        finally:
            await provider.close()
        capability=('UNSUPPORTED' if any(c['capability']=='UNSUPPORTED' for c in checks)
                    else 'FAILED' if any(c['capability']=='FAILED' for c in checks) else 'VERIFIED')
        result={'tool_call_capability':capability,'tested_at':tested,
                'latency_ms':round((time.monotonic()-start)*1000,1),'call_count':provider.call_count,
                'checks':checks,'observations':provider.observations,
                'scope':'FORCED_FUNCTION_CALL_ONLY_NOT_FULL_AGENT_OR_QUALITY_VERIFICATION'}
        with self.store.transaction():
            latest=self.store.get('provider_sessions',identifier)
            if latest.status!='DELETED' and identifier in self._keys:
                self.store.put('provider_sessions',latest.model_copy(update={
                    'tool_call_capability':capability,'last_tool_test':result}))
        return result
